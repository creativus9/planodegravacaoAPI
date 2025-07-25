import os
import ezdxf
import re
from PIL import Image, ImageDraw, ImageFont
from collections import defaultdict
from google_drive_utils import baixar_arquivo_drive, upload_to_drive

# --- Configurações de Layout (em mm) ---
# Tamanho da folha de corte (exemplo: A0 ou um tamanho personalizado)
FOLHA_LARGURA_MM, FOLHA_ALTURA_MM = 1200, 900 # Exemplo: 1.2m x 0.9m

# Espaçamentos
ESPACAMENTO_DXF_MESMO_FURO = 100  # Espaçamento horizontal entre DXFs do mesmo tipo de furo
ESPACAMENTO_DXF_FURO_DIFERENTE = 200 # Espaçamento horizontal entre grupos de furos diferentes
ESPACAMENTO_LINHA_COR = 200       # Espaçamento vertical entre linhas de cores diferentes
ESPACAMENTO_PLANO_COR = 100       # Espaçamento vertical entre o DXF do plano e a primeira linha de cor
ESPACAMENTO_ENTRE_PLANOS = 300    # Espaçamento vertical entre diferentes planos de corte

# Margens da folha
MARGEM_ESQUERDA = 50
MARGEM_SUPERIOR = 50
MARGEM_INFERIOR = 50

# Mapeamento de cores para visualização no PNG (pode ser ajustado)
COLOR_MAP = {
    'DOU': '#FFD700', # Dourado
    'ROS': '#FFC0CB', # Rosa
    'PRA': '#C0C0C0', # Prata
    'AZU': '#ADD8E6', # Azul Claro (exemplo, adicione conforme necessário)
    'VER': '#90EE90', # Verde Claro (exemplo)
    # Adicione mais conforme os códigos de cor do seu SKU
}
LETTER_MAP = {
    'DOU': 'D',
    'ROS': 'R',
    'PRA': 'P',
    'AZU': 'A',
    'VER': 'V',
    # Adicione mais conforme os códigos de cor do seu SKU
}

# --- Funções Auxiliares ---

def parse_sku(sku: str):
    """
    Analisa a string SKU e extrai as informações relevantes.
    Exemplo: PLAC-3010-2FH-AC-DOU-070-00000
    Grupos: 1-formato, 2-tamanho, 3-furo, 4-material, 5-cor, 6-quantidade, 7-estilo da arte
    """
    parts = sku.split('-')
    if len(parts) != 7:
        print(f"[WARN] SKU '{sku}' não está no formato esperado (7 grupos).")
        return None, None, None # Retorna None se o formato não for o esperado

    hole_type = parts[2] # Grupo 3: tipo de furo
    color_code = parts[4] # Grupo 5: código da cor

    return hole_type, color_code

def calcular_bbox_dxf(msp):
    """
    Calcula o bounding box (caixa delimitadora) de todas as entidades no modelspace de um DXF.
    Retorna (min_x, min_y, max_x, max_y).
    """
    min_x, min_y = float('inf'), float('inf')
    max_x, max_y = float('-inf'), float('-inf')

    for e in msp:
        try:
            bb = e.bbox()
            if bb.extmin and bb.extmax:
                exmin, exmax = bb.extmin, bb.extmax
                min_x = min(min_x, exmin.x)
                min_y = min(min_y, exmin.y)
                max_x = max(max_x, exmax.x)
                max_y = max(max_y, exmax.y)
        except Exception as err:
            # Algumas entidades podem não ter bbox ou causar erro ao calcular
            # print(f"[WARN] Erro ao calcular bbox para entidade {e.dxf.handle}: {err}")
            pass # Ignora entidades que não podem ter bbox

    if min_x == float('inf'): # Nenhum bbox válido encontrado
        return 0, 0, 0, 0 # Retorna um bbox vazio ou um ponto

    return min_x, min_y, max_x, max_y

