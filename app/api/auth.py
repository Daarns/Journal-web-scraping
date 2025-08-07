from fastapi import APIRouter, Depends, HTTPException, status, Form, Request, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi import Form, Query
from typing import Optional, List
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import re
import secrets
from app.core.database import get_db
from app.core.security import (
    create_access_token, 
    generate_token, 
    get_password_hash,
    create_csrf_token
)
from app.config.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.crud import user as user_crud
from app.crud import oauth as oauth_crud
from app.schemas import user as user_schemas
from app.schemas import auth as auth_schemas
from app.db.models import User, TokenBlacklist, PasswordReset

# Import fungsi dan variabel dari auth_utils
from app.api.auth_utils import get_current_user, get_current_user_optional, TOKEN_BLACKLIST

# Imported services
from app.services.oauth import (
    oauth,  # Objek OAuth baru
    OAuthError,
    authorize_google_redirect,  # Fungsi baru dari authlib
    get_google_token_and_userinfo,  # Fungsi baru dari authlib
    get_google_auth_url,  # Fungsi lama untuk kompatibilitas
    exchange_google_code,  # Fungsi lama untuk kompatibilitas
    get_google_user_info   # Fungsi lama untuk kompatibilitas
)
from app.services.email import send_password_reset_email
from app.core.security import generate_password_reset_token, verify_password_reset_token, generate_reset_token_pair

router = APIRouter(tags=["auth"])

@router.post("/register", response_model=auth_schemas.Token)
async def register_user(
    request: Request,
    user: user_schemas.UserCreate,
    db: Session = Depends(get_db),
    return_url: Optional[str] = Query(None),
):
    # Password validation
    if len(user.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    if not re.search(r'[A-Z]', user.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
        
    if not re.search(r'[a-z]', user.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
        
    if not re.search(r'\d', user.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
        
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', user.password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character")
    
    # Email validation (basic)
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', user.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # Username validation
    if not re.match(r'^[a-zA-Z0-9_]{3,20}$', user.username):
        raise HTTPException(status_code=400, 
                           detail="Username must be 3-20 characters and only contain letters, numbers, and underscores")

    # Check if email already registered
    db_user = user_crud.get_user_by_email(db, email=user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    # Check if username already exists
    db_username = user_crud.get_user_by_username(db, username=user.username)
    if db_username:
        raise HTTPException(status_code=400, detail="Username already taken")

    # Create new user
    user = user_crud.create_user(db=db, user=user)

    # Generate token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "name": user.full_name or user.username,
            "avatar": None,
        },
        expires_delta=access_token_expires,
    )
    response = {"access_token": access_token, "token_type": "bearer"}
    if return_url:
        response["return_url"] = return_url
    return response


@router.post("/token")
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    return_url: Optional[str] = Form(None),
):
    # Cek apakah username input adalah email (mengandung '@')
    is_email = '@' in form_data.username
    
    # Autentikasi berdasarkan jenis input
    if is_email:
        user = user_crud.authenticate_user_by_email(db, form_data.username, form_data.password)
    else:
        user = user_crud.authenticate_user_by_username(db, form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username/email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate token
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user.email,
            "name": user.full_name or user.username,
            "avatar": None,
            "jti": generate_token()  # Add token ID for revocation
        },
        expires_delta=access_token_expires,
    )
    
    response = {"access_token": access_token, "token_type": "bearer"}
    if return_url:
        response["return_url"] = return_url
    return response


# Logout
@router.post("/logout")
async def logout(request: Request, db: Session = Depends(get_db)):
    """Logout endpoint that invalidates the token"""
    # Get token from cookie or Authorization header
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "")
    else:
        token_cookie = request.cookies.get("access_token")
        if token_cookie and token_cookie.startswith("Bearer "):
            token = token_cookie.replace("Bearer ", "")
            
    if token:
        # Add to blacklist
        from jose import jwt
        from app.config.config import SECRET_KEY, ALGORITHM
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            jti = payload.get("jti")
            exp = payload.get("exp")
            
            if jti and exp:
                # Add to database blacklist
                db_token = TokenBlacklist(
                    token_id=jti,
                    expiry=datetime.fromtimestamp(exp)
                )
                db.add(db_token)
                db.commit()
                
                # Also add to in-memory blacklist
                TOKEN_BLACKLIST[jti] = exp
        except Exception as e:
            print(f"Error blacklisting token: {e}")
            
    # Return message
    return {"message": "Logout successful"}


