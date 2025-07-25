import ezdxf

def parse_sku(sku: str):
    """
    Analisa a string SKU e extrai as informações relevantes.
    Exemplo: PLAC-3010-2FH-AC-DOU-070-00000
    Grupos: 1-formato, 2-tamanho, 3-furo, 4-material, 5-cor, 6-quantidade, 7-estilo da arte
    """
    parts = sku.split('-')
    if len(parts) != 7:
        print(f"[WARN] SKU '{sku}' não está no formato esperado (7 grupos).")
        return None, None # Retorna None se o formato não for o esperado

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

