from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.config.config import DATABASE_URL

# SQLAlchemy setup dengan MySQL
SQLALCHEMY_DATABASE_URL = DATABASE_URL

# Tambahkan parameter untuk MySQL
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # Mendeteksi koneksi terputus
    pool_recycle=3600,   # Recycle koneksi setiap jam untuk menghindari "MySQL server has gone away"
    echo=False           # Set True untuk logging SQL
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()