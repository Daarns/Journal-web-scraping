import time
import tempfile
import os
import logging
from datetime import datetime
import asyncio
import aiohttp
import fitz  # PyMuPDF
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from urllib.parse import urlparse, urljoin
import re
from bs4 import BeautifulSoup
import traceback
from ..core.database import get_db
from app.db.models import PaperExtraction
from app.scrapers.paper_scraper import AdaptiveSSLManager
import random

logger = logging.getLogger(__name__)

class PdfProcessor:
    """Service untuk mengunduh dan mengekstraksi teks dari PDF paper akademik"""
    
    def __init__(self):
        # Untuk throttling request
        self.domain_last_access = {}
        self.domain_min_interval = 2.0  # detik minimum antar request ke domain yang sama
        
        # Tambahkan daftar user agents di sini
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        ]
        
        # Untuk tracking statistik ekstraksi
        self.extraction_stats = {
            "total_attempts": 0,
            "success_count": 0,
            "failed_count": 0,
            "timeouts": 0,
            "domains_processed": set(),
            "avg_extraction_time_ms": 0,
            "total_extraction_time_ms": 0,
        }

    def _update_extraction_stats(self, success, url=None, extraction_time_ms=0):
        """Update statistik ekstraksi"""
        self.extraction_stats["total_attempts"] += 1
        
        if success:
            self.extraction_stats["success_count"] += 1
        else:
            self.extraction_stats["failed_count"] += 1
        
        if extraction_time_ms > 0:
            self.extraction_stats["total_extraction_time_ms"] += extraction_time_ms
            self.extraction_stats["avg_extraction_time_ms"] = (
                self.extraction_stats["total_extraction_time_ms"] / 
                self.extraction_stats["total_attempts"]
            )
        
        if url:
            domain = urlparse(url).netloc
            self.extraction_stats["domains_processed"].add(domain)
        
        # Log summary stats every 10 extractions
        if self.extraction_stats["total_attempts"] % 10 == 0:
            logger.info(f"PDF Extraction Stats: "
                       f"Total: {self.extraction_stats['total_attempts']}, "
                       f"Success: {self.extraction_stats['success_count']} "
                       f"({int(self.extraction_stats['success_count']/self.extraction_stats['total_attempts']*100)}%), "
                       f"Failed: {self.extraction_stats['failed_count']}, "
                       f"Avg Time: {self.extraction_stats['avg_extraction_time_ms']:.1f}ms")

    async def get_or_extract_text(self, db: Session, paper_id: str, pdf_url: str, current_user=None):
        """Ambil teks dari database atau ekstrak jika belum tersedia"""
        start_time = time.time()
        
        # 1. Cek ekstraksi pribadi milik pengguna saat ini jika pengguna login
        if current_user:
            private_extraction = db.query(PaperExtraction).filter(
                PaperExtraction.paper_id == paper_id,
                PaperExtraction.user_id == current_user.id
            ).first()
            
            if private_extraction and private_extraction.extraction_status == 'success' and private_extraction.extracted_text:
                logger.info(f"Menggunakan ekstraksi PDF pribadi untuk paper_id: {paper_id}")
                
                # Update last_accessed_at
                private_extraction.last_accessed_at = datetime.utcnow()
                db.commit()
                
                return private_extraction.extracted_text, None
        
        # 2. Cek ekstraksi publik (tidak terkait pengguna spesifik)
        public_extraction = db.query(PaperExtraction).filter(
            PaperExtraction.paper_id == paper_id,
            PaperExtraction.user_id.is_(None),
            or_(
                PaperExtraction.expires_at.is_(None),  # Permanen
                PaperExtraction.expires_at > datetime.utcnow()  # Belum expired
            )
        ).first()
        
        if public_extraction and public_extraction.extraction_status == 'success' and public_extraction.extracted_text:
            logger.info(f"Menggunakan ekstraksi PDF publik untuk paper_id: {paper_id}")
            
            # Update last_accessed_at
            public_extraction.last_accessed_at = datetime.utcnow()
            db.commit()
            
            return public_extraction.extracted_text, None
            
        # Cek apakah ini Semantic Scholar paper tanpa PDF URL
        if paper_id.startswith('ss_') and (not pdf_url or pdf_url == "None" or pdf_url == ""):
            logger.info(f"Semantic Scholar paper tanpa PDF URL, mencoba mendapatkan URL PDF: {paper_id}")
            article_url = f"https://www.semanticscholar.org/paper/{paper_id.replace('ss_', '')}"
            logger.info(f"Mencoba mendapatkan PDF dari halaman artikel Semantic Scholar: {article_url}")
            
            try:
                # Tambahkan timeout global untuk seluruh proses ekstraksi
                start_time = time.time()
                extracted_text, error = await asyncio.wait_for(
                    self.extract_text_from_article_url(article_url),
                    timeout=60.0  # 60 detik timeout
                )
                extraction_time = int((time.time() - start_time) * 1000)  # dalam milidetik
                
                if extracted_text:
                    # Simpan ke database dengan pendekatan hybrid
                    # Jika user login, simpan sebagai ekstraksi pribadi
                    # Jika tidak, simpan sebagai ekstraksi publik
                    extraction = db.query(PaperExtraction).filter(
                        PaperExtraction.paper_id == paper_id,
                        PaperExtraction.user_id == (current_user.id if current_user else None)
                    ).first()
                    
                    user_id = current_user.id if current_user else None
                    
                    if not extraction:
                        extraction = PaperExtraction(
                            paper_id=paper_id,
                            pdf_url=article_url,
                            extracted_text=extracted_text,
                            extraction_status='success',
                            extraction_date=datetime.utcnow(),
                            text_length=len(extracted_text),
                            extraction_attempts=1,
                            extraction_time=extraction_time,
                            user_id=user_id,
                            last_accessed_at=datetime.utcnow()
                        )
                        db.add(extraction)
                    else:
                        extraction.extracted_text = extracted_text
                        extraction.extraction_status = 'success'
                        extraction.text_length = len(extracted_text)
                        extraction.extraction_date = datetime.utcnow()
                        extraction.extraction_attempts = (extraction.extraction_attempts or 0) + 1
                        extraction.extraction_time = extraction_time
                        extraction.last_accessed_at = datetime.utcnow()
                    db.commit()
                    
                    # Update statistik
                    self._update_extraction_stats(True, article_url, extraction_time)
                    
                    return extracted_text, None
                else:
                    # Update statistik
                    self._update_extraction_stats(False, article_url, extraction_time)
                    
                    # Log failure
                    extraction = db.query(PaperExtraction).filter(
                        PaperExtraction.paper_id == paper_id,
                        PaperExtraction.user_id == (current_user.id if current_user else None)
                    ).first()
                    
                    user_id = current_user.id if current_user else None
                    
                    if extraction:
                        extraction.extraction_status = 'failed'
                        extraction.error_message = error
                        extraction.extraction_attempts = (extraction.extraction_attempts or 0) + 1
                        extraction.extraction_time = extraction_time
                        db.commit()
                    elif error:  # Create new extraction entry for the error if it doesn't exist
                        extraction = PaperExtraction(
                            paper_id=paper_id,
                            pdf_url=article_url,
                            extraction_status='failed',
                            extraction_date=datetime.utcnow(),
                            error_message=error,
                            extraction_attempts=1,
                            extraction_time=extraction_time,
                            user_id=user_id
                        )
                        db.add(extraction)
                        db.commit()
                    
                    return None, error or "Tidak dapat menemukan PDF untuk paper Semantic Scholar ini"
                    
            except asyncio.TimeoutError:
                logger.error(f"Extraction timeout for paper_id: {paper_id}")
                extraction_time = int((time.time() - start_time) * 1000)
                
                # Update statistik
                self.extraction_stats["timeouts"] += 1
                self._update_extraction_stats(False, article_url, extraction_time)
                
                # Update database
                extraction = db.query(PaperExtraction).filter(
                    PaperExtraction.paper_id == paper_id,
                    PaperExtraction.user_id == (current_user.id if current_user else None)
                ).first()
                
                user_id = current_user.id if current_user else None
                
                if extraction:
                    extraction.extraction_status = 'failed'
                    extraction.error_message = "Timeout pada ekstraksi PDF (60 detik)"
                    extraction.extraction_attempts = (extraction.extraction_attempts or 0) + 1
                    extraction.extraction_time = extraction_time
                else:
                    extraction = PaperExtraction(
                        paper_id=paper_id,
                        pdf_url=article_url,
                        extraction_status='failed',
                        extraction_date=datetime.utcnow(),
                        error_message="Timeout pada ekstraksi PDF (60 detik)",
                        extraction_attempts=1,
                        extraction_time=extraction_time,
                        user_id=user_id
                    )
                    db.add(extraction)
                db.commit()
                
                return None, "Proses ekstraksi PDF melebihi batas waktu (timeout 60 detik)"
        
        # Cek apakah sudah diekstraksi sebelumnya
        extraction = db.query(PaperExtraction).filter(
            PaperExtraction.paper_id == paper_id,
            # Filter berdasarkan user_id jika user login, atau cek ekstraksi publik jika tidak
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
        ).order_by(
            # Prioritaskan ekstraksi pribadi jika ada
            PaperExtraction.user_id.desc()
        ).first()
        
        if extraction:
            # Update last_accessed_at
            extraction.last_accessed_at = datetime.utcnow()
            db.commit()
            
            # Jika ekstraksi sebelumnya berhasil, kembalikan teks
            if extraction.extraction_status == 'success' and extraction.extracted_text:
                logger.info(f"Using cached PDF extraction for paper_id: {paper_id}")
                return extraction.extracted_text, None
            
            # Jika failed, coba lagi jika sudah lebih dari 1 jam atau URL berbeda
            elif extraction.extraction_status == 'failed':
                # Cek jumlah percobaan ekstraksi
                if not hasattr(extraction, 'extraction_attempts') or extraction.extraction_attempts is None:
                    extraction.extraction_attempts = 1
                else:
                    extraction.extraction_attempts += 1
                
                # Batas maksimum 3 kali upaya ekstraksi
                if extraction.extraction_attempts >= 3:
                    logger.warning(f"Maximum extraction attempts (3) reached for paper_id: {paper_id}")
                    return None, "Batas maksimum upaya ekstraksi tercapai (3 kali)"
                
                # Cek waktu ekstraksi sebelumnya dan juga URL PDF
                if (datetime.utcnow() - extraction.extraction_date).total_seconds() < 3600 and extraction.pdf_url == pdf_url:
                    return None, "PDF extraction previously failed and cooldown not elapsed"
                # Jika URL berbeda dari yang diproses sebelumnya, coba lagi
                elif extraction.pdf_url != pdf_url:
                    logger.info(f"URL PDF berubah, mencoba ekstraksi ulang dari {pdf_url}")
                    extraction.pdf_url = pdf_url
                else:
                    # Jika sama URL tapi sudah lebih dari 1 jam, lanjutkan dengan percobaan baru
                    logger.info(f"Cooldown elapsed, retrying extraction for {paper_id}")
        
        # Jika belum ada atau perlu coba lagi, lakukan ekstraksi
        user_id = current_user.id if current_user else None
        
        if not extraction:
            extraction = PaperExtraction(
                paper_id=paper_id,
                pdf_url=pdf_url,
                extraction_status='in_progress',
                extraction_attempts=1,
                user_id=user_id
            )
            db.add(extraction)
        else:
            extraction.extraction_status = 'in_progress'
            extraction.extraction_date = datetime.utcnow()
        
        db.commit()
        
        start_time = time.time()
        
        try:
            # Ekstrak teks dari PDF dengan timeout global
            extracted_text, error = await asyncio.wait_for(
                self.extract_text_from_pdf_url(pdf_url),
                timeout=60.0  # 60 detik timeout
            )
            
            end_time = time.time()
            extraction_time = int((end_time - start_time) * 1000)  # dalam milidetik
            
            # Update database dengan hasil ekstraksi
            if extracted_text:
                text_length = len(extracted_text)
                extraction.extracted_text = extracted_text
                extraction.extraction_status = 'success'
                extraction.extraction_time = extraction_time
                extraction.text_length = text_length
                extraction.last_accessed_at = datetime.utcnow()
                logger.info(f"Successfully extracted PDF for {paper_id}, {text_length} characters, {extraction_time}ms")
                
                # Update statistik
                self._update_extraction_stats(True, pdf_url, extraction_time)
            else:
                extraction.extraction_status = 'failed'
                extraction.error_message = error
                extraction.extraction_time = extraction_time
                logger.error(f"Failed to extract PDF for {paper_id}: {error}")
                
                # Update statistik
                self._update_extraction_stats(False, pdf_url, extraction_time)
                
            db.commit()
            return extracted_text, error
            
        except asyncio.TimeoutError:
            end_time = time.time()
            extraction_time = int((end_time - start_time) * 1000)
            
            # Update database
            extraction.extraction_status = 'failed'
            extraction.error_message = "Timeout pada ekstraksi PDF (60 detik)"
            extraction.extraction_time = extraction_time
            db.commit()
            
            # Update statistik
            self.extraction_stats["timeouts"] += 1
            self._update_extraction_stats(False, pdf_url, extraction_time)
            
            logger.error(f"Extraction timeout for paper_id: {paper_id}")
            return None, "Proses ekstraksi PDF melebihi batas waktu (timeout 60 detik)"

    async def extract_text_from_pdf_url(self, pdf_url, depth=0, visited_urls=None):
        """Mengunduh dan mengekstrak teks dari URL PDF langsung"""
        # Inisialisasi set URL yang dikunjungi
        if visited_urls is None:
            visited_urls = set()
        
        # Batasi kedalaman rekursi
        if depth > 3:
            logger.warning(f"Kedalaman rekursi maksimum tercapai (3) untuk URL: {pdf_url}")
            return None, "Kedalaman rekursi maksimum tercapai (3)"
            
        # Cek URL duplikat untuk mencegah loop
        if pdf_url in visited_urls:
            logger.warning(f"URL sudah dikunjungi sebelumnya: {pdf_url}")
            return None, f"URL sudah dikunjungi sebelumnya: {pdf_url}"
        
        # TAMBAHKAN KODE DISINI - Penanganan PDF lokal
        if pdf_url and pdf_url.startswith('local://'):
            # Ini adalah file lokal, bukan URL internet
            local_path = pdf_url.replace('local://', '')
            if os.path.exists(local_path):
                logger.info(f"Mengakses file PDF lokal: {local_path}")
                try:
                    text = self.extract_text_from_uploaded_pdf(local_path)
                    if text:
                        return text, None
                    else:
                        return None, "Gagal mengekstrak teks dari PDF lokal"
                except Exception as e:
                    logger.error(f"Error saat mengekstrak PDF lokal: {str(e)}")
                    return None, f"Gagal mengekstrak teks dari PDF lokal: {str(e)}"
            else:
                logger.warning(f"File PDF lokal tidak ditemukan: {local_path}")
                return None, "File PDF lokal tidak ditemukan"
                
        # Tambahkan URL saat ini ke daftar yang sudah dikunjungi
        visited_urls.add(pdf_url)
        
        # ... kode throttling dan seterusnya
        
        # Throttling untuk domain yang sama
        domain = urlparse(pdf_url).netloc
        now = time.time()
        
        if domain in self.domain_last_access:
            elapsed = now - self.domain_last_access[domain]
            if elapsed < self.domain_min_interval:
                # Tunggu sebentar untuk mencegah rate-limiting
                await asyncio.sleep(self.domain_min_interval - elapsed)
        
        # Update waktu akses terakhir
        self.domain_last_access[domain] = time.time()
        
        # Deteksi URL yang mengandung path yang tidak mungkin PDF
        parsed_url = urlparse(pdf_url)
        path = parsed_url.path.lower()
        if any(x in path for x in ['about', 'policies', 'editorial', 'contact', 'login']):
            logger.warning(f"URL mengarah ke halaman non-PDF: {pdf_url}")
            return None, f"URL mengarah ke halaman non-PDF: {pdf_url}"
        
        # Validasi URL
        if not pdf_url or not self._is_valid_url(pdf_url):
            return None, "Invalid PDF URL"
        
        try:
            logger.info(f"Downloading PDF from URL: {pdf_url}")
            
            # Deteksi jenis sumber berdasarkan URL
            is_researchgate = 'researchgate.net' in pdf_url.lower()
            is_semantic_scholar = 'semanticscholar.org' in pdf_url.lower()
            is_pdfs_semantic_scholar = 'pdfs.semanticscholar.org' in pdf_url.lower() 
            is_arxiv = 'arxiv.org' in pdf_url.lower()
            is_sciencedirect = 'sciencedirect.com' in pdf_url.lower()
            
            # Headers dasar yang digunakan untuk semua sumber
            base_headers = {
                'User-Agent': random.choice(self.user_agents),  # Gunakan random User-Agent
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Cache-Control': 'no-cache',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-User': '?1',
                'DNT': '1'
            }
            
            # Pilih header khusus berdasarkan sumber
            if is_researchgate:
                logger.info("Menggunakan header khusus untuk ResearchGate")
                headers = {
                    **base_headers,
                    'Referer': 'https://www.researchgate.net/',
                    'Sec-Fetch-Site': 'same-origin',
                    'Origin': 'https://www.researchgate.net',
                    'x-requested-with': 'XMLHttpRequest',
                    'sec-fetch-site': 'same-origin'
                }

            elif is_pdfs_semantic_scholar:  # Berikan prioritas yang lebih tinggi untuk domain pdfs.semanticscholar.org
                logger.info("Menggunakan header khusus untuk domain pdfs.semanticscholar.org")
                headers = {
                    **base_headers,
                    "Accept": "application/pdf,application/x-pdf,text/html,application/xhtml+xml,*/*",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Referer": "https://www.semanticscholar.org/",
                    "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
                    "sec-ch-ua-platform": "Windows",
                    "sec-fetch-dest": "document",
                    "sec-fetch-mode": "navigate",
                    "sec-fetch-site": "same-site",
                    "DNT": "1",
                    "Cookie": "_ga=GA1.1.random.random; __Secure-SID=any-value"  # Tambahkan cookie langsung ke header
                }
                
                # Tambahkan delay acak
                await asyncio.sleep(random.uniform(2, 5))
                            
            elif is_semantic_scholar:
                logger.info("Menggunakan header khusus untuk Semantic Scholar")
                headers = {
                    **base_headers,
                    'Referer': 'https://www.semanticscholar.org/',
                    'Sec-Fetch-Site': 'cross-site',
                    'Origin': 'https://www.semanticscholar.org'
                }
            elif is_arxiv:
                logger.info("Menggunakan header khusus untuk arXiv")
                headers = {
                    **base_headers,
                    'Referer': 'https://arxiv.org/',
                    'Sec-Fetch-Site': 'same-site',
                    'Origin': 'https://arxiv.org'
                }
            elif 'springer.com' in pdf_url.lower():
                logger.info("Menggunakan header khusus untuk Springer")
                headers = {
                    **base_headers,
                    'Referer': 'https://link.springer.com/',
                    'Sec-Fetch-Site': 'same-origin',
                    'Origin': 'https://link.springer.com',
                    'Content-Type': 'application/pdf'
                }
            elif is_sciencedirect:
                logger.info("Menggunakan header khusus untuk ScienceDirect")
                headers = {
                    **base_headers,
                    'Referer': 'https://www.sciencedirect.com/',
                    'Sec-Fetch-Site': 'same-origin',
                    'Origin': 'https://www.sciencedirect.com',
                    'Content-Type': 'application/pdf'
                }
            else:
                # Header default untuk sumber lain
                logger.info("Menggunakan header default untuk URL: " + pdf_url)
                headers = {
                    **base_headers,
                    'Referer': f"https://{urlparse(pdf_url).netloc}/",
                    'Sec-Fetch-Site': 'cross-site',
                    'Origin': f"https://{urlparse(pdf_url).netloc}"
                }
            
            try:
                response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                    pdf_url,
                    headers=headers,
                    method="GET",
                    allow_redirects=True
                )
                
                if response.status != 200:
                    logger.warning(f"Failed to download PDF: HTTP {response.status}")
                    return None, f"Failed to download PDF: HTTP {response.status}"
                
                # Periksa content-type untuk memastikan ini adalah PDF
                content_type = response.headers.get('Content-Type', '').lower()
                if 'application/pdf' not in content_type:
                    if 'text/html' in content_type or 'application/xhtml' in content_type:
                        logger.info(f"URL bukan PDF langsung tetapi halaman HTML, mencoba ekstrak PDF dari halaman...")
                        # Teruskan parameter depth dan visited_urls
                        return await self.extract_text_from_article_url(pdf_url, depth + 1, visited_urls)
                    logger.warning(f"URL tidak mengarah ke file PDF. Content-Type: {content_type}")
                    return None, f"URL tidak mengarah ke file PDF. Content-Type: {content_type}"
                
                # Unduh data PDF
                pdf_data = await response.read()
                logger.info(f"PDF berhasil diunduh, ukuran: {len(pdf_data)} bytes")
                
                # Ekstrak teks dari data PDF
                extracted_text = self._extract_text_from_pdf_data(pdf_data)
                
                if not extracted_text:
                    return None, "Gagal mengekstrak teks dari PDF (PDF mungkin berupa gambar/scan atau rusak)"
                
                return extracted_text, None
                
            except aiohttp.ClientError as e:
                logger.error(f"Error jaringan saat mengunduh PDF: {str(e)}")
                return None, f"Error jaringan: {str(e)}"
                    
        except Exception as e:
            logger.error(f"Error umum saat memproses PDF: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None, f"Error saat memproses PDF: {str(e)}"
    
    async def extract_text_from_article_url(self, article_url, depth=0, visited_urls=None):
        """Ekstrak URL PDF dari halaman artikel jurnal dan kemudian ekstrak teksnya"""
        # Inisialisasi set URL yang dikunjungi
        if visited_urls is None:
            visited_urls = set()
        
        # Batasi kedalaman rekursi
        if depth > 3:
            logger.warning(f"Kedalaman rekursi maksimum tercapai (3) untuk artikel URL: {article_url}")
            return None, "Kedalaman rekursi maksimum tercapai (3)"
            
        # Cek URL duplikat untuk mencegah loop
        if article_url in visited_urls:
            logger.warning(f"URL artikel sudah dikunjungi sebelumnya: {article_url}")
            return None, f"URL sudah dikunjungi sebelumnya: {article_url}"
            
        # Tambahkan URL saat ini ke daftar yang sudah dikunjungi
        visited_urls.add(article_url)
        
        # Throttling untuk domain yang sama
        domain = urlparse(article_url).netloc
        now = time.time()
        
        if domain in self.domain_last_access:
            elapsed = now - self.domain_last_access[domain]
            if elapsed < self.domain_min_interval:
                # Tunggu sebentar untuk mencegah rate-limiting
                await asyncio.sleep(self.domain_min_interval - elapsed)
        
        # Update waktu akses terakhir
        self.domain_last_access[domain] = time.time()
        
        # Deteksi URL yang mengandung path yang tidak mungkin berisi PDF
        parsed_url = urlparse(article_url)
        path = parsed_url.path.lower()
        if any(x in path for x in ['about', 'policies', 'editorial', 'contact', 'login']):
            logger.warning(f"URL artikel mengarah ke halaman non-artikel: {article_url}")
            return None, f"URL mengarah ke halaman non-artikel: {article_url}"
        
        try:
            logger.info(f"Mengakses halaman artikel: {article_url}")
            
            # Deteksi sumber artikel
            is_semantic_scholar = 'semanticscholar.org' in article_url.lower()
            is_doi = 'doi.org' in article_url.lower()
            is_ojs = 'index.php' in article_url.lower() and ('article' in article_url.lower() or 'view' in article_url.lower())
            
         
            article_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate",  # Hapus 'br' untuk menghindari masalah brotli
                "Cache-Control": "no-cache",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1"
            }
                        
            if is_semantic_scholar:
                return await self._extract_pdf_from_semantic_scholar(article_url, None, article_headers, depth, visited_urls)
            elif is_ojs:
                # Perbaikan indentasi dan penggunaan metode ekstraksi DOI dari OJS
                doi_url = await self._extract_doi_from_ojs(article_url, article_headers)
                if doi_url:
                    logger.info(f"Menemukan DOI dari OJS: {doi_url}")
                    return await self._resolve_doi_to_pdf(doi_url, None, article_headers, depth + 1, visited_urls)
            elif is_doi:
                return await self._resolve_doi_to_pdf(article_url, None, article_headers, depth, visited_urls)

            # Jika bukan sumber khusus, lanjutkan dengan proses umum menggunakan AdaptiveSSLManager
            response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                article_url,
                headers=article_headers,
                method="GET",
                allow_redirects=True
            )
            
            if response.status != 200:
                logger.warning(f"Gagal mengakses halaman artikel (status {response.status})")
                return None, f"Gagal mengakses halaman artikel (status {response.status})"
            
            logger.info(f"Halaman artikel berhasil diakses, mencari link PDF...")
            html_content = await response.text()
            
            # Parse HTML untuk mencari link PDF
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Cari link PDF berdasarkan pattern umum
            pdf_link = await self._find_pdf_link_in_html(soup, article_url)
            
            if not pdf_link:
                logger.warning(f"Tidak dapat menemukan link PDF pada halaman artikel: {article_url}")
                return None, "Tidak dapat menemukan link PDF pada halaman artikel"
            
            # Normalisasi URL PDF (ubah relative URL menjadi absolute)
            pdf_link = self._normalize_url(pdf_link, article_url)
            
            logger.info(f"Link PDF dinormalisasi: {pdf_link}")
            
            # Cek apakah URL PDF sama dengan URL artikel (untuk mencegah infinite loop)
            if pdf_link == article_url:
                logger.warning(f"Link PDF sama dengan URL artikel, kemungkinan infinite loop: {pdf_link}")
                return None, "Link PDF sama dengan URL artikel (infinite loop)"
            
            # Gunakan URL PDF yang ditemukan untuk ekstraksi teks dengan parameter untuk mendeteksi rekursi
            return await self.extract_text_from_pdf_url(pdf_link, depth + 1, visited_urls)

        except Exception as e:
            logger.error(f"Error saat mencari PDF dari halaman artikel: {str(e)}")
            return None, f"Error saat mencari PDF: {str(e)}"
              
    def _is_valid_url(self, url):
        """Validasi URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except:
            return False
    
    def _extract_text_from_pdf_data(self, pdf_data):
        """Ekstrak teks dari data PDF binary menggunakan PyMuPDF"""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_path = temp_file.name
                temp_file.write(pdf_data)
            
            logger.info(f"PDF ditulis ke file temporary: {temp_path}")
            
            try:
                doc = fitz.open(temp_path)
                page_count = len(doc)
                logger.info(f"PDF berhasil dibuka, jumlah halaman: {page_count}")
                
                text = ""
                # Proses tiap halaman
                for page_num in range(page_count):
                    page = doc.load_page(page_num)
                    page_text = page.get_text()
                    text += page_text
                    
                    # Log statistik per halaman untuk debugging
                    if page_num == 0 or page_num == page_count-1:
                        logger.debug(f"Halaman {page_num+1}: {len(page_text)} karakter")
                
                doc.close()
                logger.info(f"Ekstrak teks PDF selesai, total: {len(text)} karakter")
                
                # Pra-proses teks
                processed_text = self._preprocess_pdf_text(text)
                
                if not processed_text or len(processed_text.strip()) < 50:
                    logger.warning(f"Teks hasil ekstraksi terlalu pendek: {len(processed_text)} karakter")
                    return None
                    
                return processed_text
            finally:
                # Bersihkan file temporary
                try:
                    os.unlink(temp_path)
                    logger.debug(f"File temporary berhasil dihapus: {temp_path}")
                except Exception as e:
                    logger.warning(f"Gagal menghapus file temporary: {str(e)}")
        except Exception as e:
            logger.error(f"Error saat ekstraksi teks dari PDF: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
     
    async def _extract_pdf_from_semantic_scholar(self, article_url, session, headers, depth=0, visited_urls=None):
        """Metode khusus untuk mengekstrak PDF dari Semantic Scholar dengan penanganan koneksi yang lebih robust"""
        if visited_urls is None:
            visited_urls = set()
        
        try:
            logger.info("Mendeteksi situs Semantic Scholar, mencari link dengan metode khusus")
            
            # Ekstrak paper ID dari URL
            paper_id = None
            if '/paper/' in article_url:
                paper_id = article_url.split('/paper/')[-1].split('/')[0]
            
            # Coba ambil data dari API Semantic Scholar terlebih dahulu jika ID tersedia
            data = None
            html_content = None
            soup = None
            
            if paper_id:
                api_url = f"https://api.semanticscholar.org/v1/paper/{paper_id}"
                
                try:
                    # 1. Tambahkan delay untuk mengurangi risiko rate limiting
                    await asyncio.sleep(2)
                    
                    # 2. Gunakan User-Agent yang lebih realistis
                    enhanced_headers = {**headers}
                    enhanced_headers["User-Agent"] = random.choice(self.user_agents)
                    
                    # 3. Tambahkan penanganan timeout dan retry
                    retry_count = 0
                    max_retries = 3
                    
                    while retry_count < max_retries:
                        try:
                            # Gunakan AdaptiveSSLManager dengan timeout yang lebih panjang
                            if session is None:
                                response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                                    api_url,
                                    headers=enhanced_headers,
                                    method="GET",
                                    timeout=30
                                )
                                if response.status == 200:
                                    data = await response.json()
                                    
                                    # Proses data jika berhasil diambil
                                    if data:
                                        # Cek apakah ada PDF URL
                                        if 'openAccessPdf' in data and data['openAccessPdf'] and 'url' in data['openAccessPdf']:
                                            pdf_url = data['openAccessPdf']['url']
                                            logger.info(f"Menemukan PDF URL dari API Semantic Scholar: {pdf_url}")
                                            
                                            # Cek apakah URL PDF sudah dikunjungi sebelumnya
                                            if pdf_url in visited_urls:
                                                logger.warning(f"PDF URL sudah dikunjungi sebelumnya: {pdf_url}")
                                                return None, f"URL sudah dikunjungi sebelumnya: {pdf_url}"
                                            
                                            result = await self.extract_text_from_pdf_url(pdf_url, depth + 1, visited_urls)
                                            # Pastikan hasil adalah tuple (extracted_text, error)
                                            if isinstance(result, tuple) and len(result) == 2:
                                                return result
                                            else:
                                                logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                                                return None, "Error format hasil ekstraksi PDF"
                                        
                                        # Cek DOI
                                        if 'doi' in data and data['doi']:
                                            doi_url = f"https://doi.org/{data['doi']}"
                                            logger.info(f"Menemukan DOI dari API Semantic Scholar: {doi_url}")
                                            
                                            # Cek apakah DOI URL sudah dikunjungi sebelumnya
                                            if doi_url in visited_urls:
                                                logger.warning(f"DOI URL sudah dikunjungi sebelumnya: {doi_url}")
                                                return None, f"URL sudah dikunjungi sebelumnya: {doi_url}"
                                            
                                            result = await self._resolve_doi_to_pdf(doi_url, session, enhanced_headers, depth + 1, visited_urls)
                                            # Pastikan hasil adalah tuple (extracted_text, error)
                                            if isinstance(result, tuple) and len(result) == 2:
                                                return result
                                            else:
                                                logger.error(f"Invalid result from _resolve_doi_to_pdf: {result}")
                                                return None, "Error format hasil ekstraksi PDF dari DOI"
                                    
                                    break  # Keluar dari loop jika sukses
                                elif response.status == 202:
                                    # Status 202 berarti Semantic Scholar melakukan processing, tunggu dan coba lagi
                                    logger.info(f"Received status 202 from API, waiting before retry {retry_count+1}/{max_retries}")
                                    await asyncio.sleep(3)  # Tunggu 3 detik
                                    retry_count += 1
                                else:
                                    logger.warning(f"API returned status {response.status}, trying fallback method")
                                    break  # Gagal dengan status non-202, coba metode fallback
                            else:
                                async with session.get(api_url, headers=enhanced_headers) as response:
                                    if response.status == 200:
                                        data = await response.json()
                                        # Proses data seperti di atas...
                                        # Cek apakah ada PDF URL
                                        if 'openAccessPdf' in data and data['openAccessPdf'] and 'url' in data['openAccessPdf']:
                                            pdf_url = data['openAccessPdf']['url']
                                            logger.info(f"Menemukan PDF URL dari API Semantic Scholar: {pdf_url}")
                                            
                                            # Cek apakah URL PDF sudah dikunjungi sebelumnya
                                            if pdf_url in visited_urls:
                                                logger.warning(f"PDF URL sudah dikunjungi sebelumnya: {pdf_url}")
                                                return None, f"URL sudah dikunjungi sebelumnya: {pdf_url}"
                                            
                                            result = await self.extract_text_from_pdf_url(pdf_url, depth + 1, visited_urls)
                                            # Pastikan hasil adalah tuple (extracted_text, error)
                                            if isinstance(result, tuple) and len(result) == 2:
                                                return result
                                            else:
                                                logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                                                return None, "Error format hasil ekstraksi PDF"
                                        
                                        # Cek DOI
                                        if 'doi' in data and data['doi']:
                                            doi_url = f"https://doi.org/{data['doi']}"
                                            logger.info(f"Menemukan DOI dari API Semantic Scholar: {doi_url}")
                                            
                                            # Cek apakah DOI URL sudah dikunjungi sebelumnya
                                            if doi_url in visited_urls:
                                                logger.warning(f"DOI URL sudah dikunjungi sebelumnya: {doi_url}")
                                                return None, f"URL sudah dikunjungi sebelumnya: {doi_url}"
                                            
                                            result = await self._resolve_doi_to_pdf(doi_url, session, enhanced_headers, depth + 1, visited_urls)
                                            # Pastikan hasil adalah tuple (extracted_text, error)
                                            if isinstance(result, tuple) and len(result) == 2:
                                                return result
                                            else:
                                                logger.error(f"Invalid result from _resolve_doi_to_pdf: {result}")
                                                return None, "Error format hasil ekstraksi PDF dari DOI"
                                        break
                                    elif response.status == 202:
                                        logger.info(f"Received status 202 from API, waiting before retry {retry_count+1}/{max_retries}")
                                        await asyncio.sleep(3)
                                        retry_count += 1
                                    else:
                                        logger.warning(f"API returned status {response.status}, trying fallback method")
                                        break
                        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                            # Tangani error koneksi atau timeout
                            logger.warning(f"Connection error to API: {str(e)}, retry {retry_count+1}/{max_retries}")
                            retry_count += 1
                            if retry_count >= max_retries:
                                raise
                            await asyncio.sleep(2 * retry_count)  # Backoff eksponensial
                
                except Exception as e:
                    logger.error(f"Error saat akses API Semantic Scholar: {str(e)}")
                    logger.info("Gagal mengakses API Semantic Scholar, menggunakan metode fallback")
            
            # Jika tidak berhasil lewat API, gunakan parsing HTML dengan penanganan status 202
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                try:
                    # Tambahkan delay bertahap
                    await asyncio.sleep(1 + retry_count)
                    
                    # 4. Tambahkan cookie dan referer untuk tampil lebih seperti browser asli
                    enhanced_headers = {
                        **headers,
                        "Referer": "https://www.semanticscholar.org/search",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache"
                    }
                    
                    if session is None:
                        response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                            article_url,
                            headers=enhanced_headers,
                            method="GET",
                            allow_redirects=True,
                            timeout=30
                        )
                        
                        if response.status == 200:
                            html_content = await response.text()
                            soup = BeautifulSoup(html_content, 'html.parser')
                            break  # Keluar dari loop retry jika sukses
                        elif response.status == 202:
                            # Status 202 mungkin adalah anti-scraping, coba lagi dengan delay lebih panjang
                            logger.info(f"Received status 202 from page, waiting before retry {retry_count+1}/{max_retries}")
                            retry_count += 1
                            await asyncio.sleep(3 * retry_count)  # Tunggu lebih lama setiap percobaan
                            if retry_count >= max_retries:
                                return None, f"Gagal mengakses halaman Semantic Scholar (status {response.status} setelah {max_retries} percobaan)"
                        else:
                            # Status error lainnya
                            logger.warning(f"Gagal mengakses halaman Semantic Scholar (status {response.status})")
                            return None, f"Gagal mengakses halaman Semantic Scholar (status {response.status})"
                    else:
                        async with session.get(article_url, headers=enhanced_headers, allow_redirects=True) as response:
                            if response.status == 200:
                                html_content = await response.text()
                                soup = BeautifulSoup(html_content, 'html.parser')
                                break
                            elif response.status == 202:
                                logger.info(f"Received status 202 from page, waiting before retry {retry_count+1}/{max_retries}")
                                retry_count += 1
                                await asyncio.sleep(3 * retry_count)
                                if retry_count >= max_retries:
                                    return None, f"Gagal mengakses halaman Semantic Scholar (status {response.status} setelah {max_retries} percobaan)"
                            else:
                                logger.warning(f"Gagal mengakses halaman Semantic Scholar (status {response.status})")
                                return None, f"Gagal mengakses halaman Semantic Scholar (status {response.status})"
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"Connection error to HTML page: {str(e)}, retry {retry_count+1}/{max_retries}")
                    retry_count += 1
                    if retry_count >= max_retries:
                        return None, f"Gagal mengakses halaman Semantic Scholar: {str(e)}"
                    # Backoff eksponensial
                    await asyncio.sleep(2 * retry_count)
            
            # 5. Coba metode alternatif jika kedua pendekatan gagal
            if (not html_content or "captcha" in html_content.lower()) and paper_id:
                logger.warning("Terdeteksi CAPTCHA atau halaman kosong dari Semantic Scholar, mencoba metode fallback DOI")
                
                # Coba ambil DOI dari URL alternatif
                try:
                    alt_api_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=externalIds"
                    response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                        alt_api_url,
                        headers=enhanced_headers,
                        method="GET",
                        timeout=30
                    )
                    
                    if response.status == 200:
                        data = await response.json()
                        if 'externalIds' in data and 'DOI' in data['externalIds']:
                            doi = data['externalIds']['DOI']
                            doi_url = f"https://doi.org/{doi}"
                            logger.info(f"Menemukan DOI dari API alternatif: {doi_url}")
                            return await self._resolve_doi_to_pdf(doi_url, session, headers, depth + 1, visited_urls)
                except Exception as e:
                    logger.error(f"Error mencoba metode fallback DOI: {str(e)}")
            
            # Jika berhasil mendapatkan HTML content, proses untuk mencari PDF link
            if soup:
                # Debug untuk melihat semua link
                all_links = soup.find_all('a', href=True)
                logger.debug(f"Total links found: {len(all_links)}")
                doi_links = [a for a in all_links if 'doi.org' in a.get('href', '')]
                logger.debug(f"DOI links found: {len(doi_links)}")
                if doi_links:
                    for i, link in enumerate(doi_links[:3]):  # Batasi hanya 3 link untuk log
                        logger.debug(f"DOI link {i+1}: {link.get('href')}, text: {link.get_text().strip()}")
                
                # 1. Cari link "View PDF" atau tombol utama
                pdf_link = None
                primary_buttons = soup.select('a[data-heap-id="paper_link_target"]')
                for btn in primary_buttons:
                    href = btn.get('href')
                    if href and ('pdf' in href.lower() or 'pdf' in btn.text.lower()):
                        # Cek jika href tidak mengarah ke halaman non-PDF
                        if not any(x in href.lower() for x in ['about', 'policies', 'editorial', 'contact']):
                            logger.info(f"Menemukan link PDF langsung di Semantic Scholar: {href}")
                            pdf_link = href
                            break
                
                # 2. Cari link berbasis DOI
                if not pdf_link:
                    doi_buttons = soup.select('a[data-heap-link-type="doi"]')
                    for btn in doi_buttons:
                        href = btn.get('href')
                        if href and 'doi.org' in href:
                            # Cek apakah DOI URL sudah dikunjungi
                            if href in visited_urls:
                                logger.warning(f"DOI URL sudah dikunjungi sebelumnya: {href}")
                                continue
                            
                            logger.info(f"Menemukan DOI di Semantic Scholar: {href}")
                            result = await self._resolve_doi_to_pdf(href, session, headers, depth + 1, visited_urls)
                            # Pastikan hasil valid
                            if isinstance(result, tuple) and len(result) == 2:
                                return result
                            else:
                                logger.error(f"Invalid result from _resolve_doi_to_pdf: {result}")
                                return None, "Error format hasil ekstraksi PDF dari DOI"
                
                # 3. Cek juga nilai 'link' attribute pada tombol yang mungkin berisi URL JSON
                if not pdf_link:
                    link_attrs = []
                    for element in soup.select('[link]'):
                        link_attr = element.get('link')
                        if link_attr and 'url' in link_attr:
                            try:
                                # Mencoba ekstrak URL dari atribut JSON-like
                                url_match = re.search(r'url:\s*["\']([^"\']+)["\']', link_attr)
                                if url_match:
                                    extracted_url = url_match.group(1)
                                    # Filter URL yang mengandung keyword non-PDF
                                    if not any(x in extracted_url.lower() for x in ['about', 'policies', 'editorial', 'contact']):
                                        link_attrs.append(extracted_url)
                            except:
                                pass
                    
                    # Coba setiap URL yang ditemukan
                    for url in link_attrs:
                        if url.startswith('http'):
                            # Cek apakah URL sudah dikunjungi
                            if url in visited_urls:
                                logger.warning(f"URL sudah dikunjungi sebelumnya: {url}")
                                continue
                                
                            logger.info(f"Mencoba URL dari atribut link: {url}")
                            if 'doi.org' in url:
                                result = await self._resolve_doi_to_pdf(url, session, headers, depth + 1, visited_urls)
                                # Pastikan hasil valid
                                if isinstance(result, tuple) and len(result) == 2:
                                    return result
                                else:
                                    logger.error(f"Invalid result from _resolve_doi_to_pdf: {result}")
                                    return None, "Error format hasil ekstraksi PDF dari DOI"
                            elif 'pdf' in url.lower():
                                pdf_link = url
                                break
                
                # Jika PDF link ditemukan, ekstrak teksnya
                if pdf_link:
                    # Normalisasi URL
                    pdf_link = self._normalize_url(pdf_link, article_url)
                    
                    # Cek apakah PDF link sama dengan article URL (mencegah loop)
                    if pdf_link == article_url:
                        logger.warning(f"PDF link sama dengan URL artikel: {pdf_link}")
                        return None, "PDF link sama dengan URL artikel (infinite loop)"
                    
                    # Cek apakah PDF link sudah dikunjungi
                    if pdf_link in visited_urls:
                        logger.warning(f"PDF link sudah dikunjungi sebelumnya: {pdf_link}")
                        return None, f"URL sudah dikunjungi sebelumnya: {pdf_link}"
                    
                    result = await self.extract_text_from_pdf_url(pdf_link, depth + 1, visited_urls)
                    # Pastikan hasil valid
                    if isinstance(result, tuple) and len(result) == 2:
                        return result
                    else:
                        logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                        return None, "Error format hasil ekstraksi PDF"
                
                # Jika tidak menemukan PDF link, cari DOI untuk resolusi
                doi_elements = soup.select('a[href*="doi.org"]')
                if doi_elements:
                    for doi_element in doi_elements[:3]:  # Coba 3 link DOI pertama
                        doi_link = doi_element['href']
                        
                        # Cek apakah DOI link sudah dikunjungi
                        if doi_link in visited_urls:
                            logger.warning(f"DOI link sudah dikunjungi sebelumnya: {doi_link}")
                            continue
                        
                        logger.info(f"Menemukan DOI link di halaman Semantic Scholar: {doi_link}")
                        result = await self._resolve_doi_to_pdf(doi_link, session, headers, depth + 1, visited_urls)
                        # Pastikan hasil valid
                        if isinstance(result, tuple) and len(result) == 2 and result[0] is not None:
                            return result
            
            return None, "Tidak dapat menemukan link PDF pada halaman Semantic Scholar"
    
        except Exception as e:
            logger.error(f"Error mencari PDF di Semantic Scholar: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None, f"Error mencari PDF di Semantic Scholar: {str(e)}"    
         
    async def _resolve_doi_to_pdf(self, doi_url, session, headers, depth=0, visited_urls=None):
        """Resolve DOI URL ke URL PDF jika memungkinkan dengan penanganan SSL adaptif"""
        if visited_urls is None:
            visited_urls = set()
        
        # Batasi kedalaman rekursi khusus untuk resolusi DOI
        if depth > 2:
            logger.warning(f"Kedalaman rekursi maksimum tercapai untuk resolusi DOI: {doi_url}")
            return None, "Kedalaman rekursi maksimum tercapai untuk resolusi DOI (2)"
            
        # Cek URL duplikat
        if doi_url in visited_urls:
            logger.warning(f"DOI URL sudah dikunjungi sebelumnya: {doi_url}")
            return None, f"URL sudah dikunjungi sebelumnya: {doi_url}"
            
        # Tambahkan DOI URL ke daftar yang sudah dikunjungi
        visited_urls.add(doi_url)
        
        try:
            logger.info(f"Resolving DOI URL: {doi_url}")
            
            # Update headers untuk request DOI
            enhanced_headers = {**headers}
            enhanced_headers["User-Agent"] = random.choice(self.user_agents)
            
            # Gunakan AdaptiveSSLManager untuk request DOI dengan penanganan SSL yang fleksibel
            try:
                response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                    doi_url,
                    headers=enhanced_headers,
                    method="GET",
                    allow_redirects=True
                )
                
                if response.status != 200:
                    logger.warning(f"Gagal resolve DOI (status {response.status})")
                    return None, f"Gagal resolve DOI (status {response.status})"
                
                # Dapatkan URL hasil redirect
                final_url = str(response.url)
                
                # Cek apakah URL hasil redirect sudah dikunjungi
                if final_url != doi_url and final_url in visited_urls:
                    logger.warning(f"URL redirect sudah dikunjungi sebelumnya: {final_url}")
                    return None, f"URL sudah dikunjungi sebelumnya: {final_url}"
                
                # Tambahkan URL hasil redirect ke daftar yang sudah dikunjungi
                if final_url != doi_url:
                    visited_urls.add(final_url)
                
                # Cek apakah redirect langsung ke PDF
                content_type = response.headers.get('Content-Type', '').lower()
                if 'application/pdf' in content_type:
                    pdf_url = final_url
                    logger.info(f"DOI redirected langsung ke PDF: {pdf_url}")
                    result = await self.extract_text_from_pdf_url(pdf_url, depth + 1, visited_urls)
                    # Pastikan hasil valid
                    if isinstance(result, tuple) and len(result) == 2:
                        return result
                    else:
                        logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                        return None, "Error format hasil ekstraksi PDF"
                
                # Parse HTML untuk menemukan PDF
                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Metode menemukan PDF di halaman jurnal
                pdf_link = await self._find_pdf_link_in_html(soup, final_url)
                
                if pdf_link:
                    # Normalisasi URL
                    pdf_link = self._normalize_url(pdf_link, final_url)
                    
                    # Jika URL PDF yang ditemukan menggunakan domain yang sama dengan DOI,
                    # pastikan kita menggunakan mode SSL yang sesuai untuk domain tersebut
                    pdf_domain = urlparse(pdf_link).netloc
                    original_domain = urlparse(final_url).netloc
                    if pdf_domain == original_domain and AdaptiveSSLManager.is_problematic_domain(final_url):
                        # Tambahkan PDF domain ke daftar bermasalah juga
                        AdaptiveSSLManager.register_domain_failure(pdf_link, "ssl_verification")
                    
                    # Cek apakah PDF link sama dengan DOI URL atau URL hasil redirect
                    if pdf_link == doi_url or pdf_link == final_url:
                        logger.warning(f"PDF link sama dengan URL DOI atau redirect: {pdf_link}")
                        return None, "PDF link sama dengan URL DOI atau redirect (infinite loop)"
                    
                    # Cek apakah PDF link sudah dikunjungi
                    if pdf_link in visited_urls:
                        logger.warning(f"PDF link sudah dikunjungi sebelumnya: {pdf_link}")
                        return None, f"URL sudah dikunjungi sebelumnya: {pdf_link}"
                    
                    logger.info(f"Menemukan PDF URL dari DOI: {pdf_link}")
                    result = await self.extract_text_from_pdf_url(pdf_link, depth + 1, visited_urls)
                    # Pastikan hasil valid
                    if isinstance(result, tuple) and len(result) == 2:
                        return result
                    else:
                        logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                        return None, "Error format hasil ekstraksi PDF"
                
                # Cek juga meta tag untuk PDF
                pdf_meta = soup.find('meta', {'name': 'citation_pdf_url'})
                if pdf_meta and pdf_meta.get('content'):
                    pdf_link = pdf_meta.get('content')
                    pdf_link = self._normalize_url(pdf_link, final_url)
                    
                    # Cek apakah PDF meta link sama dengan DOI URL atau URL hasil redirect
                    if pdf_link == doi_url or pdf_link == final_url:
                        logger.warning(f"PDF meta link sama dengan URL DOI atau redirect: {pdf_link}")
                        return None, "PDF meta link sama dengan URL DOI atau redirect (infinite loop)"
                    
                    # Cek apakah PDF meta link sudah dikunjungi
                    if pdf_link in visited_urls:
                        logger.warning(f"PDF meta link sudah dikunjungi sebelumnya: {pdf_link}")
                        return None, f"URL sudah dikunjungi sebelumnya: {pdf_link}"
                    
                    logger.info(f"Menemukan PDF URL dari meta tag: {pdf_link}")
                    result = await self.extract_text_from_pdf_url(pdf_link, depth + 1, visited_urls)
                    # Pastikan hasil valid
                    if isinstance(result, tuple) and len(result) == 2:
                        return result
                    else:
                        logger.error(f"Invalid result from extract_text_from_pdf_url: {result}")
                        return None, "Error format hasil ekstraksi PDF"
                
                return None, "Tidak dapat menemukan PDF di halaman jurnal"
                    
            except aiohttp.client_exceptions.ClientConnectorCertificateError as e:
                # Tangani SSL error secara eksplisit
                domain = urlparse(doi_url).netloc
                logger.warning(f"SSL verification failed for {domain}, retrying with SSL disabled")
                AdaptiveSSLManager.register_domain_failure(doi_url, "ssl_verification")
                
                # Coba lagi dengan SSL dinonaktifkan
                try:
                    response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                        doi_url, 
                        headers=enhanced_headers,
                        method="GET",
                        allow_redirects=True
                    )
                    if response.status != 200:
                        logger.warning(f"Gagal resolve DOI (status {response.status}) setelah retry")
                        return None, f"Gagal resolve DOI (status {response.status})"
                except Exception as e:
                    logger.error(f"Error saat mencoba ulang resolve DOI dengan SSL dinonaktifkan: {str(e)}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    return None, f"Error saat mencoba ulang resolve DOI: {str(e)}"
                    
            except Exception as e:
                logger.error(f"Error saat resolve DOI: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                return None, f"Error saat resolve DOI: {str(e)}"
                
        except Exception as e:
            logger.error(f"Error saat resolve DOI: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None, f"Error saat resolve DOI: {str(e)}"  
        
        # Tambahkan metode baru untuk ekstraksi URL dari element khusus Semantic Scholar
    def _extract_doi_from_semantic_scholar_element(self, element):
        """Ekstrak DOI URL dari element Semantic Scholar dengan format khusus"""
        try:
            # Cek apakah ini element DOI
            if element.get('data-heap-link-type') != 'doi':
                return None
                
            # Coba dapatkan href langsung
            href = element.get('href')
            if href and 'doi.org' in href:
                return href
                
            # Coba parse dari atribut link yang kompleks
            link_attr = element.get('link')
            if not link_attr:
                return None
                
            # Format link dari contoh: n { isPrimary: null, url: "https://doi.org/10.36040/jati.v9i1.12362", ... }
            url_match = re.search(r'url:\s*["\']([^"\']+)["\']', link_attr)
            if url_match:
                return url_match.group(1)
                
            return None
        except Exception as e:
            logger.error(f"Error extracting DOI from element: {str(e)}")
            return None

    async def _extract_doi_from_ojs(self, article_url, headers):
        """Metode khusus untuk mengekstrak DOI dari website OJS yang mungkin memiliki masalah SSL"""
        try:
            # Coba dengan SSL verification dinonaktifkan
            response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                article_url,
                headers=headers,
                method="GET",
                ssl=False  # Nonaktifkan SSL verification untuk website ini
            )
            
            if response.status == 200:
                html_content = await response.text()
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Coba berbagai pola DOI
                doi_patterns = [
                    'a[href*="doi.org"]',
                    'a[href*="doi:"]',
                    'meta[name="citation_doi"]',
                    'span[class*="doi"]',
                    'div[class*="doi"]'
                ]
                
                for pattern in doi_patterns:
                    elements = soup.select(pattern)
                    for elem in elements:
                        if 'href' in elem.attrs:
                            href = elem['href']
                            if 'doi.org' in href or 'doi:' in href:
                                logger.info(f"Menemukan DOI dengan pattern '{pattern}': {href}")
                                return href
                        elif 'content' in elem.attrs:
                            content = elem['content']
                            if content.startswith('10.'):
                                doi_url = f"https://doi.org/{content}"
                                logger.info(f"Menemukan DOI dari meta tag: {doi_url}")
                                return doi_url
                
                # Jika tidak ditemukan dengan selector, coba cari dengan regex dalam HTML
                doi_regex = re.search(r'(https?://doi\.org/10\.\d+/[^\s"\'<>]+)', html_content)
                if doi_regex:
                    doi_url = doi_regex.group(1)
                    logger.info(f"Menemukan DOI dengan regex: {doi_url}")
                    return doi_url
                
                return None
        except Exception as e:
            logger.error(f"Error saat mengekstrak DOI dari OJS: {str(e)}")
            return None

    async def _find_pdf_link_in_html(self, soup, base_url):
        """Method umum untuk mencari link PDF dalam HTML"""
        pdf_link = None
        
        # Dapatkan path URL saat ini untuk perbandingan
        parsed_url = urlparse(base_url)
        current_path = parsed_url.path
        current_domain = parsed_url.netloc
        
        # Daftar kata-kata yang mengindikasikan halaman non-PDF
        non_pdf_indicators = ['about', 'policies', 'editorial', 'contact', 'login', 'register', 'help', 'author', 'instruction']
        
        # 0. Cari berdasarkan class="file" atau class="pdf" (OJS baru)
        logger.info("Metode 0: Mencari link dengan class='file' atau class='pdf'")
        file_elements = soup.select('a.file, a.pdf, a.obj_galley_link.pdf, a[class*="pdf"]')
        if file_elements:
            for elem in file_elements:
                href = elem.get('href', '')
                text = elem.get_text().strip().lower()
                
                # Skip links dengan indicator non-PDF dan self-reference
                if any(ind in href.lower() for ind in non_pdf_indicators) or href == current_path:
                    continue
                    
                if 'pdf' in text or href.endswith('.pdf'):
                    pdf_link = elem['href']
                    logger.info(f"Menemukan link PDF dari class='file/pdf': {pdf_link}")
                    break
        
        # 1. Cari berdasarkan tombol "Lihat PDF" atau "Download PDF"
        if not pdf_link:
            logger.info("Metode 1: Mencari tombol/link PDF dengan teks 'PDF/Download/Lihat'")
            for a in soup.find_all('a', href=True):
                text = a.get_text().lower().strip()
                href = a['href'].lower()
                
                # Skip anchor links dan links dengan indicator non-PDF
                if href.startswith('#') or any(ind in href for ind in non_pdf_indicators):
                    continue
                    
                # Skip jika link mengarah ke halaman yang sama
                if href == current_path:
                    continue
                
                # Kondisi pencarian yang lebih lengkap
                if (('pdf' in text) or ('download' in text) or ('lihat' in text) or ('view' in text) or ('fulltext' in text)):
                    if ('pdf' in href) or ('view' in href) or ('download' in href) or ('file' in href):
                        pdf_link = a['href']
                        logger.info(f"Menemukan link PDF dari tombol: {pdf_link}")
                        break
        
        # 2. Cari berdasarkan link yang berakhiran .pdf
        if not pdf_link:
            logger.info("Metode 2: Mencari link dengan akhiran .pdf")
            pdf_elements = soup.select('a[href$=".pdf"]')
            for elem in pdf_elements:
                href = elem.get('href', '')
                if not any(ind in href.lower() for ind in non_pdf_indicators) and href != current_path:
                    pdf_link = href
                    logger.info(f"Menemukan link PDF dari ekstensi .pdf: {pdf_link}")
                    break
        
        # 3. Cari berdasarkan pattern OJS
        if not pdf_link:
            logger.info("Metode 3: Mencari link dengan pola OJS")
            ojs_patterns = [
                'a[href*="download"]',
                'a[href*="view"][href*="article"]',
                'a[href*="viewFile"]',
                'a[href*="fulltext"]',
                'a[href*="pdf"]'
            ]
            for pattern in ojs_patterns:
                elements = soup.select(pattern)
                for elem in elements:
                    href = elem.get('href', '')
                    if not any(ind in href.lower() for ind in non_pdf_indicators) and href != current_path:
                        pdf_link = href
                        logger.info(f"Menemukan link PDF dengan pola OJS: {pdf_link}")
                        break
                if pdf_link:
                    break
        
        # 4. Cari berdasarkan data-mime-type
        if not pdf_link:
            logger.info("Metode 4: Mencari link dengan mime-type PDF")
            mime_elements = soup.select('a[type="application/pdf"], a[data-mime-type="application/pdf"]')
            for elem in mime_elements:
                href = elem.get('href', '')
                if not any(ind in href.lower() for ind in non_pdf_indicators) and href != current_path:
                    pdf_link = elem['href']
                    logger.info(f"Menemukan link PDF dari mime-type: {pdf_link}")
                    break
        
        return pdf_link
    
    def _normalize_url(self, url, base_url):
        """Normalisasi URL PDF (ubah relative URL menjadi absolute)"""
        if url.startswith('/'):
            parsed_url = urlparse(base_url)
            base = f"{parsed_url.scheme}://{parsed_url.netloc}"
            return base + url
        elif not url.startswith(('http://', 'https://')):
            return urljoin(base_url, url)
        return url  

    async def backoff_retry(self, func, max_retries=3, base_delay=1):
        """Fungsi helper untuk backoff eksponensial"""
        retry = 0
        last_exception = None
        
        while retry < max_retries:
            try:
                return await func()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                retry += 1
                last_exception = e
                delay = base_delay * (2 ** (retry - 1))  # 1, 2, 4, 8...
                logger.info(f"Request failed: {str(e)}, retry {retry}/{max_retries} after {delay}s delay")
                await asyncio.sleep(delay)
        
        raise last_exception       
    
    def _preprocess_pdf_text(self, text):
        """Pra-proses teks dari PDF untuk menghasilkan input yang lebih baik untuk ringkasan"""
        # Hapus header/footer berulang
        lines = text.split("\n")
        filtered_lines = []

        # Filter baris yang terlalu pendek atau berisi nomor halaman
        for line in lines:
            line = line.strip()
            # Skip baris kosong atau nomor halaman
            if not line or re.match(r"^\d+$", line):
                continue
            # Skip header/footer yang biasa muncul
            if re.match(
                r"^(Page \d+|https?://|www\.|©|Copyright)", line, re.IGNORECASE
            ):
                continue
            filtered_lines.append(line)

        processed_text = "\n".join(filtered_lines)

        # Hapus karakter non-ASCII
        processed_text = re.sub(r"[^\x00-\x7F]+", " ", processed_text)

        # Hapus multiple whitespace
        processed_text = re.sub(r"\s+", " ", processed_text)
        
        logger.info(f"Teks PDF berhasil diproses: {len(processed_text)} karakter")
        return processed_text.strip()
    
    def extract_text_from_uploaded_pdf(self, file_path: str):
        """Extract text from an uploaded PDF file"""
        try:
            with open(file_path, "rb") as f:
                pdf_data = f.read()
            
            return self._extract_text_from_pdf_data(pdf_data)
        except Exception as e:
            logger.error(f"Error extracting text from uploaded PDF: {str(e)}")
            return None