def gerar_imagem_plano(caminho_dxf_saida: str, plano_info_dxf_path: str, layout_data: dict):
    """
    Gera e salva uma imagem PNG ilustrativa do plano de corte.
    Inclui o DXF do plano de corte e os DXFs dos itens.
    """
    png_path = caminho_dxf_saida.replace('.dxf', '.png')
    
    # Escala mm->px (ex: 1 pixel = 0.1 mm, então 1000 pixels = 100 mm)
    # Ajuste a escala para que a imagem final tenha uma resolução razoável.
    # Ex: se a folha tem 1200mm e queremos 2400px de largura, a escala é 2px/mm
    scale = 2400 / FOLHA_LARGURA_MM # Exemplo: 2 pixels por mm
    
    w_px = int(round(FOLHA_LARGURA_MM * scale))
    h_px = int(round(FOLHA_ALTURA_MM * scale))

    img = Image.new('RGB', (w_px, h_px), 'white')
    draw = ImageDraw.Draw(img)

    # Tenta carregar uma fonte TrueType para melhor qualidade de texto
    font_paths = [
        './DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
        # Adicione outros caminhos de fontes comuns se necessário
    ]
    title_font = ImageFont.load_default() # Fallback
    item_font = ImageFont.load_default() # Fallback

    for fp in font_paths:
        if os.path.exists(fp):
            try:
                title_font = ImageFont.truetype(fp, int(48 * scale / 2)) # Ajusta tamanho da fonte com a escala
                item_font = ImageFont.truetype(fp, int(24 * scale / 2)) # Ajusta tamanho da fonte com a escala
                print(f"[INFO] Fonte carregada de: {fp}")
                break
            except Exception as e:
                print(f"[WARN] Não foi possível carregar fonte de {fp}: {e}")
                continue
    
    # Desenhar o nome do plano de corte no topo
    plan_name_text = os.path.basename(plano_info_dxf_path).replace('.dxf', '')
    bbox_title = draw.textbbox((0, 0), plan_name_text, font=title_font)
    tw, th = bbox_title[2] - bbox_title[0], bbox_title[3] - bbox_title[1]
    draw.text(((w_px - tw) / 2, 10), plan_name_text, fill='black', font=title_font) # Posição fixa no topo

    # Percorre o layout_data para desenhar os retângulos e textos
    # layout_data é uma lista de objetos com { 'dxf_path', 'sku', 'pos_x', 'pos_y', 'width', 'height' }
    for item in layout_data:
        x, y = item['pos_x'], item['pos_y']
        width, height = item['width'], item['height']
        sku = item['sku']

        # Extrair cor do SKU para a visualização
        _, color_code = parse_sku(sku)
        color = COLOR_MAP.get(color_code, '#CCCCCC') # Cinza padrão se a cor não for mapeada
        letter = LETTER_MAP.get(color_code, '?')

        # Converter coordenadas de mm para pixels
        # Lembre-se que o Pillow tem (0,0) no canto superior esquerdo, e DXF no inferior esquerdo.
        # Então, y_px = h_px - (y_mm * scale)
        x_px = int(round(x * scale))
        y_px = int(round(h_px - (y * scale) - (height * scale))) # Ajuste para y do canto superior esquerdo do retângulo

        width_px = int(round(width * scale))
        height_px = int(round(height * scale))

        # Desenhar o retângulo do item
        draw.rectangle([x_px, y_px, x_px + width_px, y_px + height_px], fill=color, outline='black')

        # Desenhar a letra da cor no centro do item
        bbox_letter = draw.textbbox((0, 0), letter, font=item_font)
        lw, lh = bbox_letter[2] - bbox_letter[0], bbox_letter[3] - bbox_letter[1]
        draw.text((x_px + (width_px - lw) / 2, y_px + (height_px - lh) / 2), letter, fill='black', font=item_font)

    # Salvar a imagem PNG
    os.makedirs(os.path.dirname(png_path) or '.', exist_ok=True)
    img.save(png_path)
    print(f"[INFO] Imagem PNG salva: {png_path}")
    return png_path

