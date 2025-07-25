from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import os
import datetime

# Importações das funções de composição DXF e de interação com o Google Drive
from dxf_layout_engine import compor_dxf_personalizado # Importa do novo arquivo
from google_drive_utils import upload_to_drive, mover_arquivos_antigos, buscar_arquivo_personalizado_por_id_e_sku

app = FastAPI()

# --- Configuração CORS ---
origins = [
    "http://localhost",
    "http://localhost:5173", # O endereço padrão do seu frontend React em desenvolvimento
    # Adicione a URL do seu Railway aqui quando o deploy for feito:
    # "https://sua-aplicacao-railway.up.railway.app",
    "https://script.google.com", # Para permitir requisições do Google Apps Script
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- Fim da Configuração CORS ---

class ItemEntrada(BaseModel):
    """
    Define o modelo de dados para cada item DXF a ser composto.
    - id_arquivo_drive: O ID do arquivo DXF no Google Drive.
    - sku: O SKU completo do item (ex: PLAC-3010-2FH-AC-DOU-070-00000).
    """
    id_arquivo_drive: str = Field(..., description="ID do arquivo DXF no Google Drive.")
    sku: str = Field(..., description="SKU completo do item (ex: PLAC-3010-2FH-AC-DOU-070-00000).")

class EntradaComposicao(BaseModel):
    """
    Define o modelo de dados para a entrada da requisição POST para composição.
    - itens: Lista de objetos ItemEntrada.
    - nome_plano_corte: O nome do plano de corte (ex: "01", "A").
    - id_pasta_drive: O ID da pasta principal do Google Drive onde os arquivos personalizados estão.
    """
    itens: List[ItemEntrada] = Field(..., min_items=1, description="Lista de itens DXF a serem compostos.")
    nome_plano_corte: str = Field(..., description="Nome do plano de corte (ex: '01', 'A').")
    id_pasta_drive: str = Field(..., description="ID da pasta principal do Google Drive onde os arquivos DXF personalizados estão.")


@app.post("/compor-plano")
async def compor_plano(entrada: EntradaComposicao):
    """
    Endpoint para compor um novo arquivo DXF
    baseado nos itens fornecidos, organizando-os por cor e tipo de furo.
    O arquivo DXF resultante é enviado para o Google Drive.
    """
    if not entrada.itens:
        raise HTTPException(status_code=400, detail="Nenhum item fornecido para composição.")

    print(f"[INFO] Iniciando composição do plano: {entrada.nome_plano_corte}")
    print(f"[INFO] ID da pasta do Drive: {entrada.id_pasta_drive}")
    print(f"[INFO] Total de itens a processar: {len(entrada.itens)}")

    try:
        # Chama a função principal de composição
        caminho_dxf_saida = compor_dxf_personalizado( # Agora retorna apenas o caminho do DXF
            file_ids_and_skus=[item.model_dump() for item in entrada.itens], # Passa como lista de dicionários
            plan_name=entrada.nome_plano_corte,
            drive_folder_id=entrada.id_pasta_drive
        )

        # Faz o upload do arquivo DXF gerado para o Google Drive
        url_dxf = upload_to_drive(caminho_dxf_saida, os.path.basename(caminho_dxf_saida), "application/dxf", entrada.id_pasta_drive)

        # Limpa o arquivo temporário após o upload
        if os.path.exists(caminho_dxf_saida):
            os.remove(caminho_dxf_saida)
            print(f"[INFO] Arquivo temporário DXF removido: {caminho_dxf_saida}")

        print(f"[INFO] Composição do plano '{entrada.nome_plano_corte}' concluída com sucesso.")
        return {
            "message": "Plano de corte DXF composto e enviado ao Google Drive com sucesso!",
            "dxf_url": url_dxf,
        }

    except FileNotFoundError as e:
        print(f"[ERROR] Erro de arquivo não encontrado: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"[ERROR] Erro na composição do plano: {e}")
        raise HTTPException(status_code=500, detail=f"Erro interno ao processar a requisição: {e}")

@app.post("/mover-arquivos-antigos")
async def mover_antigos_endpoint(id_pasta_drive: str):
    """
    Endpoint para mover arquivos DXF e PNG antigos (com data diferente da atual)
    para uma subpasta 'arquivo morto' no Google Drive.
    """
    print(f"[INFO] Iniciando movimentação de arquivos antigos na pasta: {id_pasta_drive}")
    try:
        moved_count = mover_arquivos_antigos(drive_folder_id=id_pasta_drive)
        print(f"[INFO] {moved_count} arquivos antigos movidos com sucesso.")
        return {"message": f"{moved_count} arquivos antigos movidos para 'arquivo morto'."}
    except Exception as e:
        print(f"[ERROR] Erro ao mover arquivos antigos: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao mover arquivos antigos: {e}")

@app.get("/")
async def root():
    return {"message": "API de Composição DXF e Gerenciamento de Drive está online!"}

