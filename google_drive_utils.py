import os
import json
import datetime
import re
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

print("DEBUG: google_drive_utils.py - Início do carregamento do módulo.")

# Carrega credenciais direto da variável de ambiente
SERVICE_ACCOUNT_JSON = os.getenv("SERVICE_ACCOUNT_JSON") # Alterado para maiúsculas, é uma convenção comum
if not SERVICE_ACCOUNT_JSON:
    print("ERROR: google_drive_utils.py - Variável de ambiente 'SERVICE_ACCOUNT_JSON' não foi encontrada.")
    raise Exception("Variável de ambiente 'SERVICE_ACCOUNT_JSON' não foi encontrada. Por favor, configure-a no Railway.")

try:
    info = json.loads(SERVICE_ACCOUNT_JSON)
    print("DEBUG: google_drive_utils.py - SERVICE_ACCOUNT_JSON carregado e parseado com sucesso.")
except json.JSONDecodeError as e:
    print(f"ERROR: google_drive_utils.py - Conteúdo da variável 'SERVICE_ACCOUNT_JSON' não é um JSON válido: {e}")
    raise Exception(f"Conteúdo da variável 'SERVICE_ACCOUNT_JSON' não é um JSON válido: {e}")
except Exception as e:
    print(f"ERROR: google_drive_utils.py - Erro inesperado ao carregar SERVICE_ACCOUNT_JSON: {e}")
    raise Exception(f"Erro inesperado ao carregar SERVICE_ACCOUNT_JSON: {e}")

try:
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=["https://www.googleapis.com/auth/drive"]
    )
    print("DEBUG: google_drive_utils.py - Credenciais criadas com sucesso.")
except Exception as e:
    print(f"ERROR: google_drive_utils.py - Erro ao criar credenciais do serviço: {e}")
    raise Exception(f"Erro ao criar credenciais do serviço: {e}")

try:
    drive_service = build('drive', 'v3', credentials=creds)
    print("DEBUG: google_drive_utils.py - Serviço do Google Drive construído com sucesso.")
except Exception as e:
    print(f"ERROR: google_drive_utils.py - Erro ao construir o serviço do Google Drive: {e}")
    raise Exception(f"Erro ao construir o serviço do Google Drive: {e}")


# O ID da pasta principal do Google Drive, fornecido pelo usuário.
# Este será configurado no main.py ou passado como parâmetro.
# Por enquanto, deixamos como uma variável global para facilitar a referência,
# mas será mais flexível se for passado para as funções.
# Para este novo projeto, o ID é '1fLWrdK6MUhbeyBDvWHjz-2bTmZ2GB0ap'
# No entanto, para manter a flexibilidade, vamos permitir que seja passado como argumento
# ou lido de uma variável de ambiente se necessário.
# Por agora, usaremos o ID fornecido como padrão para as funções.
DEFAULT_FOLDER_ID = "1fLWrdK6MUhbeyBDvWHjz-2bTmZ2GB0ap"
print("DEBUG: google_drive_utils.py - DEFAULT_FOLDER_ID definido.")


