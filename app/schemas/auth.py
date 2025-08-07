from pydantic import BaseModel, EmailStr
from typing import Optional

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class OAuthUserInfo(BaseModel):
    provider: str
    id: str
    email: EmailStr
    name: str
    avatar: Optional[str] = None

class Token(BaseModel):
    access_token: str
    token_type: str
    
class TokenData(BaseModel):
    email: Optional[str] = None
    
class PasswordReset(BaseModel):
    email: EmailStr
    
class PasswordUpdate(BaseModel):
    token: str
    new_password: str