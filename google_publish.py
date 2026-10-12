"""Native Google Slides publisher using a placeholder-tagged template.
Requires GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_SLIDES_TEMPLATE_ID, GOOGLE_DRIVE_FOLDER_ID.
The template is expected to have slide 1 cover and slides 2-11 article placeholders.
Each repeated placeholder is scoped to its slide pageObjectId.
"""
import os
from google.oauth2 import service_account
import json
from googleapiclient.discovery import build
SCOPES=['https://www.googleapis.com/auth/drive.file','https://www.googleapis.com/auth/presentations']
def get_credentials(scopes):
    raw=os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON','').strip()
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw),scopes=scopes)
    path=os.getenv('GOOGLE_APPLICATION_CREDENTIALS','')
    if path:
        return service_account.Credentials.from_service_account_file(path,scopes=scopes)
    raise RuntimeError('Google publishing credentials are not configured')

def create_google_slides(snapshot):
    missing=[k for k in ('GOOGLE_SLIDES_TEMPLATE_ID','GOOGLE_DRIVE_FOLDER_ID') if not os.getenv(k)]
    if missing:raise RuntimeError('Missing '+', '.join(missing))
    creds=get_credentials(SCOPES)
    drive=build('drive','v3',credentials=creds,cache_discovery=False)
    slides=build('slides','v1',credentials=creds,cache_discovery=False)
    template=os.environ['GOOGLE_SLIDES_TEMPLATE_ID'];folder=os.environ['GOOGLE_DRIVE_FOLDER_ID']
    copy=drive.files().copy(fileId=template,body={'name':f'نشرة الذكاء الاصطناعي {snapshot["issue"]} - نسخة عربية','parents':[folder]},fields='id,webViewLink',supportsAllDrives=True).execute()
    sid=copy['id']
    presentation=slides.presentations().get(presentationId=sid).execute();pages=presentation.get('slides',[])
    if len(pages)<11:raise RuntimeError('Google Slides template must have 11 slides (cover and 10 news slides).')
    def replace(old,new,page):return {'replaceAllText':{'containsText':{'text':old,'matchCase':True},'replaceText':str(new),'pageObjectIds':[page]}}
    cmds=[replace('{{ISSUE}}',snapshot['issue'],pages[0]['objectId']),replace('{{DATE}}',snapshot['date'],pages[0]['objectId'])]
    for x,a in enumerate(snapshot['articles']):
        pg=pages[x+1]['objectId']
        for old,key in [('{{TITLE}}','headline'),('{{BODY}}','body'),('{{CATEGORY}}','category'),('{{URL}}','url')]:cmds.append(replace(old,a[key],pg))
        # Only replace images after safe upload/approval and explicit asset hosting is implemented.
        # Native replaceImage needs publicly fetchable URI; never use unlicensed stock previews.
    slides.presentations().batchUpdate(presentationId=sid,body={'requests':cmds}).execute()
    return f'https://docs.google.com/presentation/d/{sid}/edit',sid

def create_google_short_doc(docx_bytes,snapshot):
    """Convert generated short DOCX into native Google Doc in the issue folder."""
    from googleapiclient.http import MediaIoBaseUpload
    import io
    missing=[k for k in ('GOOGLE_DRIVE_FOLDER_ID',) if not os.getenv(k)]
    if missing: raise RuntimeError('Missing '+', '.join(missing))
    creds=get_credentials(SCOPES+['https://www.googleapis.com/auth/documents'])
    drive=build('drive','v3',credentials=creds,cache_discovery=False)
    media=MediaIoBaseUpload(io.BytesIO(docx_bytes),mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',resumable=False)
    obj=drive.files().create(body={'name':f'مختصر نشرة الذكاء الاصطناعي {snapshot["issue"]}','mimeType':'application/vnd.google-apps.document','parents':[os.environ['GOOGLE_DRIVE_FOLDER_ID']]},media_body=media,fields='id,webViewLink',supportsAllDrives=True).execute()
    return obj.get('webViewLink') or ('https://docs.google.com/document/d/'+obj['id']+'/edit'),obj['id']