def baixar_arquivo_drive(file_id: str, nome_arquivo_local: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Baixa um arquivo do Google Drive usando seu ID.
    Salva o arquivo em um caminho temporário local e retorna esse caminho.
    """
    print(f"DEBUG: baixar_arquivo_drive() - Tentando baixar arquivo ID: {file_id}, Nome: {nome_arquivo_local}")
    local_path = f"/tmp/{nome_arquivo_local}"
    try:
        # Tenta baixar o arquivo
        request = drive_service.files().get_media(fileId=file_id)
        with open(local_path, 'wb') as f:
            data = request.execute()
            f.write(data)
        print(f"[INFO] Arquivo '{nome_arquivo_local}' (ID: {file_id}) baixado para '{local_path}'.")
        return local_path
    except HttpError as error:
        if error.resp.status == 404:
            print(f"ERROR: baixar_arquivo_drive() - Arquivo com ID '{file_id}' não encontrado: {error}")
            raise FileNotFoundError(f"Arquivo com ID '{file_id}' não encontrado no Drive.")
        else:
            print(f"ERROR: baixar_arquivo_drive() - Erro HTTP ao baixar arquivo com ID '{file_id}': {error}")
            raise Exception(f"Erro ao baixar arquivo com ID '{file_id}': {error}")
    except Exception as e:
        print(f"ERROR: baixar_arquivo_drive() - Erro inesperado ao baixar arquivo com ID '{file_id}': {e}")
        raise Exception(f"Erro inesperado ao baixar arquivo com ID '{file_id}': {e}")


def buscar_arquivo_personalizado_por_id_e_sku(target_id: str, sku: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Busca um arquivo no Google Drive que contenha o ID (ex: XXXX) e "Arquivo Personalizado"
    no nome, dentro da pasta especificada.
    Retorna o ID do arquivo e seu nome completo no Drive.
    """
    print(f"DEBUG: buscar_arquivo_personalizado_por_id_e_sku() - Buscando arquivo para ID: {target_id}, SKU: {sku}")
    escaped_target_id = re.escape(target_id)
    
    query = f"'{drive_folder_id}' in parents and name contains '{target_id}' and name contains 'Arquivo Personalizado' and mimeType != 'application/vnd.google-apps.folder'"
    
    try:
        response = drive_service.files().list(q=query, fields="files(id, name)").execute()
        files = response.get('files', [])

        pattern = re.compile(rf"^{escaped_target_id}\s*-\s*Arquivo Personalizado.*\.dxf$", re.IGNORECASE)

        found_files = []
        for f in files:
            if pattern.match(f['name']):
                found_files.append(f)

        if not found_files:
            print(f"ERROR: buscar_arquivo_personalizado_por_id_e_sku() - Nenhum arquivo 'Arquivo Personalizado' com ID '{target_id}' encontrado.")
            raise FileNotFoundError(f"Nenhum arquivo 'Arquivo Personalizado' com ID '{target_id}' encontrado no Drive.")
        
        print(f"DEBUG: buscar_arquivo_personalizado_por_id_e_sku() - Arquivo encontrado: {found_files[0]['name']}")
        return found_files[0]['id'], found_files[0]['name']

    except HttpError as error:
        print(f"ERROR: buscar_arquivo_personalizado_por_id_e_sku() - Erro HTTP: {error}")
        raise Exception(f"Erro ao buscar arquivo personalizado para ID '{target_id}': {error}")
    except Exception as e:
        print(f"ERROR: buscar_arquivo_personalizado_por_id_e_sku() - Erro inesperado: {e}")
        raise Exception(f"Erro inesperado ao buscar arquivo personalizado para ID '{target_id}': {e}")


def upload_to_drive(caminho_arquivo_local: str, nome_arquivo_drive: str, mime_type: str, drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Faz upload de um arquivo para o Google Drive e retorna sua URL pública.
    """
    print(f"DEBUG: upload_to_drive() - Tentando upload de: {nome_arquivo_drive}")
    file_metadata = {'name': nome_arquivo_drive, 'parents': [drive_folder_id]}
    media = MediaFileUpload(caminho_arquivo_local, mimetype=mime_type)
    
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        drive_service.permissions().create(
            fileId=file.get('id'), body={'role':'reader','type':'anyone'}
        ).execute()
        public_url = f"https://drive.google.com/file/d/{file.get('id')}/view"
        print(f"[INFO] Arquivo '{nome_arquivo_drive}' enviado ao Drive: {public_url}")
        return public_url
    except HttpError as error:
        print(f"ERROR: upload_to_drive() - Erro HTTP: {error}")
        raise Exception(f"Erro ao fazer upload do arquivo '{nome_arquivo_drive}': {error}")
    except Exception as e:
        print(f"ERROR: upload_to_drive() - Erro inesperado: {e}")
        raise Exception(f"Erro inesperado ao fazer upload do arquivo '{nome_arquivo_drive}': {e}")


def mover_arquivos_antigos(drive_folder_id: str = DEFAULT_FOLDER_ID):
    """
    Move arquivos .dxf e .png com data diferente da atual para subpasta 'arquivo morto'.
    Retorna quantidade movida.
    """
    print(f"DEBUG: mover_arquivos_antigos() - Iniciando para pasta: {drive_folder_id}")
    hoje = datetime.datetime.now().strftime("%d-%m-%Y")
    
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
            print(f"ERROR: mover_arquivos_antigos() - Erro HTTP ao criar subpasta 'arquivo morto': {error}")
            raise Exception(f"Erro ao criar subpasta 'arquivo morto': {error}")
        except Exception as e:
            print(f"ERROR: mover_arquivos_antigos() - Erro inesperado ao criar subpasta 'arquivo morto': {e}")
            raise Exception(f"Erro inesperado ao criar subpasta 'arquivo morto': {e}")

    if not dest_id:
        print("ERROR: mover_arquivos_antigos() - Não foi possível encontrar ou criar a pasta 'arquivo morto'.")
        raise Exception("Não foi possível encontrar ou criar a pasta 'arquivo morto'.")

    query_files = f"'{drive_folder_id}' in parents and (mimeType='application/dxf' or mimeType='image/png')"
    resp_files = drive_service.files().list(q=query_files, fields="files(id,name,parents)").execute()
    files = resp_files.get('files', [])
    
    moved_count = 0
    for f in files:
        name = f.get('name', '')
        match = re.search(r'(\d{2}-\d{2}-\d{4})\.(dxf|png)$', name)
        
        if match:
            file_date_str = match.group(1)
            if file_date_str != hoje:
                try:
                    drive_service.files().update(
                        fileId=f['id'],
                        addParents=dest_id,
                        removeParents=drive_folder_id,
                        fields='id, parents'
                    ).execute()
                    print(f"[INFO] Arquivo '{name}' movido para 'arquivo morto'.")
                    moved_count += 1
                except HttpError as error:
                    print(f"[ERROR] mover_arquivos_antigos() - Falha HTTP ao mover '{name}': {error}")
                except Exception as e:
                    print(f"[ERROR] mover_arquivos_antigos() - Erro inesperado ao mover '{name}': {e}")
    print(f"DEBUG: mover_arquivos_antigos() - Concluído. Movidos: {moved_count}")
    return moved_count

def arquivo_existe_drive(nome_arquivo: str, drive_folder_id: str = DEFAULT_FOLDER_ID, subfolder_name: str = None):
    """
    Verifica se um arquivo existe no Google Drive.
    Retorna True se existe, False se não.
    Pode buscar em uma subpasta específica se 'subfolder_name' for fornecido.
    """
    print(f"DEBUG: arquivo_existe_drive() - Verificando existência de '{nome_arquivo}' em '{drive_folder_id}' (subpasta: {subfolder_name})")
    parent_id = drive_folder_id
    if subfolder_name:
        query_subfolder = f"'{drive_folder_id}' in parents and name='{subfolder_name}' and mimeType='application/vnd.google-apps.folder'"
        subfolder_response = drive_service.files().list(q=query_subfolder, fields="files(id)").execute()
        subfolders = subfolder_response.get('files', [])
        if not subfolders:
            print(f"[WARN] Subpasta '{subfolder_name}' não encontrada em '{drive_folder_id}'.")
            return False
        parent_id = subfolders[0]['id']

    query_file = f"'{parent_id}' in parents and name='{nome_arquivo}' and mimeType != 'application/vnd.google-apps.folder'"
    try:
        response = drive_service.files().list(q=query_file, fields="files(id)").execute()
        files = response.get('files', [])
        print(f"DEBUG: arquivo_existe_drive() - Encontrados {len(files)} arquivos para '{nome_arquivo}'.")
        return len(files) > 0
    except HttpError as error:
        print(f"ERROR: arquivo_existe_drive() - Erro HTTP ao verificar existência: {error}")
        return False
    except Exception as e:
        print(f"ERROR: arquivo_existe_drive() - Erro inesperado ao verificar existência: {e}")
        return False

print("DEBUG: google_drive_utils.py - Fim do carregamento do módulo.")
