from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Dict # Removido Tuple, Any que não são mais necessários aqui
import os
import datetime
# ezdxf não precisa ser importado aqui, pois é usado apenas dentro de dxf_layout_engine

# Importações das funções de composição DXF e de interação com o Google Drive
# CORRIGIDO: Importando APENAS compor_dxf_personalizado, que é a função principal
from dxf_layout_engine import compor_dxf_personalizado
from google_drive_utils import upload_to_drive, mover_arquivos_antigos, buscar_arquivo_personalizado_por_id_e_sku

app = FastAPI()

# --- Configuração CORS ---
origins = [
    "http://localhost",
    "http://localhost:5173", # O endereço padrão do seu frontend React em desenvolvimento
    "https://web-production-ba02.up.railway.app", # Adicionado a URL do seu Railway
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

class PlanData(BaseModel):
    """
    Define o modelo de dados para cada plano de corte dentro da requisição.
    - plan_name: O nome do plano de corte (ex: "01", "A").
    - items: Lista de objetos ItemEntrada associados a este plano.
    """
    plan_name: str = Field(..., description="Nome do plano de corte (ex: '01', 'A').")
    items: List[ItemEntrada] = Field(..., min_items=1, description="Lista de itens DXF para este plano.")

class EntradaComposicao(BaseModel):
    """
    Define o modelo de dados para a entrada da requisição POST para composição.
    Agora aceita uma lista de planos, cada um com seus itens.
    - plans: Lista de objetos PlanData.
    - id_pasta_entrada_drive: O ID da pasta do Google Drive de onde os arquivos DXF personalizados são lidos.
    - id_pasta_saida_drive: O ID da pasta do Google Drive onde o DXF gerado será salvo.
    - output_filename: Opcional. Nome do arquivo DXF de saída. Se não fornecido, será gerado automaticamente.
    """
    plans: List[PlanData] = Field(..., min_items=1, description="Lista de planos de corte a serem compostos.")
    id_pasta_entrada_drive: str = Field(..., description="ID da pasta do Google Drive de onde os arquivos DXF personalizados são lidos.")
    id_pasta_saida_drive: str = Field(..., description="ID da pasta do Google Drive onde o DXF gerado será salvo.")
    output_filename: Optional[str] = Field(None, description="Nome do arquivo DXF de saída. Se não fornecido, será gerado automaticamente.")


@app.post("/compor-plano")
async def compor_plano(entrada: EntradaComposicao):
    """
    Endpoint para compor um novo arquivo DXF combinando múltiplos planos de corte,
    organizando-os verticalmente. O arquivo DXF resultante é enviado para a pasta
    de saída especificada no Google Drive.
    """
    if not entrada.plans:
        raise HTTPException(status_code=400, detail="Nenhum plano fornecido para composição.")

    print(f"[INFO] Iniciando composição de múltiplos planos.")
    print(f"[INFO] ID da pasta de entrada do Drive: {entrada.id_pasta_entrada_drive}")
    print(f"[INFO] ID da pasta de saída do Drive: {entrada.id_pasta_saida_drive}")
    print(f"[INFO] Total de planos a processar: {len(entrada.plans)}")
    if entrada.output_filename:
        print(f"[INFO] Nome de arquivo de saída especificado: {entrada.output_filename}")

    try:
        # Chama a função principal de composição
        # compor_dxf_personalizado agora lida com a criação do DXF e o posicionamento interno
        caminho_dxf_saida = compor_dxf_personalizado(
            plans=[plan.model_dump() for plan in entrada.plans], # Passa a lista de planos como dicionários
            drive_folder_id=entrada.id_pasta_entrada_drive,
            output_filename=entrada.output_filename
        )
        
        # Faz o upload do arquivo DXF gerado para o Google Drive
        url_dxf = upload_to_drive(
            caminho_dxf_saida,
            os.path.basename(caminho_dxf_saida),
            "application/dxf",
            entrada.id_pasta_saida_drive
        )

        # Limpa o arquivo temporário após o upload
        if os.path.exists(caminho_dxf_saida):
            os.remove(caminho_dxf_saida)
            print(f"[INFO] Arquivo temporário DXF removido: {caminho_dxf_saida}")

        print(f"[INFO] Composição de múltiplos planos concluída com sucesso.")
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

