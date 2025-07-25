import os
import ezdxf
import re
import datetime
from collections import defaultdict
from typing import Optional # Importa Optional

# Importa as funções utilitárias e de Google Drive
from dxf_utils import parse_sku, calcular_bbox_dxf
from google_drive_utils import baixar_arquivo_drive, upload_to_drive, buscar_arquivo_personalizado_por_id_e_sku # Importa buscar_arquivo_personalizado_por_id_e_sku

# --- Configurações de Layout (em mm) ---
# Tamanho da folha de corte (exemplo: A0 ou um tamanho personalizado)
FOLHA_LARGURA_MM, FOLHA_ALTURA_MM = 1200, 900 # Exemplo: 1.2m x 0.9m

# Espaçamentos
ESPACAMENTO_DXF_MESMO_FURO = 100  # Espaçamento horizontal entre DXFs do mesmo tipo de furo
ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes
ESPACAMENTO_LINHA_COR = 200       # Espaçamento vertical entre linhas de cores diferentes
ESPACAMENTO_PLANO_COR = 100       # Espaçamento vertical entre o DXF do plano e a primeira linha de cor

# Margens da folha
MARGEM_ESQUERDA = 50
MARGEM_SUPERIOR = 50
MARGEM_INFERIOR = 50

def compor_dxf_personalizado(
    file_ids_and_skus: list[dict],
    plan_name: str,
    drive_folder_id: str,
    output_filename: Optional[str] = None # Novo parâmetro opcional
):
    """
    Componha um novo arquivo DXF organizando os DXFs de entrada
    baseado em cor, tipo de furo e plano de corte.
    Gera um DXF de saída.

    Args:
        file_ids_and_skus: Lista de dicionários, cada um com 'id_arquivo_drive' (ID lógico do nome) do Drive
                           e 'sku' correspondente.
                           Ex: [{'id_arquivo_drive': '250721QAF71Q8E', 'sku': 'PLAC-3010-2FH-AC-DOU-070-00000'}]
        plan_name: Nome do plano de corte (ex: "01", "A").
        drive_folder_id: ID da pasta principal do Google Drive.
        output_filename: Opcional. Nome do arquivo DXF de saída. Se não fornecido, será gerado automaticamente.

    Returns:
        O caminho local para o arquivo DXF de saída.
    """
    doc = ezdxf.new('R2010') # Use uma versão do DXF compatível
    msp = doc.modelspace()

    # Estrutura para organizar os DXFs por cor e furo
    # { 'DOU': { '2FH': [ {dxf_entity, original_sku, bbox_width, bbox_height}, ... ] } }
    organized_dxfs = defaultdict(lambda: defaultdict(list))
    
    # --- 1. Baixar e Organizar DXFs de Itens ---
    print("[INFO] Baixando e organizando DXFs de itens...")
    for item_data in file_ids_and_skus:
        target_id_from_sheet = item_data['id_arquivo_drive'] 
        sku = item_data['sku']
        
        hole_type, color_code = parse_sku(sku)
        if not hole_type or not color_code:
            print(f"[WARN] SKU '{sku}' inválido, ignorando item.")
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

            entities_to_add = []
            for entity in item_msp:
                entities_to_add.append(entity.copy())

            organized_dxfs[color_code][hole_type].append({
                'entities': entities_to_add,
                'sku': sku,
                'bbox_width': dxf_width,
                'bbox_height': dxf_height,
                'original_min_x': min_x,
                'original_min_y': min_y
            })
            print(f"[INFO] DXF para SKU '{sku}' (cor: {color_code}, furo: {hole_type}) processado. Dimensões: {dxf_width:.2f}x{dxf_height:.2f} mm")

        except ezdxf.DXFStructureError as e:
            print(f"[ERROR] Arquivo DXF '{dxf_path_local}' corrompido ou inválido: {e}")
        except Exception as e:
            print(f"[ERROR] Erro ao processar DXF '{dxf_path_local}': {e}")
        finally:
            if os.path.exists(dxf_path_local):
                os.remove(dxf_path_local)

    # --- 2. Preparar DXF do Plano de Corte ---
    plano_info_dxf_path = os.path.join("Plano_Info", f"{plan_name}.dxf")
    
    plano_width = 0
    plano_height = 0
    plano_block_name = None # Para armazenar o nome do bloco do plano

    if os.path.exists(plano_info_dxf_path):
        try:
            plano_doc = ezdxf.readfile(plano_info_dxf_path)
            plano_msp = plano_doc.modelspace()
            
            min_x_plano, min_y_plano, max_x_plano, max_y_plano = calcular_bbox_dxf(plano_msp)
            plano_width = max_x_plano - min_x_plano
            plano_height = max_y_plano - min_y_plano

            plano_block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
            if plano_block_name not in doc.blocks:
                blk = doc.blocks.new(name=plano_block_name)
                # Translada as entidades do plano para que seu bbox comece em (0,0) dentro do bloco
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


    # --- 3. Posicionar e Inserir DXFs no Modelspace ---
    
    # current_y_cursor: Representa a coordenada Y do TOPO do próximo elemento a ser posicionado
    current_y_cursor = FOLHA_ALTURA_MM - MARGEM_SUPERIOR
    print(f"[DEBUG] Posição inicial do cursor Y (topo da folha - margem): {current_y_cursor:.2f} mm")

    # Inserir o DXF do plano de corte no topo, se houver
    if plano_info_dxf_path and plano_block_name:
        # A posição Y para o canto inferior esquerdo do bloco do plano
        # é o cursor atual menos a altura do plano
        plano_insert_y = current_y_cursor - plano_height
        msp.add_blockref(plano_block_name, insert=(MARGEM_ESQUERDA, plano_insert_y))
        print(f"[DEBUG] Plano de corte '{plan_name}.dxf' inserido em X:{MARGEM_ESQUERDA:.2f}, Y:{plano_insert_y:.2f}. Topo em Y:{current_y_cursor:.2f}")
        
        # Atualiza o cursor Y para o próximo elemento (abaixo do plano + espaçamento)
        current_y_cursor = plano_insert_y - ESPACAMENTO_PLANO_COR
        print(f"[DEBUG] Cursor Y após plano de corte: {current_y_cursor:.2f} mm (abaixo do plano + espaçamento)")
    else:
        print("[DEBUG] Nenhum DXF de plano de corte para inserir.")


    # Ordenar cores para um layout consistente (ex: alfabético)
    sorted_colors = sorted(organized_dxfs.keys())

    for color_code in sorted_colors:
        color_group = organized_dxfs[color_code]
        current_x_pos = MARGEM_ESQUERDA # Reseta X para cada nova linha de cor
        
        # Encontra a altura máxima dos DXFs nesta linha de cor para determinar o avanço vertical
        max_height_in_color_line = 0
        for hole_type in color_group:
            for dxf_item in color_group[hole_type]:
                max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])

        # A posição Y para esta linha de cor (canto inferior esquerdo dos itens)
        # current_y_cursor já está no topo da linha atual, então subtraímos a altura máxima da linha
        row_base_y = current_y_cursor - max_height_in_color_line
        print(f"[DEBUG] Iniciando linha de cor '{color_code}'. Altura máx na linha: {max_height_in_color_line:.2f} mm. Base Y da linha: {row_base_y:.2f} mm")
        
        # Ordenar tipos de furo para um layout consistente
        sorted_hole_types = sorted(color_group.keys())

        first_hole_type_in_line = True
        for hole_type in sorted_hole_types:
            hole_type_group = color_group[hole_type]
            
            if not first_hole_type_in_line:
                current_x_pos += ESPACAMENTO_DXF_FURO_DIFERENTE # Espaçamento entre grupos de furos
                print(f"[DEBUG] Avançando X para novo grupo de furo '{hole_type}': {current_x_pos:.2f} mm")
            
            # Ordenar DXFs dentro do grupo de furo (opcional, mas bom para consistência)
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
                    current_x_pos += ESPACAMENTO_DXF_MESMO_FURO # Espaçamento entre DXFs do mesmo furo
                    print(f"[DEBUG] Avançando X para próximo DXF no grupo: {current_x_pos:.2f} mm")

                # Calcular offset para mover o DXF para a posição atual (current_x_pos, row_base_y)
                # O ponto de referência para a inserção é o canto inferior esquerdo do bbox do DXF
                offset_x = current_x_pos - original_min_x
                offset_y = row_base_y - original_min_y # Usar row_base_y para alinhar a base da linha

                for ent in entities:
                    new_ent = ent.copy()
                    new_ent.translate(offset_x, offset_y, 0)
                    msp.add_entity(new_ent)
                
                print(f"[DEBUG] Item '{sku}' inserido em X:{current_x_pos:.2f}, Y:{row_base_y:.2f}. Offset: ({offset_x:.2f}, {offset_y:.2f})")
                current_x_pos += bbox_width # Avança X pela largura do DXF
                first_dxf_in_group = False
            
            first_hole_type_in_line = False
        
        # Após processar todos os furos para uma cor, avança Y para a próxima linha de cor
        current_y_cursor = row_base_y - ESPACAMENTO_LINHA_COR
        print(f"[DEBUG] Cursor Y após linha de cor '{color_code}': {current_y_cursor:.2f} mm (abaixo da linha + espaçamento)")


    # --- 4. Salvar DXF ---
    # Nome do arquivo de saída
    if output_filename:
        output_dxf_name = output_filename
    else:
        timestamp = datetime.datetime.now().strftime("%d-%m-%Y_%H%M%S")
        output_dxf_name = f"Plano de corte {plan_name} {timestamp}.dxf"

    # Caminho temporário para salvar localmente antes do upload
    caminho_saida_dxf = f"/tmp/{output_dxf_name}"

    os.makedirs(os.path.dirname(caminho_saida_dxf) or '.', exist_ok=True)
    doc.saveas(caminho_saida_dxf)
    print(f"[INFO] DXF de saída salvo: {caminho_saida_dxf}")
    
    # Retorna o caminho local do DXF. O upload será feito no main.py.
    return caminho_saida_dxf

