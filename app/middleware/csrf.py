from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

# Path yang tidak memerlukan CSRF protection
CSRF_EXEMPT_PATHS = [
    "/api/search", 
    "/api/ai/question", 
    "/api/ai/suggest-keywords",
    "/api/activity/collections"
]

# Path untuk debugging CSRF (jika diperlukan)
CSRF_DEBUG_PATHS = ["/debug-csrf"]

class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Periksa apakah path dibebaskan dari validasi CSRF
        path = request.url.path
        
        # Exempt paths - bypass CSRF check completely
        if any(path.startswith(exempt_path) for exempt_path in CSRF_EXEMPT_PATHS):
            return await call_next(request)
        
        # Special handling for debug paths
        is_debug_path = any(path.startswith(debug_path) for debug_path in CSRF_DEBUG_PATHS)
        
        # Hanya validasi pada metode non-safe (POST, PUT, DELETE, PATCH)
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            return await call_next(request)

        # Coba ambil CSRF token dari header
        csrf_token = request.headers.get("X-CSRF-Token")
        cookie_token = request.cookies.get("csrf_token")
        
        # Debug logging for debug paths
        if is_debug_path:
            print(f"CSRF Debug - Path: {path}")
            print(f"CSRF Debug - Method: {request.method}")
            print(f"CSRF Debug - Header Token: {csrf_token}")
            print(f"CSRF Debug - Cookie Token: {cookie_token}")
            print(f"CSRF Debug - All Headers: {request.headers}")
            print(f"CSRF Debug - All Cookies: {request.cookies}")

        # Verifikasi CSRF token
        if not cookie_token:
            if is_debug_path:
                print("CSRF Debug - Missing cookie token")
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token missing"}
            )

        if not csrf_token or csrf_token != cookie_token:
            if is_debug_path:
                print("CSRF Debug - Invalid or missing header token")
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token invalid"}
            )

        # Jika verifikasi berhasil, lanjutkan ke handler berikutnya
        return await call_next(request)