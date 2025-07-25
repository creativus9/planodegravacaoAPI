import ezdxf
from ezdxf.math import BoundingBox, Vec3 # Adiciona importação de BoundingBox e Vec3

def parse_sku(sku: str):
    """
    Analisa a string SKU e extrai as informações relevantes.
    Exemplo: PLAC-3010-2FH-AC-DOU-070-00000
    Grupos: 1-formato, 2-tamanho, 3-furo, 4-material, 5-cor, 6-quantidade, 7-estilo da arte
    """
    parts = sku.split('-')
    if len(parts) != 7:
        print(f"[WARN] SKU '{sku}' não está no formato esperado (7 grupos).")
        return None, None, None, None # Retorna None para todos os valores se o formato não for o esperado

    # Extrai os novos campos
    dxf_format = parts[0] # Grupo 1: formato
    dxf_size = parts[1]   # Grupo 2: tamanho
    hole_type = parts[2]  # Grupo 3: tipo de furo
    color_code = parts[4] # Grupo 5: código da cor

    return dxf_format, dxf_size, hole_type, color_code

def calcular_bbox_dxf(msp):
    """
    Calcula o bounding box (caixa delimitadora) de todas as entidades no modelspace de um DXF.
    Retorna (min_x, min_y, max_x, max_y).
    Esta versão itera sobre as entidades e usa BoundingBox para maior robustez.
    """
    bbox_union = BoundingBox() # Inicializa uma caixa delimitadora vazia
    found_any_entity = False # Flag para verificar se alguma entidade foi processada

    for e in msp:
        found_any_entity = True # Encontrou pelo menos uma entidade
        try:
            # Tenta obter a caixa delimitadora da entidade
            entity_bbox = e.bbox()
            
            if entity_bbox.is_empty:
                # Se a bbox da entidade for vazia, pula para a próxima
                continue

            # Adiciona os pontos extremos da bbox da entidade à bbox de união
            bbox_union.extend(entity_bbox.extmin)
            bbox_union.extend(entity_bbox.extmax)

        except Exception as err:
            # Ignora entidades que causam erro no cálculo da bbox
            pass

    if not found_any_entity:
        print(f"[WARN] Nenhuma entidade encontrada no modelspace para calcular bbox. Retornando 0,0,0,0.")
        return 0, 0, 0, 0

    if bbox_union.is_empty:
        print(f"[WARN] Bounding box união está vazio (provavelmente todas as entidades tinham bbox vazio ou erro). Retornando 0,0,0,0.")
        return 0, 0, 0, 0

    # Extrai as coordenadas da caixa delimitadora de união
    min_x, min_y = bbox_union.extmin.x, bbox_union.extmin.y
    max_x, max_y = bbox_union.extmax.x, bbox_union.extmax.y

    # Validação básica: se min_x/y for maior ou igual a max_x/y, significa que não há extensão de geometria válida
    if min_x >= max_x or min_y >= max_y:
        print(f"[WARN] Bounding box calculado é inválido (min >= max). Retornando 0,0,0,0. (min_x={min_x}, max_x={max_x}, min_y={min_y}, max_y={max_y})")
        return 0, 0, 0, 0

    return min_x, min_y, max_x, max_y
```
Aqui estão as atualizações para o Canvas `dxf_layout_engine.py`:


```python
import os
import ezdxf
import re
import datetime
from collections import defaultdict
from typing import Optional, List, Tuple, Any # Adiciona List, Tuple, Any

# Importa as funções utilitárias e de Google Drive
from dxf_utils import parse_sku, calcular_bbox_dxf
from google_drive_utils import baixar_arquivo_drive, upload_to_drive, buscar_arquivo_personalizado_por_id_e_sku # Importa buscar_arquivo_personalizado_por_id_e_sku

# --- Configurações de Layout (em mm) ---
# Tamanho da folha de corte (exemplo: A0 ou um tamanho personalizado)
FOLHA_LARGURA_MM, FOLHA_ALTURA_MM = 1200, 900 # Exemplo: 1.2m x 0.9m