# Auth check endpoint
@router.get("/auth/check")
async def check_auth(current_user: Optional[user_schemas.User] = Depends(get_current_user_optional)):
    """Check if user is authenticated and return user info"""
    if current_user:
        return {
            "authenticated": True,
            "user": {
                "email": current_user.email,
                "name": current_user.full_name or current_user.username,
                "username": current_user.username,
                "avatar": None  # You can populate this from OAuth profile if available
            }
        }
    return {"authenticated": False}


@router.post("/password-reset-request")
async def request_password_reset(
    request: Request,
    email: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """Request a password reset token to be sent via email"""
    # Validasi CSRF
    cookie_token = request.cookies.get("csrf_token")
    if csrf_token != cookie_token:
        # Debug untuk menemukan penyebab mismatch
        print(f"CSRF token mismatch: Form={csrf_token}, Cookie={cookie_token}")
        raise HTTPException(status_code=403, detail="CSRF token validation failed")
    
    # Get base URL for reset link
    base_url = str(request.base_url).rstrip('/')
    
    # Temukan user dengan email
    user = user_crud.get_user_by_email(db, email)
    
    # Selalu kembalikan respons sukses untuk mencegah email enumeration
    if not user:
        return {"message": "Jika email Anda terdaftar, Anda akan menerima link reset password"}
    
    # Generate pasangan token (ID yang aman untuk URL dan token panjang untuk validasi)
    token_id, reset_token = generate_reset_token_pair()
    
    # Buat entri baru di tabel password_resets
    expiry_time = datetime.utcnow() + timedelta(minutes=10)
    
    # Simpan di database terpisah
    password_reset = PasswordReset(
        id=token_id,
        email=email,
        token=reset_token,
        is_valid=True,
        expires_at=expiry_time,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None
    )
    db.add(password_reset)
    
    # Simpan juga referensi di tabel user untuk kompatibilitas dengan kode yang sudah ada
    user.password_reset_token = reset_token
    user.password_reset_expires = expiry_time
    
    db.commit()
    
    # Kirim email reset password dengan URL yang aman (hanya mengandung token ID)
    await send_password_reset_email(email, token_id, base_url)
    
    return {"message": "Jika email Anda terdaftar, Anda akan menerima link reset password"}

@router.post("/reset-password")
async def reset_password(
    request: Request,
    token: str = Form(...),
    email: str = Form(...),
    token_id: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db)
):
    """Reset password using token from form"""
    # Validasi CSRF - diubah untuk jadi lebih toleran
    cookie_token = request.cookies.get("csrf_token")
    
    # Debug output
    print(f"CSRF Debug - Reset Password API:")
    print(f"Form CSRF: {csrf_token}")
    print(f"Cookie CSRF: {cookie_token}")
    print(f"State CSRF: {getattr(request.state, 'csrf_token', None)}")
    
    # Gunakan token dari cookie atau state jika form token kosong atau tidak cocok
    if csrf_token != cookie_token:
        # Jika ada di state, gunakan itu (diset oleh middleware)
        if hasattr(request.state, "csrf_token"):
            print("Using CSRF token from request state")
            csrf_token = request.state.csrf_token
        # Atau gunakan dari cookie
        elif cookie_token:
            print("Using CSRF token from cookie")
            csrf_token = cookie_token
        
        # Jika masih tidak cocok, tolak request
        if csrf_token != cookie_token:
            print(f"Final CSRF validation failed: {csrf_token} != {cookie_token}")
            raise HTTPException(status_code=403, detail="CSRF token validation failed")
    
    # Validasi konfirmasi password
    if new_password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    
    # Validasi password strength
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    
    if not re.search(r'[A-Z]', new_password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
        
    if not re.search(r'[a-z]', new_password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
        
    if not re.search(r'\d', new_password):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
        
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', new_password):
        raise HTTPException(status_code=400, detail="Password must contain at least one special character")
    
    # Verifikasi reset token dari database berdasarkan token_id
    password_reset = db.query(PasswordReset).filter(
        PasswordReset.id == token_id,
        PasswordReset.is_valid == True,
        PasswordReset.expires_at > datetime.utcnow()
    ).first()
    
    # Debug output untuk membantu troubleshooting
    if password_reset:
        print(f"Found password reset record: ID={password_reset.id}, Email={password_reset.email}")
        print(f"Token match: {password_reset.token == token}")
        print(f"Email match: {password_reset.email == email}")
    else:
        print(f"No valid password reset record found for token_id: {token_id}")
    
    if not password_reset or password_reset.token != token or password_reset.email != email:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Get user by email
    user = user_crud.get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Update password
    user.hashed_password = get_password_hash(new_password)
    
    # Invalidate token dalam tabel password_resets
    password_reset.is_valid = False
    password_reset.used_at = datetime.utcnow()
    password_reset.user_agent = request.headers.get("user-agent")
    password_reset.ip_address = request.client.host if request.client else None
    
    # Clear reset token dari tabel user
    user.password_reset_token = None
    user.password_reset_expires = None
    
    # Simpan perubahan
    db.commit()
    
    return {"message": "Password has been reset successfully"}

@router.get("/reset-password-info")
async def get_reset_password_info(
    token_id: str,
    db: Session = Depends(get_db)
):
    """Get email and token info for reset password token"""
    # Log untuk debug
    print(f"Fetching reset password info for token_id: {token_id}")
    
    # Cari token dari database
    password_reset = db.query(PasswordReset).filter(
        PasswordReset.id == token_id,
        PasswordReset.is_valid == True,
        PasswordReset.expires_at > datetime.utcnow()
    ).first()
    
    if not password_reset:
        print(f"Token not found or expired: {token_id}")
        raise HTTPException(status_code=404, detail="Token tidak ditemukan atau sudah kedaluwarsa")
    
    print(f"Found reset info: Email={password_reset.email}")
    
    # Kembalikan email dan jangan kembalikan token penuh untuk keamanan
    return {"email": password_reset.email, "token": password_reset.token}

@router.get("/auth/google")
async def google_login(request: Request, return_url: str = "/search"):
    """Inisiasi login Google OAuth dengan URL pengembalian yang tepat"""
    try:
        # Pastikan return_url defaultnya adalah /search jika tidak ada
        if not return_url or return_url == "/":
            return_url = "/search"
            
        # Debug log
        print(f"Starting Google OAuth flow with return_url: {return_url}")
        
        # Gunakan state parameter untuk menyimpan return_url dan tambahkan token keamanan
        state_data = f"{return_url}|{secrets.token_urlsafe(16)}"
        
        # Gunakan fungsi dari authlib dengan state yang disempurnakan
        return await authorize_google_redirect(request, state=state_data)
    except OAuthError as e:
        print(f"Error in Google OAuth: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Google OAuth error: {str(e)}")

@router.get("/auth/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """Handle callback from Google OAuth using Authlib"""
    print(f"Google callback received with params: {dict(request.query_params)}")
    try:
        # Ekstrak state dari request query params
        state = request.query_params.get('state', '/search')
        
        # Parse state parameter untuk mendapatkan return_url
        parts = state.split('|')
        return_url = parts[0] if len(parts) > 0 else "/search"
        
        # Pastikan return_url defaultnya adalah /search
        if not return_url or return_url == "/":
            return_url = "/search"
            
        print(f"Processing Google callback with return_url: {return_url}")
        
        try:
            # Mendapatkan token dan info user
            token_data, user_info = await get_google_token_and_userinfo(request)
            print(f"Successfully got user info: {user_info.email}")
            
            # Debug: Tampilkan semua atribut user_info
            print("User info attributes:")
            if hasattr(user_info, '__dict__'):
                for key, value in user_info.__dict__.items():
                    print(f"  - {key}: {value}")
            elif isinstance(user_info, dict):
                for key, value in user_info.items():
                    print(f"  - {key}: {value}")
            else:
                print(f"  - Type: {type(user_info)}")
                print(f"  - Dir: {dir(user_info)}")
                
        except Exception as e:
            print(f"Error in get_google_token_and_userinfo: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
        
        # Ekstrak informasi pengguna
        email = user_info.email
        name = user_info.name
        
        # PERBAIKAN: Ekstraksi picture URL dengan pengecekan yang lebih baik
        picture = None
        
        # Debug semua atribut untuk membantu troubleshooting
        print("DEBUG - Semua atribut user_info:")
        if hasattr(user_info, '__dict__'):
            for key, value in user_info.__dict__.items():
                if key == 'avatar':
                    picture = value  # Prioritaskan atribut avatar
                    print(f"Found avatar in attribute '{key}': {value}")
                elif key == 'picture' and not picture:
                    picture = value
                    print(f"Found avatar in attribute '{key}': {value}")
                else:
                    print(f"Attribute '{key}': {value}")
                    
        # Fallback jika belum dapat picture
        if not picture:
            if hasattr(user_info, 'avatar'):
                picture = user_info.avatar
                print(f"Avatar URL extracted from avatar attribute: {picture}")
            elif hasattr(user_info, 'picture'):
                picture = user_info.picture
                print(f"Avatar URL extracted from picture attribute: {picture}")
            elif hasattr(user_info, 'image') and hasattr(user_info.image, 'url'):
                picture = user_info.image.url
                print(f"Avatar URL extracted from image.url: {picture}")
            elif isinstance(user_info, dict):
                picture = user_info.get('avatar') or user_info.get('picture') or user_info.get('image', {}).get('url')
                print(f"Avatar URL extracted from dict: {picture}")
        
        # Jika picture ada, pastikan URL lengkap
        if picture and not picture.startswith(('http://', 'https://')):
            picture = f"https:{picture}" if picture.startswith('//') else picture
            print(f"Fixed avatar URL: {picture}")
        
        print(f"Final avatar URL to be saved: {picture}")
        
        # Periksa apakah user sudah ada di database
        db_user = user_crud.get_user_by_email(db, email)
        print(f"User exists in database: {bool(db_user)}")
        
        # Cek atau buat akun OAuth
        oauth_account = None
        if hasattr(user_info, 'id'):
            oauth_id = user_info.id
            oauth_account = oauth_crud.get_oauth_account(
                db, 
                provider="google", 
                oauth_id=oauth_id
            )
        
        if not db_user:
            # Buat user baru dari data Google
            print(f"Creating new user for: {email}")
            username = email.split("@")[0]
            # Pastikan username unik
            base_username = username
            counter = 1
            while user_crud.get_user_by_username(db, username):
                username = f"{base_username}{counter}"
                counter += 1
                
            # Buat password yang memenuhi validasi (dengan karakter khusus)
            secure_password = f"{generate_token()}!@#"  # Tambahkan karakter khusus
            
            # Buat user tanpa password (random password)
            user_data = user_schemas.UserCreate(
                email=email,
                username=username,
                full_name=name,
                password=secure_password,  # Gunakan password dengan karakter khusus
                is_oauth_user=True  # Tandai sebagai user OAuth
            )
            db_user = user_crud.create_user(db=db, user=user_data, is_verified=True)
            print(f"New user created with id: {db_user.id}")
        
        # Perbarui atau buat akun OAuth
        if hasattr(user_info, 'id'):
            oauth_id = user_info.id
            
            if not oauth_account:
                # Buat akun OAuth baru jika belum ada
                oauth_account = oauth_crud.create_oauth_account(
                    db=db,
                    user_id=db_user.id,
                    provider="google",
                    oauth_id=oauth_id,
                    oauth_email=email,
                    oauth_name=name,
                    oauth_avatar=picture
                )
                print(f"New OAuth account created for user {db_user.id}")
            else:
                # Update akun OAuth yang sudah ada
                oauth_account.oauth_email = email
                oauth_account.oauth_name = name
                if picture:  # Hanya update avatar jika ada
                    oauth_account.oauth_avatar = picture
                oauth_account.updated_at = datetime.utcnow()  # Update timestamp
                db.commit()
                print(f"Updated OAuth account for user {db_user.id}")
        
        # Ambil avatar URL dari akun OAuth
        avatar_url = None
        if oauth_account:
            avatar_url = oauth_account.oauth_avatar
            print(f"Using avatar URL from OAuth account: {avatar_url}")
        elif picture:
            avatar_url = picture
            print(f"Using avatar URL from Google response: {avatar_url}")
        
        # Generate token dengan avatar dari OAuth account
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": email,
                "name": name or db_user.username,
                "avatar": avatar_url,  # Gunakan avatar dari akun OAuth
                "jti": generate_token()
            },
            expires_delta=access_token_expires,
        )
        
        # Log token data untuk debug
        try:
            from jose import jwt
            from app.config.config import SECRET_KEY, ALGORITHM
            token_payload = jwt.decode(
                access_token, 
                SECRET_KEY,
                algorithms=[ALGORITHM],
                options={"verify_signature": False}
            )
            print(f"Token payload created: {token_payload}")
            print(f"Avatar in token: {token_payload.get('avatar')}")
        except Exception as e:
            print(f"Error decoding token for debug: {e}")
        
        # Redirect dengan token di URL fragment
        redirect_url = f"{return_url}#token={access_token}"
        
        print(f"Redirecting to: {redirect_url}")
        return RedirectResponse(
            url=redirect_url,
            status_code=status.HTTP_303_SEE_OTHER
        )
        
    except OAuthError as e:
        print(f"Error in Google callback (OAuthError): {str(e)}")
        return RedirectResponse(url="/login?error=google_auth_failed")
    except Exception as e:
        print(f"Unexpected error in Google callback: {str(e)}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url="/login?error=google_auth_failed")