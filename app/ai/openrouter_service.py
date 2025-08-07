import os
import logging
import httpx
import json
import hashlib
import time
import re
import asyncio
from typing import Dict, List, Any, Optional, Union

logger = logging.getLogger(__name__)

class OpenRouterService:
    """Service for interacting with OpenRouter API"""
    
    # Model definitions with priority levels
    BEST_FREE_MODELS = [
        "mistralai/mistral-small-3.2-24b-instruct:free",
        "meta-llama/llama-4-scout:free"           
        "tngtech/deepseek-r1t2-chimera:free",
        "deepseek/deepseek-chat-v3-0324:free",
    ]

    FALLBACK_FREE_MODELS = [
        "allenai/olmo-7b-instruct",
        "nousresearch/nous-capybara-7b"
    ]
    
    def __init__(self):
        self.api_key = os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            logger.warning("OPENROUTER_API_KEY not found in environment variables")
        
        self.base_url = "https://openrouter.ai/api/v1"
        self.default_model = "mistralai/mistral-small-3.2-24b-instruct:free"  # Default model jika tidak ada yang ditentukan
        self.cache = {}

        self._last_request_time = 0
        self._min_request_interval = 0.5
    
    # Tambahkan metode ini ke class OpenRouterService
    async def generate_with_fallback(self, prompt, max_tokens=1024, temperature=0.7):
        """Generate content using available free models with fallback"""
        errors = []
        
        # Gunakan model pertama dari BEST_FREE_MODELS sebagai model cepat (fast model)
        fast_model = self.BEST_FREE_MODELS[0]  
        
        try:
            # Coba model cepat terlebih dahulu
            logger.info(f"Trying fast model: {fast_model}")
            return await self.generate_content(prompt, model=fast_model, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            logger.warning(f"Fast model failed: {str(e)}")
            errors.append(f"Error with {fast_model}: {str(e)}")
        
        # Coba model utama lainnya secara sequential untuk menghindari rate limit
        # dan terlalu banyak request parallel yang gagal
        for model in self.BEST_FREE_MODELS[1:3]:  # Coba 2 model berikutnya
            try:
                logger.info(f"Trying model: {model}")
                return await self.generate_content(prompt, model=model, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                logger.warning(f"Model {model} failed: {str(e)}")
                errors.append(f"Error with {model}: {str(e)}")
                # Tunggu sebentar sebelum mencoba model berikutnya
                await asyncio.sleep(0.5)
        
        # Jika semua model utama gagal, coba model fallback
        for model in self.FALLBACK_FREE_MODELS:
            try:
                logger.info(f"Trying fallback model: {model}")
                return await self.generate_content(prompt, model=model, max_tokens=max_tokens, temperature=temperature)
            except Exception as e:
                logger.warning(f"Fallback model {model} failed: {str(e)}")
                errors.append(f"Error with {model}: {str(e)}")
                await asyncio.sleep(0.5)  # Tambahkan delay kecil
        
        logger.error(f"All models failed: {errors}")
        return "Maaf, semua model AI saat ini tidak tersedia. Silakan coba lagi nanti."
    
    # Tambahkan metode untuk generate keywords
    async def generate_keywords(self, query: str, max_keywords: int = 5) -> List[str]:
        """Generate keyword suggestions for search query using OpenRouter"""
        try:
            prompt = f"""
            Berikan saran kata kunci pencarian untuk topik berikut:
            
            {query}
            
            Berikan maksimal {max_keywords} kata kunci dalam format JSON list.
            Contoh output yang diinginkan:
            ["kata kunci 1", "kata kunci 2", "kata kunci 3"]
            """
            
            response = await self.generate_with_fallback(prompt)
            
            # Coba ekstrak JSON list dari response
            import re
            import json
            
            # Pattern untuk mencari JSON array
            json_match = re.search(r'\[\s*"[^"]+(?:",\s*"[^"]+")*\s*\]', response)
            if json_match:
                json_str = json_match.group(0)
                try:
                    keywords = json.loads(json_str)
                    if isinstance(keywords, list):
                        return keywords[:max_keywords]
                except:
                    pass
                    
            # Fallback: ekstrak kata-kata menggunakan regex
            keywords_match = re.findall(r'"([^"]+)"', response)
            if keywords_match:
                return keywords_match[:max_keywords]
                
            # Fallback terakhir: split text
            words = response.replace("[", "").replace("]", "").replace("\"", "").split(",")
            return [w.strip() for w in words if w.strip()][:max_keywords]
            
        except Exception as e:
            logger.error(f"Error generating keywords with OpenRouter: {e}")
            return []
    
    def _get_cache_key(self, content_type, content, params=None):
        """Generate a cache key from content and parameters"""
        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        
        param_str = ""
        if params:
            param_str = "_" + hashlib.md5(str(params).encode('utf-8')).hexdigest()[:10]
        
        return f"openrouter_{content_type}_{content_hash}{param_str}"
    
    async def generate_content(self, prompt: str, model=None, temperature=0.7, max_tokens=1024, use_cache=True) -> str:
        """Generate content using OpenRouter API"""
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set in environment variables")
        
        # Use default model if none specified
        model = model or self.default_model
        
        # Check cache first
        if use_cache:
            cache_key = self._get_cache_key("prompt", prompt[:200], {
                "model": model,
                "temp": temperature,
                "max_tokens": max_tokens
            })
            
            if cache_key in self.cache:
                logger.info(f"Using cached response for prompt with model {model}")
                return self.cache[cache_key]
        
        # Implement basic rate limiting
        current_time = time.time()
        time_since_last_request = current_time - getattr(self, '_last_request_time', 0)
        if time_since_last_request < getattr(self, '_min_request_interval', 0.5):
            await asyncio.sleep(getattr(self, '_min_request_interval', 0.5) - time_since_last_request)
        self._last_request_time = time.time()
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://knowvera.com",  # Ganti dengan URL website Anda
            "X-Title": "Knowvera AI Research Assistant"  # Ganti dengan nama aplikasi Anda
        }
        
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            logger.info(f"Sending request to OpenRouter with model {model}")
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload
                )
                
                if response.status_code != 200:
                    logger.error(f"OpenRouter API error: {response.status_code} - {response.text}")
                    raise Exception(f"OpenRouter API error: {response.status_code} - {response.text}")
                
                result = response.json()
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                
                # Cache the result
                if use_cache and content:
                    self.cache[cache_key] = content
                
                return content
                
        except Exception as e:
            logger.error(f"Error generating content with OpenRouter: {str(e)}")
            raise
    
        # Perbaiki baris 206 dan sekitarnya:
    def generate_paper_summary(self, title: str, content: str, is_full_paper: bool = False) -> str:
        """Generate ringkasan artikel dengan format yang konsisten dan penanganan token limit dan fallback ke OpenRouter"""
        
        # Jika konten terlalu besar, lakukan chunking
        max_safe_chars = 40000  # Sekitar 10k token
        if len(content) > max_safe_chars and is_full_paper:
            logger.info(f"Content too large ({len(content)} chars), using chunking strategy")
            return asyncio.run(self._generate_summary_with_chunking(title, content))  # ✅ ASYNC CALL
            
        # Tentukan prompt berdasarkan apakah ini full paper atau abstrak
        if is_full_paper:
            prompt = (
                f"Berikut adalah full text dari jurnal akademik dengan judul: '{title}'. "
                "Buatlah ringkasan komprehensif dari jurnal ini dalam format terstruktur yang mencakup: "
                "1) Latar belakang dan tujuan penelitian, "
                "2) Metodologi yang digunakan, "
                "3) Hasil utama dan temuan penting, "
                "4) Implikasi dan kesimpulan. "
                "Berikan ringkasan yang terstruktur dengan subheading untuk setiap bagian. "
                "Gunakan tanda ## untuk subheadings.\n\n"
                f"Full text jurnal:\n{content}\n\n"
                "Ringkasan:"
            )
        else:
            # Prompt untuk abstrak (yang sudah ada)
            prompt = (
                f"Berikut adalah abstrak dari jurnal akademik dengan judul: '{title}'. "
                "Buatlah ringkasan dari abstrak ini dalam format terstruktur meliputi: "
                "1) Latar belakang dan tujuan, "
                "2) Metodologi, "
                "3) Hasil utama, dan "
                "4) Kesimpulan. "
                "Gunakan tanda ## untuk subheadings.\n\n"
                f"Abstrak:\n{content}\n\n"
                "Ringkasan:"
            )
        
        # Buat cache key untuk menyimpan hasil
        cache_key = f"summary_{title}_{len(content)}"
        if cache_key in self.cache:
            logger.info(f"Using cached summary for paper: {title}")
            return self.cache[cache_key]
            
        try:
            # ✅ GUNAKAN ASYNC CALL
            response = asyncio.run(self.generate_with_fallback(prompt))
            
            # Simpan ke cache
            self.cache[cache_key] = response
            
            return response
        except Exception as e:
            # Error handling yang lebih sederhana tetapi masih mendukung fallback
            logger.error(f"Error generating summary: {e}")
            return f"Maaf, tidak dapat membuat ringkasan saat ini. Error: {str(e)}"
    
    async def _generate_summary_with_chunking(self, title: str, content: str) -> str:
        """Generate summary for large papers by breaking into chunks"""
        logger.info(f"Using chunking strategy for paper: {title}")
        
        # Buat cache key untuk menyimpan hasil
        cache_key = self._get_cache_key("chunked_summary", f"{title}_{len(content)}")
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
                # Process chunk with model
                chunk_notes = await self.generate_with_fallback(
                    chunk_prompt,
                    max_tokens=1024,
                    temperature=0.3
                )
                notes.append(f"### {section_name.capitalize()}\n{chunk_notes}")
                
                # Wait briefly between chunks to avoid rate limits
                await asyncio.sleep(1)
                
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
            # Gunakan model untuk ringkasan final
            final_summary = await self.generate_with_fallback(
                final_prompt,
                max_tokens=2048,
                temperature=0.3
            )
            
            # Cache the result
            self.cache[cache_key] = final_summary
            
            return final_summary
        except Exception as e:
            logger.error(f"Error generating final summary: {e}")
            # Fallback ke notes yang sudah dikumpulkan
            fallback_summary = f"## Ringkasan Paper: {title}\n\nBerikut adalah poin-poin penting dari paper berdasarkan bagian yang berhasil dianalisis:\n\n{combined_notes}"
            self.cache[cache_key] = fallback_summary
            return fallback_summary
            
    async def answer_question(self, question: str, context: Optional[str] = None, full_text: Optional[str] = None) -> str:
        """Answer a question about a paper with available context"""
        # Define which context to use
        context_to_use = full_text if full_text else context
        context_prefix = f"Context:\n{context_to_use}\n\n" if context_to_use else ""
        
        # Create cache key
        cache_key = self._get_cache_key("qa", question + (context_to_use or "")[:500])
        
        if cache_key in self.cache:
            logger.info("Using cached QA response")
            return self.cache[cache_key]
        
        # Prepare prompt
        prompt = f"""
        {context_prefix}
        Question: {question}
        
        Berikan jawaban yang informatif, akademis, dan berdasarkan penelitian ilmiah. 
        Jika pertanyaan memerlukan referensi, sertakan referensi.
        Jika konteks tidak cukup untuk menjawab pertanyaan, katakan dengan jujur bahwa Anda memerlukan informasi lebih lanjut.
        """
        
        try:
            # Choose model based on context length
            response = await self.generate_with_fallback(prompt, max_tokens=1024, temperature=0.3)
            
            # Cache result
            self.cache[cache_key] = response
            
            return response
        except Exception as e:
            logger.error(f"Error answering question: {e}")
            return "Maaf, tidak dapat menjawab pertanyaan saat ini."

# Create singleton instance
openrouter_service = OpenRouterService()