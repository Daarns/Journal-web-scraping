from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import uuid
import re

from app.db.models import User, OAuthAccount
from app.schemas import user as user_schemas
from app.schemas import auth as auth_schemas
from app.core.security import get_password_hash, verify_password, generate_token

def get_user(db: Session, user_id: int):
    return db.query(User).filter(User.id == user_id).first()

def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()

def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()

def create_user(db: Session, user: user_schemas.UserCreate, is_verified: bool = False):
    # Tambahkan validasi password hanya jika bukan user OAuth
    if not getattr(user, 'is_oauth_user', False):
        # Validasi password seperti minimal 8 karakter
        if len(user.password) < 8:
            raise ValueError("Password must be at least 8 characters")
            
        # Validasi huruf besar
        if not re.search(r'[A-Z]', user.password):
            raise ValueError("Password must contain at least one uppercase letter")
            
        # Validasi huruf kecil
        if not re.search(r'[a-z]', user.password):
            raise ValueError("Password must contain at least one lowercase letter")
            
        # Validasi angka
        if not re.search(r'\d', user.password):
            raise ValueError("Password must contain at least one number")
            
        # Validasi karakter khusus
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', user.password):
            raise ValueError("Password must contain at least one special character")
    
    hashed_password = get_password_hash(user.password)
    
    # Generate verification token hanya jika user tidak ter-verifikasi
    verification_token = None
    verification_token_expires = None
    
    if not is_verified:
        verification_token = generate_token()
        verification_token_expires = datetime.utcnow() + timedelta(hours=24)
    
    # Buat user dengan atau tanpa token verifikasi berdasarkan status verifikasi
    db_user = User(
        email=user.email,
        username=user.username,
        hashed_password=hashed_password,
        full_name=user.full_name,
        is_verified=is_verified,
        verification_token=verification_token,
        verification_token_expires=verification_token_expires
    )
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def authenticate_user_by_email(db: Session, email: str, password: str):
    user = get_user_by_email(db, email)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def authenticate_user_by_username(db: Session, username: str, password: str):
    user = get_user_by_username(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

# Fungsi authenticate_user asli sebagai wrapper
def authenticate_user(db: Session, username_or_email: str, password: str):
    # Deteksi apakah input berisi '@' (email)
    if '@' in username_or_email:
        return authenticate_user_by_email(db, username_or_email, password)
    else:
        return authenticate_user_by_username(db, username_or_email, password)