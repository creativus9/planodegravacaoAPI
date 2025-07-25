import os
import ezdxf
import re
import datetime
from collections import defaultdict

# Importa as funções utilitárias e de Google Drive
from dxf_utils import parse_sku, calcular_bbox_dxf
from google_drive_utils import baixar_arquivo_drive, upload_to_drive # upload_to_drive ainda é usado para o DXF

# --- Configurações de Layout (em mm) ---
# Tamanho da folha de corte (exemplo: A0 ou um tamanho personalizado)
FOLHA_LARGURA_MM, FOLHA_ALTURA_MM = 1200, 900 # Exemplo: 1.2m x 0.9m

# Espaçamentos
ESPACAMENTO_DXF_MESMO_FURO = 100  # Espaçamento horizontal entre DXFs do mesmo tipo de furo
ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes
ESPACAMENTO_LINHA_COR = 200       # Espaçamento vertical entre linhas de cores diferentes
ESPACAMENTO_PLANO_COR = 100       # Espaçamento vertical entre o DXF do plano e a primeira linha de cor
# ESPACAMENTO_ENTRE_PLANOS = 300    # Não mais necessário se só um plano por vez

# Margens da folha
MARGEM_ESQUERDA = 50
MARGEM_SUPERIOR = 50
MARGEM_INFERIOR = 50

# COLOR_MAP e LETTER_MAP removidos, pois são apenas para PNG

