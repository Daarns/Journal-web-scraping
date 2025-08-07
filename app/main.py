from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from pathlib import Path
from app.config.config import STATIC_DIR, TEMPLATE_DIR
from app.services.oauth import oauth
from starlette.middleware.sessions import SessionMiddleware
from app.middleware.security import SecurityHeadersMiddleware, RateLimitMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.config.config import SECRET_KEY
from app.core.security import create_csrf_token
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.db.models import User
from datetime import datetime
from app.db.models import User, PasswordReset
from app.api.search_routes import router as search_router
from app.api.ai_routes import router as ai_router
from app.api.auth_utils import get_current_user, get_current_user_optional
import logging
from app.api.proxy import router as proxy_router
import secrets
import os
from app.scrapers.paper_scraper import AdaptiveSSLManager
from apscheduler.schedulers.background import BackgroundScheduler
from app.tasks.cleanup import cleanup_expired_extractions

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

app = FastAPI(title="Knowvera")

# Add security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    max_age=3600,  # 1 hour
    same_site="lax",
    https_only=False,  # Set to True in production with HTTPS
)

app.include_router(search_router)
app.include_router(ai_router)
app.include_router(proxy_router)

# Mount static directory
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="static")

# Setup templates
templates = Jinja2Templates(directory=TEMPLATE_DIR)

AdaptiveSSLManager.initialize()

scheduler = BackgroundScheduler()
scheduler.add_job(cleanup_expired_extractions, 'interval', hours=24)  # Jalankan setiap 24 jam
scheduler.start()

# Add shutdown event handler for scheduler
@app.on_event("shutdown")
def shutdown_event():
    if scheduler.running:
        scheduler.shutdown()

# Add templates context processor for CSRF
@app.middleware("http")
async def add_csrf_token_to_request(request: Request, call_next):
    # Daftar path yang memerlukan CSRF protection
    csrf_pages = [
        "/login",
        "/register",
        "/forget-password",
        "/reset-password",
        "/reset-password-form",
    ]

    # Daftar path yang TIDAK memerlukan CSRF protection (akses publik)
    csrf_exempt_paths = [
        "/api/search", 
        "/api/ai/question", 
        "/api/ai/suggest-keywords",
        "/api/activity/collections",
        "/api/ai/upload-pdf"
    ]

    # Jika path saat ini termasuk dalam daftar yang tidak memerlukan CSRF
    if request.method == "POST" and any(
        request.url.path.startswith(path) for path in csrf_exempt_paths
    ):
        return await call_next(request)

    # Sisanya mengikuti logika CSRF yang sudah ada
    if request.method == "GET" and any(path in request.url.path for path in csrf_pages):
        if not hasattr(request.state, "csrf_token"):
            request.state.csrf_token = create_csrf_token()

    # Lanjutkan request
    response = await call_next(request)

    # Jika ini adalah halaman dengan form dan belum ada cookie CSRF token
    path_match = any(path in request.url.path for path in csrf_pages)
    if request.method == "GET" and path_match and "csrf_token" not in request.cookies:
        # Tambahkan cookie CSRF token ke response
        csrf_token = (
            request.state.csrf_token
            if hasattr(request.state, "csrf_token")
            else create_csrf_token()
        )
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=True,
            secure=False,  # Set True di production dengan HTTPS
            samesite="lax",
        )

    return response


# Middleware untuk menambahkan CSRF token ke semua respons untuk guest users
@app.middleware("http")
async def add_csrf_token_to_all_responses(request: Request, call_next):
    # Jalankan request terlebih dahulu
    response = await call_next(request)
    
    # Generate CSRF token jika belum ada di cookies
    if "csrf_token" not in request.cookies:
        csrf_token = create_csrf_token()
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,  # False agar bisa dibaca JS
            secure=False,    # True di production
            samesite="lax",  # Lebih permisif
            max_age=86400    # 1 hari
        )
    
    return response


from app.api import api_router, auth

# Tambahkan api_router
app.include_router(api_router, prefix="/api")
# Mount routers
app.include_router(auth.router, prefix="/api")


# Endpoint khusus untuk mendapatkan CSRF token melalui AJAX
@app.get("/api/get-csrf-token")
async def get_csrf_token():
    """Endpoint untuk mendapatkan CSRF token via AJAX"""
    csrf_token = create_csrf_token()

    response = JSONResponse(content={"csrf_token": csrf_token})
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # False agar bisa dibaca oleh JavaScript
        secure=False,  # Set True di production dengan HTTPS
        samesite="lax",
        max_age=1800,  # 30 menit
    )

    return response


# Template routes
@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/search")
async def search_page(request: Request):
    return templates.TemplateResponse("search.html", {"request": request})


@app.get("/login")
async def login_page(request: Request):
    # Add CSRF token to template context
    context = {
        "request": request,
        "csrf_token": (
            request.state.csrf_token
            if hasattr(request.state, "csrf_token")
            else create_csrf_token()
        ),
    }
    return templates.TemplateResponse("auth/login.html", context)


@app.get("/register")
async def register_page(request: Request):
    # Add CSRF token to template context
    context = {
        "request": request,
        "csrf_token": (
            request.state.csrf_token
            if hasattr(request.state, "csrf_token")
            else create_csrf_token()
        ),
    }
    return templates.TemplateResponse("auth/register.html", context)


