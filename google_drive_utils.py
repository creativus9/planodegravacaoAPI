import os
import json
import datetime
import re # Importar módulo de expressões regulares
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# Carrega credenciais direto da variável de ambiente
SERVICE_ACCOUNT_JSON = os.getenv("service_account.json")
if not SERVICE_ACCOUNT_JSON:
    raise Exception("Variável de ambiente 'service_account.json' não foi encontrada. Por favor, configure-a no Railway.")

try:
    info = json.loads(SERVICE_ACCOUNT_JSON)
except json.JSONDecodeError:
    raise Exception("Conteúdo da variável 'service_account.json' não é um JSON válido.")

creds = service_account.Credentials.from_service_account_info(
    info,
    scopes=["https://www.googleapis.com/auth/drive"]
)

drive_service = build('drive', 'v3', credentials=creds)

# O ID da pasta principal do Google Drive, fornecido pelo usuário.
# Este será configurado no main.py ou passado como parâmetro.
# Por enquanto, deixamos como uma variável global para facilitar a referência,
# mas será mais flexível se for passado para as funções.
# Para este novo projeto, o ID é '1fLWrdK6MUhbeyBDvWHjz-2bTmZ2GB0ap'
# No entanto, para manter a flexibilidade, vamos permitir que seja passado como argumento
# ou lido de uma variável de ambiente se necessário.
# Por agora, usaremos o ID fornecido como padrão para as funções.
DEFAULT_FOLDER_ID = "1fLWrdK6MUhbeyBDvWHjz-2bTmZ2GB0ap"


