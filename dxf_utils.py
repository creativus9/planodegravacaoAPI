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
    Usa msp.get_extents() para uma abordagem mais robusta.
    """
    try:
        # get_extents() retorna (extmin, extmax) onde extmin e extmax são Vec3 objects
        extmin, extmax = msp.get_extents()

        # Verifica se os extents são válidos (não infinitos ou NaN)
        # Vec3 objects têm atributos x, y, z
        if not all(map(lambda c: c is not None and not float('inf') in c and not float('-inf') in c and not float('nan') in c, [extmin, extmax])):
            print(f"[WARN] get_extents() retornou valores inválidos: extmin={extmin}, extmax={extmax}")
            return 0, 0, 0, 0

        min_x, min_y = extmin.x, extmin.y
        max_x, max_y = extmax.x, extmax.y

        # Basic validation: if min_x/y is greater than max_x/y, it means no valid geometry
        if min_x >= max_x or min_y >= max_y:
            print(f"[WARN] Bounding box inválido (min >= max): min_x={min_x}, max_x={max_x}, min_y={min_y}, max_y={max_y}")
            return 0, 0, 0, 0

        return min_x, min_y, max_x, max_y
    except Exception as e:
        print(f"[ERROR] Erro ao calcular bbox com get_extents(): {e}")
        return 0, 0, 0, 0 # Retorna 0 se houver qualquer erro

