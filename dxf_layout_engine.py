import os
import ezdxf
import re
import datetime
from collections import defaultdict
from typing import Optional, List, Dict # Adiciona List e Dict para tipagem

# Importa as funções utilitárias e de Google Drive
from dxf_utils import parse_sku, calcular_bbox_dxf
from google_drive_utils import baixar_arquivo_drive, upload_to_drive, buscar_arquivo_personalizado_por_id_e_sku

# --- Configurações de Layout (em mm) ---
# Tamanho da folha de corte (exemplo: A0 ou um tamanho personalizado)
FOLHA_LARGURA_MM, FOLHA_ALTURA_MM = 1200, 900 # Exemplo: 1.2m x 0.9m

# Espaçamentos
ESPACAMENTO_DXF_MESMO_FURO = 100  # Espaçamento horizontal entre DXFs do mesmo tipo de furo
ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes
ESPACAMENTO_LINHA_COR = 200       # Espaçamento vertical entre linhas de cores diferentes
ESPACAMENTO_PLANO_COR = 100       # Espaçamento vertical entre o DXF do plano e a primeira linha de cor
ESPACAMENTO_ENTRE_PLANOS = 300    # Espaçamento vertical entre diferentes blocos de planos (plano + seus itens)
ESPACAMENTO_BARRA_SEPARADORA = 100 # Espaçamento antes e depois da Barra.dxf

# Margens da folha
MARGEM_ESQUERDA = 50
MARGEM_SUPERIOR = 50
MARGEM_INFERIOR = 50

# --- Dimensões Fixas para Fallback ---
# Usadas se calcular_bbox_dxf retornar 0x0
PLANO_DXF_FIXED_WIDTH_MM = 236.0
PLANO_DXF_FIXED_HEIGHT_MM = 21.5

ITEM_DXF_FIXED_WIDTH_MM = 129.0
ITEM_DXF_FIXED_HEIGHT_MM = 225.998

# --- Informações da Barra Separadora (Adicionado) ---
BARRA_DXF_FILENAME = "Barra.dxf"
BARRA_DXF_WIDTH_MM = 10.0
BARRA_DXF_HEIGHT_MM = 250.0 # Altura da barra, para que ela se estenda verticalmente

