import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
import io
from dateutil.parser import isoparse
from datetime import datetime, timezone, timedelta

# --- Configuração do Serviço do Google Drive ---
# As credenciais são carregadas de uma variável de ambiente no Railway
SERVICE_ACCOUNT_FILE_CONTENT = os.getenv('GOOGLE_CREDENTIALS_JSON')
SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """Autentica e retorna um objeto de serviço do Google Drive."""
    try:
        # Usa o conteúdo JSON diretamente
        creds_dict = os.environ.get('GOOGLE_CREDENTIALS_JSON_DICT')
        if not creds_dict:
            print("[ERROR] Variável de ambiente 'GOOGLE_CREDENTIALS_JSON_DICT' não encontrada.")
            return None
            
        import json
        creds_info = json.loads(creds_dict)
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        service = build('drive', 'v3', credentials=creds)
        print("[INFO] Autenticação com o Google Drive bem-sucedida.")
        return service
    except Exception as e:
        print(f"[ERROR] Falha ao autenticar com o Google Drive: {e}")
        return None

def buscar_arquivo_personalizado_por_id_e_sku(target_id: str, sku: str, drive_folder_id: str):
    drive_service = get_drive_service()
    if not drive_service:
        raise ConnectionError("Falha ao conectar ao Google Drive.")

    query = f"name = '{target_id}.dxf' and '{drive_folder_id}' in parents and trashed = false"
    try:
        results = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = results.get('files', [])
        if items:
            print(f"[INFO] Encontrado arquivo '{items[0]['name']}' (ID: {items[0]['id']}) para o ID lógico '{target_id}'.")
            return items[0]['id'], items[0]['name']
        else:
            raise FileNotFoundError(f"Nenhum arquivo .dxf encontrado para o ID lógico '{target_id}' na pasta especificada.")
    except HttpError as error:
        print(f"[ERROR] Erro ao buscar arquivo por ID lógico '{target_id}': {error}")
        raise

def baixar_arquivo_drive(file_id, local_filename, drive_folder_id):
    drive_service = get_drive_service()
    if not drive_service:
        raise ConnectionError("Falha ao conectar ao Google Drive.")
    
    request = drive_service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = io.BytesIO()
    downloader.write(request.execute())
    
    with open(local_filename, 'wb') as f:
        f.write(downloader.getvalue())
    print(f"[INFO] Arquivo '{local_filename}' (ID: {file_id}) baixado com sucesso.")
    return local_filename

def upload_to_drive(file_path: str, folder_id: str):
    drive_service = get_drive_service()
    if not drive_service:
        raise ConnectionError("Falha ao conectar ao Google Drive.")

    file_metadata = {'name': os.path.basename(file_path), 'parents': [folder_id]}
    media = MediaFileUpload(file_path, mimetype='application/dxf')
    try:
        file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink').execute()
        print(f"[INFO] Upload bem-sucedido. ID do arquivo: {file.get('id')}, Link: {file.get('webViewLink')}")
        return file.get('id'), file.get('webViewLink')
    except HttpError as error:
        print(f"[ERROR] Erro durante o upload para o Drive: {error}")
        raise

def mover_arquivos_antigos(drive_service, pasta_origem_id, pasta_destino_id, dias_antigos=30):
    """Move arquivos mais antigos que 'dias_antigos' de uma pasta para outra."""
    data_limite = (datetime.now(timezone.utc) - timedelta(days=dias_antigos)).isoformat()
    query = f"'{pasta_origem_id}' in parents and modifiedTime < '{data_limite}' and trashed = false"
    
    try:
        results = drive_service.files().list(q=query, fields="files(id, name, parents)").execute()
        items = results.get('files', [])
        
        if not items:
            print(f"[INFO] Nenhum arquivo com mais de {dias_antigos} dias encontrado na pasta de origem.")
            return 0

        moved_count = 0
        for item in items:
            file_id = item['id']
            previous_parents = ",".join(item.get('parents'))
            
            drive_service.files().update(
                fileId=file_id,
                addParents=pasta_destino_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            print(f"[INFO] Arquivo '{item['name']}' movido para a pasta de arquivos antigos.")
            moved_count += 1
            
        return moved_count

    except HttpError as error:
        print(f"[ERROR] Erro ao mover arquivos antigos: {error}")
        return 0

def esvaziar_lixeira_drive(drive_service):
    """Esvazia a lixeira do Google Drive da conta de serviço."""
    try:
        drive_service.files().emptyTrash().execute()
        print("[INFO] Lixeira do Google Drive esvaziada com sucesso.")
        return True, "Lixeira esvaziada com sucesso."
    except HttpError as error:
        print(f"[ERROR] Erro ao tentar esvaziar a lixeira: {error}")
        return False, f"Erro ao esvaziar a lixeira: {error}"

def listar_todos_arquivos_com_detalhes(drive_service, folder_id):
    """
    Lista todos os arquivos em uma pasta específica do Drive, incluindo seus IDs, nomes e data de criação.
    """
    query = f"'{folder_id}' in parents and trashed = false"
    files = []
    page_token = None
    try:
        while True:
            response = drive_service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name, createdTime)',
                pageToken=page_token
            ).execute()
            
            files.extend(response.get('files', []))
            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
        print(f"[INFO] Encontrados {len(files)} arquivos na pasta {folder_id}.")
        return files
    except HttpError as error:
        print(f"[ERROR] Erro ao listar arquivos na pasta {folder_id}: {error}")
        return []

def excluir_arquivo_drive(drive_service, file_id):
    """
    Exclui permanentemente um arquivo do Google Drive.
    """
    try:
        drive_service.files().delete(fileId=file_id).execute()
        print(f"[INFO] Arquivo com ID '{file_id}' excluído permanentemente.")
        return True
    except HttpError as error:
        print(f"[ERROR] Erro ao excluir o arquivo com ID '{file_id}': {error}")
        return False

