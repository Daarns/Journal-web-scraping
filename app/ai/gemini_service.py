import google.generativeai as genai
from app.config.ai_config import init_gemini
import json
import logging
from typing import List, Dict, Any, Optional, Union
import time
import re
import random

logger = logging.getLogger(__name__)

class RateLimitExceeded(Exception):
    """Exception yang digunakan ketika batas rate limit token tercapai"""
    def __init__(self, message, retry_after=None):
        self.retry_after = retry_after
        super().__init__(message)
    pass

class GeminiService:
    """Service for interacting with Google Gemini Pro model"""
    
    def __init__(self):
        self._models = {}  # Cache untuk multiple model instances
        self._current_model_name = None
        self._model= None
        
        # Token tracking per model
        self.token_count_tracker = {
            "gemini-2.5-flash": {
                "minute": {"count": 0, "reset_time": time.time() + 60},
                "hour": {"count": 0, "reset_time": time.time() + 3600},
                "day": {"count": 0, "reset_time": time.time() + 86400}
            },
            "gemini-2.5-flash-lite-preview-06-17": {
                "minute": {"count": 0, "reset_time": time.time() + 60},
                "hour": {"count": 0, "reset_time": time.time() + 3600},
                "day": {"count": 0, "reset_time": time.time() + 86400}
            },
            "gemini-2.0-flash": {
                "minute": {"count": 0, "reset_time": time.time() + 60},
                "hour": {"count": 0, "reset_time": time.time() + 3600},
                "day": {"count": 0, "reset_time": time.time() + 86400}
            },
            "gemini-1.5-flash": {
                "minute": {"count": 0, "reset_time": time.time() + 60},
                "hour": {"count": 0, "reset_time": time.time() + 3600},
                "day": {"count": 0, "reset_time": time.time() + 86400}
            }
        }
        
        # Token limits optimal untuk setiap model
        self.token_limits = {
            "gemini-2.5-flash": {
                "minute": 60000,
                "hour": 300000,
                "day": 5000000
            },
            "gemini-2.5-flash-lite-preview-06-17": {
                "minute": 80000,  # Lite model biasanya punya limit lebih tinggi
                "hour": 400000,
                "day": 6000000
            },
            "gemini-2.0-flash": {
                "minute": 45000,  # Experimental model
                "hour": 250000,
                "day": 4000000
            },
            "gemini-1.5-flash": {
                "minute": 50000,  # Model lama
                "hour": 250000,
                "day": 4000000
            }
        }
        
        self.cache = {}
    
    def _count_tokens(self, text):
        # Estimasi kasar: 1 token ~ 4 karakter untuk bahasa Inggris
        return len(text) // 4
    
    def _check_rate_limit_for_model(self, input_text, model_name):
        """Optimized rate limit check untuk model spesifik"""
        if model_name not in self.token_count_tracker:
            logger.warning(f"Unknown model {model_name}, using default limits")
            model_name = "gemini-2.5-flash"
        
        now = time.time()
        estimated_tokens = self._count_tokens(input_text)
        
        # Quick reset check (hanya cek yang penting)
        tracker = self.token_count_tracker[model_name]
        limits = self.token_limits[model_name]
        
        # Reset counters if needed
        for period in ["minute", "hour", "day"]:
            if now > tracker[period]["reset_time"]:
                tracker[period]["count"] = 0
                if period == "minute":
                    tracker[period]["reset_time"] = now + 60
                elif period == "hour":
                    tracker[period]["reset_time"] = now + 3600
                else:
                    tracker[period]["reset_time"] = now + 86400
        
        # Quick limit check (prioritas minute check untuk responsivitas)
        if tracker["minute"]["count"] + estimated_tokens > limits["minute"]:
            raise RateLimitExceeded(f"Rate limit exceeded for {model_name} (minute)")
        
        # Update counters
        for period in tracker:
            tracker[period]["count"] += estimated_tokens
        
    def _check_rate_limit(self, input_text):
        """Check if the request would exceed token rate limits - fallback untuk single model"""
        # Gunakan model primary sebagai default untuk backward compatibility
        return self._check_rate_limit_for_model(input_text, "gemini-2.5-flash")

    def get_best_model_for_task(self, task_type="general", prompt_length=0):
        """Get optimal model based on task type and prompt size - untuk optimasi waktu dan limit"""
        from app.config.ai_config import get_model_for_task
        
        # Strategi pemilihan model berdasarkan kompleksitas dan ukuran
        if prompt_length > 30000:  # Very large content
            task_type = "complex"
        elif prompt_length < 1000:  # Small/quick tasks
            task_type = "fast"
        
        try:
            model, model_name = get_model_for_task(task_type)
            
            # Cache model instance untuk performa
            if model_name not in self._models:
                self._models[model_name] = model
            
            self._current_model_name = model_name
            logger.info(f"Selected {model_name} for task: {task_type} (prompt: {prompt_length} chars)")
            return model, model_name
            
        except Exception as e:
            logger.warning(f"Failed to get optimal model, using fallback: {e}")
            raise RateLimitExceeded("All Gemini models are unavailable")
    
    def _get_optimal_config(self, task_type, max_output_tokens, temperature):
        """Get optimal generation config based on task type"""
        # ❌ HAPUS SAFETY SETTINGS DARI SINI
        # Safety settings sudah ditangani di level model initialization
        
        base_config = {
            "temperature": temperature,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": max_output_tokens,
        }
        
        # Optimize config based on task
        if task_type == "fast":
            base_config.update({
                "temperature": min(0.3, temperature),  # Lower temp for faster, more focused responses
                "top_k": 20,  # Reduced for speed
                "max_output_tokens": min(512, max_output_tokens)  # Limit output for speed
            })
        elif task_type == "complex":
            base_config.update({
                "temperature": max(0.7, temperature),  # Higher temp for creativity
                "top_p": 0.9,
                "max_output_tokens": max_output_tokens
            })
        
        return base_config
    
    def generate_content_optimized(self, prompt: str, temperature=0.7, max_output_tokens=1024, use_cache=True, task_type="general") -> str:
        """Optimized content generation dengan smart model selection"""
        
        start_time = time.time()
        
        # Cek cache dulu untuk speed optimization
        if use_cache:
            cache_key = self._get_cache_key("prompt", prompt, 
                                        {"temp": temperature, "max_tokens": max_output_tokens, "task": task_type})
            if cache_key in self.cache:
                logger.info(f"Cache hit - response time: {time.time() - start_time:.2f}s")
                return self.cache[cache_key]
        
        # Smart model selection berdasarkan prompt size dan task type
        prompt_length = len(prompt)
        
        # ✅ REDUCED RETRY: Layer 1: Coba maksimal 1 attempt per model (bukan 3)
        for attempt in range(1):  # ✅ HANYA 1 ATTEMPT untuk speed
            try:
                # Get optimal model
                model, model_name = self.get_best_model_for_task(task_type, prompt_length)
                
                # Quick rate limit check
                self._check_rate_limit_for_model(prompt, model_name)
                
                logger.info(f"Processing with {model_name} (single attempt)")
                
                # ✅ SIMPLE GENERATION CONFIG - NO SAFETY SETTINGS
                gen_config = {
                    "temperature": temperature,
                    "top_p": 0.95,
                    "top_k": 40,
                    "max_output_tokens": max_output_tokens,
                }
                
                # Optimize based on task type
                if task_type == "fast":
                    gen_config.update({
                        "temperature": min(0.3, temperature),
                        "top_k": 20,
                        "max_output_tokens": min(512, max_output_tokens)
                    })
                elif task_type == "complex":
                    gen_config.update({
                        "temperature": max(0.7, temperature),
                        "top_p": 0.9,
                        "max_output_tokens": max_output_tokens
                    })
                
                # ✅ NO RETRY - single call only
                response = model.generate_content(
                    contents=prompt,
                    generation_config=gen_config
                )
                
                # Quick safety check
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = candidate.finish_reason
                    
                    if finish_reason == 2:  # SAFETY
                        logger.warning(f"Content blocked by {model_name} safety filters, immediate fallback")
                        # ✅ IMMEDIATE FALLBACK - no retry
                        break
                    elif finish_reason == 3:  # RECITATION
                        logger.warning(f"Content blocked by {model_name} due to recitation, immediate fallback")
                        break
                    elif finish_reason not in [1, None]:  # Not STOP or unspecified
                        logger.warning(f"Content issue with {model_name} (finish_reason: {finish_reason}), immediate fallback")
                        break
                
                # Success - cache and return
                processing_time = time.time() - start_time
                logger.info(f"Generation successful with {model_name} in {processing_time:.2f}s")
                
                if use_cache:
                    self.cache[cache_key] = response.text
                    self._manage_cache_size()
                
                return response.text
                
            except Exception as e:
                error_str = str(e).lower()
                logger.warning(f"Single attempt failed with {model_name}: {e}")
                # ✅ NO RETRY - immediate fallback
                break
        
        # ✅ IMMEDIATE FALLBACK: Fast fallback to OpenRouter if Gemini fails
        processing_time = time.time() - start_time
        if processing_time > 10:  # ✅ REDUCED timeout threshold
            logger.warning("Processing taking too long, returning error message")
            return "Maaf, pemrosesan memakan waktu terlalu lama. Silakan coba dengan query yang lebih sederhana."
        
        logger.info("Gemini attempt failed, immediate fallback to OpenRouter")
        try:
            return self.fallback_to_openrouter(prompt, temperature, max_output_tokens)
        except Exception as e:
            logger.error(f"OpenRouter fallback failed: {e}")
            return "Maaf, semua layanan AI saat ini tidak tersedia. Silakan coba lagi nanti."
    
    @property
    def model(self):
        """Lazy initialization dengan multi-model support"""
        if self._model is None:
            try:
                # Gunakan get_best_model_for_task untuk mendapatkan model terbaik
                self._model, self._current_model_name = self.get_best_model_for_task("general")
            except Exception as e:
                logger.error(f"Error initializing any Gemini model: {e}")
                raise RateLimitExceeded("Failed to initialize any Gemini model, falling back to alternatives")
        return self._model
    
    def retry_with_backoff(self, func, max_retries=1, initial_backoff=1):  # ✅ REDUCED max_retries
        """Retry function with minimal backoff untuk speed"""
        retries = 0
        while True:
            try:
                return func()
            except Exception as e:
                retries += 1
                error_str = str(e).lower()
                
                # Fast detection untuk rate limit
                is_rate_limit_error = any(term in error_str for term in 
                                        ["rate limit", "quota exceeded", "resource exhausted", 
                                        "too many requests", "429", "try again later"])
                
                # ✅ IMMEDIATE FAIL untuk rate limit
                if is_rate_limit_error:
                    logger.warning(f"Rate limit detected, immediate fallback (no retry)")
                    raise RateLimitExceeded(f"Rate limit exceeded, immediate fallback required")
                    
                # ✅ REDUCED max retries
                if retries > max_retries:
                    logger.error(f"Maximum retries ({max_retries}) reached: {e}")
                    raise
                
                # ✅ SHORTER backoff time
                backoff_time = 0.5  # Fixed short backoff
                logger.warning(f"Retrying after {backoff_time}s due to: {e}")
                time.sleep(backoff_time)
    
    def _get_cache_key(self, content_type, content, params=None):
        """Generate a cache key from content and parameters"""
        import hashlib
        
        # Hash the content to create a shorter key
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        # Add parameters to the key if provided
        param_str = ""
        if params:
            param_str = "_" + hashlib.md5(str(params).encode('utf-8')).hexdigest()[:10]
        
        return f"{content_type}_{content_hash}{param_str}"
    
    def generate_content(self, prompt: str, temperature=0.7, max_output_tokens=1024, use_cache=True) -> str:
        """Generate content using Gemini Pro with caching and rate limit handling with OpenRouter fallback"""
        return self.generate_content_optimized(prompt, temperature, max_output_tokens, use_cache, "general")
    
    def _manage_cache_size(self, max_size=100):
        """Ensure cache doesn't grow too large by removing oldest entries"""
        if len(self.cache) > max_size:
            # Remove oldest 10% of entries
            items_to_remove = max(1, int(max_size * 0.1))
            keys_to_remove = list(self.cache.keys())[:items_to_remove]
            
            for key in keys_to_remove:
                del self.cache[key]
                
            logger.info(f"Cache cleanup: removed {len(keys_to_remove)} oldest entries, new size: {len(self.cache)}")
    
    def extract_json_from_text(self, text: str) -> Dict:
        """Extract JSON object from text response"""
        try:
            # Find JSON object in text
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                return json.loads(json_str)
            
            # Check for JSON array
            json_start = text.find('[')
            json_end = text.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                return json.loads(json_str)
            
            # No JSON found
            logger.warning("No JSON found in text")
            return {"text": text}
            
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON: {e}")
            return {"text": text}
    
    def generate_suggested_keywords(self, query: str, max_keywords: int = 5, search_context: dict = None) -> List[str]:
        """Generate keyword suggestions dengan context-aware strategy"""
        if len(query) < 10:
            return []
        
        # ✅ IMMEDIATE cache check
        cache_key = f"keywords_{query[:50]}_{search_context.get('search_type', 'general') if search_context else 'general'}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # ✅ CONTEXT-AWARE prompt generation
        if search_context and search_context.get('search_type') == 'author_only':
            # NO SUGGESTIONS untuk author-only search
            return []
        
        elif search_context and search_context.get('search_type') == 'author_with_topic':
            # Topic-focused suggestions untuk author+topic search
            author_name = search_context.get('author_name', '')
            topic_keywords = search_context.get('topic_keywords', [])
            main_topic = topic_keywords[0] if topic_keywords else ''
            
            prompt = f"""Berikan 5 variasi kata kunci untuk pencarian literatur ilmiah yang BERFOKUS PADA TOPIK.
    
    Topik utama: "{main_topic}"
    Konteks: Pengguna sudah mencari paper dari penulis "{author_name}" tentang "{main_topic}"
    
    Berikan variasi pencarian yang dapat membantu menemukan paper serupa dari penulis LAIN atau perspektif berbeda:
    - Variasi terminologi dari topik "{main_topic}"
    - Pendekatan atau metode terkait
    - Aplikasi atau implementasi
    - Review atau survey tentang topik ini
    - Perkembangan terbaru di bidang ini
    
    Format: ["variasi 1", "variasi 2", "variasi 3", "variasi 4", "variasi 5"]"""
    
        else:
            # General suggestions untuk topic search
            safe_query = self._make_query_safe(query)
            
            prompt = f"""Anda adalah asisten pencarian jurnal akademik. Berikan 5 variasi kata kunci untuk pencarian literatur ilmiah.
    
    Topik penelitian: "{safe_query}"
    
    Buatlah kata kunci alternatif yang berfokus pada:
    - Aspek akademik dan penelitian
    - Terminologi ilmiah standar
    - Variasi istilah yang relevan
    - Sinonim dalam konteks penelitian
    - Nama penulis terkenal di bidang ini (opsional)
    
    Format output: ["kata kunci 1", "kata kunci 2", "kata kunci 3", "kata kunci 4", "kata kunci 5"]
    
    Kata kunci akademik:"""
        
        try:
            response_text = self.generate_content_optimized(
                prompt, 
                temperature=0.05,
                max_output_tokens=100,
                task_type="fast",
                use_cache=False
            )
            
            result = self.extract_json_from_text(response_text)
            
            if isinstance(result, list) and len(result) > 0:
                # Filter dan validate keywords
                safe_keywords = self._filter_safe_keywords(result)
                
                # Cache hasil
                self.cache[cache_key] = safe_keywords
                return safe_keywords[:max_keywords]
            else:
                # Fallback jika AI gagal
                fallback_keywords = self._generate_fallback_keywords(query, max_keywords)
                self.cache[cache_key] = fallback_keywords
                return fallback_keywords
                
        except Exception as e:
            logger.error(f"Error generating suggested keywords: {e}")
            # Return fallback keywords
            fallback_keywords = self._generate_fallback_keywords(query, max_keywords)
            return fallback_keywords

    def _make_query_safe(self, query: str) -> str:
        """Buat query lebih aman untuk processing AI"""
        # Dictionary replacement untuk istilah sensitif
        safe_replacements = {
            "kedokteran": "ilmu kesehatan",
            "medis": "kesehatan",
            "penyakit": "kondisi kesehatan",
            "diagnosis": "identifikasi",
            "terapi": "pendekatan",
            "pengobatan": "intervensi",
            "pasien": "subjek penelitian",
            "dokter": "praktisi kesehatan",
            "rumah sakit": "fasilitas kesehatan",
            "klinik": "pusat kesehatan"
        }
        
        safe_query = query.lower()
        for sensitive_term, safe_term in safe_replacements.items():
            safe_query = safe_query.replace(sensitive_term, safe_term)
        
        return safe_query

    def _filter_safe_keywords(self, keywords: List[str]) -> List[str]:
        """Filter keywords untuk memastikan keamanan"""
        safe_keywords = []
        
        # Daftar kata yang sebaiknya dihindari
        avoid_terms = ["diagnosis", "pengobatan", "terapi", "pasien", "dokter"]
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            is_safe = True
            
            # Check apakah mengandung istilah yang dihindari
            for term in avoid_terms:
                if term in keyword_lower:
                    is_safe = False
                    break
            
            if is_safe and len(keyword.strip()) > 3:
                safe_keywords.append(keyword.strip())
        
        return safe_keywords

    def _generate_fallback_keywords(self, query: str, max_keywords: int) -> List[str]:
        """Generate keywords menggunakan rule-based approach sebagai fallback"""
        try:
            import re
            
            # Extract kata-kata penting dari query
            words = re.findall(r'\b\w+\b', query.lower())
            
            # Filter kata-kata umum
            stop_words = {"dan", "atau", "dengan", "untuk", "dari", "pada", "yang", "di", "ke", "ini", "itu", "adalah", "akan", "telah", "dapat", "dalam", "tentang", "antara", "sampai", "tahun"}
            important_words = [w for w in words if w not in stop_words and len(w) > 3]
            
            # Generate variasi kata kunci
            fallback_keywords = []
            
            if important_words:
                # Kombinasi dengan kata akademik
                academic_terms = ["penelitian", "studi", "analisis", "kajian", "tinjauan"]
                
                for word in important_words[:2]:  # Ambil 2 kata penting pertama
                    for term in academic_terms[:2]:  # Kombinasi dengan 2 term akademik
                        fallback_keywords.append(f"{term} {word}")
                
                # Tambahkan kata asli
                fallback_keywords.extend(important_words[:2])
                
                # Tambahkan kombinasi umum
                fallback_keywords.extend([
                    "jurnal ilmiah",
                    "publikasi akademik",
                    "penelitian terbaru"
                ])
            else:
                # Default keywords jika tidak bisa extract
                fallback_keywords = [
                    "penelitian akademik",
                    "jurnal ilmiah",
                    "studi terbaru",
                    "publikasi penelitian",
                    "artikel ilmiah"
                ]
            
            return fallback_keywords[:max_keywords]
            
        except Exception as e:
            logger.error(f"Fallback keyword generation failed: {e}")
            return ["penelitian akademik", "jurnal ilmiah", "studi terbaru"]
    
    def generate_paper_summary(self, title: str, content: str, is_full_paper: bool = False) -> str:
        """Generate paper summary - OPTIMIZED untuk berbagai ukuran konten"""
        
        # Quick size assessment untuk optimal model selection
        content_length = len(content)
        
        # Optimized chunking threshold
        max_safe_chars = 25000  # Reduced for better performance
        
        if content_length > max_safe_chars and is_full_paper:
            logger.info(f"Large content ({content_length} chars), using optimized chunking")
            return self._generate_summary_with_chunking_optimized(title, content)
        
        # Determine task complexity
        task_type = "complex" if is_full_paper and content_length > 15000 else "general"
        
        # Prompt dalam bahasa Indonesia
        if is_full_paper:
            prompt = f"""Buatlah ringkasan dari paper akademik berikut dalam format terstruktur:

    Judul: {title}

    Konten: {content}

    Berikan ringkasan dalam 4 bagian:
    1. Latar Belakang & Tujuan
    2. Metodologi  
    3. Hasil Utama
    4. Kesimpulan

    Setiap bagian 3-4 kalimat yang ringkas dan jelas."""
        else:
            prompt = f"""Buatlah ringkasan dari abstrak berikut:

    Judul: {title}
    Abstrak: {content}

    Format ringkasan:
    1. Tujuan
    2. Metode
    3. Hasil  
    4. Kesimpulan

    Berikan ringkasan yang singkat dan informatif dalam bahasa Indonesia."""
        
        try:
            return self.generate_content_optimized(
                prompt,
                temperature=0.3,
                max_output_tokens=800 if is_full_paper else 400,
                task_type=task_type
            )
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return f"Tidak dapat membuat ringkasan saat ini karena keterbatasan layanan. Silakan coba lagi nanti."
    
    def _generate_summary_with_chunking(self, title: str, content: str) -> str:
        """Generate summary for large content by breaking it into chunks dengan fallback ke OpenRouter"""
        logger.info(f"Using chunking strategy for paper: {title}")
        
        # Buat cache key untuk menyimpan hasil
        cache_key = f"chunked_summary_{title}_{len(content)}"
        if cache_key in self.cache:
            logger.info(f"Using cached chunked summary for paper: {title}")
            return self.cache[cache_key]
        
        # Bagi teks menjadi beberapa bagian
        chunk_size = 15000  # ~3.75k tokens per chunk
        
        # Strategi chunking yang lebih cerdas:
        # 1. Ambil bagian awal (introduction, abstract)
        intro_size = min(chunk_size, len(content) // 3)
        intro_chunk = content[:intro_size]
        
        # 2. Cari dan ambil bagian methods/methodology
        methods_match = re.search(r"(?i)(methodology|methods|experimental design|materials and methods)", content)
        methods_chunk = ""
        if methods_match:
            methods_start = methods_match.start()
            methods_end = min(methods_start + chunk_size, len(content))
            methods_chunk = content[methods_start:methods_end]
        
        # 3. Cari dan ambil bagian results/findings
        results_match = re.search(r"(?i)(results|findings|observations|data analysis)", content)
        results_chunk = ""
        if results_match:
            results_start = results_match.start()
            results_end = min(results_start + chunk_size, len(content))
            results_chunk = content[results_start:results_end]
        
        # 4. Cari dan ambil bagian conclusion/discussion
        conclusion_match = re.search(r"(?i)(conclusion|discussion|summary|implications|future work)", content[-(chunk_size*2):])
        conclusion_chunk = ""
        if conclusion_match:
            # Offset dari akhir dokumen
            conclusion_start = len(content) - (chunk_size*2) + conclusion_match.start()
            conclusion_chunk = content[conclusion_start:]
        else:
            # Jika tidak menemukan conclusion, ambil bagian akhir
            conclusion_chunk = content[-chunk_size:]
        
        # Proses setiap chunk
        chunks = [
            ("introduction", intro_chunk),
            ("methods", methods_chunk),
            ("results", results_chunk),
            ("conclusion", conclusion_chunk)
        ]
        
        notes = []
        for section_name, chunk in chunks:
            if not chunk.strip():
                continue
                
            # Buat prompt untuk setiap chunk
            chunk_prompt = (
                f"Berikut adalah bagian {section_name} dari jurnal akademik berjudul: '{title}'. "
                f"Ekstrak 3-5 poin penting dari bagian ini:\n\n{chunk}\n\n"
                f"Poin penting dari bagian {section_name}:"
            )
            
            try:
                # Beri jeda antar request untuk menghindari rate limit
                if notes:  # Jika bukan yang pertama
                    time.sleep(2)
                
                # Cek rate limit
                try:
                    self._check_rate_limit(chunk_prompt)
                    chunk_notes = self.generate_content(chunk_prompt)
                    notes.append(f"### {section_name.capitalize()}\n{chunk_notes}")
                except RateLimitExceeded as e:
                    logger.warning(f"Rate limit hit during chunk processing: {str(e)}")
                    
                    # Fallback ke OpenRouter untuk chunk ini
                    from app.ai.openrouter_service import openrouter_service
                    import asyncio
                    
                    loop = asyncio.get_event_loop()
                    chunk_notes = loop.run_until_complete(
                        openrouter_service.generate_with_fallback(
                            chunk_prompt,
                            max_tokens=1024,
                            temperature=0.3
                        )
                    )
                    notes.append(f"### {section_name.capitalize()}\n{chunk_notes}")
                    time.sleep(1)  # Tunggu sebentar sebelum request berikutnya
            except Exception as e:
                logger.error(f"Error processing chunk {section_name}: {e}")
                notes.append(f"### {section_name.capitalize()}\nTidak dapat memproses bagian ini karena error.")
        
        # Buat summary final dari notes
        combined_notes = "\n\n".join(notes)
        
        final_prompt = (
            f"Berdasarkan catatan-catatan berikut dari jurnal akademik '{title}', "
            f"buatlah ringkasan komprehensif dalam format terstruktur yang mencakup: "
            "1) Latar belakang dan tujuan penelitian, "
            "2) Metodologi yang digunakan, "
            "3) Hasil utama dan temuan penting, "
            "4) Implikasi dan kesimpulan.\n\n"
            f"Gunakan tanda ## untuk subheadings.\n\n"
            f"Catatan dari paper:\n{combined_notes}\n\n"
            "Ringkasan final:"
        )
        
        try:
            # Cek rate limit sebelum membuat ringkasan final
            try:
                self._check_rate_limit(final_prompt)
                final_summary = self.generate_content(final_prompt)
                
                # Simpan ke cache
                self.cache[cache_key] = final_summary
                
                return final_summary
            except RateLimitExceeded as e:
                logger.error(f"Rate limit hit during final summary generation, using OpenRouter: {e}")
                
                # Fallback ke OpenRouter untuk ringkasan final
                from app.ai.openrouter_service import openrouter_service
                import asyncio
                
                loop = asyncio.get_event_loop()
                final_summary = loop.run_until_complete(
                    openrouter_service.generate_with_fallback(
                        final_prompt,
                        max_tokens=2048,
                        temperature=0.3
                    )
                )
                
                # Simpan ke cache
                self.cache[cache_key] = final_summary
                
                return final_summary
        except Exception as e:
            logger.error(f"Error generating final summary: {e}")
            # Fallback ke notes yang berhasil dihasilkan
            fallback_summary = f"## Ringkasan Paper: {title}\n\nBerikut adalah poin-poin penting dari paper berdasarkan bagian yang berhasil dianalisis:\n\n{combined_notes}\n\n*Catatan: Ringkasan penuh tidak dapat dibuat karena batas kuota API.*"
            
            # Simpan fallback ke cache juga
            self.cache[cache_key] = fallback_summary
            
            return fallback_summary
    
    def answer_question(self, question: str, context: Optional[str] = None) -> str:
        """Answer a question based on provided context"""
        context_text = f"Context:\n{context}\n\n" if context else ""
        
        prompt = f"""
        {context_text}
        Question: {question}
        
        Berikan jawaban yang informatif, akademis, dan berdasarkan penelitian ilmiah. 
        Jika pertanyaan memerlukan referensi, sertakan referensi.
        """
        
        try:
            return self.generate_content(prompt)
        except Exception as e:
            logger.error(f"Error answering question: {e}")
            return "Maaf, tidak dapat menjawab pertanyaan saat ini."
    
    def extract_search_parameters(self, query: str) -> Dict[str, Any]:
        """Extract structured search parameters from natural language query"""
        prompt = f"""
        From the following natural language query about academic papers, extract structured search parameters:
        
        "{query}"
        
        Extract these parameters:
        1. Main topic/subject
        2. Any specific fields mentioned
        3. Date range (if specified)
        4. Authors (if mentioned)
        5. Keywords for the search
        
        Return ONLY a JSON object with the following structure:
        {{
            "topic": "main topic",
            "fields": ["field1", "field2"],
            "start_year": number or null,
            "end_year": number or null,
            "authors": ["author1", "author2"] or [],
            "keywords": ["keyword1", "keyword2", "keyword3"]
        }}
        """
        
        try:
            response_text = self.generate_content(prompt)
            result = self.extract_json_from_text(response_text)
            
            # Ensure we have the expected fields with defaults
            if isinstance(result, dict):
                return {
                    "topic": result.get("topic", query),
                    "fields": result.get("fields", []),
                    "start_year": result.get("start_year"),
                    "end_year": result.get("end_year"),
                    "authors": result.get("authors", []),
                    "keywords": result.get("keywords", query.split())
                }
            
            # Fallback
            return {
                "topic": query,
                "fields": [],
                "start_year": None,
                "end_year": None,
                "authors": [],
                "keywords": query.split()
            }
            
        except Exception as e:
            logger.error(f"Error extracting search parameters: {e}")
            return {
                "topic": query,
                "fields": [],
                "start_year": None,
                "end_year": None,
                "authors": [],
                "keywords": query.split()
            }
    
    def generate_suggested_queries(self, original_query: str, top_papers: List[Dict]) -> List[str]:
        """Generate suggested queries based on top results"""
        if not top_papers:
            return []
            
        # Create context from top papers
        paper_context = "\n\n".join([
            f"Title: {paper.get('title', '')}\nAuthors: {paper.get('authors', '')}\nYear: {paper.get('year', '')}\nSummary: {paper.get('summary', '')}"
            for paper in top_papers[:3]
        ])
        
        prompt = f"""
        Original query: "{original_query}"
        
        Top paper results:
        {paper_context}
        
        Based on the original query and the top results, suggest 3-5 alternative search queries that might help the user find more relevant papers. Return only a JSON array of strings.
        
        Example response format: ["query 1", "query 2", "query 3"]
        """
        
        try:
            response_text = self.generate_content(prompt)
            result = self.extract_json_from_text(response_text)
            
            if isinstance(result, list):
                return result[:5]
            
            # Fallback
            return []
            
        except Exception as e:
            logger.error(f"Error generating suggested queries: {e}")
            return []
        
        # Tambahkan metode baru ke class GeminiService (pastikan hanya menambahkan, jangan menghapus kode yang sudah ada)
    
    def answer_question_from_full_text(self, question: str, full_text: str) -> str:
        """OPTIMIZED QA dari full text dengan timeout protection"""
        
        start_time = time.time()
        
        # Quick timeout check
        if len(full_text) > 50000:
            logger.warning("Text too large for optimal processing, using smart truncation")
            full_text = self._smart_truncate_for_qa(question, full_text, max_chars=25000)
        
        try:
            # Cache check first
            cache_key = self._get_cache_key("qa_optimized", question + full_text[:200])
            if cache_key in self.cache:
                logger.info(f"QA cache hit in {time.time() - start_time:.2f}s")
                return self.cache[cache_key]
            
            # Prompt dalam bahasa Indonesia
            prompt = f"""Jawab pertanyaan berikut berdasarkan paper akademik yang diberikan:

    Pertanyaan: {question}

    Konten paper: {full_text}

    Berikan jawaban yang akurat dan ringkas dalam 2-3 kalimat menggunakan bahasa Indonesia."""
            
            # Use appropriate model based on complexity
            task_type = "complex" if len(full_text) > 15000 else "general"
            
            response = self.generate_content_optimized(
                prompt,
                temperature=0.2,  # Lower for accuracy
                max_output_tokens=300,  # Limit for speed
                task_type=task_type
            )
            
            # Cache successful result
            self.cache[cache_key] = response
            
            processing_time = time.time() - start_time
            logger.info(f"QA completed in {processing_time:.2f}s")
            
            return response
            
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"QA error after {processing_time:.2f}s: {e}")
            
            if processing_time > 45:  # Near timeout
                return "Waktu pemrosesan terlalu lama. Silakan coba dengan pertanyaan yang lebih singkat atau dokumen yang lebih kecil."
            else:
                return f"Tidak dapat menjawab pertanyaan karena keterbatasan layanan: {str(e)}"
            
    def _smart_truncate_for_qa(self, question: str, text: str, max_chars: int = 25000) -> str:
        """Smart truncation yang mempertahankan konteks relevan untuk QA"""
        
        if len(text) <= max_chars:
            return text
        
        # Extract keywords from question
        question_words = set(question.lower().split())
        
        # Split into paragraphs and score relevance
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        # Score paragraphs based on question keyword overlap
        scored_paras = []
        for para in paragraphs:
            para_words = set(para.lower().split())
            overlap = len(question_words.intersection(para_words))
            scored_paras.append((overlap, para))
        
        # Sort by relevance
        scored_paras.sort(key=lambda x: x[0], reverse=True)
        
        # Build truncated text with most relevant paragraphs
        result = ""
        for score, para in scored_paras:
            if len(result) + len(para) > max_chars:
                break
            result += para + "\n\n"
        
        # If still empty, use first part
        if not result.strip():
            result = text[:max_chars]
        
        return result.strip()
    
    def _generate_summary_with_chunking_optimized(self, title: str, content: str) -> str:
        """Optimized chunking strategy untuk large content dengan bahasa Indonesia"""
        
        # Smaller, more focused chunks untuk speed
        chunk_size = 8000  # Reduced size
        
        # Smart section detection (more efficient regex)
        sections = []
        
        # Find key sections quickly dengan pattern bahasa Indonesia dan Inggris
        patterns = {
            "pendahuluan": r"(?i)(abstract|abstrak|introduction|pendahuluan|latar belakang|background)",
            "metode": r"(?i)(method|metode|methodology|metodologi|approach|pendekatan)",
            "hasil": r"(?i)(results|hasil|findings|temuan|analysis|analisis)", 
            "kesimpulan": r"(?i)(conclusion|kesimpulan|discussion|diskusi|summary|ringkasan|implications|implikasi)"
        }
        
        for section_name, pattern in patterns.items():
            match = re.search(pattern, content)
            if match:
                start = match.start()
                end = min(start + chunk_size, len(content))
                chunk_text = content[start:end]
                if len(chunk_text.strip()) > 200:  # Minimum meaningful content
                    sections.append((section_name, chunk_text))
        
        # If no sections found, use simple chunking
        if not sections:
            sections = [("bagian", content[i:i+chunk_size]) for i in range(0, len(content), chunk_size)][:4]
        
        # Process chunks in parallel-like manner (sequential but optimized)
        notes = []
        for section_name, chunk in sections:
            if not chunk.strip():
                continue
            
            # Prompt dalam bahasa Indonesia untuk chunk processing
            chunk_prompt = f"""Ekstrak 3 poin penting dari bagian {section_name} berikut dalam bahasa Indonesia:

    {chunk}

    Berikan 3 poin penting dalam format list."""
            
            try:
                # Use lite model for chunk processing
                chunk_notes = self.generate_content_optimized(
                    chunk_prompt,
                    temperature=0.2,
                    max_output_tokens=200,
                    task_type="fast"
                )
                notes.append(f"**{section_name.title()}:**\n{chunk_notes}")
            except Exception as e:
                logger.warning(f"Error processing {section_name}: {e}")
                continue
        
        # Quick final summary dalam bahasa Indonesia
        if notes:
            combined = "\n\n".join(notes)
            final_prompt = f"""Buatlah ringkasan akhir untuk paper '{title}' berdasarkan catatan berikut:

    {combined}

    Berikan ringkasan komprehensif dalam bahasa Indonesia dengan format:
    ## Latar Belakang & Tujuan
    ## Metodologi
    ## Hasil Utama  
    ## Kesimpulan"""
            
            try:
                return self.generate_content_optimized(
                    final_prompt,
                    temperature=0.3,
                    max_output_tokens=600,
                    task_type="general"
                )
            except Exception:
                # Fallback to combined notes
                return f"## Ringkasan: {title}\n\n{combined}"
        
        return f"Tidak dapat memproses dokumen besar: {title}"
    
    def answer_question_with_context(self, question: str, papers_context: list) -> str:
        """Jawab pertanyaan berdasarkan konteks paper yang diberikan"""
        try:
            # Buat konteks dari papers yang diberikan
            context_text = ""
            for i, paper in enumerate(papers_context):
                title = paper.get("title", "Unknown Title")
                authors = paper.get("authors", "Unknown Authors")
                year = paper.get("year", "Unknown Year")
                summary = paper.get("summary", "")
                
                context_text += f"Paper {i+1}:\n"
                context_text += f"Title: {title}\n"
                context_text += f"Authors: {authors}\n"
                context_text += f"Year: {year}\n"
                context_text += f"Abstract: {summary}\n\n"
            
            # Jika tidak ada konteks, berikan respon umum
            if not context_text.strip():
                prompt = f"""
                Anda adalah AI asisten akademik yang membantu menjawab pertanyaan tentang riset akademik.
                Pertanyaan: {question}
                
                Jawab pertanyaan ini dengan pengetahuan umum akademik Anda dalam bahasa Indonesia. 
                Jika pertanyaan spesifik tentang paper tertentu yang tidak ada dalam konteks, 
                jelaskan bahwa Anda membutuhkan informasi lebih lanjut tentang paper tersebut.
                """
            else:
                prompt = f"""
                Anda adalah AI asisten akademik yang membantu menjawab pertanyaan tentang paper ilmiah.
                
                Berikut adalah konteks dari beberapa paper ilmiah:
                
                {context_text}
                
                Berdasarkan informasi di atas, jawablah pertanyaan berikut dalam bahasa Indonesia:
                
                {question}
                
                Jika jawabannya tidak dapat ditemukan dalam konteks yang diberikan, mohon jelaskan bahwa informasi tersebut
                tidak tersedia dalam abstrak paper dan mungkin memerlukan akses ke teks lengkap paper.
                """
            
            # ✅ GUNAKAN generate_content_optimized INSTEAD OF self.model
            task_type = "complex" if len(context_text) > 10000 else "general"
            response = self.generate_content_optimized(
                prompt,
                temperature=0.3,
                max_output_tokens=500,
                task_type=task_type
            )
            return response
            
        except Exception as e:
            logger.error(f"Error in answer_question_with_context: {e}")
            return f"Maaf, terjadi kesalahan saat mencoba menjawab pertanyaan Anda: {str(e)}"
        

    def generate_citation(self, title: str, authors: str, year: str = None, source: str = None, style: str = "APA"):
        """Generate citation for a paper in requested style with journal name in italics"""
        if not year or year == "n.d.":
            year = "n.d."
            
        # Clean up source/journal name - remove mentions of specific databases
        journal_name = source or ""
        for term in ["google scholar", "semantic scholar", "ieee", "pubmed", "springer", "acm"]:
            journal_name = re.sub(r'(?i)' + term, '', journal_name)
        journal_name = journal_name.strip().strip(',').strip('.')
        
        # Parse title to extract article title and journal if needed
        article_title = title
        journal_title = journal_name
        
        # Improved author parsing function
        def parse_author_name(author_str):
            """Parse author string into components"""
            # Handle formats like "NWA Sardi" or "Sardi NWA"
            parts = author_str.strip().split()
            
            # Jika tidak ada parts, kembalikan string kosong
            if not parts:
                return {"last": "", "first": "", "initials": "", "initials_with_space": "", "initials_no_dots": ""}
                
            # Deteksi format berdasarkan pola: jika bagian pertama berisi huruf kapital saja, 
            # kemungkinan itu adalah inisial
            if len(parts) > 1 and parts[0].isupper() and len(parts[0]) <= 5:
                # Format "NWA Sardi" -> ubah jadi "Sardi, N. W. A."
                last = parts[-1]
                initials_part = ' '.join(parts[:-1])
                
                # Handle initials without spaces like "NWA"
                initials_expanded = []
                for init_part in initials_part.split():
                    # Expand each character to have a dot
                    chars = [f"{c}." for c in init_part]
                    initials_expanded.extend(chars)
                
                initials = ' '.join(initials_expanded)
                initials_no_spaces = ''.join(initials_expanded)
                initials_no_dots = ''.join([c for c in initials_part if c.isalpha()])
                
                return {
                    "last": last,
                    "first": initials_part,
                    "initials": initials,  # N. W. A.
                    "initials_with_space": initials,  # N. W. A.
                    "initials_no_spaces": initials_no_spaces,  # N.W.A.
                    "initials_no_dots": initials_no_dots  # NWA
                }
            else:
                # Format "Sardi NWA" atau format lainnya
                last = parts[0]
                if len(parts) > 1:
                    first_parts = parts[1:]
                    first = ' '.join(first_parts)
                    
                    # Create variations of initials
                    initials_list = [p[0] + '.' for p in first_parts]
                    initials = ' '.join(initials_list)  # N. W. A.
                    initials_no_spaces = ''.join(initials_list)  # N.W.A.
                    initials_no_dots = ''.join([p[0] for p in first_parts])  # NWA
                    
                    return {
                        "last": last,
                        "first": first,
                        "initials": initials,
                        "initials_with_space": initials,
                        "initials_no_spaces": initials_no_spaces,
                        "initials_no_dots": initials_no_dots
                    }
                else:
                    # Hanya ada satu kata
                    return {
                        "last": last,
                        "first": "",
                        "initials": "",
                        "initials_with_space": "",
                        "initials_no_spaces": "",
                        "initials_no_dots": ""
                    }
        
        try:
            # Split authors string into list
            author_list = [a.strip() for a in authors.split(',') if a.strip()]
            
            # Parse each author name
            parsed_authors = [parse_author_name(author) for author in author_list]
            
            # Format citations according to style
            if style == "APA":
                # Format: Sardi, N. W. A., Adnyasari, N. L. P. S. M., & Suryaningsih, M. T. (2023). Interdental. Jurnal Kedokteran Gigi.
                formatted_authors = []
                
                for author in parsed_authors:
                    if author["initials"]:
                        formatted_authors.append(f"{author['last']}, {author['initials_with_space']}")
                    else:
                        formatted_authors.append(author["last"])
                
                # Join authors with proper APA formatting
                if len(formatted_authors) > 2:
                    authors_text = ", ".join(formatted_authors[:-1]) + ", & " + formatted_authors[-1]
                elif len(formatted_authors) == 2:
                    authors_text = formatted_authors[0] + " & " + formatted_authors[1]
                else:
                    authors_text = formatted_authors[0] if formatted_authors else ""
                    
                # Return properly formatted APA citation
                return f"{authors_text} ({year}). {article_title}. {journal_title}"
                
            elif style == "MLA":
                # Format: Sardi, N. W. A., et al. "Interdental." Jurnal Kedokteran Gigi, 2023.
                formatted_authors = []
                
                for author in parsed_authors:
                    if author["initials"]:
                        formatted_authors.append(f"{author['last']}, {author['initials_with_space']}")
                    else:
                        formatted_authors.append(author["last"])
                
                # Use "et al." for multiple authors in MLA
                if len(formatted_authors) > 1:
                    authors_text = f"{formatted_authors[0]}, et al"
                else:
                    authors_text = formatted_authors[0] if formatted_authors else ""
                    
                # Return properly formatted MLA citation
                return f"{authors_text}. \"{article_title}.\" {journal_title}, {year}."
                
            elif style == "Chicago":
                # Format: Sardi, N. W. A., N. L. P. S. M. Adnyasari, and M. T. Suryaningsih. 2023. "Interdental." Jurnal Kedokteran Gigi.
                formatted_authors = []
                
                for i, author in enumerate(parsed_authors):
                    # First author: Last, First format
                    if i == 0:
                        if author["initials"]:
                            formatted_authors.append(f"{author['last']}, {author['initials_with_space']}")
                        else:
                            formatted_authors.append(author["last"])
                    # Subsequent authors: First Last format
                    else:
                        if author["initials"]:
                            formatted_authors.append(f"{author['initials_with_space']} {author['last']}")
                        else:
                            formatted_authors.append(author["last"])
                
                # Join authors with Chicago formatting
                if len(formatted_authors) > 2:
                    authors_text = ", ".join(formatted_authors[:-1]) + ", and " + formatted_authors[-1]
                elif len(formatted_authors) == 2:
                    authors_text = formatted_authors[0] + " and " + formatted_authors[1]
                else:
                    authors_text = formatted_authors[0] if formatted_authors else ""
                    
                # Return properly formatted Chicago citation
                return f"{authors_text}. {year}. \"{article_title}.\" {journal_title}."
                
            elif style == "Harvard":
                # Format: Sardi, N.W.A., Adnyasari, N.L.P.S.M. & Suryaningsih, M.T., 2023. Interdental. Jurnal Kedokteran Gigi.
                formatted_authors = []
                
                for author in parsed_authors:
                    if author["initials_no_spaces"]:
                        formatted_authors.append(f"{author['last']}, {author['initials_no_spaces']}")
                    else:
                        formatted_authors.append(author["last"])
                
                # Join authors with Harvard formatting
                if len(formatted_authors) > 2:
                    authors_text = ", ".join(formatted_authors[:-1]) + " & " + formatted_authors[-1]
                elif len(formatted_authors) == 2:
                    authors_text = formatted_authors[0] + " & " + formatted_authors[1]
                else:
                    authors_text = formatted_authors[0] if formatted_authors else ""
                    
                # Return properly formatted Harvard citation
                return f"{authors_text}, {year}. {article_title}. {journal_title}."
                
            elif style == "Vancouver":
                # Format: Sardi NWA, Adnyasari NLPSM, Suryaningsih MT. Interdental. Jurnal Kedokteran Gigi. 2023.
                formatted_authors = []
                
                for author in parsed_authors:
                    if author["initials_no_dots"]:
                        formatted_authors.append(f"{author['last']} {author['initials_no_dots']}")
                    else:
                        formatted_authors.append(author["last"])
                
                # Join authors with commas, Vancouver style
                authors_text = ", ".join(formatted_authors)
                
                # Return properly formatted Vancouver citation
                return f"{authors_text}. {article_title}. {journal_title}. {year}."
                
            elif style == "IEEE":
                # Format: [1] N. W. A. Sardi, N. L. P. S. M. Adnyasari, and M. T. Suryaningsih, "Interdental," Jurnal Kedokteran Gigi, 2023.
                formatted_authors = []
                
                for author in parsed_authors:
                    if author["initials"]:
                        formatted_authors.append(f"{author['initials_with_space']} {author['last']}")
                    else:
                        formatted_authors.append(author["last"])
                
                # Join authors with IEEE formatting
                if len(formatted_authors) > 2:
                    authors_text = ", ".join(formatted_authors[:-1]) + ", and " + formatted_authors[-1]
                elif len(formatted_authors) == 2:
                    authors_text = formatted_authors[0] + " and " + formatted_authors[1]
                else:
                    authors_text = formatted_authors[0] if formatted_authors else ""
                    
                # Return properly formatted IEEE citation
                return f"[1] {authors_text}, \"{article_title},\" {journal_title}, {year}."
                
            else:
                # Default to APA if style is unknown
                return f"Unknown citation style: {style}"
        
        except Exception as e:
            print(f"Error in citation formatting: {e}")
            import traceback
            traceback.print_exc()
            # Simple fallback format
            return f"{authors} ({year}). {title}. {journal_name}."
        
    def fallback_to_openrouter(self, prompt: str, temperature=0.7, max_tokens=1024) -> str:
        """Fallback to OpenRouter when Gemini hits rate limit"""
        from app.ai.openrouter_service import openrouter_service
        import asyncio
        import nest_asyncio
        
        try:
            logger.info("Falling back to OpenRouter due to Gemini rate limit")
            
            # Gunakan nest_asyncio untuk mengatasi "event loop already running"
            try:
                # Coba patch event loop yang sudah berjalan
                nest_asyncio.apply()
                
                # Gunakan event loop yang sama
                loop = asyncio.get_event_loop()
                response = loop.run_until_complete(
                    openrouter_service.generate_with_fallback(
                        prompt, 
                        max_tokens=max_tokens, 
                        temperature=temperature
                    )
                )
                return response
            except (ImportError, RuntimeError) as e:
                # Jika nest_asyncio tidak tersedia atau gagal, gunakan pendekatan thread
                logger.warning(f"Failed to use nest_asyncio: {e}, trying thread approach")
                
                import concurrent.futures
                
                def run_in_executor():
                    # Buat loop baru di thread terpisah
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(
                            openrouter_service.generate_with_fallback(
                                prompt, 
                                max_tokens=max_tokens, 
                                temperature=temperature
                            )
                        )
                        return result
                    finally:
                        new_loop.close()
                    
                # Jalankan di thread terpisah
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_executor)
                    response = future.result(timeout=30)  # Tambahkan timeout untuk menghindari hang
                    
                return response
                    
        except Exception as e:
            logger.error(f"OpenRouter fallback failed: {e}")
            return f"Maaf, permintaan tidak dapat diproses karena batas kuota API. Silakan coba lagi nanti."
    
    async def generate_content_async(self, prompt: str) -> str:
        """Async version of generate_content"""
        try:
            self._check_rate_limit()
            
            # Use asyncio to run the sync method in a thread pool
            import asyncio
            loop = asyncio.get_event_loop()
            
            response = await loop.run_in_executor(
                None, 
                lambda: self.model.generate_content(prompt)
            )
            
            self.request_count += 1
            self.last_request_time = time.time()
            
            return response.text
            
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                raise RateLimitExceeded("Gemini API rate limit exceeded")
            raise e
        
# Singleton instance
gemini_service = GeminiService()