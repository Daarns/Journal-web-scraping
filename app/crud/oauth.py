from sqlalchemy.orm import Session
from app.db.models import OAuthAccount, User
from datetime import datetime

def get_oauth_account(db: Session, provider: str, oauth_id: str):
    """Ambil akun OAuth berdasarkan provider dan ID"""
    return db.query(OAuthAccount).filter(
        OAuthAccount.oauth_provider == provider,
        OAuthAccount.oauth_id == oauth_id
    ).first()

def get_oauth_account_by_user_id(db: Session, user_id: int, provider: str):
    """Ambil akun OAuth berdasarkan user_id dan provider"""
    return db.query(OAuthAccount).filter(
        OAuthAccount.user_id == user_id,
        OAuthAccount.oauth_provider == provider
    ).first()

def create_oauth_account(
    db: Session, 
    user_id: int, 
    provider: str, 
    oauth_id: str, 
    oauth_email: str, 
    oauth_name: str = None,
    oauth_avatar: str = None
):
    """Buat akun OAuth baru"""
    db_oauth = OAuthAccount(
        user_id=user_id,
        oauth_provider=provider,
        oauth_id=oauth_id,
        oauth_email=oauth_email,
        oauth_name=oauth_name,
        oauth_avatar=oauth_avatar
    )
    db.add(db_oauth)
    db.commit()
    db.refresh(db_oauth)
    return db_oauth

def update_oauth_avatar(db: Session, provider: str, oauth_id: str, avatar_url: str):
    """Update avatar URL untuk akun OAuth"""
    oauth_account = get_oauth_account(db, provider, oauth_id)
    if oauth_account:
        oauth_account.oauth_avatar = avatar_url
        oauth_account.updated_at = datetime.utcnow()
        db.commit()
        return oauth_account
    return None