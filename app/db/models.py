from sqlalchemy import Boolean, Column, String, Integer, DateTime, ForeignKey, UniqueConstraint, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime, timedelta
from app.db.base_class import Base

# Fungsi untuk menghasilkan waktu WIB
def wib_time():
    """Return current UTC time + 7 hours (WIB timezone)"""
    return datetime.utcnow() + timedelta(hours=7)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True)
    username = Column(String(100), unique=True, index=True)
    full_name = Column(String(200))
    hashed_password = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(String(100), nullable=True)
    verification_token_expires = Column(DateTime, nullable=True)
    password_reset_token = Column(String(100), nullable=True)
    password_reset_expires = Column(DateTime, nullable=True)
    
    # Gunakan fungsi wib_time() untuk kolom datetime
    created_at = Column(DateTime, default=wib_time)
    updated_at = Column(DateTime, default=wib_time, onupdate=wib_time)
    
    # Relasi dengan OAuthAccount
    oauth_accounts = relationship("OAuthAccount", back_populates="user")
    search_history = relationship("SearchHistory", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user", cascade="all, delete-orphan")
    activities = relationship("UserActivity", back_populates="user", cascade="all, delete-orphan")
    collections = relationship("Collection", back_populates="user", cascade="all, delete-orphan")
    citations = relationship("Citation", back_populates="user", cascade="all, delete-orphan")
    extractions = relationship("PaperExtraction", back_populates="user", cascade="all, delete-orphan")


# Model baru untuk Password Reset dengan ID yang aman
class PasswordReset(Base):
    """Model untuk menyimpan token reset password dengan ID yang aman untuk URL"""
    __tablename__ = "password_resets"
    
    id = Column(String(36), primary_key=True, index=True)  # UUID untuk URL
    email = Column(String(255), index=True, nullable=False)  # Email pengguna
    token = Column(String(255), nullable=False)  # Token asli, tidak terekspos di URL
    is_valid = Column(Boolean, default=True)
    created_at = Column(DateTime, default=wib_time)
    expires_at = Column(DateTime)
    
    # Optional: Track successful resets
    used_at = Column(DateTime, nullable=True)
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)

# Existing classes...
class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    oauth_provider = Column(String(50))
    oauth_id = Column(String(255))
    oauth_email = Column(String(255))
    oauth_name = Column(String(200))
    oauth_avatar = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=wib_time)
    updated_at = Column(DateTime, default=wib_time, onupdate=wib_time)
    
    # Relasi dengan User
    user = relationship("User", back_populates="oauth_accounts")

    
    __table_args__ = (
        UniqueConstraint('oauth_provider', 'oauth_id', name='uq_oauth_account_provider_id'),
    )

class TokenBlacklist(Base):
    __tablename__ = "token_blacklist"
    
    id = Column(Integer, primary_key=True, index=True)
    token_id = Column(String(100), unique=True, index=True)
    blacklisted_at = Column(DateTime, default=wib_time)
    expiry = Column(DateTime)

class PaperExtraction(Base):
    __tablename__ = "paper_extractions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    paper_id = Column(String(255), nullable=False, index=True)  # Hapus unique constraint
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    pdf_url = Column(Text, nullable=False)
    extracted_text = Column(Text, nullable=True)
    extraction_status = Column(String(50), nullable=False, default="pending")
    extraction_date = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_accessed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)
    extraction_time = Column(Integer, nullable=True)
    text_length = Column(Integer, nullable=True)
    extraction_attempts = Column(Integer, nullable=False, default=1)
    summary = Column(Text, nullable=True)
    summary_date = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationship
    user = relationship("User", back_populates="extractions")
    
    __table_args__ = (
        UniqueConstraint('paper_id', 'user_id', name='uq_paper_user_extraction'),
    )

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    paper_id = Column(String(255), nullable=False, index=True)
    paper_title = Column(String(500), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_message_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    user = relationship("User", back_populates="chat_sessions")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    is_user = Column(Boolean, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Relationship
    session = relationship("ChatSession", back_populates="messages")

class UserActivity(Base):
    __tablename__ = "user_activities"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    paper_id = Column(String(255), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)  # view, summarize, question, citation
    timestamp = Column(DateTime, nullable=False, default=wib_time)
    # Metadata tambahan seperti berapa lama dilihat, dll
    activity_data = Column(Text, nullable=True)  # Menyimpan data JSON jika diperlukan
    
    # Relationship
    user = relationship("User", back_populates="activities")
    
# Tambahkan model untuk saved collections/folders
class Collection(Base):
    __tablename__ = "collections"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=wib_time)
    updated_at = Column(DateTime, nullable=False, default=wib_time, onupdate=wib_time)
    
    # Relationship
    user = relationship("User", back_populates="collections")
    papers = relationship("CollectionPaper", back_populates="collection", cascade="all, delete-orphan")
    
# Tambahkan model junction untuk collection-paper
class CollectionPaper(Base):
    __tablename__ = "collection_papers"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, ForeignKey("collections.id", ondelete="CASCADE"), nullable=False)
    paper_id = Column(String(255), nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, default=wib_time)
    notes = Column(Text, nullable=True)
    
    # Metadata paper untuk caching
    title = Column(String(500), nullable=False)
    authors = Column(String(500), nullable=True)
    year = Column(String(10), nullable=True)
    source = Column(String(100), nullable=True)
    
    # Relationship
    collection = relationship("Collection", back_populates="papers")
    
    __table_args__ = (
        UniqueConstraint('collection_id', 'paper_id', name='uq_collection_paper'),
    )

# Tambahkan model untuk menyimpan sitasi yang dihasilkan
class Citation(Base):
    __tablename__ = "citations"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    paper_id = Column(String(255), nullable=False, index=True)
    style = Column(String(50), nullable=False)  # APA, MLA, Chicago, Vancouver, dll
    citation_text = Column(Text, nullable=False)
    generated_at = Column(DateTime, nullable=False, default=wib_time)
    
    # Relationship
    user = relationship("User", back_populates="citations")