def baixar_arquivo_drive(file_id: str, nome_arquivo_local: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Baixa um arquivo do Google Drive usando seu ID.
    Salva o arquivo em um caminho temporário local e retorna esse caminho.
    """
    local_path = f"/tmp/{nome_arquivo_local}"
    try:
        # Tenta baixar o arquivo
        request = drive_service.files().get_media(fileId=file_id)
        with open(local_path, 'wb') as f:
            # Usa o método iter_content para lidar com arquivos grandes de forma eficiente
            # Embora get_media retorne o conteúdo diretamente, esta é uma boa prática
            # para downloads maiores. Para arquivos pequenos, o 'execute()' já traz tudo.
            data = request.execute()
            f.write(data)
        print(f"[INFO] Arquivo '{nome_arquivo_local}' (ID: {file_id}) baixado para '{local_path}'.")
        return local_path
    except HttpError as error:
        if error.resp.status == 404:
            raise FileNotFoundError(f"Arquivo com ID '{file_id}' não encontrado no Drive.")
        else:
            raise Exception(f"Erro ao baixar arquivo com ID '{file_id}': {error}")
    except Exception as e:
        raise Exception(f"Erro inesperado ao baixar arquivo com ID '{file_id}': {e}")


def buscar_arquivo_personalizado_por_id_e_sku(target_id: str, sku: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Busca um arquivo no Google Drive que contenha o ID (ex: XXXX) e "Arquivo Personalizado"
    no nome, dentro da pasta especificada.
    Retorna o ID do arquivo e seu nome completo no Drive.
    """
    # Escapar caracteres especiais do ID para uso em regex
    escaped_target_id = re.escape(target_id)
    
    # Regex para encontrar o padrão "XXXX - Arquivo Personalizado" ou variações
    # Lida com espaços extras e hífens
    # Ex: "XXXX - Aplique Personalizado", "XXXX- Arquivo Personalizado", "XXXX -Arquivo Personalizado"
    # O re.IGNORECASE é para tornar a busca case-insensitive para "Arquivo Personalizado"
    
    # Construir a query para o Google Drive API
    # Usamos 'contains' para o nome do arquivo, o que é mais flexível que 'name='
    # E filtramos pela pasta pai
    query = f"'{drive_folder_id}' in parents and name contains '{target_id}' and name contains 'Arquivo Personalizado' and mimeType != 'application/vnd.google-apps.folder'"
    
    try:
        response = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = response.get('files', [])

        # Filtrar os resultados usando regex para garantir o padrão exato e flexibilidade
        # e também para tentar corresponder o SKU se necessário (embora o pedido inicial não inclua SKU na busca do nome)
        
        # O padrão pode ser "ID - Arquivo Personalizado" ou "ID-Arquivo Personalizado"
        # O re.IGNORECASE é para "Arquivo Personalizado"
        # O re.escape(target_id) garante que o ID seja tratado literalmente
        pattern = re.compile(rf"^{escaped_target_id}\s*-\s*Arquivo Personalizado.*\.dxf$", re.IGNORECASE)

        found_files = []
        for f in files:
            if pattern.match(f['name']):
                found_files.append(f)

        if not found_files:
            raise FileNotFoundError(f"Nenhum arquivo 'Arquivo Personalizado' com ID '{target_id}' encontrado no Drive.")
        
        # Se houver múltiplos, podemos adicionar lógica para escolher o mais relevante
        # Por enquanto, pegamos o primeiro que corresponde
        return found_files[0]['id'], found_files[0]['name']

    except HttpError as error:
        raise Exception(f"Erro ao buscar arquivo personalizado para ID '{target_id}': {error}")
    except Exception as e:
        raise Exception(f"Erro inesperado ao buscar arquivo personalizado para ID '{target_id}': {e}")


def upload_to_drive(caminho_arquivo_local: str, nome_arquivo_drive: str, mime_type: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Faz upload de um arquivo para o Google Drive e retorna sua URL pública.
    """
    file_metadata = {'name': nome_arquivo_drive, 'parents': [drive_folder_id]}
    media = MediaFileUpload(caminho_arquivo_local, mimetype=mime_type)
    
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        # Define as permissões para que o arquivo seja público (qualquer um pode ler)
        drive_service.permissions().create(
            fileId=file.get('id'), body={'role':'reader','type':'anyone'}
        ).execute()
        public_url = f"https://drive.google.com/file/d/{file.get('id')}/view"
        print(f"[INFO] Arquivo '{nome_arquivo_drive}' enviado ao Drive: {public_url}")
        return public_url
    except HttpError as error:
        raise Exception(f"Erro ao fazer upload do arquivo '{nome_arquivo_drive}': {error}")
    except Exception as e:
        raise Exception(f"Erro inesperado ao fazer upload do arquivo '{nome_arquivo_drive}': {e}")


def mover_arquivos_antigos(drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Move arquivos .dxf e .png com data diferente da atual para subpasta 'arquivo morto'.
    Retorna quantidade movida.
    """
    hoje = datetime.datetime.now().strftime("%d-%m-%Y")
    
    # 1. Garantir que a subpasta 'arquivo morto' exista
    query_folder = f"'{drive_folder_id}' in parents and name='arquivo morto' and mimeType='application/vnd.google-apps.folder'"
    res_folder = drive_service.files().list(q=query_folder, fields="files(id)").execute().get('files', [])
    
    dest_id = None
    if res_folder:
        dest_id = res_folder[0]['id']
        print(f"[INFO] Subpasta 'arquivo morto' encontrada com ID: {dest_id}")
    else:
        try:
            meta = {'name':'arquivo morto','mimeType':'application/vnd.google-apps.folder','parents':[drive_folder_id]}
            folder = drive_service.files().create(body=meta, fields='id').execute()
            dest_id = folder.get('id')
            print(f"[INFO] Subpasta 'arquivo morto' criada com ID: {dest_id}")
        except HttpError as error:
            raise Exception(f"Erro ao criar subpasta 'arquivo morto': {error}")
        except Exception as e:
            raise Exception(f"Erro inesperado ao criar subpasta 'arquivo morto': {e}")

    if not dest_id:
        raise Exception("Não foi possível encontrar ou criar a pasta 'arquivo morto'.")

    # 2. Listar arquivos na pasta principal
    query_files = f"'{drive_folder_id}' in parents and (mimeType='application/dxf' or mimeType='image/png')"
    resp_files = drive_service.files().list(q=query_files, fields="files(id,name,parents)").execute()
    files = resp_files.get('files', [])
    
    moved_count = 0
    for f in files:
        name = f.get('name', '')
        # Verifica se o nome do arquivo contém uma data no formato "DD-MM-YYYY"
        # e se essa data é diferente da data atual.
        # Ex: "Plano de corte 01 25-07-2025.dxf"
        match = re.search(r'(\d{2}-\d{2}-\d{4})\.(dxf|png)$', name)
        
        if match:
            file_date_str = match.group(1)
            if file_date_str != hoje:
                try:
                    # Move o arquivo para a subpasta 'arquivo morto'
                    drive_service.files().update(
                        fileId=f['id'],
                        addParents=dest_id,
                        removeParents=drive_folder_id,
                        fields='id, parents'
                    ).execute()
                    print(f"[INFO] Arquivo '{name}' movido para 'arquivo morto'.")
                    moved_count += 1
                except HttpError as error:
                    print(f"[ERROR] Falha ao mover '{name}': {error}")
                except Exception as e:
                    print(f"[ERROR] Erro inesperado ao mover '{name}': {e}")
    return moved_count

def arquivo_existe_drive(nome_arquivo: str, drive_folder_id: str = DEFAULT_FOLDER_ID, subfolder_name: str = None):
    """
    Verifica se um arquivo existe no Google Drive.
    Retorna True se existe, False se não.
    Pode buscar em uma subpasta específica se 'subfolder_name' for fornecido.
    """
    parent_id = drive_folder_id
    if subfolder_name:
        # Primeiro, encontra o ID da subpasta
        query_subfolder = f"'{drive_folder_id}' in parents and name='{subfolder_name}' and mimeType='application/vnd.google-apps.folder'"
        subfolder_response = drive_service.files().list(q=query_subfolder, fields="files(id)").execute()
        subfolders = subfolder_response.get('files', [])
        if not subfolders:
            print(f"[WARN] Subpasta '{subfolder_name}' não encontrada em '{drive_folder_id}'.")
            return False # Subpasta não existe, então o arquivo não pode estar nela
        parent_id = subfolders[0]['id']

    query_file = f"'{parent_id}' in parents and name='{nome_arquivo}' and mimeType != 'application/vnd.google-apps.folder'"
    try:
        response = drive_service.files().list(q=query_file, fields="files(id)").execute()
        files = response.get('files', [])
        return len(files) > 0
    except HttpError as error:
        print(f"[ERROR] Erro ao verificar existência de '{nome_arquivo}' no Drive: {error}")
        return False
    except Exception as e:
        print(f"[ERROR] Erro inesperado ao verificar existência de '{nome_arquivo}' no Drive: {e}")
        return False
