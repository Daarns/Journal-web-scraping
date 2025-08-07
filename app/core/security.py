from datetime import datetime, timedelta
from jose import jwt
from passlib.context import CryptContext
from typing import Optional, Union, Any
from app.config.config import SECRET_KEY, ALGORITHM, CSRF_SECRET_KEY
import secrets
from sqlalchemy.orm import Session
from app.db.models import User
import uuid

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(token: str) -> dict:
    """Verify and decode JWT token"""
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if decoded_token.get("exp") < datetime.utcnow().timestamp():
            return None
        return decoded_token
    except jwt.JWTError:
        return None

def create_csrf_token():
    """Generate a CSRF token"""
    return secrets.token_hex(32)

def encode_csrf_token(csrf_token: str):
    """Encode CSRF token with JWT for validation"""
    payload = {
        "csrf_token": csrf_token,
        "exp": datetime.utcnow() + timedelta(hours=24)
    }
    return jwt.encode(payload, CSRF_SECRET_KEY, algorithm=ALGORITHM)

def verify_csrf_token(token: str, csrf_token: str) -> bool:
    """Verify CSRF token against encoded version"""
    try:
        decoded = jwt.decode(token, CSRF_SECRET_KEY, algorithms=[ALGORITHM])
        return decoded["csrf_token"] == csrf_token
    except:
        return False

def generate_token():
    """Generate a random token for password reset"""
    return secrets.token_urlsafe(32)

def generate_password_reset_token() -> str:
    """Generate a secure random token for password reset"""
    return secrets.token_urlsafe(32)

def generate_reset_token_pair():
    """Generate a pair of tokens - one secure for validation and one for URL"""
    # UUID untuk URL (cukup pendek tapi unik)
    token_id = str(uuid.uuid4())
    # Token panjang untuk validasi (tidak ditampilkan di URL)
    reset_token = generate_password_reset_token()  # Gunakan fungsi yang sudah ada
    return token_id, reset_token

def verify_password_reset_token(token: str, email: str, db: Session) -> bool:
    """Verify if a password reset token is valid and not expired"""
    # Ambil user dari database
    user = db.query(User).filter(User.email == email).first()
    
    if not user:
        return False
        
    # Cek jika token sesuai dan belum kedaluwarsa
    if (user.password_reset_token != token or 
        not user.password_reset_expires or 
        user.password_reset_expires < datetime.utcnow()):
        return False
    
    return True