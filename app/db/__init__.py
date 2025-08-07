from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.models import Base
from app.config.config import DATABASE_URL
import logging

# Import model-model untuk memastikan mereka terdaftar dengan Base
from app.db.models import User  # Import ini untuk memastikan semua model terdaftar
from app.db.search_history import SearchHistory

# Import relasi untuk menghubungkan model-model
from app.db.search_history import SearchHistory

def init_db():
    """Initialize the database - gunakan alembic untuk migrasi schema, bukan create_all."""
    try:
        # Hanya buat engine, JANGAN create_all
        engine = create_engine(DATABASE_URL)
        
        # Create session factory
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        logging.info("Database connection initialized successfully.")
        return engine, SessionLocal
    except Exception as e:
        logging.error(f"Error initializing database connection: {e}")
        raise