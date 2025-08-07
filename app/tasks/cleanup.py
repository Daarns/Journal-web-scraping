from datetime import datetime, timedelta
import os
import logging
from sqlalchemy.sql import or_
from app.core.database import get_db
from app.db.models import PaperExtraction

logger = logging.getLogger(__name__)

def cleanup_expired_extractions():
    """Membersihkan ekstraksi PDF yang sudah kedaluarsa"""
    db = next(get_db())
    try:
        # Ambil ekstraksi yang sudah expired
        expired_extractions = db.query(PaperExtraction).filter(
            or_(
                # Ekstraksi dengan TTL yang sudah lewat
                PaperExtraction.expires_at < datetime.utcnow(),
                # Ekstraksi publik yang sudah sangat lama (lebih dari 30 hari)
                PaperExtraction.extraction_date < datetime.utcnow() - timedelta(days=30)
            )
        ).all()
        
        for extraction in expired_extractions:
            if extraction.pdf_url and extraction.pdf_url.startswith('local://'):
                # Hapus file PDF dari disk
                file_path = extraction.pdf_url.replace('local://', '')
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"Removed expired PDF file: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to remove {file_path}: {str(e)}")
                    
                # Update status di database atau hapus record
                # Opsi 1: Hapus record dari database
                # db.delete(extraction)
                
                # Opsi 2: Update status sebagai expired tapi pertahankan metadata
                extraction.extraction_status = 'expired'
                extraction.extracted_text = None  # Kosongkan teks untuk menghemat ruang
                extraction.pdf_url = None  # Hapus referensi ke file yang sudah tidak ada
                
        db.commit()
        logger.info(f"Cleaned up {len(expired_extractions)} expired PDF extractions")
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error during PDF cleanup: {str(e)}")