# Espaçamentos
ESPACAMENTO_DXF_MESMO_FURO = 100  # Espaçamento horizontal entre DXFs do mesmo tipo de furo
# ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes (Substituído pela barra)
ESPACAMENTO_LINHA_COR = 200       # Espaçamento vertical entre linhas de cores diferentes
ESPACAMENTO_PLANO_COR = 100       # Espaçamento vertical entre o DXF do plano e a primeira linha de cor

# Margens da folha
MARGEM_ESQUERDA = 50
MARGEM_SUPERIOR = 50
MARGEM_INFERIOR = 50

# --- Dimensões Fixas para Fallback (Adicionado) ---
# Usadas se calcular_bbox_dxf retornar 0x0
PLANO_DXF_FIXED_WIDTH_MM = 236.0
PLANO_DXF_FIXED_HEIGHT_MM = 21.5

ITEM_DXF_FIXED_WIDTH_MM = 129.0
ITEM_DXF_FIXED_HEIGHT_MM = 225.998

# --- Configurações da Barra Separadora ---
BARRA_DXF_PATH = os.path.join("Plano_Info", "Barra.dxf")
BARRA_DXF_FIXED_WIDTH_MM = 10.0
BARRA_DXF_FIXED_HEIGHT_MM = 250.0
ESPACAMENTO_SEPARADOR = 100 # Espaçamento de 100mm antes e depois da barra

# Variável global para armazenar as entidades da barra
barra_entities = []
barra_width = BARRA_DXF_FIXED_WIDTH_MM
barra_height = BARRA_DXF_FIXED_HEIGHT_MM
barra_original_min_x, barra_original_min_y = 0.0, 0.0

def load_barra_dxf():
    """Carrega as entidades do Barra.dxf uma vez."""
    global barra_entities, barra_width, barra_height, barra_original_min_x, barra_original_min_y
    if not barra_entities: # Carrega apenas se ainda não foi carregado
        if os.path.exists(BARRA_DXF_PATH):
            try:
                barra_doc = ezdxf.readfile(BARRA_DXF_PATH)
                barra_msp = barra_doc.modelspace()
                
                min_x_barra, min_y_barra, max_x_barra, max_y_barra = calcular_bbox_dxf(barra_msp)
                
                # Fallback para dimensões fixas se bbox for 0x0
                if (max_x_barra - min_x_barra) == 0.0 and (max_y_barra - min_y_barra) == 0.0:
                    print(f"[WARN] Dimensões de Barra.dxf calculadas como 0x0. Usando dimensões fixas: {BARRA_DXF_FIXED_WIDTH_MM}x{BARRA_DXF_FIXED_HEIGHT_MM} mm.")
                    barra_width = BARRA_DXF_FIXED_WIDTH_MM
                    barra_height = BARRA_DXF_FIXED_HEIGHT_MM
                    barra_original_min_x, barra_original_min_y = 0.0, 0.0
                else:
                    barra_width = max_x_barra - min_x_barra
                    barra_height = max_y_barra - min_y_barra
                    barra_original_min_x, barra_original_min_y = min_x_barra, min_y_barra

                for ent in barra_msp:
                    barra_entities.append(ent.copy())
                print(f"[INFO] Barra.dxf carregado. Dimensões: {barra_width:.2f}x{barra_height:.2f} mm")
            except ezdxf.DXFStructureError as e:
                print(f"[ERROR] Arquivo DXF '{BARRA_DXF_PATH}' corrompido ou inválido: {e}")
                barra_entities = []
            except Exception as e:
                print(f"[ERROR] Erro ao carregar DXF '{BARRA_DXF_PATH}': {e}")
                barra_entities = []
        else:
            print(f"[WARN] Barra.dxf não encontrado em '{BARRA_DXF_PATH}'. Separadores não serão inseridos.")

