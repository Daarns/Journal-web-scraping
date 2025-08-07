from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import verify_token
from app.config.config import SECRET_KEY, ALGORITHM
from app.db.models import TokenBlacklist
from app.schemas.user import UserInDB
from app.crud.user import get_user_by_email
from typing import Optional
from datetime import datetime

# Token blacklist global
TOKEN_BLACKLIST = {}

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/token", auto_error=False)

async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Optional[UserInDB]:
    """
    Get current user from token, return None if no valid token
    """
    if not token:
        # Try to get token from cookie
        token_cookie = request.cookies.get("access_token")
        if token_cookie and token_cookie.startswith("Bearer "):
            token = token_cookie.replace("Bearer ", "")
    
    if not token:
        return None
        
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        jti: str = payload.get("jti")
        
        if email is None:
            return None
            
        # Check if token is blacklisted
        if jti:
            # Check in-memory blacklist first (faster)
            if jti in TOKEN_BLACKLIST:
                return None
                
            # Check database blacklist
            blacklisted = db.query(TokenBlacklist).filter_by(token_id=jti).first()
            if blacklisted:
                return None
                
        # Get user from database
        user = get_user_by_email(db, email)
        if user is None:
            return None
        
        return user
    except JWTError:
        return None

async def get_current_user(
    current_user: Optional[UserInDB] = Depends(get_current_user_optional)
) -> UserInDB:
    """
    Get current user or raise 401 if not authenticated
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user