@app.get("/forget-password")
async def forget_password_page(request: Request):
    """Render the forget password page"""
    # Generate CSRF token baru
    csrf_token = create_csrf_token()

    # Tambahkan CSRF token ke template context
    context = {
        "request": request,
        "csrf_token": csrf_token,
        "page_title": "Lupa Password",
    }

    # Template response dengan CSRF token
    response = templates.TemplateResponse("auth/forget_password.html", context)

    # Set CSRF token cookie dengan waktu yang cukup panjang dan tanpa httponly
    # agar JavaScript bisa membacanya untuk debugging
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # False untuk debugging, sebaiknya True di production
        secure=False,  # False untuk HTTP local, True untuk HTTPS
        samesite="lax",
        max_age=1800,  # 30 menit
    )

    print(f"Setting CSRF cookie with token: {csrf_token}")

    return response


@app.get("/reset-password")
async def reset_password_page(
    request: Request,
    token_id: str,  # Gunakan token_id, bukan token+email
    db: Session = Depends(get_db),
):
    """Render reset password page, only accessible with valid token ID"""
    # Debug output
    print(f"Accessing reset password with token_id: {token_id}")

    # Cari token dari database berdasarkan ID
    password_reset = (
        db.query(PasswordReset)
        .filter(
            PasswordReset.id == token_id,
            PasswordReset.is_valid == True,
            PasswordReset.expires_at > datetime.utcnow(),
        )
        .first()
    )

    # Debug output untuk objek password_reset
    if password_reset:
        print(
            f"Found password reset: ID={password_reset.id}, Email={password_reset.email}, Valid={password_reset.is_valid}"
        )
        print(
            f"Expires at: {password_reset.expires_at}, Current time: {datetime.utcnow()}"
        )
    else:
        print("Password reset not found or expired")

    # Jika token tidak ditemukan atau kedaluwarsa
    if not password_reset:
        # Generate CSRF token
        csrf_token = create_csrf_token()
        response = templates.TemplateResponse(
            "auth/invalid_reset_token.html",
            {"request": request, "csrf_token": csrf_token},
        )
        response.set_cookie(
            key="csrf_token",
            value=csrf_token,
            httponly=False,  # False untuk debugging
            secure=False,
            samesite="lax",
        )
        return response

    # Ambil token asli dan email dari database
    reset_token = password_reset.token
    email = password_reset.email

    # Debug values
    print(f"Using token: {reset_token[:5]}... (hidden), email: {email}")

    # Generate CSRF token
    csrf_token = create_csrf_token()

    # Token valid, tampilkan form reset password
    context = {
        "request": request,
        "csrf_token": csrf_token,
        "token": reset_token,  # Token asli disimpan sebagai hidden field
        "email": email,  # Email disimpan sebagai hidden field dan ditampilkan
        "token_id": token_id,  # Token ID untuk digunakan dalam API call
    }

    # Debug context untuk memastikan data dikirim ke template
    print(
        f"Context data sent to template: token_present={bool(reset_token)}, email={email}, token_id={token_id}"
    )

    response = templates.TemplateResponse("auth/reset_password.html", context)

    # Set cookie dengan CSRF token
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,  # False untuk debugging
        secure=False,
        samesite="lax",
    )

    return response


# Endpoint reset password form yang mengambil data dari session
@app.get("/reset-password-form")
async def reset_password_form(request: Request, id: str):
    """Render reset password form after validation"""
    # Periksa apakah ID sesi reset valid
    if (
        not id
        or "reset_session_id" not in request.session
        or request.session["reset_session_id"] != id
        or "reset_token" not in request.session
        or "reset_email" not in request.session
    ):
        # Invalid session or expired
        return RedirectResponse(url="/forget-password", status_code=302)

    # Ambil token dan email dari session
    token = request.session["reset_token"]
    email = request.session["reset_email"]

    # Generate CSRF token
    csrf_token = create_csrf_token()

    # Tampilkan form dengan token dan email dari session, bukan dari URL
    response = templates.TemplateResponse(
        "auth/reset_password.html",
        {
            "request": request,
            "csrf_token": csrf_token,
            "token": token,  # Ini akan disimpan sebagai hidden field
            "email": email,  # Ini akan ditampilkan di form dan disimpan sebagai hidden field
            "display_email": email,  # Tambahkan untuk dipastikan ditampilkan
        },
    )

    response.set_cookie(
        key="csrf_token", value=csrf_token, httponly=True, secure=False, samesite="lax"
    )
    return response


# Endpoint debug CSRF untuk pengujian (Hapus ini di production)
@app.get("/debug-csrf")
async def debug_csrf(request: Request):
    """Debug endpoint untuk memeriksa CSRF token"""
    csrf_token = request.cookies.get("csrf_token", "Tidak ada CSRF token di cookies")
    return {
        "csrf_token_in_cookie": csrf_token,
        "csrf_token_in_state": getattr(
            request.state, "csrf_token", "Tidak ada di state"
        ),
        "cookies": {k: v for k, v in request.cookies.items()},
        "headers": {k: v for k, v in request.headers.items() if k.lower() != "cookie"},
    }


# Tambahkan route redirect untuk backward compatibility
@app.get("/auth/google")
async def legacy_google_auth(request: Request, return_url: str = "/search"):
    """Redirect to the API endpoint with proper return URL"""
    # Default return URL ke /search jika tidak ada
    if not return_url or return_url == "/":
        return_url = "/search"

    print(
        f"Redirecting from /auth/google to /api/auth/google with return_url={return_url}"
    )
    return RedirectResponse(url=f"/api/auth/google?return_url={return_url}")


@app.get("/collections", response_class=HTMLResponse)
async def collections_page(
    request: Request, user: User = Depends(get_current_user_optional)
):
    """Halaman untuk melihat koleksi paper"""
    return templates.TemplateResponse(
        "collections.html", {"request": request, "user": user}
    )