def compor_dxf_personalizado(
    file_ids_and_skus: list[dict],
    plan_name: str,
    drive_folder_id: str
):
    """
    Componha um novo arquivo DXF organizando os DXFs de entrada
    baseado em cor, tipo de furo e plano de corte.
    Gera um DXF de saída e um PNG de visualização, e os envia para o Drive.

    Args:
        file_ids_and_skus: Lista de dicionários, cada um com 'file_id' do Drive
                           e 'sku' correspondente.
                           Ex: [{'file_id': 'abc', 'sku': 'PLAC-3010-2FH-AC-DOU-070-00000'}]
        plan_name: Nome do plano de corte (ex: "01", "A").
        drive_folder_id: ID da pasta principal do Google Drive.

    Returns:
        Uma tupla (caminho_dxf_saida, caminho_png_saida)
    """
    doc = ezdxf.new('R2010') # Use uma versão do DXF compatível
    msp = doc.modelspace()

    # Estrutura para organizar os DXFs por cor e furo
    # { 'DOU': { '2FH': [ {dxf_entity, original_sku, bbox_width, bbox_height}, ... ] } }
    organized_dxfs = defaultdict(lambda: defaultdict(list))
    
    # Lista para armazenar dados para a geração do PNG
    png_layout_data = []

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
        # O nome do arquivo local pode ser o SKU para garantir unicidade
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
    if not os.path.exists(plano_info_dxf_path):
        print(f"[WARN] DXF do plano de corte '{plano_info_dxf_path}' não encontrado localmente.")
        # Se não encontrar, podemos criar um placeholder ou levantar um erro
        # Por enquanto, vamos prosseguir sem ele, mas o usuário deve garantir que exista.
        plano_info_dxf_path = None # Indica que não há DXF de plano para inserir

    if plano_info_dxf_path:
        try:
            plano_doc = ezdxf.readfile(plano_info_dxf_path)
            plano_msp = plano_doc.modelspace()
            
            # Calcular bbox do plano para posicionamento
            min_x_plano, min_y_plano, max_x_plano, max_y_plano = calcular_bbox_dxf(plano_msp)
            plano_width = max_x_plano - min_x_plano
            plano_height = max_y_plano - min_y_plano

            # Posição inicial para o plano (canto superior esquerdo da folha - margem)
            # O DXF do plano será colocado 100mm acima da primeira linha de cor.
            # Por enquanto, vamos colocá-lo no canto superior esquerdo da folha com margem.
            # O ajuste de 100mm acima da primeira cor será feito no cálculo das posições dos itens.
            
            # Inserir o DXF do plano no documento principal
            # Criar um bloco para o plano de corte para facilitar a inserção
            block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
            if block_name not in doc.blocks:
                blk = doc.blocks.new(name=block_name)
                for ent in plano_msp:
                    blk.add_entity(ent.copy())
            
            # Calcular a posição de inserção do bloco do plano
            # Queremos que o canto inferior esquerdo do bbox do plano esteja em (MARGEM_ESQUERDA, FOLHA_ALTURA_MM - MARGEM_SUPERIOR - plano_height)
            # Para isso, precisamos transladar o bloco para que seu min_x, min_y fique no 0,0 do bloco,
            # e então inserir o bloco na posição desejada.
            
            # Offset para mover o conteúdo do bloco para 0,0
            offset_x_block = -min_x_plano
            offset_y_block = -min_y_plano

            # Posição de inserção do bloco no modelspace
            insert_x = MARGEM_ESQUERDA
            insert_y = FOLHA_ALTURA_MM - MARGEM_SUPERIOR - plano_height # Coloca no topo com margem

            # Adicionar o bloco ao modelspace
            msp.add_blockref(block_name, insert=(insert_x, insert_y))
            print(f"[INFO] DXF do plano de corte '{plan_name}.dxf' inserido.")

            # Adicionar o plano de corte aos dados do PNG para visualização
            png_layout_data.append({
                'dxf_path': plano_info_dxf_path,
                'sku': f"PLANO-{plan_name}", # SKU fictício para identificação
                'pos_x': insert_x,
                'pos_y': insert_y,
                'width': plano_width,
                'height': plano_height
            })

        except ezdxf.DXFStructureError as e:
            print(f"[ERROR] Arquivo DXF do plano de corte '{plano_info_dxf_path}' corrompido ou inválido: {e}")
            plano_info_dxf_path = None
        except Exception as e:
            print(f"[ERROR] Erro ao carregar ou inserir DXF do plano de corte '{plano_info_dxf_path}': {e}")
            plano_info_dxf_path = None


    # --- 3. Posicionar e Inserir DXFs de Itens ---
    current_y = FOLHA_ALTURA_MM - MARGEM_SUPERIOR # Começa do topo, abaixo da margem

    # Se o DXF do plano foi inserido, ajustar a posição inicial dos itens
    if plano_info_dxf_path:
        # A posição Y do plano é FOLHA_ALTURA_MM - MARGEM_SUPERIOR - plano_height
        # A primeira linha de cor deve estar 100mm abaixo da parte inferior do plano.
        # Então, current_y deve ser (FOLHA_ALTURA_MM - MARGEM_SUPERIOR - plano_height) - ESPACAMENTO_PLANO_COR
        # Mas como estamos construindo de baixo para cima no DXF, e o PNG de cima para baixo,
        # precisamos pensar na lógica de coordenadas.
        # Para o DXF, vamos começar a colocar os itens abaixo do plano.
        # A base do plano está em (insert_y). A primeira linha de itens deve começar em insert_y - ESPACAMENTO_PLANO_COR.
        # No entanto, a altura do item também importa.
        
        # Para simplificar, vamos definir a "linha de base" do primeiro item
        # A altura total do plano + espaçamento + altura do primeiro item
        # Vamos calcular a altura de todos os elementos e subtrair da altura da folha
        # para que o layout comece do topo e se expanda para baixo.

        # Para DXF, (0,0) é inferior esquerdo. Para PNG, (0,0) é superior esquerdo.
        # Vamos calcular as posições para o DXF (inferior esquerdo) e depois converter para PNG.
        
        # Altura acumulada do layout
        total_layout_height = 0
        
        # Adiciona a altura do DXF do plano, se houver
        if plano_info_dxf_path:
            total_layout_height += plano_height + ESPACAMENTO_PLANO_COR

        # Calcula a altura total necessária para os itens
        # Precisamos iterar sobre as cores e furos para estimar a altura máxima de cada linha
        # e somar os espaçamentos.
        
        # Para simplificar o posicionamento inicial, vamos assumir que o layout começa
        # na margem inferior e cresce para cima no DXF, e depois ajustamos para o PNG.
        
        current_y_dxf = MARGEM_INFERIOR # Posição Y inicial para o primeiro item (base)
        
        # Se houver um plano, o plano estará acima de tudo.
        # Vamos posicionar os itens primeiro, e depois o plano acima deles.

        # Ordenar cores para um layout consistente (ex: alfabético)
        sorted_colors = sorted(organized_dxfs.keys())

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
                # Pode ser por largura, altura, ou nome do SKU
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
                    # O ponto de referência para a inserção é o canto inferior esquerdo do bbox do DXF
                    offset_x = current_x_dxf - original_min_x
                    offset_y = current_y_dxf - original_min_y

                    # Adicionar entidades ao modelspace
                    for ent in entities:
                        new_ent = ent.copy()
                        new_ent.translate(offset_x, offset_y, 0)
                        msp.add_entity(new_ent)
                    
                    # Adicionar dados para o PNG
                    png_layout_data.append({
                        'dxf_path': f"/tmp/{sku}.dxf", # Usar o caminho temporário para referência
                        'sku': sku,
                        'pos_x': current_x_dxf,
                        'pos_y': current_y_dxf,
                        'width': bbox_width,
                        'height': bbox_height
                    })

                    current_x_dxf += bbox_width # Avança X pela largura do DXF
                    first_dxf_in_group = False
                
                first_hole_type_in_line = False
            
            # Após processar todos os furos para uma cor, avança Y para a próxima linha de cor
            # A altura da linha é determinada pela altura máxima dos DXFs nessa linha + espaçamento
            max_height_in_color_line = 0
            for hole_type in color_group:
                for dxf_item in color_group[hole_type]:
                    max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])
            
            current_y_dxf += max_height_in_color_line + ESPACAMENTO_LINHA_COR
        
        # Ajustar a posição do plano de corte para ficar 100mm acima da primeira linha de cor
        # Isso é um pouco complicado com a abordagem de construir de baixo para cima.
        # Uma alternativa é calcular a altura total do layout e então ajustar todas as coordenadas
        # para que o layout se encaixe na folha, com o plano no topo.

        # Vamos recalcular as posições finais para o PNG e para o DXF,
        # garantindo que o plano esteja 100mm acima da primeira linha de cor.
        
        # Encontre a menor Y (mais baixa) dos itens que foram posicionados
        min_y_items_positioned = float('inf')
        max_y_items_positioned = float('-inf')
        if png_layout_data:
            for item in png_layout_data:
                # Exclui o item do plano de corte se ele já foi adicionado
                if not item['sku'].startswith("PLANO-"):
                    min_y_items_positioned = min(min_y_items_positioned, item['pos_y'])
                    max_y_items_positioned = max(max_y_items_positioned, item['pos_y'] + item['height'])
        
        # Se não há itens, ou se só há o plano, a base é a margem inferior
        if min_y_items_positioned == float('inf'):
            min_y_items_positioned = MARGEM_INFERIOR
            max_y_items_positioned = MARGEM_INFERIOR # Apenas para ter um ponto de referência

        # Ajuste vertical para que o plano de corte fique acima da primeira linha de cor
        # A "primeira linha de cor" é a que tem o menor Y (mais abaixo)
        
        # Se o plano de corte foi inserido, precisamos movê-lo para a posição correta
        if plano_info_dxf_path:
            # A posição Y do plano deve ser: topo_dos_itens + ESPACAMENTO_PLANO_COR
            # Vamos recalcular a posição Y do plano no DXF
            # O ponto de inserção do bloco do plano é seu canto inferior esquerdo.
            # Se o plano tem altura 'plano_height', seu topo está em 'insert_y + plano_height'
            
            # A posição base para o plano deve ser o topo do layout dos itens + espaçamento
            # Vamos calcular o deslocamento vertical total para todo o layout
            
            # Altura total dos itens (do mais baixo ao mais alto)
            height_of_items_layout = max_y_items_positioned - min_y_items_positioned
            
            # Altura total do layout incluindo plano e espaçamentos
            total_content_height = height_of_items_layout
            if plano_info_dxf_path:
                total_content_height += ESPACAMENTO_PLANO_COR + plano_height

            # Se o conteúdo for maior que a folha, podemos ter problemas.
            # Por enquanto, assumimos que cabe.
            
            # Deslocamento para centralizar verticalmente ou alinhar ao topo
            # Vamos alinhar o topo do layout (topo do plano) com a margem superior.
            
            # Posição Y do topo do plano no DXF (será o mais alto)
            top_of_plan_y_dxf = FOLHA_ALTURA_MM - MARGEM_SUPERIOR
            
            # Posição Y do canto inferior esquerdo do bloco do plano
            new_plano_insert_y_dxf = top_of_plan_y_dxf - plano_height
            
            # Deslocamento vertical para todo o conteúdo do DXF
            # Onde o plano está agora vs onde deveria estar
            current_plano_insert_y_dxf = png_layout_data[0]['pos_y'] if png_layout_data and png_layout_data[0]['sku'].startswith("PLANO-") else 0
            
            # Se o plano já foi inserido, precisamos ajustar sua posição e a de todos os outros itens.
            # A abordagem mais simples é:
            # 1. Calcular o layout como se tudo começasse do (MARGEM_ESQUERDA, MARGEM_INFERIOR).
            # 2. Calcular o bbox total do layout resultante.
            # 3. Calcular um deslocamento para mover o layout para a posição desejada na folha.
            # 4. Aplicar este deslocamento a todas as entidades.

            # Re-criar o documento para aplicar o deslocamento global
            final_doc = ezdxf.new('R2010')
            final_msp = final_doc.modelspace()
            
            # Offset para o plano de corte (se houver)
            plano_offset_y = 0
            if plano_info_dxf_path:
                # O plano será colocado acima da primeira linha de cor
                # A primeira linha de cor está em min_y_items_positioned
                # Então, o plano deve começar em min_y_items_positioned + ESPACAMENTO_PLANO_COR
                # E seu topo será em min_y_items_positioned + ESPACAMENTO_PLANO_COR + plano_height
                
                # Para o DXF, vamos posicionar o plano com seu canto inferior esquerdo em:
                # (MARGEM_ESQUERDA, min_y_items_positioned + ESPACAMENTO_PLANO_COR)
                
                # Se o plano já foi adicionado ao png_layout_data, remova-o para re-adicionar com a posição final
                png_layout_data = [item for item in png_layout_data if not item['sku'].startswith("PLANO-")]

                # Inserir o DXF do plano no documento final
                block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
                if block_name not in final_doc.blocks: # Garante que o bloco é criado uma vez
                    blk = final_doc.blocks.new(name=block_name)
                    plano_doc_temp = ezdxf.readfile(plano_info_dxf_path)
                    plano_msp_temp = plano_doc_temp.modelspace()
                    for ent in plano_msp_temp:
                        blk.add_entity(ent.copy())

                plano_insert_x = MARGEM_ESQUERDA
                plano_insert_y = max_y_items_positioned + ESPACAMENTO_PLANO_COR

                final_msp.add_blockref(block_name, insert=(plano_insert_x, plano_insert_y))
                
                # Adicionar o plano de corte aos dados do PNG com a posição final
                png_layout_data.append({
                    'dxf_path': plano_info_dxf_path,
                    'sku': f"PLANO-{plan_name}",
                    'pos_x': plano_insert_x,
                    'pos_y': plano_insert_y,
                    'width': plano_width,
                    'height': plano_height
                })
                
                # Atualizar a altura total do layout
                total_content_height = (plano_insert_y + plano_height) - min_y_items_positioned

            # Calcular o deslocamento vertical para alinhar o layout ao topo da folha (com margem)
            # O topo do layout deve estar em FOLHA_ALTURA_MM - MARGEM_SUPERIOR
            # O ponto mais alto atual do layout é max_y_items_positioned (se não houver plano)
            # ou (plano_insert_y + plano_height) se houver plano.
            
            current_max_y_layout = max([item['pos_y'] + item['height'] for item in png_layout_data]) if png_layout_data else 0
            
            vertical_offset_to_align_top = (FOLHA_ALTURA_MM - MARGEM_SUPERIOR) - current_max_y_layout
            
            # Aplicar o deslocamento a todas as entidades no final_msp e aos dados do PNG
            for item in png_layout_data:
                item['pos_y'] += vertical_offset_to_align_top
                # Se for um bloco (como o plano), também precisamos mover o bloco de referência
                # No ezdxf, o blockref é uma entidade no msp.
                # Para entidades individuais, a translação já foi aplicada.
                # Para blocos, a translação é aplicada ao ponto de inserção.
                
                # Para os itens, eles já foram transladados para suas posições relativas.
                # Agora, precisamos transladar o *conjunto* de todos os itens e o plano.
                # A maneira mais fácil é criar um novo documento e inserir tudo com o offset final.

            # Re-adicionar todos os itens ao final_msp com o offset vertical final
            # Isso é um pouco redundante, mas garante que todas as posições estejam corretas.
            # Vamos refazer a inserção dos itens no final_doc.
            
            # Limpa o final_msp para re-inserir tudo
            final_doc = ezdxf.new('R2010')
            final_msp = final_doc.modelspace()

            # Inserir o DXF do plano (se houver) com a posição final ajustada
            if plano_info_dxf_path:
                block_name = f"PLANO_INFO_{plan_name.replace('.','_')}"
                if block_name not in final_doc.blocks:
                    blk = final_doc.blocks.new(name=block_name)
                    plano_doc_temp = ezdxf.readfile(plano_info_dxf_path)
                    plano_msp_temp = plano_doc_temp.modelspace()
                    for ent in plano_msp_temp:
                        blk.add_entity(ent.copy())
                
                # A posição Y final do plano é a original + vertical_offset_to_align_top
                final_plano_insert_y = (max_y_items_positioned + ESPACAMENTO_PLANO_COR) + vertical_offset_to_align_top
                final_msp.add_blockref(block_name, insert=(MARGEM_ESQUERDA, final_plano_insert_y))
                
                # Atualizar a posição do plano no png_layout_data
                for item in png_layout_data:
                    if item['sku'].startswith("PLANO-"):
                        item['pos_y'] = final_plano_insert_y
                        break

            # Re-inserir os DXFs dos itens com o offset vertical final
            current_y_dxf = (min_y_items_positioned + vertical_offset_to_align_top) # Nova base Y para itens
            
            for color_code in sorted_colors:
                color_group = organized_dxfs[color_code]
                current_x_dxf = MARGEM_ESQUERDA
                
                first_hole_type_in_line = True
                for hole_type in sorted_hole_types:
                    hole_type_group = color_group[hole_type]
                    
                    if not first_hole_type_in_line:
                        current_x_dxf += ESPACAMENTO_DXF_FURO_DIFERENTE
                    
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
                            current_x_dxf += ESPACAMENTO_DXF_MESMO_FURO

                        # Calcular offset para mover o DXF para a posição atual (current_x_dxf, current_y_dxf)
                        offset_x = current_x_dxf - original_min_x
                        offset_y = current_y_dxf - original_min_y

                        for ent in entities:
                            new_ent = ent.copy()
                            new_ent.translate(offset_x, offset_y, 0)
                            final_msp.add_entity(new_ent)
                        
                        # Atualizar a posição no png_layout_data
                        for item in png_layout_data:
                            if item['sku'] == sku and item['pos_x'] == current_x_dxf - bbox_width: # Verifica se é o mesmo item antes do ajuste
                                item['pos_x'] = current_x_dxf
                                item['pos_y'] = current_y_dxf
                                break

                        current_x_dxf += bbox_width
                        first_dxf_in_group = False
                    
                    first_hole_type_in_line = False
                
                max_height_in_color_line = 0
                for hole_type in color_group:
                    for dxf_item in color_group[hole_type]:
                        max_height_in_color_line = max(max_height_in_color_line, dxf_item['bbox_height'])
                
                current_y_dxf += max_height_in_color_line + ESPACAMENTO_LINHA_COR


    # --- 4. Salvar e Gerar PNG ---
    # Nome do arquivo de saída
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y_%H%M%S")
    output_dxf_name = f"Plano de corte {plan_name} {timestamp}.dxf"
    output_png_name = f"Plano de corte {plan_name} {timestamp}.png"

    # Caminhos temporários para salvar localmente antes do upload
    caminho_saida_dxf = f"/tmp/{output_dxf_name}"
    caminho_saida_png = f"/tmp/{output_png_name}"

    os.makedirs(os.path.dirname(caminho_saida_dxf) or '.', exist_ok=True)
    final_doc.saveas(caminho_saida_dxf)
    print(f"[INFO] DXF de saída salvo: {caminho_saida_dxf}")

    # Gerar a imagem PNG
    gerar_imagem_plano(caminho_saida_dxf, plano_info_dxf_path, png_layout_data)
    
    # Retorna os caminhos locais. O upload será feito no main.py.
    return caminho_saida_dxf, caminho_saida_png

