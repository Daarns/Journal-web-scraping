from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
import re

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: str

# Hapus class UserCreate pertama yang tidak menggunakan validator

class UserInDB(UserBase):
    id: int
    is_active: bool
    is_verified: bool
    hashed_password: str
    
    class Config:
        form_mode = True

class User(UserBase):
    id: int
    
    class Config:
        form_mode = True

# Ubah PasswordValidator menjadi mixin atau gunakan field_validator langsung di UserCreate
class UserCreate(UserBase):
    password: str
    is_oauth_user:bool = False
    # Gunakan field_validator bukan validator (untuk Pydantic v2)
    @field_validator('password')
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password must be at least 8 characters')
        if not re.search(r'[A-Z]', v):
            raise ValueError('Password must contain at least one uppercase letter')
        if not re.search(r'[a-z]', v):
            raise ValueError('Password must contain at least one lowercase letter')
        if not re.search(r'\d', v):
            raise ValueError('Password must contain at least one number')
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', v):
            raise ValueError('Password must contain at least one special character')
        return v