def compor_dxf_personalizado(
    file_ids_and_skus: list[dict],
    plan_name: str,
    drive_folder_id: str
):
    """
    Componha um novo arquivo DXF organizando os DXFs de entrada
    baseado em cor, tipo de furo e plano de corte.
    Gera um DXF de saída.

    Args:
        file_ids_and_skus: Lista de dicionários, cada um com 'file_id' do Drive
                           e 'sku' correspondente.
                           Ex: [{'file_id': 'abc', 'sku': 'PLAC-3010-2FH-AC-DOU-070-00000'}]
        plan_name: Nome do plano de corte (ex: "01", "A").
        drive_folder_id: ID da pasta principal do Google Drive.

    Returns:
        O caminho local para o arquivo DXF de saída.
    """
    doc = ezdxf.new('R2010') # Use uma versão do DXF compatível
    msp = doc.modelspace()

    # Estrutura para organizar os DXFs por cor e furo
    # { 'DOU': { '2FH': [ {dxf_entity, original_sku, bbox_width, bbox_height}, ... ] } }
    organized_dxfs = defaultdict(lambda: defaultdict(list))
    
    # png_layout_data removido

    # --- 1. Baixar e Organizar DXFs de Itens ---
    print("[INFO] Baixando e organizando DXFs de itens...")
    for item_data in file_ids_and_skus:
        file_id = item_data['file_id']
        sku = item_data['sku']
        
        hole_type, color_code = parse_sku(sku)
        if not hole_type or not color_code:
            print(f"[WARN] SKU '{sku}' inválido, ignorando item.")
            continue

        # Baixar o arquivo DXF do Google Drive
        local_dxf_name = f"{sku}.dxf"
        try:
            dxf_path_local = baixar_arquivo_drive(file_id, local_dxf_name, drive_folder_id)
        except Exception as e:
            print(f"[ERROR] Falha ao baixar DXF para SKU '{sku}' (ID: {file_id}): {e}")
            continue # Pula para o próximo item se o download falhar

        try:
            # Ler o DXF e calcular seu bounding box
            item_doc = ezdxf.readfile(dxf_path_local)
            item_msp = item_doc.modelspace()
            min_x, min_y, max_x, max_y = calcular_bbox_dxf(item_msp)
            
            # Calcular largura e altura do DXF
            dxf_width = max_x - min_x
            dxf_height = max_y - min_y

            # Armazenar as entidades e suas propriedades
            entities_to_add = []
            for entity in item_msp:
                entities_to_add.append(entity.copy()) # Copia as entidades para o novo documento

            organized_dxfs[color_code][hole_type].append({
                'entities': entities_to_add,
                'sku': sku,
                'bbox_width': dxf_width,
                'bbox_height': dxf_height,
                'original_min_x': min_x, # Para calcular o offset de translação
                'original_min_y': min_y
            })
            print(f"[INFO] DXF para SKU '{sku}' (cor: {color_code}, furo: {hole_type}) processado.")

        except ezdxf.DXFStructureError as e:
            print(f"[ERROR] Arquivo DXF '{dxf_path_local}' corrompido ou inválido: {e}")
        except Exception as e:
            print(f"[ERROR] Erro ao processar DXF '{dxf_path_local}': {e}")
        finally:
            # Limpar o arquivo temporário
            if os.path.exists(dxf_path_local):
                os.remove(dxf_path_local)

    # --- 2. Inserir DXF do Plano de Corte ---
    # Caminho para o DXF do plano de corte (assumindo que está na pasta Plano_Info local)
    plano_info_dxf_path = os.path.join("Plano_Info", f"{plan_name}.dxf")
    
    plano_width = 0
    plano_height = 0
    plano_insert_x = MARGEM_ESQUERDA # Posição inicial temporária
    plano_insert_y = FOLHA_ALTURA_MM - MARGEM_SUPERIOR # Posição inicial temporária

    if os.path.exists(plano_info_dxf_path):
        try:
            plano_doc = ezdxf.readfile(plano_info_dxf_path)
            plano_msp = plano_doc.modelspace()
            
            # Calcular bbox do plano para posicionamento
            min_x_plano, min_y_plano, max_x_plano, max_y_plano = calcular_bbox_dxf(plano_msp)
            plano_width = max_x_plano - min_x_plano
            plano_height = max_y_plano - min_y_plano

            # Criar um bloco para o plano de corte para facilitar a inserção
            block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
            if block_name not in doc.blocks:
                blk = doc.blocks.new(name=block_name)
                for ent in plano_msp:
                    blk.add_entity(ent.copy())
            
            # Não adicionamos ao png_layout_data, apenas preparamos para inserção final no DXF
            print(f"[INFO] DXF do plano de corte '{plano_info_dxf_path}' carregado.")

        except ezdxf.DXFStructureError as e:
            print(f"[ERROR] Arquivo DXF do plano de corte '{plano_info_dxf_path}' corrompido ou inválido: {e}")
            plano_info_dxf_path = None
        except Exception as e:
            print(f"[ERROR] Erro ao carregar ou inserir DXF do plano de corte '{plano_info_dxf_path}': {e}")
            plano_info_dxf_path = None
    else:
        print(f"[WARN] DXF do plano de corte '{plano_info_dxf_path}' não encontrado localmente. Não será inserido.")
        plano_info_dxf_path = None


    # --- 3. Posicionar e Inserir DXFs de Itens ---
    # Para DXF, (0,0) é inferior esquerdo.
    
    current_y_dxf = MARGEM_INFERIOR # Posição Y inicial para o primeiro item (base)
    
    # Ordenar cores para um layout consistente (ex: alfabético)
    sorted_colors = sorted(organized_dxfs.keys())

    # Lista para armazenar as posições temporárias dos itens para cálculo do offset global
    temp_item_positions = []

    for color_code in sorted_colors:
        color_group = organized_dxfs[color_code]
        current_x_dxf = MARGEM_ESQUERDA # Reseta X para cada nova linha de cor
        
        # Ordenar tipos de furo para um layout consistente
        sorted_hole_types = sorted(color_group.keys())

        first_hole_type_in_line = True
        for hole_type in sorted_hole_types:
            hole_type_group = color_group[hole_type]
            
            if not first_hole_type_in_line:
                current_x_dxf += ESPACAMENTO_DXF_FURO_DIFERENTE # Espaçamento entre grupos de furos
            
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
                    current_x_dxf += ESPACAMENTO_DXF_MESMO_FURO # Espaçamento entre DXFs do mesmo furo

                # Calcular offset para mover o DXF para a posição atual (current_x_dxf, current_y_dxf)
                offset_x = current_x_dxf - original_min_x
                offset_y = current_y_dxf - original_min_y

                temp_item_positions.append({
                    'entities': entities,
                    'pos_x': current_x_dxf,
                    'pos_y': current_y_dxf,
                    'width': bbox_width,
                    'height': bbox_height,
                    'offset_x': offset_x,
                    'offset_y': offset_y
                })

                current_x_dxf += bbox_width # Avança X pela largura do DXF
                first_dxf_in_group = False
            
            first_hole_type_in_line = False
        
        max_height_in_color_line = 0
        for hole_type in color_group:
            for dxf_item in color_group[hole_type]:
                max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])
        
        current_y_dxf += max_height_in_color_line + ESPACAMENTO_LINHA_COR

    # --- 4. Ajustar Posições Finais e Inserir no DXF ---
    
    # Encontre a menor Y (mais baixa) e maior Y (mais alta) dos itens que foram posicionados
    min_y_items_positioned = float('inf')
    max_y_items_positioned = float('-inf')
    
    if temp_item_positions:
        for item in temp_item_positions:
            min_y_items_positioned = min(min_y_items_positioned, item['pos_y'])
            max_y_items_positioned = max(max_y_items_positioned, item['pos_y'] + item['height'])
    
    # Se não há itens, a base é a margem inferior
    if min_y_items_positioned == float('inf'):
        min_y_items_positioned = MARGEM_INFERIOR
        max_y_items_positioned = MARGEM_INFERIOR # Apenas para ter um ponto de referência

    # Calcular a altura total do layout dos itens (do mais baixo ao mais alto)
    height_of_items_layout = max_y_items_positioned - min_y_items_positioned
    
    # Calcular a altura total do conteúdo (itens + plano + espaçamentos)
    total_content_height = height_of_items_layout
    if plano_info_dxf_path:
        total_content_height += ESPACAMENTO_PLANO_COR + plano_height

    # Calcular o deslocamento vertical para alinhar o topo do layout (topo do plano ou topo dos itens)
    # com a margem superior da folha.
    
    # O ponto mais alto do layout (se houver plano, é o topo do plano; senão, é o topo dos itens)
    current_max_y_layout = max_y_items_positioned
    if plano_info_dxf_path:
        # Se houver plano, a posição Y do plano será calculada para ficar acima dos itens
        # A base do plano será: max_y_items_positioned + ESPACAMENTO_PLANO_COR
        current_max_y_layout = max_y_items_positioned + ESPACAMENTO_PLANO_COR + plano_height

    # Deslocamento vertical para mover todo o layout para que seu topo esteja na posição desejada
    vertical_offset_global = (FOLHA_ALTURA_MM - MARGEM_SUPERIOR) - current_max_y_layout
    
    # Inserir o DXF do plano (se houver) com a posição final ajustada
    if plano_info_dxf_path:
        block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
        # A posição Y final do plano é a original (temporária) + vertical_offset_global
        final_plano_insert_y = (max_y_items_positioned + ESPACAMENTO_PLANO_COR) + vertical_offset_global
        final_msp_plano_insert_x = MARGEM_ESQUERDA # Assume que o plano sempre começa na margem esquerda

        msp.add_blockref(block_name, insert=(final_msp_plano_insert_x, final_plano_insert_y))
        print(f"[INFO] DXF do plano de corte '{plan_name}.dxf' inserido na posição final.")

    # Inserir os DXFs dos itens com o offset vertical final
    for item in temp_item_positions:
        # Para os itens DXF, aplique o offset global às entidades
        for ent in item['entities']:
            new_ent = ent.copy()
            # O offset original já foi calculado para mover o item para sua posição relativa
            # Agora, adicione o offset global para a posição final
            new_ent.translate(item['offset_x'], item['offset_y'] + vertical_offset_global, 0)
            msp.add_entity(new_ent)


    # --- 5. Salvar DXF ---
    # Nome do arquivo de saída
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y_%H%M%S")
    output_dxf_name = f"Plano de corte {plan_name} {timestamp}.dxf"

    # Caminho temporário para salvar localmente antes do upload
    caminho_saida_dxf = f"/tmp/{output_dxf_name}"

    os.makedirs(os.path.dirname(caminho_saida_dxf) or '.', exist_ok=True)
    doc.saveas(caminho_saida_dxf)
    print(f"[INFO] DXF de saída salvo: {caminho_saida_dxf}")
    
    # Retorna o caminho local do DXF. O upload será feito no main.py.
    return caminho_saida_dxf

