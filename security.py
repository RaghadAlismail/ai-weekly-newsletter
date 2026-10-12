"""Google OpenID Connect, strict email allow-list, CSRF validation."""
import hmac
import json
import os
import secrets
from flask import session, request, abort
from authlib.integrations.flask_client import OAuth

ROLES=('coordinator','content_reviewer','language_reviewer','designer','approver','admin')

def authorized_people():
    raw=os.getenv('AUTHORIZED_USERS_JSON','{}')
    users=json.loads(raw)
    if not isinstance(users,dict):raise ValueError('AUTHORIZED_USERS_JSON must be an email-to-role object')
    normalized={}
    for email,role in users.items():
        if role not in ROLES or '@' not in email:raise ValueError('Invalid authorized user/role')
        normalized[email.casefold().strip()]=role
    return normalized

def init_google(app):
    oauth=OAuth(app)
    if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
        oauth.register(name='google',client_id=os.environ['GOOGLE_CLIENT_ID'],client_secret=os.environ['GOOGLE_CLIENT_SECRET'],server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',client_kwargs={'scope':'openid email profile'})
    return oauth

def verified_identity(userinfo):
    email=(userinfo.get('email') or '').casefold().strip()
    is_verified=userinfo.get('email_verified') in (True,'true')
    role=authorized_people().get(email)
    domain=os.getenv('ALLOWED_GOOGLE_DOMAIN','').casefold().strip()
    if not is_verified or not role or (domain and not email.endswith('@'+domain)):
        return None
    return {'email':email,'name':str(userinfo.get('name') or email)[:120],'role':role, 'sub':str(userinfo.get('sub') or '')}

def csrf_token():
    if '_csrf' not in session:session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']

def enforce_csrf():
    if request.method in ('POST','PUT','PATCH','DELETE'):
        supplied=request.form.get('_csrf') or request.headers.get('X-CSRF-Token','')
        expected=session.get('_csrf')
        if not expected or not supplied or not hmac.compare_digest(str(supplied),str(expected)):abort(400,'CSRF validation failed')
