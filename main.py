import os
import shutil
import tempfile
import re
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime, timedelta, timezone
from dateutil.parser import isoparse

# Adicionando prints para depuração no início
print("DEBUG: main.py - Início do carregamento do módulo.")

# Importa as funções utilitárias e de Google Drive
try:
    from google_drive_utils import (
        get_drive_service,
        upload_to_drive,
        mover_arquivos_antigos,
        esvaziar_lixeira_drive,
        listar_todos_arquivos_com_detalhes,
        excluir_arquivo_drive
    )
    print("DEBUG: main.py - google_drive_utils importado com sucesso.")
except ImportError as e:
    print(f"ERROR: main.py - Falha ao importar google_drive_utils: {e}")
    raise

try:
    from dxf_layout_engine import (
        generate_single_plan_layout_data, 
        NoEntitiesFoundError
    )
    print("DEBUG: main.py - dxf_layout_engine importado com sucesso.")
except ImportError as e:
    print(f"ERROR: main.py - Falha ao importar dxf_layout_engine: {e}")
    raise

# Importa ezdxf para a composição final
try:
    import ezdxf
    print("DEBUG: main.py - ezdxf importado com sucesso.")
except ImportError as e:
    print(f"ERROR: main.py - Falha ao importar ezdxf: {e}")
    raise

print("DEBUG: main.py - Todas as importações foram concluídas.")

app = FastAPI()

# --- Modelos de Dados Pydantic ---
class DXFItem(BaseModel):
    id_arquivo_drive: str
    sku: str

class Plan(BaseModel):
    plan_name: str
    items: List[DXFItem]

class CompositionRequest(BaseModel):
    plans: List[Plan]
    id_pasta_entrada_drive: str
    id_pasta_saida_drive: str
    output_filename: str

# IDs de pastas para manutenção
ID_PASTA_SAIDA_DRIVE = "18RIUiRS7SugpUeGOIAxu3gVj9D6-MD2G"
ID_PASTA_ANTIGOS_DRIVE = "1sCb7g9L4I9lJeY-9N-yJj2L92s-YPMi9"
ID_PASTA_PLANOS_DE_CORTE = "18RIUiRS7SugpUeGOIAxu3gVj9D6-MD2G" # Pasta para limpar arquivos mortos

@app.get("/")
def read_root():
    return {"message": "API de Composição DXF está operacional."}

@app.post("/compor-plano")
async def compor_plano_de_corte(request_data: CompositionRequest):
    print(f"[INFO] Recebida nova requisição para compor plano: {request_data.output_filename}")
    
    # --- Criação de um Documento DXF Final ---
    final_doc = ezdxf.new('R2010')
    final_doc.header['$INSUNITS'] = 4  # Milímetros
    final_msp = final_doc.modelspace()
    
    current_x_offset = 0 # Offset horizontal para posicionar os planos
    ESPACAMENTO_ENTRE_PLANOS = 500.0 # Espaçamento em mm
    
    failed_items_global = [] # Lista para acumular todos os IDs de itens que falharam
    
    for plan_data in sorted(request_data.plans, key=lambda p: p.plan_name):
        plan_name = plan_data.plan_name
        items = [{'id_arquivo_drive': item.id_arquivo_drive, 'sku': item.sku} for item in plan_data.items]
        
        print(f"[INFO] Processando plano: {plan_name}")
        
        try:
            # Gera as entidades e posições relativas para o plano atual
            (
                relative_entities_with_coords, 
                layout_width, 
                layout_height,
                failed_ids_this_plan
            ) = generate_single_plan_layout_data(
                file_ids_and_skus=items,
                plan_name=plan_name,
                drive_folder_id=request_data.id_pasta_entrada_drive,
            )
            
            # Adiciona os IDs que falharam neste plano à lista global
            if failed_ids_this_plan:
                failed_items_global.extend(failed_ids_this_plan)

            # Adiciona as entidades ao MSP final, aplicando o offset horizontal
            for ent, _, _ in relative_entities_with_coords:
                ent.translate(current_x_offset, 0, 0)
                final_msp.add_entity(ent)
            
            # Atualiza o offset para o próximo plano
            current_x_offset += layout_width + ESPACAMENTO_ENTRE_PLANOS
            print(f"[INFO] Plano '{plan_name}' adicionado ao layout final. Largura: {layout_width:.2f}, Altura: {layout_height:.2f}")

        except NoEntitiesFoundError as e:
            print(f"[WARN] Plano '{plan_name}' ignorado: {e}")
            # Adiciona todos os IDs de itens deste plano à lista de falhas, pois o plano não foi gerado
            failed_items_global.extend([item['id_arquivo_drive'] for item in items])
            continue # Pula para o próximo plano
        except Exception as e:
            print(f"[ERROR] Erro inesperado ao gerar layout para o plano '{plan_name}': {e}")
            failed_items_global.extend([item['id_arquivo_drive'] for item in items])
            continue # Pula para o próximo plano

    # --- Salvar e Fazer Upload do DXF Final ---
    temp_dir = tempfile.mkdtemp()
    final_dxf_path = os.path.join(temp_dir, request_data.output_filename)
    
    try:
        final_doc.saveas(final_dxf_path)
        print(f"[INFO] DXF final '{request_data.output_filename}' salvo temporariamente em '{final_dxf_path}'.")
        
        # Faz o upload para o Google Drive
        file_id, web_view_link = upload_to_drive(final_dxf_path, request_data.id_pasta_saida_drive)
        
        # Limpa o diretório temporário
        shutil.rmtree(temp_dir)
        
        return {
            "message": "DXF composto e enviado para o Google Drive com sucesso!",
            "dxf_url": web_view_link,
            "file_id": file_id,
            "failed_items": list(set(failed_items_global)) # Remove duplicatas antes de retornar
        }
    except Exception as e:
        # Limpa o diretório temporário em caso de erro
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        print(f"[ERROR] Erro ao salvar ou fazer upload do DXF final: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao finalizar o processo DXF: {e}")