def generate_single_plan_layout_data(
    file_ids_and_skus: list[dict],
    plan_name: str,
    drive_folder_id: str,
) -> Tuple[List[Tuple[Any, float, float]], float, float]:
    """
    Gera as entidades DXF e suas posições relativas para o layout de um único plano de corte,
    assumindo que o canto inferior esquerdo do layout final será (0,0).

    Args:
        file_ids_and_skus: Lista de dicionários, cada um com 'id_arquivo_drive' (ID lógico do nome) do Drive
                           e 'sku' correspondente.
        plan_name: Nome do plano de corte (ex: "01", "A").
        drive_folder_id: ID da pasta principal do Google Drive.

    Returns:
        Uma tupla contendo:
        - Uma lista de tuplas: (entidade ezdxf copiada, x_pos_relativa, y_pos_relativa)
        - A largura total do layout do plano.
        - A altura total do layout do plano.
    """
    
    # Carrega a barra DXF se ainda não foi carregada
    load_barra_dxf()

    # Usaremos um documento temporário para calcular as posições relativas
    # e depois copiaremos as entidades para o documento principal no main.py
    temp_doc = ezdxf.new('R2010') 
    temp_msp = temp_doc.modelspace()

    # Estrutura para organizar os DXFs por cor, formato, tamanho e furo
    # { 'DOU': { 'PLAC': { '3010': { '2FH': [ {dxf_entity, original_sku, bbox_width, bbox_height, original_min_x, original_min_y}, ... ] } } } }
    organized_dxfs = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    
    # --- 1. Baixar e Organizar DXFs de Itens ---
    print(f"[INFO] Baixando e organizando DXFs de itens para o plano '{plan_name}'...")
    for item_data in file_ids_and_skus:
        target_id_from_sheet = item_data['id_arquivo_drive'] 
        sku = item_data['sku']
        
        dxf_format, dxf_size, hole_type, color_code = parse_sku(sku)
        if not dxf_format or not dxf_size or not hole_type or not color_code:
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

            # --- Fallback para dimensões fixas se bbox for 0x0 (Adicionado) ---
            if dxf_width == 0.0 and dxf_height == 0.0:
                print(f"[WARN] Dimensões de SKU '{sku}' calculadas como 0x0. Usando dimensões fixas: {ITEM_DXF_FIXED_WIDTH_MM}x{ITEM_DXF_FIXED_HEIGHT_MM} mm.")
                dxf_width = ITEM_DXF_FIXED_WIDTH_MM
                dxf_height = ITEM_DXF_FIXED_HEIGHT_MM
                # Para o offset, assumimos que o ponto de origem do desenho é (0,0) se não houver bbox válido
                min_x, min_y = 0.0, 0.0 
            # --- Fim do Fallback ---

            entities_to_add = []
            for entity in item_msp:
                entities_to_add.append(entity.copy()) # Copia para evitar referências ao doc original

            organized_dxfs[color_code][dxf_format][dxf_size][hole_type].append({
                'entities': entities_to_add,
                'sku': sku,
                'bbox_width': dxf_width,
                'bbox_height': dxf_height,
                'original_min_x': min_x,
                'original_min_y': min_y
            })
            print(f"[INFO] DXF para SKU '{sku}' (cor: {color_code}, formato: {dxf_format}, tamanho: {dxf_size}, furo: {hole_type}) processado. Dimensões: {dxf_width:.2f}x{dxf_height:.2f} mm")

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
    plano_entities = [] # Lista para armazenar as entidades do plano
    plano_original_min_x, plano_original_min_y = 0.0, 0.0

    if os.path.exists(plano_info_dxf_path):
        try:
            plano_doc = ezdxf.readfile(plano_info_dxf_path)
            plano_msp = plano_doc.modelspace()
            
            min_x_plano, min_y_plano, max_x_plano, max_y_plano = calcular_bbox_dxf(plano_msp)
            plano_width = max_x_plano - min_x_plano
            plano_height = max_y_plano - min_y_plano
            plano_original_min_x, plano_original_min_y = min_x_plano, min_y_plano

            # --- Fallback para dimensões fixas se bbox for 0x0 (Adicionado) ---
            if plano_width == 0.0 and plano_height == 0.0:
                print(f"[WARN] Dimensões do plano '{plan_name}.dxf' calculadas como 0x0. Usando dimensões fixas: {PLANO_DXF_FIXED_WIDTH_MM}x{PLANO_DXF_FIXED_HEIGHT_MM} mm.")
                plano_width = PLANO_DXF_FIXED_WIDTH_MM
                plano_height = PLANO_DXF_FIXED_HEIGHT_MM
                plano_original_min_x, plano_original_min_y = 0.0, 0.0 # Reinicia offset se usar fixo
            # --- Fim do Fallback ---

            for ent in plano_msp:
                plano_entities.append(ent.copy()) # Copia para evitar referências ao doc original
            
            print(f"[INFO] DXF do plano de corte '{plano_info_dxf_path}' carregado. Dimensões: {plano_width:.2f}x{plano_height:.2f} mm")

        except ezdxf.DXFStructureError as e:
            print(f"[ERROR] Arquivo DXF do plano de corte '{plano_info_dxf_path}' corrompido ou inválido: {e}")
            plano_entities = [] # Limpa as entidades se houver erro
        except Exception as e:
            print(f"[ERROR] Erro ao carregar DXF do plano de corte '{plano_info_dxf_path}': {e}")
            plano_entities = [] # Limpa as entidades se houver erro
    else:
        print(f"[WARN] DXF do plano de corte '{plano_info_dxf_path}' não encontrado localmente. Não será inserido.")

    # --- 3. Posicionar e Coletar Entidades no Modelspace Relativo ---
    
    # Esta lista armazenará todas as entidades com suas posições finais RELATIVAS
    # ao canto inferior esquerdo do layout deste plano (que será (0,0) após o ajuste final)
    all_relative_entities_with_coords = []

    # Altura total estimada para o layout deste plano (primeira passagem para estimar altura)
    estimated_layout_height = 0
    if plano_entities:
        estimated_layout_height += plano_height + ESPACAMENTO_PLANO_COR
    
    # Adiciona a altura de cada linha de cor + espaçamento
    for color_code in sorted(organized_dxfs.keys()):
        color_group = organized_dxfs[color_code]
        max_height_in_color_line = 0
        
        if barra_entities: # Considera a altura da barra se ela for inserida
            max_height_in_color_line = max(max_height_in_color_line, barra_height)

        for dxf_format in sorted(color_group.keys()):
            format_group = color_group[dxf_format]
            for dxf_size in sorted(format_group.keys()):
                size_group = format_group[dxf_size]
                for hole_type in size_group.keys():
                    for dxf_item in size_group[hole_type]:
                        max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])
        
        # Se houver itens nesta linha de cor, adiciona a altura máxima e o espaçamento da linha de cor
        if max_height_in_color_line > 0:
            estimated_layout_height += max_height_in_color_line + ESPACAMENTO_LINHA_COR
    
    # Remove o último espaçamento de linha de cor, pois não há próxima linha
    if organized_dxfs and estimated_layout_height > 0:
        estimated_layout_height -= ESPACAMENTO_LINHA_COR
    
    # Se não houver itens nem plano, definimos uma altura mínima para evitar 0
    if estimated_layout_height == 0:
        estimated_layout_height = 1 # Altura mínima para um layout vazio

    # Agora, posicionamos os elementos de cima para baixo.
    current_y_pos_for_new_row = estimated_layout_height - MARGEM_INFERIOR # Começa do topo do espaço disponível

    # Inserir o DXF do plano de corte no topo, se houver
    if plano_entities:
        plano_insert_y = current_y_pos_for_new_row - plano_height
        
        offset_x_plano = MARGEM_ESQUERDA - plano_original_min_x
        offset_y_plano = plano_insert_y - plano_original_min_y

        for ent in plano_entities:
            new_ent = ent.copy()
            new_ent.translate(offset_x_plano, offset_y_plano, 0)
            all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x_plano, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y_plano))
        
        print(f"[DEBUG] Plano de corte '{plan_name}.dxf' inserido em X:{MARGEM_ESQUERDA:.2f}, Y:{plano_insert_y:.2f} (relativo).")
        
        current_y_pos_for_new_row = plano_insert_y - ESPACAMENTO_PLANO_COR
        print(f"[DEBUG] Cursor Y após plano de corte: {current_y_pos_for_new_row:.2f} mm (abaixo do plano + espaçamento)")
    else:
        print("[DEBUG] Nenhum DXF de plano de corte para inserir.")


    # Ordenar cores para um layout consistente (ex: alfabético)
    sorted_colors = sorted(organized_dxfs.keys())

    for color_code in sorted_colors:
        color_group = organized_dxfs[color_code]
        current_x_pos = MARGEM_ESQUERDA # Reseta X para cada nova linha de cor
        
        # Encontra a altura máxima dos DXFs nesta linha de cor para determinar o avanço vertical
        max_height_in_color_line = 0
        if barra_entities:
            max_height_in_color_line = max(max_height_in_color_line, barra_height)

        for dxf_format in sorted(color_group.keys()):
            format_group = color_group[dxf_format]
            for dxf_size in sorted(format_group.keys()):
                size_group = format_group[dxf_size]
                for hole_type in size_group.keys():
                    for dxf_item in size_group[hole_type]:
                        max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])

        # A posição Y para esta linha de cor (canto inferior esquerdo dos itens)
        row_base_y = current_y_pos_for_new_row - max_height_in_color_line
        print(f"[DEBUG] Iniciando linha de cor '{color_code}'. Altura máx na linha: {max_height_in_color_line:.2f} mm. Base Y da linha: {row_base_y:.2f} mm")
        
        sorted_formats = sorted(color_group.keys())
        first_format_in_line = True
        for dxf_format in sorted_formats:
            format_group = color_group[dxf_format]

            if not first_format_in_line:
                # Inserir separador antes de um novo formato
                if barra_entities:
                    current_x_pos += ESPACAMENTO_SEPARADOR
                    offset_x_barra = current_x_pos - barra_original_min_x
                    # A barra deve estar alinhada com a base da linha de itens, ou um pouco acima se for mais alta
                    offset_y_barra = row_base_y - barra_original_min_y 
                    
                    for ent in barra_entities:
                        new_ent = ent.copy()
                        new_ent.translate(offset_x_barra, offset_y_barra, 0)
                        all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x_barra, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y_barra))
                    print(f"[DEBUG] Barra.dxf inserida antes do formato '{dxf_format}' em X:{current_x_pos:.2f}.")
                    current_x_pos += barra_width + ESPACAMENTO_SEPARADOR # Avança X pela largura da barra + espaçamento
                else:
                    current_x_pos += ESPACAMENTO_DXF_MESMO_FURO # Fallback se a barra não for carregada
                print(f"[DEBUG] Avançando X para novo formato '{dxf_format}': {current_x_pos:.2f} mm")
            
            sorted_sizes = sorted(format_group.keys())
            first_size_in_format = True
            for dxf_size in sorted_sizes:
                size_group = format_group[dxf_size]

                if not first_size_in_format:
                    # Inserir separador antes de um novo tamanho
                    if barra_entities:
                        current_x_pos += ESPACAMENTO_SEPARADOR
                        offset_x_barra = current_x_pos - barra_original_min_x
                        offset_y_barra = row_base_y - barra_original_min_y
                        for ent in barra_entities:
                            new_ent = ent.copy()
                            new_ent.translate(offset_x_barra, offset_y_barra, 0)
                            all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x_barra, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y_barra))
                        print(f"[DEBUG] Barra.dxf inserida antes do tamanho '{dxf_size}' em X:{current_x_pos:.2f}.")
                        current_x_pos += barra_width + ESPACAMENTO_SEPARADOR
                    else:
                        current_x_pos += ESPACAMENTO_DXF_MESMO_FURO
                    print(f"[DEBUG] Avançando X para novo tamanho '{dxf_size}': {current_x_pos:.2f} mm")

                sorted_hole_types = sorted(size_group.keys())
                first_hole_type_in_size = True
                for hole_type in sorted_hole_types:
                    hole_type_group = size_group[hole_type]
                    
                    if not first_hole_type_in_size:
                        # Inserir separador antes de um novo tipo de furo
                        if barra_entities:
                            current_x_pos += ESPACAMENTO_SEPARADOR
                            offset_x_barra = current_x_pos - barra_original_min_x
                            offset_y_barra = row_base_y - barra_original_min_y
                            for ent in barra_entities:
                                new_ent = ent.copy()
                                new_ent.translate(offset_x_barra, offset_y_barra, 0)
                                all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x_barra, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y_barra))
                            print(f"[DEBUG] Barra.dxf inserida antes do furo '{hole_type}' em X:{current_x_pos:.2f}.")
                            current_x_pos += barra_width + ESPACAMENTO_SEPARADOR
                        else:
                            current_x_pos += ESPACAMENTO_DXF_MESMO_FURO
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
                        offset_x = current_x_pos - original_min_x
                        offset_y = row_base_y - original_min_y # Usar row_base_y para alinhar a base da linha

                        for ent in entities:
                            new_ent = ent.copy()
                            new_ent.translate(offset_x, offset_y, 0)
                            all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y))
                        
                        print(f"[DEBUG] Item '{sku}' inserido em X:{current_x_pos:.2f}, Y:{row_base_y:.2f} (relativo).")
                        current_x_pos += bbox_width # Avança X pela largura do DXF
                        first_dxf_in_group = False
                    
                    first_hole_type_in_size = False
                first_size_in_format = False
            first_format_in_line = False
        
        # Após processar todos os furos para uma cor, avança Y para a próxima linha de cor
        current_y_pos_for_new_row = row_base_y - ESPACAMENTO_LINHA_COR
        print(f"[DEBUG] Cursor Y após linha de cor '{color_code}': {current_y_pos_for_new_row:.2f} mm (abaixo da linha + espaçamento)")

    # --- 4. Calcular Bounding Box Final do Layout do Plano e Ajustar para (0,0) ---
    min_x_layout, min_y_layout, max_x_layout, max_y_layout = 0, 0, 0, 0
    
    if all_relative_entities_with_coords:
        from ezdxf.math import BoundingBox
        layout_bbox = BoundingBox()

        # Adiciona todas as entidades ao temp_msp para calcular o bbox
        for ent, _, _ in all_relative_entities_with_coords:
            temp_msp.add_entity(ent) # Adiciona a entidade já com a posição relativa calculada

        min_x_layout, min_y_layout, max_x_layout, max_y_layout = calcular_bbox_dxf(temp_msp)

        if min_x_layout == max_x_layout and min_y_layout == max_y_layout and len(all_relative_entities_with_coords) > 0:
            print("[WARN] Bounding box final do layout do plano ainda é 0x0. Pode haver entidades sem geometria.")
            layout_width = MARGEM_ESQUERDA * 2 + 100 # Exemplo de largura mínima
            layout_height = estimated_layout_height # Usa a altura estimada
            
            return [(ent, x, y) for ent, x, y in all_relative_entities_with_coords], layout_width, layout_height
            
    else:
        print("[INFO] Nenhum item ou plano para o layout. Retornando layout vazio.")
        return [], 0.0, 0.0

    # Ajustar todas as entidades para que o canto inferior esquerdo do layout seja (0,0)
    offset_x_final = -min_x_layout
    offset_y_final = -min_y_layout

    final_entities_with_coords = []
    for ent, current_x, current_y in all_relative_entities_with_coords:
        new_ent = ent.copy() # Copia novamente para não modificar a referência original
        new_ent.translate(offset_x_final, offset_y_final, 0)
        final_entities_with_coords.append((new_ent, current_x + offset_x_final, current_y + offset_y_final))

    layout_width = max_x_layout - min_x_layout
    layout_height = max_y_layout - min_y_layout

    print(f"[INFO] Layout do plano '{plan_name}' gerado. Dimensões: {layout_width:.2f}x{layout_height:.2f} mm")
    return final_entities_with_coords, layout_width, layout_height
