from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response
import httpx
import logging
import re
from typing import Optional
from datetime import datetime, timedelta

router = APIRouter(prefix="/proxy", tags=["proxy"])
logger = logging.getLogger(__name__)

# Daftar domain yang diizinkan - tambahkan domain ini untuk keamanan

ALLOWED_DOMAINS = [
    "googleusercontent.com",
    "google.com",
    "googleapis.com",
    "gstatic.com",
    "ggpht.com",  # Google Photos domain
    "lh1.googleusercontent.com",
    "lh2.googleusercontent.com", 
    "lh3.googleusercontent.com",
    "lh4.googleusercontent.com",
    "lh5.googleusercontent.com",
    "lh6.googleusercontent.com",
    "photos.google.com",
    "githubusercontent.com",
    "gravatar.com"
]

@router.get("/avatar")
async def proxy_avatar(url: str = Query(...)):
    """Proxy untuk mengambil avatar dari URL eksternal"""
    try:
        # Debug info
        logger.info(f"Avatar proxy request received for URL: {url}")
        
        # Validasi URL
        if not url.startswith(('http://', 'https://')):
            logger.warning(f"Invalid URL protocol: {url}")
            raise HTTPException(status_code=400, detail="Invalid URL protocol")
        
        # Domain verification
        domain_allowed = False
        matched_domain = None
        for domain in ALLOWED_DOMAINS:
            if domain in url:
                domain_allowed = True
                matched_domain = domain
                break
                
        if not domain_allowed:
            logger.warning(f"Blocked request to unauthorized domain: {url}")
            return Response(
                content=b"Domain not allowed",
                status_code=403,
                media_type="text/plain"
            )
            
        logger.info(f"Domain verification passed: {matched_domain} in {url}")
        
        # PERBAIKAN: Penanganan URL Google Photos yang lebih baik
        processed_url = url
        original_url = url
        
        # Untuk Google Photos, coba berbagai format URL
        if "googleusercontent.com" in url:
            logger.info(f"Detected Google Photos URL")
            
            # Ubah =s96-c menjadi =s256-c (resolusi lebih besar untuk debugging)
            if "=" in url:
                try:
                    base_url = url.split("=")[0]
                    processed_url = f"{base_url}=s256-c"
                    logger.info(f"Modified size parameter: {processed_url}")
                except Exception as e:
                    logger.error(f"Error modifying URL: {e}")
            
            # Tambahkan opsi fallback dengan menghapus parameter size
            fallback_url = url.split("=")[0] if "=" in url else url
            logger.info(f"Fallback URL (no parameters): {fallback_url}")
        
        # Header yang lebih lengkap untuk meniru browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://accounts.google.com/",
            "Origin": "https://accounts.google.com",
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache"
        }
        
        # Proses fetching dengan multiple fallbacks
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # Log semua URLs yang akan dicoba
            urls_to_try = [processed_url, original_url, fallback_url] 
            urls_to_try = list(set(urls_to_try))  # Remove duplicates
            logger.info(f"Will try URLs in sequence: {urls_to_try}")
            
            # Coba semua URLs secara berurutan sampai sukses
            response = None
            success_url = None
            
            for try_url in urls_to_try:
                try:
                    logger.info(f"Trying URL: {try_url}")
                    resp = await client.get(try_url, headers=headers)
                    logger.info(f"Response for {try_url}: {resp.status_code}")
                    
                    # Jika berhasil, simpan response dan URL yang sukses
                    if resp.status_code == 200:
                        response = resp
                        success_url = try_url
                        logger.info(f"Success with URL: {success_url}")
                        break
                except Exception as e:
                    logger.error(f"Error fetching {try_url}: {e}")
            
            # Jika tidak ada yang berhasil
            if not response or response.status_code != 200:
                logger.error(f"All URL attempts failed")
                return Response(
                    content=b"Failed to load image from all sources", 
                    status_code=404,
                    media_type="text/plain"
                )
                
            # Proses response yang berhasil
            content_type = response.headers.get("content-type", "image/*")
            logger.info(f"Successfully loaded avatar, content-type: {content_type}")
            
            # Validasi content type
            if not content_type.startswith(('image/', 'application/octet-stream')):
                logger.warning(f"Blocked non-image content type: {content_type}")
                return Response(
                    content=b"Content type not allowed",
                    status_code=403,
                    media_type="text/plain"
                )
            
            # Set cache headers
            cache_headers = {
                "Cache-Control": "public, max-age=86400",  # 1 day
                "Content-Type": content_type,
                "Access-Control-Allow-Origin": "*"
            }
            
            return Response(
                content=response.content, 
                media_type=content_type,
                headers=cache_headers
            )
                
    except Exception as e:
        logger.error(f"Error in proxy_avatar: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        return Response(
            content=f"Error processing avatar: {str(e)}".encode(), 
            status_code=500,
            media_type="text/plain"
        )
    
# Tambahkan endpoint untuk pengujian status
@router.get("/status")
async def proxy_status():
    """Endpoint untuk mengecek status layanan proxy"""
    return {"status": "operational", "supported_domains": ALLOWED_DOMAINS}