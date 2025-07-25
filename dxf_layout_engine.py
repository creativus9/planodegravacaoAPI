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
ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes
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
    
    # Usaremos um documento temporário para calcular as posições relativas
    # e depois copiaremos as entidades para o documento principal no main.py
    temp_doc = ezdxf.new('R2010') 
    temp_msp = temp_doc.modelspace()

    # Estrutura para organizar os DXFs por cor e furo
    # { 'DOU': { '2FH': [ {dxf_entity, original_sku, bbox_width, bbox_height, original_min_x, original_min_y}, ... ] } }
    organized_dxfs = defaultdict(lambda: defaultdict(list))
    
    # --- 1. Baixar e Organizar DXFs de Itens ---
    print(f"[INFO] Baixando e organizando DXFs de itens para o plano '{plan_name}'...")
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

    # current_y_cursor: Representa a coordenada Y do TOPO do próximo elemento a ser posicionado
    # Começamos do topo do layout relativo, que será ajustado para (0,0) no final.
    # Por enquanto, assumimos que o layout pode crescer para cima a partir de um "piso" 0.
    # A altura total será calculada no final.
    
    # A lógica de posicionamento será de cima para baixo, então o "topo" inicial é a altura máxima esperada
    # para este plano, que será ajustada.
    
    # Para simplificar o cálculo do bbox final, vamos posicionar tudo como se o canto inferior esquerdo
    # do layout final fosse (0,0). Isso significa que as coordenadas Y serão positivas.
    # current_y_cursor será a coordenada Y do canto inferior esquerdo da PRÓXIMA linha a ser inserida.
    
    # Primeiro, determinamos a altura total necessária para este plano.
    # Isso é um pouco complexo porque a altura depende do conteúdo.
    # Vamos fazer uma primeira passagem "virtual" para calcular a altura.

    # Altura total estimada para o layout deste plano
    estimated_layout_height = 0
    if plano_entities:
        estimated_layout_height += plano_height + ESPACAMENTO_PLANO_COR
    
    # Adiciona a altura de cada linha de cor + espaçamento
    for color_code in sorted(organized_dxfs.keys()):
        color_group = organized_dxfs[color_code]
        max_height_in_color_line = 0
        for hole_type in color_group:
            for dxf_item in color_group[hole_type]:
                max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])
        estimated_layout_height += max_height_in_color_line + ESPACAMENTO_LINHA_COR
    
    # Remove o último espaçamento de linha de cor, pois não há próxima linha
    if organized_dxfs:
        estimated_layout_height -= ESPACAMENTO_LINHA_COR
    
    # Se não houver itens nem plano, definimos uma altura mínima para evitar 0
    if estimated_layout_height == 0:
        estimated_layout_height = 1 # Altura mínima para um layout vazio

    # Agora, posicionamos os elementos de cima para baixo.
    # current_y_pos_for_new_row: A coordenada Y do canto inferior esquerdo da próxima "linha" de elementos.
    # Começa na altura total estimada menos a margem inferior (se houver, mas aqui é relativo a 0,0)
    current_y_pos_for_new_row = estimated_layout_height - MARGEM_INFERIOR # Começa do topo do espaço disponível

    # Inserir o DXF do plano de corte no topo, se houver
    if plano_entities:
        # A posição Y para o canto inferior esquerdo do bloco do plano
        # é o cursor atual menos a altura do plano
        plano_insert_y = current_y_pos_for_new_row - plano_height
        
        offset_x_plano = MARGEM_ESQUERDA - plano_original_min_x
        offset_y_plano = plano_insert_y - plano_original_min_y

        for ent in plano_entities:
            new_ent = ent.copy()
            new_ent.translate(offset_x_plano, offset_y_plano, 0)
            all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x_plano, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y_plano))
        
        print(f"[DEBUG] Plano de corte '{plan_name}.dxf' inserido em X:{MARGEM_ESQUERDA:.2f}, Y:{plano_insert_y:.2f} (relativo).")
        
        # Atualiza o cursor Y para o próximo elemento (abaixo do plano + espaçamento)
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
        for hole_type in color_group:
            for dxf_item in color_group[hole_type]:
                max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])

        # A posição Y para esta linha de cor (canto inferior esquerdo dos itens)
        # current_y_pos_for_new_row já está no topo da linha atual, então subtraímos a altura máxima da linha
        row_base_y = current_y_pos_for_new_row - max_height_in_color_line
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
                    all_relative_entities_with_coords.append((new_ent, new_ent.dxf.insert.x if hasattr(new_ent.dxf, 'insert') else offset_x, new_ent.dxf.insert.y if hasattr(new_ent.dxf, 'insert') else offset_y))
                
                print(f"[DEBUG] Item '{sku}' inserido em X:{current_x_pos:.2f}, Y:{row_base_y:.2f} (relativo).")
                current_x_pos += bbox_width # Avança X pela largura do DXF
                first_dxf_in_group = False
            
            first_hole_type_in_line = False
        
        # Após processar todos os furos para uma cor, avança Y para a próxima linha de cor
        current_y_pos_for_new_row = row_base_y - ESPACAMENTO_LINHA_COR
        print(f"[DEBUG] Cursor Y após linha de cor '{color_code}': {current_y_pos_for_new_row:.2f} mm (abaixo da linha + espaçamento)")

    # --- 4. Calcular Bounding Box Final do Layout do Plano e Ajustar para (0,0) ---
    min_x_layout, min_y_layout, max_x_layout, max_y_layout = 0, 0, 0, 0
    
    if all_relative_entities_with_coords:
        # Para calcular o bbox real, precisamos adicionar as entidades a um temp_msp
        # e depois calcular o bbox desse modelspace.
        # Ou, podemos iterar sobre as entidades e seus pontos de inserção já calculados.
        
        # Vamos criar um bbox de união para todas as entidades já com suas posições relativas
        from ezdxf.math import BoundingBox, Vec3
        layout_bbox = BoundingBox()

        for ent, x_pos, y_pos in all_relative_entities_with_coords:
            # Para entidades complexas como INSERTs, o bbox() já considera a transformação.
            # Para outras, como LINE, CIRCLE, etc., o bbox() retorna o bbox do objeto em suas próprias coordenadas.
            # Precisamos transladar esses bboxes para a posição final.
            try:
                entity_bbox = ent.bbox()
                if not entity_bbox.is_empty:
                    # Translada os pontos do bbox da entidade para sua posição final no layout
                    # Isso é um pouco mais complexo, pois ent.bbox() retorna o bbox em coordenadas locais.
                    # Se 'ent' já foi transladado, seus pontos já estão nas coordenadas relativas.
                    # A forma mais segura é recalcular o bbox do modelspace temporário
                    # após adicionar todas as entidades a ele.
                    pass # Faremos isso abaixo
            except Exception:
                pass # Ignora entidades que não têm um bbox válido

        # Adiciona todas as entidades ao temp_msp para calcular o bbox
        for ent, _, _ in all_relative_entities_with_coords:
            temp_msp.add_entity(ent) # Adiciona a entidade já com a posição relativa calculada

        min_x_layout, min_y_layout, max_x_layout, max_y_layout = calcular_bbox_dxf(temp_msp)

        # Se o bbox ainda for 0,0,0,0, e houver entidades, significa um problema no cálculo do bbox
        if min_x_layout == max_x_layout and min_y_layout == max_y_layout and len(all_relative_entities_with_coords) > 0:
            print("[WARN] Bounding box final do layout do plano ainda é 0x0. Pode haver entidades sem geometria.")
            # Fallback para uma dimensão mínima se o bbox for degenerado
            layout_width = MARGEM_ESQUERDA * 2 + 100 # Exemplo de largura mínima
            layout_height = estimated_layout_height # Usa a altura estimada
            # Não há ajuste para (0,0) se não houver bbox real
            
            # Retorna as entidades como estão, sem ajuste de offset, e as dimensões estimadas
            return [(ent, x, y) for ent, x, y in all_relative_entities_with_coords], layout_width, layout_height
            
    else:
        # Se não houver entidades, o layout tem 0 de largura e altura
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

