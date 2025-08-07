import aiohttp
from typing import Dict, Any, Optional
from authlib.integrations.starlette_client import OAuth as StarletteOauth, OAuthError as AuthlibOAuthError
from fastapi import Request
from app.config.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI
from app.schemas.auth import OAuthUserInfo

# Inisialisasi OAuth client
oauth = StarletteOauth()
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile',
        'prompt': 'consent'
    }
)

class OAuthError(Exception):
    """Custom exception untuk error OAuth"""
    pass

async def get_google_auth_url(state: str = None) -> str:
    """
    Generate URL untuk autentikasi Google OAuth2.
    
    Fungsi ini tetap disediakan untuk kompatibilitas dengan kode lama,
    tetapi implementasinya menggunakan authlib.
    """
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'email profile',
        'access_type': 'offline',
        'prompt': 'consent'
    }
    
    # Tambahkan state parameter jika ada
    if state:
        params['state'] = state
    
    query_string = '&'.join([f"{key}={value}" for key, value in params.items()])
    return f"https://accounts.google.com/o/oauth2/auth?{query_string}"

async def authorize_google_redirect(request: Request, state: str = None) -> str:
    """
    Fungsi baru yang menggunakan Authlib untuk menghasilkan redirect URL.
    Ini lebih direkomendasikan daripada get_google_auth_url.
    """
    try:
        return await oauth.google.authorize_redirect(request, GOOGLE_REDIRECT_URI, state=state)
    except AuthlibOAuthError as e:
        raise OAuthError(f"Failed to generate auth URL: {str(e)}")

async def exchange_google_code(code: str) -> Dict[str, Any]:
    """
    Exchange kode otorisasi untuk token Google OAuth.
    
    Fungsi ini tetap disediakan untuk kompatibilitas dengan kode lama,
    tetapi implementasinya diubah menggunakan aiohttp.
    """
    token_url = "https://oauth2.googleapis.com/token"
    
    data = {
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': GOOGLE_REDIRECT_URI
    }
    
    # Menggunakan aiohttp untuk HTTP request asinkron
    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data=data) as response:
            if response.status != 200:
                text = await response.text()
                raise OAuthError(f"Failed to exchange code: {text}")
            
            return await response.json()

async def get_google_token_and_userinfo(request: Request) -> tuple:
    """
    Fungsi baru yang menggunakan Authlib untuk mendapatkan token dan info user.
    """
    try:
        # Debug
        print("Starting OAuth token exchange...")
        
        # Authlib menangani pertukaran kode dan validasi token
        token = await oauth.google.authorize_access_token(request)
        print(f"Token received from Google: {list(token.keys())}")
        
        if not token or 'access_token' not in token:
            raise OAuthError("Failed to get access token")
        
        # Dapatkan user info menggunakan access_token
        # JANGAN MENGGUNAKAN parse_id_token yang bermasalah
        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {token['access_token']}"}
            async with session.get(userinfo_endpoint, headers=headers) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise OAuthError(f"Failed to get user info: {text}")
                
                user_data = await resp.json()
                print(f"User info fetched directly: {user_data.get('email')}")
        
        if 'email' not in user_data:
            print(f"User info missing email: {user_data.keys()}")
            raise OAuthError("User info missing email")
        
        # Buat objek user info
        return token, OAuthUserInfo(
            provider="google",
            id=user_data['sub'],
            email=user_data['email'],
            name=user_data.get('name', ''),
            avatar=user_data.get('picture', None)
        )
    except AuthlibOAuthError as e:
        print(f"Authlib OAuth error: {str(e)}")
        raise OAuthError(f"Authlib error: {str(e)}")
    except Exception as e:
        print(f"Unexpected error in get_google_token_and_userinfo: {str(e)}")
        import traceback
        traceback.print_exc()
        raise OAuthError(f"Unexpected error: {str(e)}")

async def get_google_user_info(access_token: str) -> OAuthUserInfo:
    """
    Mendapatkan info pengguna dari Google dengan access token.
    
    Fungsi ini tetap disediakan untuk kompatibilitas dengan kode lama.
    """
    user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    headers = {'Authorization': f'Bearer {access_token}'}
    
    async with aiohttp.ClientSession() as session:
        async with session.get(user_info_url, headers=headers) as response:
            if response.status != 200:
                text = await response.text()
                raise OAuthError(f"Failed to get user info: {text}")
            
            user_data = await response.json()
    
    # Ubah format data yang diterima dari Google ke format OAuthUserInfo
    return OAuthUserInfo(
        provider="google",
        id=user_data['sub'],
        email=user_data['email'],
        name=user_data.get('name', ''),
        avatar=user_data.get('picture', None)
    )