@app.post("/mover-antigos")
async def mover_antigos():
    drive_service = get_drive_service()
    if not drive_service:
        raise HTTPException(status_code=500, detail="Falha ao autenticar com o Google Drive.")
    
    moved_count = mover_arquivos_antigos(drive_service, ID_PASTA_SAIDA_DRIVE, ID_PASTA_ANTIGOS_DRIVE)
    return {"message": f"{moved_count} arquivos foram movidos.", "moved": moved_count}

@app.post("/esvaziar-lixeira")
async def esvaziar_lixeira():
    drive_service = get_drive_service()
    if not drive_service:
        raise HTTPException(status_code=500, detail="Falha ao autenticar com o Google Drive.")
        
    success, message = esvaziar_lixeira_drive(drive_service)
    if not success:
        raise HTTPException(status_code=500, detail=message)
        
    return {"message": message}

@app.post("/excluir-mortos")
async def excluir_arquivos_mortos():
    """
    Endpoint para excluir "arquivos mortos" da pasta de saída do Drive.
    "Arquivos mortos" são definidos como arquivos que correspondem ao padrão "Plano de corte..."
    e são mais antigos que um determinado período (ex: 1 dia).
    """
    try:
        drive_service = get_drive_service()
        if not drive_service:
            raise HTTPException(status_code=500, detail="Falha ao autenticar com o Google Drive.")

        # 1. Listar todos os arquivos na pasta de saída
        print(f"[INFO] Listando arquivos na pasta de destino: {ID_PASTA_PLANOS_DE_CORTE}")
        arquivos_na_pasta = listar_todos_arquivos_com_detalhes(drive_service, ID_PASTA_PLANOS_DE_CORTE)
        
        if not arquivos_na_pasta:
            return {"message": "Nenhum arquivo encontrado na pasta de destino. Nada a fazer."}

        # 2. Definir critérios para "arquivo morto"
        padrao_nome = re.compile(r"^Plano de corte.*\.dxf$", re.IGNORECASE)
        limite_tempo = datetime.now(timezone.utc) - timedelta(days=1)
        
        arquivos_excluidos_count = 0
        erros_count = 0

        # 3. Iterar e excluir arquivos que correspondem aos critérios
        for arquivo in arquivos_na_pasta:
            nome_arquivo = arquivo.get('name')
            id_arquivo = arquivo.get('id')
            data_criacao_str = arquivo.get('createdTime')
            
            if not all([nome_arquivo, id_arquivo, data_criacao_str]):
                continue # Pula arquivos com metadados incompletos

            # Verifica o nome do arquivo
            if padrao_nome.match(nome_arquivo):
                # Verifica a data de criação
                data_criacao = isoparse(data_criacao_str)
                if data_criacao < limite_tempo:
                    print(f"[INFO] Arquivo '{nome_arquivo}' (ID: {id_arquivo}) marcado para exclusão (criado em {data_criacao}).")
                    if excluir_arquivo_drive(drive_service, id_arquivo):
                        arquivos_excluidos_count += 1
                    else:
                        erros_count += 1

        if arquivos_excluidos_count == 0 and erros_count == 0:
            message = "Nenhum arquivo morto (Plano de corte com mais de 1 dia) foi encontrado para excluir."
        else:
            message = f"{arquivos_excluidos_count} arquivos mortos foram excluídos com sucesso."
            if erros_count > 0:
                message += f" {erros_count} arquivos não puderam ser excluídos devido a erros."

        return {"message": message, "deleted_count": arquivos_excluidos_count}

    except Exception as e:
        print(f"[ERROR] Erro crítico no endpoint /excluir-mortos: {e}")
        raise HTTPException(status_code=500, detail=f"Ocorreu um erro interno no servidor: {e}")

print("DEBUG: main.py - Fim do carregamento do módulo. Aplicação FastAPI pronta.")

