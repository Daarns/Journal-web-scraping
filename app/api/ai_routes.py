from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Body
from datetime import datetime
from typing import  Optional
from pydantic import BaseModel
from ..ai.search_service import search_service
from .auth_utils import get_current_user_optional, get_current_user
from ..db.models import User, PaperExtraction, ChatSession, ChatMessage, UserActivity
from ..core.database import get_db
from ..services.pdf_services import PdfProcessor
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from ..ai.gemini_service import gemini_service
import logging
from ..db.models import PaperExtraction 
import os
import json


logger = logging.getLogger(__name__)

# Define Pydantic models
class KeywordRequest(BaseModel):
    query: str

class SummaryRequest(BaseModel):
    paper_id: str
    title: str
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None

class QuestionRequest(BaseModel):
    question: str
    paper_id: Optional[str] = None
    paper_title: Optional[str] = None
    context: Optional[str] = None
    pdf_url: Optional[str] = None
    use_full_text: Optional[bool] = False
    guest_mode: Optional[bool] = False
    session_id: Optional[int] = None
    force_persistent: Optional[bool] = False 
# Initialize router
router = APIRouter(prefix="/api/ai", tags=["ai"])
pdf_processor = PdfProcessor()

@router.post("/suggest-keywords")
async def suggest_keywords(
    request: dict,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Generate keyword suggestions dengan context awareness"""
    try:
        query = request.get("query", "")
        search_context = request.get("search_context", {})
        
        if not query or len(query.strip()) < 3:
            return {"keywords": []}
        
        # ✅ CONTEXT-AWARE suggestions
        keywords = gemini_service.generate_suggested_keywords(
            query, 
            max_keywords=5,
            search_context=search_context
        )
        
        return {"keywords": keywords}
        
    except Exception as e:
        logger.error(f"Error generating keyword suggestions: {str(e)}")
        return {"keywords": []}

@router.post("/summarize")
async def summarize_paper(
    request: SummaryRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Generate a comprehensive summary of a paper using Gemini Pro"""
    try:
        logger.info(f"Summarize request: paper_id={request.paper_id}, title={request.title}, pdf_url={request.pdf_url}")
        
        # Cek apakah ringkasan sudah tersimpan
        extraction = db.query(PaperExtraction).filter(
            PaperExtraction.paper_id == request.paper_id,
            or_(
                PaperExtraction.user_id == current_user.id if current_user else False,
                and_(
                    PaperExtraction.user_id.is_(None),
                    or_(
                        PaperExtraction.expires_at.is_(None),
                        PaperExtraction.expires_at > datetime.utcnow()
                    )
                )
            )
        ).order_by(PaperExtraction.user_id.desc()).first()
        
        if extraction and extraction.summary:
            logger.info(f"Menggunakan ringkasan tersimpan untuk paper_id: {request.paper_id}")
            return {
                "summary": extraction.summary,
                "used_pdf": extraction.extraction_status == 'success',
                "pdf_url": extraction.pdf_url,
                "text_length": extraction.text_length if hasattr(extraction, 'text_length') else 0
            }
        
        # Inisialisasi variabel
        paper_text = request.abstract
        used_pdf = False
        extraction_time = None
        error_reason = None
        pdf_url = request.pdf_url
        
        # Jika pdf_url kosong tapi paper_id adalah Semantic Scholar, coba dapatkan PDF URL
        if (not pdf_url or pdf_url == "") and request.paper_id and request.paper_id.startswith("ss_"):
            logger.info(f"PDF URL kosong untuk paper Semantic Scholar, mencoba mendapatkan URL PDF: {request.paper_id}")
            paper_id_clean = request.paper_id.replace("ss_", "")
            semantic_url = f"https://www.semanticscholar.org/paper/{paper_id_clean}"
            
            # Coba ekstrak teks langsung dari URL artikel Semantic Scholar
            full_text, error = await pdf_processor.extract_text_from_article_url(semantic_url)
            
            if full_text:
                paper_text = full_text
                used_pdf = True
            else:
                logger.warning(f"Gagal mendapatkan PDF dari Semantic Scholar: {error}")
                error_reason = error

        elif (not pdf_url or pdf_url == "") and request.paper_id and request.paper_id.startswith("gs_"):
            logger.info(f"PDF URL kosong untuk paper Google Scholar, mencoba mendapatkan URL PDF alternatif")
            
            # Ekstrak ID Google Scholar
            gs_id = request.paper_id.replace("gs_", "")
            
            # Coba dengan paper scraper untuk mencari URL alternatif
            try:
                from ..scrapers.paper_scraper import PaperScraper
                scraper = PaperScraper()
                pdf_url = await scraper._scrape_semantic_scholar_detail_page_for_pdf(f"https://www.semanticscholar.org/paper/search?q={request.title}")
                
                if pdf_url:
                    logger.info(f"Menemukan URL PDF alternatif melalui scraping: {pdf_url}")
                    
                    # Coba ekstrak dari URL PDF alternatif
                    full_text, error = await pdf_processor.get_or_extract_text(db, request.paper_id, pdf_url, current_user)
                    
                    if full_text and not error:
                        paper_text = full_text
                        used_pdf = True
                    else:
                        logger.warning(f"Gagal mengekstrak dari URL PDF alternatif: {error}")
                        error_reason = error
            except Exception as scrape_error:
                logger.error(f"Gagal melakukan scraping alternatif: {str(scrape_error)}")
        
        # Jika PDF URL tersedia, coba ekstrak teks lengkap
        elif pdf_url:
            # Ekstrak dari PDF URL dengan pendekatan hybrid (user-specific atau publik)
            full_text, error = await pdf_processor.get_or_extract_text(db, request.paper_id, pdf_url, current_user)
            
            # Cek apakah ekstraksi berhasil
            if full_text and not error:
                paper_text = full_text
                used_pdf = True
                
                # Dapatkan waktu ekstraksi dari database untuk logging
                extraction = db.query(PaperExtraction).filter(
                    PaperExtraction.paper_id == request.paper_id,
                    or_(
                        PaperExtraction.user_id == current_user.id if current_user else False,
                        PaperExtraction.user_id.is_(None)
                    )
                ).order_by(PaperExtraction.user_id.desc()).first()
                
                if extraction:
                    extraction_time = extraction.extraction_time
            else:
                # Jika ekstraksi gagal, gunakan abstrak dan simpan alasan error
                logger.warning(f"Failed to extract PDF, using abstract. Error: {error}")
                error_reason = error
        
        # Generate summary menggunakan model Gemini Pro
        summary = gemini_service.generate_paper_summary(request.title, paper_text, is_full_paper=used_pdf)
        
        logger.info(f"Summary generated for paper {request.paper_id}, used_pdf={used_pdf}, extraction_time={extraction_time}ms")
        
        # Simpan ringkasan ke database jika ekstraksi ada
        if extraction:
            extraction.summary = summary
            extraction.summary_date = datetime.utcnow()
            db.commit()
            logger.info(f"Ringkasan disimpan ke database untuk paper_id: {request.paper_id}")
        
        # Return hasil summary dan metadata
        return {
            "summary": summary,
            "used_pdf": used_pdf,
            "extraction_time": extraction_time,
            "error_reason": error_reason,
            "pdf_url": pdf_url,  # Kembalikan URL PDF untuk opsi download
            "text_length": len(paper_text) if paper_text else 0
        }
    
    except Exception as e:
        logger.error(f"Error in summarize_paper: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating summary: {str(e)}")

@router.post("/question")
async def answer_question(
    request: QuestionRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Answer questions about research papers using Gemini Pro with PERSISTENT sessions"""
    try:
        question = request.question
        paper_id = request.paper_id
        paper_title = request.paper_title
        context = request.context
        pdf_url = request.pdf_url
        use_full_text = request.use_full_text
        force_persistent = getattr(request, 'force_persistent', False)
        
        # Variabel untuk tracking penggunaan PDF
        used_pdf = False
        full_text = None
        
        # ✅ PERSISTENT SESSION LOGIC
        session = None
        is_new_session = False
        
        # ✅ PRIORITY 1: Gunakan session_id yang diberikan jika ada (persistent session)
        if request.session_id and current_user:
            session = db.query(ChatSession).filter(
                ChatSession.id == request.session_id,
                ChatSession.user_id == current_user.id
            ).first()
            
            if session:
                logger.info(f"Using PERSISTENT session {session.id} for paper {paper_id}")
            else:
                logger.warning(f"Session {request.session_id} not found, will create new one")
        
        # ✅ PRIORITY 2: Cari existing session untuk paper ini (one paper = one session forever)
        if not session and current_user and paper_id:
            existing_session = db.query(ChatSession).filter(
                ChatSession.user_id == current_user.id,
                ChatSession.paper_id == paper_id
            ).order_by(ChatSession.last_message_at.desc()).first()
            
            if existing_session:
                # ✅ GUNAKAN session yang sudah ada (PERSISTENT)
                session = existing_session
                logger.info(f"Found and using PERSISTENT session {session.id} for paper {paper_id}")
                is_new_session = False
            else:
                # ✅ Buat session baru PERSISTENT untuk paper ini
                session = ChatSession(
                    user_id=current_user.id,
                    paper_id=paper_id,
                    paper_title=paper_title,
                    created_at=datetime.utcnow(),
                    last_message_at=datetime.utcnow()
                )
                db.add(session)
                db.commit()
                db.refresh(session)
                logger.info(f"Created new PERSISTENT session {session.id} for paper {paper_id}")
                is_new_session = True
        
        # ✅ PDF PROCESSING - Jika paper_id tersedia dan use_full_text, coba dapatkan teks PDF dari database
        if paper_id and use_full_text:
            extraction = db.query(PaperExtraction).filter(
                PaperExtraction.paper_id == paper_id,
                or_(
                    PaperExtraction.user_id == current_user.id if current_user else False,
                    and_(
                        PaperExtraction.user_id.is_(None),
                        or_(
                            PaperExtraction.expires_at.is_(None),
                            PaperExtraction.expires_at > datetime.utcnow()
                        )
                    )
                )
            ).order_by(PaperExtraction.user_id.desc()).first()
            
            if extraction and extraction.extraction_status == 'success' and extraction.extracted_text:
                full_text = extraction.extracted_text
                used_pdf = True
                logger.info(f"Using cached PDF extraction for question on paper {paper_id}")
            elif pdf_url:
                # Jika tidak ada cache, ekstrak dari PDF URL
                logger.info(f"No cache found, extracting PDF for question: {pdf_url}")
                pdf_text, error = await pdf_processor.get_or_extract_text(db, paper_id, pdf_url, current_user)
                
                if pdf_text and not error:
                    full_text = pdf_text
                    used_pdf = True
                    logger.info(f"Successfully extracted PDF for question")
                else:
                    logger.warning(f"Failed to extract PDF for question: {error}")
        
        # ✅ GENERATE ANSWER - Generate answer based on available text
        answer = await search_service.answer_question(
            question,
            context,
            full_text if used_pdf else None
        )
        
        # ✅ SAVE MESSAGES - Tambahkan pesan ke session jika ada session dan user login
        if session and current_user:
            # Simpan pesan user
            user_message = ChatMessage(
                session_id=session.id,
                is_user=True,
                message=question,
                created_at=datetime.utcnow()
            )
            db.add(user_message)
            
            # Simpan jawaban AI
            ai_message = ChatMessage(
                session_id=session.id,
                is_user=False,
                message=answer,
                created_at=datetime.utcnow()
            )
            db.add(ai_message)
            
            # ✅ UPDATE session timestamp untuk persistence
            session.last_message_at = datetime.utcnow()
            db.commit()
            
            logger.info(f"Messages saved to PERSISTENT session {session.id}")
        
        # ✅ RETURN RESPONSE dengan persistent session info
        return {
            "answer": answer,
            "used_pdf": used_pdf,
            "session_id": session.id if session else None,
            "is_new_session": is_new_session,
            "paper_id": paper_id,
            "persistent_session": True  # ✅ MARK sebagai persistent
        }
        
    except Exception as e:
        logger.error(f"Error in answer_question: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/paper-chat-session/{paper_id}")
async def get_paper_chat_session(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get latest chat session for a specific paper - PERSISTENT VERSION"""
    try:
        # ✅ ALWAYS return the LATEST session for this paper (PERSISTENT behavior)
        session = db.query(ChatSession).filter(
            ChatSession.paper_id == paper_id,
            ChatSession.user_id == current_user.id
        ).order_by(ChatSession.last_message_at.desc()).first()
        
        if session:
            # ✅ Get paper title from session
            paper_title = session.paper_title or "Unknown Paper"
            
            return {
                "session_id": session.id,
                "paper_title": paper_title,
                "paper_authors": None,  # Could be added to ChatSession model later
                "paper_abstract": None,  # Could be added to ChatSession model later
                "pdf_url": None,  # Could be retrieved from PaperExtraction
                "created_at": session.created_at,
                "last_message_at": session.last_message_at,
                "persistent_session": True  # ✅ Mark sebagai persistent
            }
        
        return {
            "session_id": None,
            "persistent_session": False
        }
        
    except Exception as e:
        logger.error(f"Error getting paper chat session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat-history/{paper_id}")
async def get_chat_history(
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_optional)
):
    """Get chat history for a paper"""
    # Implementasi akan ditambahkan nanti setelah tabel chat_sessions dibuat
    return {"messages": []}

@router.post("/upload-pdf")
async def upload_pdf(
    paper_id: str = Form(...),
    title: str = Form(...),
    pdf_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Upload PDF manual untuk paper yang ekstraksi otomatisnya gagal"""
    try:
        # Validasi file PDF
        pdf_content = await pdf_file.read()
        if len(pdf_content) > 50 * 1024 * 1024:  # 50MB limit
            raise HTTPException(status_code=400, detail="File terlalu besar (max 50MB)")

        if not pdf_file.content_type == "application/pdf":
            raise HTTPException(status_code=400, detail="File harus berformat PDF")

        # Generate unique filename berdasarkan paper_id dan user (jika login)
        storage_path = "temp_pdfs"
        os.makedirs(storage_path, exist_ok=True)

        filename_prefix = paper_id
        if current_user:
            filename_prefix = f"{paper_id}_{current_user.id}"  # Prefix dengan user ID jika login
        
        file_path = f"{storage_path}/{filename_prefix}.pdf"
        
        # Simpan file ke storage
        with open(file_path, "wb") as f:
            f.write(pdf_content)

        # Ekstrak teks dari PDF
        extracted_text = pdf_processor._extract_text_from_pdf_data(pdf_content)
        if not extracted_text:
            raise HTTPException(status_code=400, detail="Tidak dapat mengekstrak teks dari PDF")

        # Tentukan jenis ekstraksi (pribadi atau umum) dan TTL
        from datetime import datetime, timedelta
        
        # Default: ekstraksi pribadi untuk user login, atau ekstraksi umum dengan TTL untuk tamu
        is_private = current_user is not None
        expiration_date = None
        user_id = current_user.id if current_user else None
        
        if not current_user:
            # Untuk tamu: hasil ekstraksi berlaku 24 jam
            expiration_date = datetime.utcnow() + timedelta(hours=24)
        
        # Cek apakah sudah ada ekstraksi pribadi user ini
        if current_user:
            user_extraction = db.query(PaperExtraction).filter(
                PaperExtraction.paper_id == paper_id,
                PaperExtraction.user_id == current_user.id
            ).first()
            
            if user_extraction:
                # Update ekstraksi yang sudah ada
                user_extraction.extracted_text = extracted_text
                user_extraction.extraction_status = "success"
                user_extraction.pdf_url = f"local://{file_path}"
                user_extraction.extraction_date = datetime.utcnow()
                user_extraction.text_length = len(extracted_text)
                
                # Generate summary dan simpan
                summary = gemini_service.generate_paper_summary(title, extracted_text, is_full_paper=True)
                user_extraction.summary = summary
                user_extraction.summary_date = datetime.utcnow()
                
                db.commit()
                
                logger.info(f"PDF berhasil diproses dan ekstraksi pribadi diperbarui untuk user_id: {current_user.id}")
                return {
                    "summary": summary,
                    "used_pdf": True,
                    "text_length": len(extracted_text),
                    "message": "PDF berhasil diproses dan ekstraksi pribadi diperbarui"
                }
        
        # Cek apakah sudah ada ekstraksi publik untuk paper ini
        public_extraction = db.query(PaperExtraction).filter(
            PaperExtraction.paper_id == paper_id,
            PaperExtraction.user_id.is_(None)
        ).first()
        
        # Buat atau update entri ekstraksi
        extraction = db.query(PaperExtraction).filter(
            PaperExtraction.paper_id == paper_id,
            or_(
                PaperExtraction.user_id == user_id if user_id else False,
                PaperExtraction.user_id.is_(None)
            )
        ).order_by(PaperExtraction.user_id.desc()).first()
        
        # Generate summary
        summary = gemini_service.generate_paper_summary(title, extracted_text, is_full_paper=True)
        
        if not extraction:
            # Buat ekstraksi baru
            extraction = PaperExtraction(
                paper_id=paper_id,
                pdf_url=f"local://{file_path}",
                extraction_status="success",
                extracted_text=extracted_text,
                extraction_date=datetime.utcnow(),
                text_length=len(extracted_text),
                user_id=user_id,  # Null untuk ekstraksi publik, user_id untuk pribadi
                expires_at=expiration_date,  # Null untuk permanent, datetime untuk TTL
                summary=summary,
                summary_date=datetime.utcnow()
            )
            db.add(extraction)
        else:
            # Update ekstraksi yang sudah ada
            extraction.extracted_text = extracted_text
            extraction.extraction_status = "success"
            extraction.pdf_url = f"local://{file_path}"
            extraction.extraction_date = datetime.utcnow()
            extraction.text_length = len(extracted_text)
            extraction.user_id = user_id
            extraction.expires_at = expiration_date
            extraction.summary = summary
            extraction.summary_date = datetime.utcnow()
            
        db.commit()
        
        # Pesan berdasarkan status login
        message = "PDF berhasil diproses"
        if not current_user:
            message += " (sebagai tamu - hasil ekstraksi tersedia selama 24 jam)"
        
        logger.info(f"PDF berhasil diupload dan diproses untuk paper_id: {paper_id}")
        return {
            "summary": summary,
            "used_pdf": True,
            "text_length": len(extracted_text),
            "message": message,
            "guest_mode": current_user is None
        }
    
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error processing PDF upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Gagal memproses PDF: {str(e)}")
    
@router.post("/check-extraction")
async def check_extraction(
        request: dict,
        db: Session = Depends(get_db),
        current_user: Optional[User] = Depends(get_current_user_optional)
    ):
        """Cek apakah paper memiliki ekstraksi PDF yang tersedia"""
        try:
            paper_id = request.get("paper_id")
            if not paper_id:
                raise HTTPException(status_code=400, detail="paper_id harus disediakan")
            
            # Cek ekstraksi dengan pendekatan hybrid
            extraction = db.query(PaperExtraction).filter(
                PaperExtraction.paper_id == paper_id,
                or_(
                    PaperExtraction.user_id == current_user.id if current_user else False,
                    and_(
                        PaperExtraction.user_id.is_(None),
                        or_(
                            PaperExtraction.expires_at.is_(None),
                            PaperExtraction.expires_at > datetime.utcnow()
                        )
                    )
                )
            ).order_by(PaperExtraction.user_id.desc()).first()
            
            if extraction and extraction.extraction_status == 'success' and extraction.extracted_text:
                return {
                    "has_extraction": True,
                    "pdf_url": extraction.pdf_url,
                    "text_length": extraction.text_length if hasattr(extraction, 'text_length') else len(extraction.extracted_text)
                }
            
            return {
                "has_extraction": False,
                "pdf_url": None
            }
            
        except HTTPException as e:
            raise e
        except Exception as e:
            logger.error(f"Error checking extraction: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Error checking extraction: {str(e)}")  
    
@router.get("/chat-sessions")
async def get_chat_sessions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of user's chat sessions - GROUPED BY PAPER untuk persistent behavior"""
    try:
        # ✅ GROUP BY paper_id to show only latest session per paper
        from sqlalchemy import func
        
        # Subquery untuk mendapatkan session terbaru per paper
        latest_sessions_subq = db.query(
            ChatSession.paper_id,
            func.max(ChatSession.last_message_at).label('max_date')
        ).filter(
            ChatSession.user_id == current_user.id
        ).group_by(ChatSession.paper_id).subquery()
        
        # Query utama untuk mendapatkan session detail
        sessions = db.query(ChatSession).join(
            latest_sessions_subq,
            and_(
                ChatSession.paper_id == latest_sessions_subq.c.paper_id,
                ChatSession.last_message_at == latest_sessions_subq.c.max_date,
                ChatSession.user_id == current_user.id
            )
        ).order_by(ChatSession.last_message_at.desc()).limit(20).all()
        
        result = []
        for session in sessions:
            # Ambil pesan pertama dari user untuk deskripsi
            first_question = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.id,
                ChatMessage.is_user == True
            ).order_by(ChatMessage.created_at.asc()).first()
            
            # ✅ Get latest question untuk better UI
            latest_question = db.query(ChatMessage).filter(
                ChatMessage.session_id == session.id,
                ChatMessage.is_user == True
            ).order_by(ChatMessage.created_at.desc()).first()
            
            # PERBAIKAN: Gunakan paper_title dari session, jangan coba dari extraction
            paper_title = session.paper_title if session.paper_title else "Unknown Paper"
            
            result.append({
                "id": session.id,
                "paper_id": session.paper_id,
                "question": latest_question.message if latest_question else (first_question.message if first_question else "Chat Session"),
                "first_question": first_question.message if first_question else "Chat Session",  # ✅ For backward compatibility
                "paper_title": paper_title,
                "created_at": session.created_at,
                "last_message_at": session.last_message_at,
                "persistent_session": True  # ✅ Mark all as persistent
            })
        
        logger.info(f"Returning {len(result)} persistent chat sessions for user {current_user.id}")
        return result
        
    except Exception as e:
        logger.error(f"Error getting chat sessions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/chat-sessions/{session_id}")
async def get_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detail of a specific chat session with messages"""
    try:
        # Cek akses terhadap session
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Chat session tidak ditemukan")
        
        # Ambil semua pesan dalam session
        messages = db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).order_by(ChatMessage.created_at.asc()).all()
        
        # PERBAIKAN: Gunakan paper_title dari session langsung
        paper_title = session.paper_title if session.paper_title else "Unknown Paper"
        
        # Format response
        return {
            "id": session.id,
            "paper_id": session.paper_id,
            "paper_title": paper_title,  # Gunakan judul yang sudah disimpan
            "created_at": session.created_at,
            "messages": [
                {
                    "id": msg.id,
                    "is_user": msg.is_user,
                    "message": msg.message,
                    "created_at": msg.created_at
                } for msg in messages
            ]
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error getting chat session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.delete("/chat-sessions/{session_id}")
async def delete_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a chat session and all its messages"""
    try:
        # Verifikasi session milik user ini
        session = db.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id
        ).first()
        
        if not session:
            raise HTTPException(status_code=404, detail="Chat session tidak ditemukan")
        
        # Hapus semua pesan dari session terlebih dahulu
        db.query(ChatMessage).filter(
            ChatMessage.session_id == session_id
        ).delete()
        
        # Hapus session
        db.delete(session)
        db.commit()
        
        return {"message": "Chat session berhasil dihapus"}
    except HTTPException as e:
        raise e
    except Exception as e:
        db.rollback()
        logger.error(f"Error deleting chat session: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting chat session: {str(e)}")
    
