from sqlalchemy import create_engine
from app.db.models import Base
from app.config.config import DATABASE_URL
import logging

def init_db():
    """Initialize the database with required tables."""
    try:
        # Create engine using properly escaped DATABASE_URL
        engine = create_engine(
            DATABASE_URL,
            pool_pre_ping=True,  # Mendeteksi koneksi terputus
            pool_recycle=3600,   # Recycle koneksi setiap jam untuk menghindari "MySQL server has gone away"
            echo=False           # Set True untuk logging SQL
        )
        
        # Create all tables
        Base.metadata.create_all(bind=engine)
        
        logging.info("Database initialized successfully.")
    except Exception as e:
        logging.error(f"Error initializing database: {e}")
        raise