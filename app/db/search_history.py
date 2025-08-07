from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import datetime
from typing import Optional
import logging
from app.db.base_class import Base
from ..core.database import get_db

logger = logging.getLogger(__name__)

class SearchHistory(Base):
    __tablename__ = "search_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    query = Column(Text)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    results_count = Column(Integer, default=0)
    
    # Perbaikan: Gunakan string "User" dan tambahkan relationship setelah import circular dipecahkan
    # user = relationship("User", back_populates="search_history")  # Definisi lama
    
    # Gunakan ini sebagai gantinya:
    user = relationship("User", back_populates="search_history")

async def save_search_history(user_id: int, query: str, results_count: int = 0):
    """Save search query to user's history with actual results count"""
    if not user_id:
        return
    
    try:
        db = next(get_db())
        
        logger.info(f"Saving search history with {results_count} results")
        
        new_search = SearchHistory(
            user_id=user_id,
            query=query,
            results_count=results_count  # Pastikan menggunakan jumlah hasil yang diberikan
        )
        
        db.add(new_search)
        db.commit()
        db.refresh(new_search)
        logger.info(f"Saved search history for user {user_id}: {query[:30]}... with {results_count} results")
    except Exception as e:
        logger.error(f"Error saving search history: {e}")
        # Get a new db session if there was an error
        db = next(get_db())
        db.rollback()