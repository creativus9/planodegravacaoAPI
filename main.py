from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional, Tuple, Any
import os
import datetime
import ezdxf # Importa ezdxf aqui

# Importações das funções de composição DXF e de interação com o Google Drive
from dxf_layout_engine import generate_single_plan_layout_data, FOLHA_LARGURA_MM, ESPACAMENTO_LINHA_COR, NoEntitiesFoundError # Importa a nova função, constantes e a exceção
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
    """
    plan_name: str = Field(..., description="Nome do plano de corte (ex: '01', 'A').")
    items: List[ItemEntrada] = Field(..., min_items=1, description="Lista de itens DXF para este plano.")

class EntradaComposicao(BaseModel):
    """
    Define o modelo de dados para a entrada da requisição POST para composição.
    - plans: Lista de objetos PlanData, cada um representando um plano de corte.
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

    # Cria um novo documento DXF principal
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()

    # Variáveis para controlar o posicionamento vertical global
    current_y_offset_global = 0.0 # Começa do fundo do documento e cresce para cima
    max_overall_width = 0.0

    # Ordena os planos pelo nome para garantir uma ordem consistente (ex: 01, 02, A, B)
    sorted_plans = sorted(entrada.plans, key=lambda p: p.plan_name)

    try:
        for i, plan_data in enumerate(sorted_plans):
            print(f"[INFO] Processando plano '{plan_data.plan_name}' ({i+1}/{len(sorted_plans)})...")
            
            try:
                # Gera os dados do layout para um único plano
                entities_with_relative_coords, layout_width, layout_height = \
                    generate_single_plan_layout_data(
                        file_ids_and_skus=[item.model_dump() for item in plan_data.items],
                        plan_name=plan_data.plan_name,
                        drive_folder_id=entrada.id_pasta_entrada_drive
                    )
                
                # Se a função retornar sem levantar exceção, mas a lista de entidades estiver vazia,
                # isso é um problema. No novo dxf_layout_engine, isso levantaria NoEntitiesFoundError.
                if not entities_with_relative_coords:
                    print(f"[WARN] Plano '{plan_data.plan_name}' não gerou entidades visíveis. Pulando.")
                    continue # Ou levantar um erro mais específico aqui se cada plano for crítico

                # Atualiza a largura máxima geral do documento
                max_overall_width = max(max_overall_width, layout_width)

                # Adiciona as entidades do plano atual ao modelspace principal, com o offset vertical
                for ent, x_rel, y_rel in entities_with_relative_coords:
                    # O (x_rel, y_rel) já é relativo ao canto inferior esquerdo do layout do plano.
                    # Precisamos transladar para a posição global no documento principal.
                    # current_y_offset_global é a base Y para o plano atual.
                    new_ent = ent.copy() # Copia a entidade novamente para o novo documento
                    new_ent.translate(0, current_y_offset_global, 0) # Aplica o offset vertical
                    msp.add_entity(new_ent)
                    
                print(f"[DEBUG] Plano '{plan_data.plan_name}' adicionado ao DXF principal na altura Y: {current_y_offset_global:.2f} mm.")

                # Atualiza o offset Y global para o próximo plano
                # Adiciona a altura do layout do plano atual mais um espaçamento entre planos
                current_y_offset_global += layout_height + ESPACAMENTO_LINHA_COR # Reutiliza ESPACAMENTO_LINHA_COR para planos

            except NoEntitiesFoundError as e:
                print(f"[ERROR] Erro na geração do layout para o plano '{plan_data.plan_name}': {e}")
                # Se um plano específico não gerou entidades, consideramos uma falha para a requisição inteira.
                # Isso impede a geração de um DXF incompleto ou vazio.
                raise HTTPException(status_code=400, detail=f"Falha ao gerar layout para o plano '{plan_data.plan_name}': {e}")
            except FileNotFoundError as e:
                print(f"[ERROR] Erro de arquivo não encontrado para o plano '{plan_data.plan_name}': {e}")
                raise HTTPException(status_code=404, detail=f"Arquivo necessário não encontrado para o plano '{plan_data.plan_name}': {e}")
            except Exception as e:
                print(f"[ERROR] Erro inesperado ao processar plano '{plan_data.plan_name}': {e}")
                raise HTTPException(status_code=500, detail=f"Erro interno ao processar plano '{plan_data.plan_name}': {e}")

        # Verifica se alguma entidade foi realmente adicionada ao documento principal
        if not msp:
            raise HTTPException(status_code=400, detail="Nenhuma entidade DXF válida foi gerada para nenhum dos planos fornecidos.")

        # Nome do arquivo de saída
        if entrada.output_filename:
            output_dxf_name = entrada.output_filename
        else:
            timestamp = datetime.datetime.now().strftime("%d-%m-%Y_%H%M%S")
            # Gera um nome de arquivo com todos os planos envolvidos
            plan_names_in_filename = " - ".join(p.plan_name for p in sorted_plans)
            output_dxf_name = f"Plano de Gravação {plan_names_in_filename} {timestamp}.dxf"

        # Caminho temporário para salvar localmente antes do upload
        caminho_saida_dxf = f"/tmp/{output_dxf_name}"

        os.makedirs(os.path.dirname(caminho_saida_dxf) or '.', exist_ok=True)
        doc.saveas(caminho_saida_dxf)
        print(f"[INFO] DXF de saída salvo: {caminho_saida_dxf}")
        
        # Faz o upload do arquivo DXF gerado para o Google Drive
        url_dxf = upload_to_drive(
            caminho_saida_dxf,
            os.path.basename(caminho_saida_dxf),
            "application/dxf",
            entrada.id_pasta_saida_drive
        )

        # Limpa o arquivo temporário após o upload
        if os.path.exists(caminho_saida_dxf):
            os.remove(caminho_saida_dxf)
            print(f"[INFO] Arquivo temporário DXF removido: {caminho_saida_dxf}")

        print(f"[INFO] Composição de múltiplos planos concluída com sucesso.")
        return {
            "message": "Plano de corte DXF composto e enviado ao Google Drive com sucesso!",
            "dxf_url": url_dxf,
        }

    except HTTPException as e:
        # Re-levanta HTTPException para que o FastAPI a capture e retorne ao cliente
        raise e
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