def compor_dxf_personalizado(
    plans: List[Dict], # Agora recebe uma lista de dicionários de planos
    drive_folder_id: str,
    output_filename: Optional[str] = None # Nome de arquivo de saída opcional
):
    """
    Componha um novo arquivo DXF organizando múltiplos planos de corte
    e seus respectivos itens.

    Args:
        plans: Lista de dicionários, cada um representando um plano de corte.
               Ex: [{'plan_name': '01', 'items': [{'id_arquivo_drive': 'abc', 'sku': '...'}]]
        drive_folder_id: ID da pasta principal do Google Drive.
        output_filename: Opcional. Nome do arquivo DXF de saída. Se não fornecido, será gerado automaticamente.

    Returns:
        O caminho local para o arquivo DXF de saída.
    """
    doc = ezdxf.new('R2010') # Use uma versão do DXF compatível
    msp = doc.modelspace()

    # current_y_cursor: Representa a coordenada Y do TOPO do próximo bloco de plano/itens a ser posicionado
    # Começa do topo da folha, abaixo da margem superior
    current_y_cursor = FOLHA_ALTURA_MM - MARGEM_SUPERIOR
    print(f"[DEBUG] Posição inicial do cursor Y (topo da folha - margem): {current_y_cursor:.2f} mm")

    # Ordena os planos pelo nome para garantir uma ordem consistente no layout
    sorted_plans = sorted(plans, key=lambda p: p['plan_name'])

    # Carregar o DXF da Barra Separadora uma única vez e criar um bloco
    barra_block_name = "BARRA_SEPARADORA"
    barra_dxf_path = os.path.join("Plano_Info", BARRA_DXF_FILENAME)
    if os.path.exists(barra_dxf_path):
        try:
            barra_doc = ezdxf.readfile(barra_dxf_path)
            barra_msp = barra_doc.modelspace()
            min_x_barra, min_y_barra, max_x_barra, max_y_barra = calcular_bbox_dxf(barra_msp)
            
            # Usar dimensões fixas se o bbox for 0x0 para a barra também
            if (max_x_barra - min_x_barra) == 0.0 and (max_y_barra - min_y_barra) == 0.0:
                print(f"[WARN] Dimensões de '{BARRA_DXF_FILENAME}' calculadas como 0x0. Usando dimensões fixas: {BARRA_DXF_WIDTH_MM}x{BARRA_DXF_HEIGHT_MM} mm.")
                min_x_barra, min_y_barra = 0.0, 0.0
                barra_width = BARRA_DXF_WIDTH_MM
                barra_height = BARRA_DXF_HEIGHT_MM
            else:
                barra_width = max_x_barra - min_x_barra
                barra_height = max_y_barra - min_y_barra

            if barra_block_name not in doc.blocks:
                blk_barra = doc.blocks.new(name=barra_block_name)
                offset_x_barra_block = -min_x_barra
                offset_y_barra_block = -min_y_barra
                for ent in barra_msp:
                    new_ent = ent.copy()
                    new_ent.translate(offset_x_barra_block, offset_y_barra_block, 0)
                    blk_barra.add_entity(new_ent)
            print(f"[INFO] DXF da barra separadora '{BARRA_DXF_FILENAME}' carregado e preparado como bloco. Dimensões: {barra_width:.2f}x{barra_height:.2f} mm")
        except Exception as e:
            print(f"[ERROR] Erro ao carregar DXF da barra separadora '{BARRA_DXF_FILENAME}': {e}")
            barra_block_name = None # Impede o uso se houver erro
    else:
        print(f"[WARN] DXF da barra separadora '{BARRA_DXF_FILENAME}' não encontrado em 'Plano_Info'. Barras não serão inseridas.")
        barra_block_name = None

    for plan_data in sorted_plans:
        plan_name = plan_data['plan_name']
        file_ids_and_skus = plan_data['items']

        print(f"\n[INFO] --- Processando Plano de Corte: {plan_name} ---")

        # --- Processar DXF do Plano de Corte (ex: 01.dxf, A.dxf) ---
        plano_info_dxf_path = os.path.join("Plano_Info", f"{plan_name}.dxf")
        
        plano_width = 0
        plano_height = 0
        plano_block_name = None

        if os.path.exists(plano_info_dxf_path):
            try:
                plano_doc = ezdxf.readfile(plano_info_dxf_path)
                plano_msp = plano_doc.modelspace()
                
                min_x_plano, min_y_plano, max_x_plano, max_y_plano = calcular_bbox_dxf(plano_msp)
                plano_width = max_x_plano - min_x_plano
                plano_height = max_y_plano - min_y_plano

                # --- Fallback para dimensões fixas se bbox for 0x0 ---
                if plano_width == 0.0 and plano_height == 0.0:
                    print(f"[WARN] Dimensões do plano '{plan_name}.dxf' calculadas como 0x0. Usando dimensões fixas: {PLANO_DXF_FIXED_WIDTH_MM}x{PLANO_DXF_FIXED_HEIGHT_MM} mm.")
                    plano_width = PLANO_DXF_FIXED_WIDTH_MM
                    plano_height = PLANO_DXF_FIXED_HEIGHT_MM
                    min_x_plano, min_y_plano = 0.0, 0.0 # Assumimos origem (0,0) para fallback
                # --- Fim do Fallback ---

                plano_block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
                if plano_block_name not in doc.blocks:
                    blk = doc.blocks.new(name=plano_block_name)
                    offset_x_plano_block = -min_x_plano
                    offset_y_plano_block = -min_y_plano
                    for ent in plano_msp:
                        new_ent = ent.copy()
                        new_ent.translate(offset_x_plano_block, offset_y_plano_block, 0)
                        blk.add_entity(new_ent)
                
                print(f"[INFO] DXF do plano de corte '{plano_info_dxf_path}' carregado e preparado como bloco. Dimensões: {plano_width:.2f}x{plano_height:.2f} mm")

            except ezdxf.DXFStructureError as e:
                print(f"[ERROR] Arquivo DXF do plano de corte '{plano_info_dxf_path}' corrompido ou inválido: {e}")
                plano_info_dxf_path = None
            except Exception as e:
                print(f"[ERROR] Erro ao carregar ou inserir DXF do plano de corte '{plano_info_dxf_path}': {e}")
                plano_info_dxf_path = None
        else:
            print(f"[WARN] DXF do plano de corte '{plano_info_dxf_path}' não encontrado localmente. Não será inserido.")
            plano_info_dxf_path = None

        # --- Inserir o DXF do Plano de Corte no Modelspace ---
        plano_insert_y = current_y_cursor - plano_height
        
        if plano_info_dxf_path and plano_block_name:
            msp.add_blockref(plano_block_name, insert=(MARGEM_ESQUERDA, plano_insert_y))
            print(f"[DEBUG] Plano de corte '{plan_name}.dxf' inserido em X:{MARGEM_ESQUERDA:.2f}, Y:{plano_insert_y:.2f}. Topo em Y:{current_y_cursor:.2f}")
            
            current_y_cursor = plano_insert_y - ESPACAMENTO_PLANO_COR
            print(f"[DEBUG] Cursor Y após plano de corte: {current_y_cursor:.2f} mm (abaixo do plano + espaçamento)")
        else:
            print(f"[DEBUG] Nenhum DXF de plano de corte '{plan_name}' para inserir.")

        # --- Baixar e Organizar DXFs de Itens para o Plano Atual ---
        # organized_dxfs_for_current_plan: { 'cor': { 'formato': { 'furo': [ {item_data}, ... ] } } }
        organized_dxfs_for_current_plan = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        print(f"[INFO] Baixando e organizando DXFs de itens para o plano {plan_name}...")
        for item_data in file_ids_and_skus:
            target_id_from_sheet = item_data['id_arquivo_drive'] 
            sku = item_data['sku']
            
            # Agora parse_sku retorna formato, furo, cor
            format_code, hole_type, color_code = parse_sku(sku)
            if not format_code or not hole_type or not color_code:
                print(f"[WARN] SKU '{sku}' inválido ou incompleto, ignorando item.")
                continue

            try:
                real_file_id, nome_arquivo_drive = buscar_arquivo_personalizado_por_id_e_sku(
                    target_id=target_id_from_sheet,
                    sku=sku,
                    drive_folder_id=drive_folder_id
                )
                print(f"[INFO] Arquivo encontrado no Drive: ID real='{real_file_id}', Nome='{nome_arquivo_drive}'")
            except FileNotFoundError as e:
                print(f"[ERROR] Falha ao encontrar arquivo no Drive para ID lógico '{target_id_from_sheet}' e SKU '{sku}': {e}")
                continue
            except Exception as e:
                print(f"[ERROR] Erro inesperado ao buscar arquivo no Drive para ID lógico '{target_id_from_sheet}' e SKU '{sku}': {e}")
                continue

            local_dxf_name = f"{sku}.dxf"
            try:
                dxf_path_local = baixar_arquivo_drive(real_file_id, local_dxf_name, drive_folder_id)
            except Exception as e:
                print(f"[ERROR] Falha ao baixar DXF para SKU '{sku}' (ID real: {real_file_id}): {e}")
                continue

            try:
                item_doc = ezdxf.readfile(dxf_path_local)
                item_msp = item_doc.modelspace()
                min_x, min_y, max_x, max_y = calcular_bbox_dxf(item_msp)
                
                dxf_width = max_x - min_x
                dxf_height = max_y - min_y

                # --- Fallback para dimensões fixas se bbox for 0x0 ---
                if dxf_width == 0.0 and dxf_height == 0.0:
                    print(f"[WARN] Dimensões de SKU '{sku}' calculadas como 0x0. Usando dimensões fixas: {ITEM_DXF_FIXED_WIDTH_MM}x{ITEM_DXF_FIXED_HEIGHT_MM} mm.")
                    dxf_width = ITEM_DXF_FIXED_WIDTH_MM
                    dxf_height = ITEM_DXF_FIXED_HEIGHT_MM
                    min_x, min_y = 0.0, 0.0 # Assumimos origem (0,0) para fallback
                # --- Fim do Fallback ---

                entities_to_add = []
                for entity in item_msp:
                    entities_to_add.append(entity.copy())

                # Organiza por cor, depois formato, depois furo
                organized_dxfs_for_current_plan[color_code][format_code][hole_type].append({
                    'entities': entities_to_add,
                    'sku': sku,
                    'bbox_width': dxf_width,
                    'bbox_height': dxf_height,
                    'original_min_x': min_x,
                    'original_min_y': min_y
                })
                print(f"[INFO] DXF para SKU '{sku}' (cor: {color_code}, formato: {format_code}, furo: {hole_type}) processado. Dimensões: {dxf_width:.2f}x{dxf_height:.2f} mm")

            except ezdxf.DXFStructureError as e:
                print(f"[ERROR] Arquivo DXF '{dxf_path_local}' corrompido ou inválido: {e}")
            except Exception as e:
                print(f"[ERROR] Erro ao processar DXF '{dxf_path_local}': {e}")
            finally:
                if os.path.exists(dxf_path_local):
                    os.remove(dxf_path_local)

        # --- Posicionar e Inserir DXFs de Itens para o Plano Atual ---
        current_x_pos = MARGEM_ESQUERDA # Reseta X para cada nova linha de cor

        sorted_colors_for_current_plan = sorted(organized_dxfs_for_current_plan.keys())

        for color_code in sorted_colors_for_current_plan:
            color_group = organized_dxfs_for_current_plan[color_code]
            
            max_height_in_color_line = 0
            # Encontrar a altura máxima de todos os itens nesta linha de cor (considerando todos os formatos e furos)
            for format_code_inner in color_group:
                for hole_type_inner in color_group[format_code_inner]:
                    for dxf_item in color_group[format_code_inner][hole_type_inner]:
                        max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])

            row_base_y = current_y_cursor - max_height_in_color_line
            print(f"[DEBUG] Iniciando linha de cor '{color_code}' para plano '{plan_name}'. Altura máx na linha: {max_height_in_color_line:.2f} mm. Base Y da linha: {row_base_y:.2f} mm")
            
            sorted_formats_for_current_color = sorted(color_group.keys())

            last_format_code = None # Para controlar a inserção da barra
            for format_code_inner in sorted_formats_for_current_color:
                format_group = color_group[format_code_inner]
                
                # Inserir Barra.dxf antes de um novo formato (se não for o primeiro formato na linha de cor)
                if last_format_code is not None: # Se não for o primeiro formato desta linha de cor
                    if barra_block_name:
                        current_x_pos += ESPACAMENTO_BARRA_SEPARADORA
                        # Alinha a base da barra com a base da linha de itens
                        msp.add_blockref(barra_block_name, insert=(current_x_pos, row_base_y)) 
                        current_x_pos += BARRA_DXF_WIDTH_MM + ESPACAMENTO_BARRA_SEPARADORA
                        print(f"[DEBUG] Barra.dxf inserida antes do formato '{format_code_inner}' em X:{current_x_pos - BARRA_DXF_WIDTH_MM - ESPACAMENTO_BARRA_SEPARADORA:.2f}")
                    else:
                        current_x_pos += ESPACAMENTO_DXF_FURO_DIFERENTE # Fallback para espaçamento se barra não existir
                        print(f"[DEBUG] Avançando X para novo formato '{format_code_inner}': {current_x_pos:.2f} mm (sem barra)")
                
                sorted_hole_types_for_current_format = sorted(format_group.keys())
                
                last_hole_type = None # Para controlar a inserção da barra
                for hole_type_inner in sorted_hole_types_for_current_format:
                    hole_type_group = format_group[hole_type_inner]
                    
                    # Inserir Barra.dxf antes de um novo furo (se não for o primeiro furo neste formato)
                    if last_hole_type is not None: # Se não for o primeiro furo deste grupo de formato
                        if barra_block_name:
                            current_x_pos += ESPACAMENTO_BARRA_SEPARADORA
                            # Alinha a base da barra com a base da linha de itens
                            msp.add_blockref(barra_block_name, insert=(current_x_pos, row_base_y)) 
                            current_x_pos += BARRA_DXF_WIDTH_MM + ESPACAMENTO_BARRA_SEPARADORA
                            print(f"[DEBUG] Barra.dxf inserida antes do furo '{hole_type_inner}' em X:{current_x_pos - BARRA_DXF_WIDTH_MM - ESPACAMENTO_BARRA_SEPARADORA:.2f}")
                        else:
                            current_x_pos += ESPACAMENTO_DXF_FURO_DIFERENTE # Fallback para espaçamento se barra não existir
                            print(f"[DEBUG] Avançando X para novo furo '{hole_type_inner}': {current_x_pos:.2f} mm (sem barra)")

                    sorted_hole_type_dxfs = sorted(hole_type_group, key=lambda x: x['sku'])

                    first_dxf_in_group = True
                    for dxf_item in sorted_hole_type_dxfs:
                        entities = dxf_item['entities']
                        sku = dxf_item['sku']
                        bbox_width = dxf_item['bbox_width']
                        bbox_height = dxf_item['bbox_height']
                        original_min_x = dxf_item['original_min_x']
                        original_min_y = dxf_item['original_min_y']

                        if not first_dxf_in_group:
                            current_x_pos += ESPACAMENTO_DXF_MESMO_FURO
                            print(f"[DEBUG] Avançando X para próximo DXF no grupo: {current_x_pos:.2f} mm")

                        offset_x = current_x_pos - original_min_x
                        offset_y = row_base_y - original_min_y

                        for ent in entities:
                            new_ent = ent.copy()
                            new_ent.translate(offset_x, offset_y, 0)
                            msp.add_entity(new_ent)
                        
                        print(f"[DEBUG] Item '{sku}' inserido em X:{current_x_pos:.2f}, Y:{row_base_y:.2f}. Offset: ({offset_x:.2f}, {offset_y:.2f})")
                        current_x_pos += bbox_width
                        first_dxf_in_group = False
                    
                    last_hole_type = hole_type_inner # Atualiza o último tipo de furo processado
                last_format_code = format_code_inner # Atualiza o último formato processado
            
            current_y_cursor = row_base_y - ESPACAMENTO_LINHA_COR
            print(f"[DEBUG] Cursor Y após linha de cor '{color_code}' para plano '{plan_name}': {current_y_cursor:.2f} mm (abaixo da linha + espaçamento)")
        
        current_y_cursor -= ESPACAMENTO_ENTRE_PLANOS
        print(f"[DEBUG] Cursor Y após plano '{plan_name}' e seus itens: {current_y_cursor:.2f} mm (abaixo do bloco do plano + espaçamento entre planos)")


    # --- 4. Salvar DXF ---
    final_output_dxf_name = output_filename if output_filename else f"Plano de Gravação {datetime.datetime.now().strftime('%d-%m-%Y_%H%M%S')}.dxf"
    
    caminho_saida_dxf = f"/tmp/{final_output_dxf_name}"
    
    os.makedirs(os.path.dirname(caminho_saida_dxf) or '.', exist_ok=True)
    doc.saveas(caminho_saida_dxf)
    print(f"[INFO] DXF de saída salvo: {caminho_saida_dxf}")

    return caminho_saida_dxf

