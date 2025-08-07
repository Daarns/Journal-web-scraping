from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict
from typing import Callable, Dict, List
from app.config.config import RATE_LIMIT_WINDOW, LOGIN_MAX_ATTEMPTS
import ipaddress

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses"""
    
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        
        # Security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'; "
            "style-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com 'unsafe-inline'; "
            "img-src 'self' data: https://lh3.googleusercontent.com; "
            "font-src 'self' https://cdnjs.cloudflare.com; "
            "connect-src 'self'; "
            "frame-src 'self' https://accounts.google.com; "
            "object-src 'none'"
        )
        
        return response

class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting for sensitive endpoints"""
    
    def __init__(self, app, window_seconds: int = RATE_LIMIT_WINDOW, 
                 max_requests: int = LOGIN_MAX_ATTEMPTS):
        super().__init__(app)
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.blocked_ips: Dict[str, float] = {}
        
    async def dispatch(self, request: Request, call_next):
        # Skip rate limiting for non-sensitive paths
        path = request.url.path.lower()
        if not (path.endswith('/token') or path.endswith('/register') or 
                path.endswith('/password-reset-request')):
            return await call_next(request)
        
        # Get client IP, handle forwarded headers for proxies
        client_ip = request.client.host
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
            
        # Try to normalize IP address (for IPv6 compatibility)
        try:
            client_ip = str(ipaddress.ip_address(client_ip))
        except ValueError:
            pass
            
        # Check if IP is blocked
        now = time.time()
        if client_ip in self.blocked_ips:
            block_until = self.blocked_ips[client_ip]
            if now < block_until:
                # Still blocked
                remaining = int(block_until - now)
                return Response(
                    content=f"Too many attempts. Please try again in {remaining} seconds",
                    status_code=429,
                    headers={"Retry-After": str(remaining)}
                )
            else:
                # Block expired
                del self.blocked_ips[client_ip]
        
        # Remove old requests outside the window
        self.requests[client_ip] = [req_time for req_time in self.requests[client_ip]
                                  if now - req_time < self.window_seconds]
        
        # Check if too many requests
        if len(self.requests[client_ip]) >= self.max_requests:
            # Block for double the window time
            block_until = now + (2 * self.window_seconds)
            self.blocked_ips[client_ip] = block_until
            
            return Response(
                content="Too many login attempts. Please try again later.",
                status_code=429,
                headers={"Retry-After": str(2 * self.window_seconds)}
            )
        
        # Add current request time
        self.requests[client_ip].append(now)
        
        # Process request normally
        return await call_next(request)