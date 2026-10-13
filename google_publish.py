"""Private Google Workspace exports using the editor's explicit OAuth consent."""
import os,json,base64,hashlib,io
from flask import current_app,session
from cryptography.fernet import Fernet
from storage import database
SCOPES=['https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/presentations','https://www.googleapis.com/auth/documents']
def token_cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(str(current_app.secret_key).encode()).digest()))
def token_db():
    return database(os.getenv('NEWSLETTER_DATA_DIR','/tmp/newsletter-data'))
def store_google_token(email,token):
    with token_db() as c:
        old=c.execute('SELECT payload FROM google_oauth_tokens WHERE email=?',(email,)).fetchone()
        if old and not token.get('refresh_token'):
            prior=json.loads(token_cipher().decrypt(old['payload'].encode()));token['refresh_token']=prior.get('refresh_token')
        payload=token_cipher().encrypt(json.dumps(token).encode()).decode()
        c.execute('INSERT INTO google_oauth_tokens(email,payload) VALUES(?,?) ON CONFLICT(email) DO UPDATE SET payload=excluded.payload',(email,payload))
def publishing_connected(email):
    with token_db() as c:return c.execute('SELECT email FROM google_oauth_tokens WHERE email=?',(email,)).fetchone() is not None

def get_credentials(scopes=SCOPES):
    from google.oauth2.credentials import Credentials
    email=session.get('email','').casefold()
    with token_db() as c:r=c.execute('SELECT payload FROM google_oauth_tokens WHERE email=?',(email,)).fetchone()
    if not r:raise RuntimeError('Connect Google publishing from the workspace first.')
    token=json.loads(token_cipher().decrypt(r['payload'].encode()))
    granted=set(str(token.get('scope','')).split())
    if not set(scopes).issubset(granted):raise RuntimeError('Reconnect Google publishing and grant the requested document permissions.')
    import datetime
    expiry=datetime.datetime.fromtimestamp(token.get('expires_at',0),datetime.timezone.utc).replace(tzinfo=None)
    creds=Credentials(token=token.get('access_token'),refresh_token=token.get('refresh_token'),token_uri='https://oauth2.googleapis.com/token',client_id=os.environ['GOOGLE_CLIENT_ID'],client_secret=os.environ['GOOGLE_CLIENT_SECRET'],scopes=SCOPES,expiry=expiry)
    if not creds.valid:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        token['access_token']=creds.token;token['expires_at']=creds.expiry.replace(tzinfo=datetime.timezone.utc).timestamp();store_google_token(email,token)
    return creds

def upload_google_file(data,mimetype,target_mimetype,name):
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseUpload
    drive=build('drive','v3',credentials=get_credentials(),cache_discovery=False)
    metadata={'name':name,'mimeType':target_mimetype}
    # Optional folder must be accessible to this app; no shared-drive-wide privileges.
    if os.getenv('GOOGLE_DRIVE_FOLDER_ID'):metadata['parents']=[os.environ['GOOGLE_DRIVE_FOLDER_ID']]
    obj=drive.files().create(body=metadata,media_body=MediaIoBaseUpload(io.BytesIO(data),mimetype=mimetype,resumable=False),fields='id,webViewLink',supportsAllDrives=True).execute()
    return obj['webViewLink'],obj['id']
def create_google_slides(snapshot,deck_bytes):
    return upload_google_file(deck_bytes,'application/vnd.openxmlformats-officedocument.presentationml.presentation','application/vnd.google-apps.presentation',f'نشرة الذكاء الاصطناعي {snapshot["issue"]} - نسخة عربية')
def create_google_short_doc(docx_bytes,snapshot):
    return upload_google_file(docx_bytes,'application/vnd.openxmlformats-officedocument.wordprocessingml.document','application/vnd.google-apps.document',f'مختصر نشرة الذكاء الاصطناعي {snapshot["issue"]}')