# Di app/api/ai_routes.py
@router.post("/reset-extraction")
async def reset_extraction(
    request: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Hapus ekstraksi PDF untuk paper tertentu"""
    paper_id = request.get("paper_id")
    if not paper_id:
        raise HTTPException(status_code=400, detail="paper_id diperlukan")
    
    # Hapus ekstraksi milik user untuk paper_id ini
    extraction = db.query(PaperExtraction).filter(
        PaperExtraction.paper_id == paper_id,
        PaperExtraction.user_id == current_user.id
    ).first()
    
    if extraction:
        # Jika ada file PDF lokal, hapus file tersebut
        if extraction.pdf_url and extraction.pdf_url.startswith('local://'):
            try:
                file_path = extraction.pdf_url.replace('local://', '')
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Berhasil menghapus file PDF: {file_path}")
            except Exception as e:
                logger.error(f"Gagal menghapus file PDF: {str(e)}")
        
        # Hapus record dari database
        db.delete(extraction)
        db.commit()
        
        # Log aktivitas
        activity = UserActivity(
            user_id=current_user.id,
            paper_id=paper_id,
            activity_type="reset_extraction",
            activity_data=json.dumps({"action": "reset_pdf"})
        )
        db.add(activity)
        db.commit()
        
        return {"success": True, "message": "Ekstraksi PDF berhasil dihapus"}
    
    return {"success": False, "message": "Tidak ada ekstraksi PDF untuk dihapus"}