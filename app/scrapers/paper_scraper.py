import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
import random
import json  
from typing import List, Dict, Optional
import logging
from app.scrapers.ieee_scraper import search_ieee, parse_year_filter
from semanticscholar import SemanticScholar
from urllib.parse import urlencode, urlparse
import time
from datetime import datetime, timedelta
import functools
import ssl
import traceback
import os
from pathlib import Path

# Konfigurasi logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AdaptiveSSLManager:
    """Manager yang secara dinamis mengelola domain-domain dengan masalah SSL"""
    
    # Konfigurasi file penyimpanan
    CONFIG_DIR = Path("config")
    PROBLEMATIC_DOMAINS_FILE = CONFIG_DIR / "problematic_domains.json"
    
    # Set untuk menyimpan domain bermasalah
    _problematic_domains = {
        'ejournal.itn.ac.id',
        'repository.uinjkt.ac.id', 
        'ejournal.unida.gontor.ac.id',
        # Domain known to be problematic
    }
    
    # Cache untuk domain yang dicoba selama sesi ini
    _domain_attempts = {}
    
    @classmethod
    def initialize(cls):
        """Load problematic domains from file at startup"""
        try:
            if not cls.CONFIG_DIR.exists():
                cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                
            if cls.PROBLEMATIC_DOMAINS_FILE.exists():
                with open(cls.PROBLEMATIC_DOMAINS_FILE, "r") as f:
                    loaded_domains = json.load(f)
                    if isinstance(loaded_domains, list):
                        cls._problematic_domains.update(loaded_domains)
                        logger.info(f"Loaded {len(loaded_domains)} problematic domains from file")
        except Exception as e:
            logger.error(f"Error initializing AdaptiveSSLManager: {e}")
    
    @classmethod
    def save_problematic_domains(cls):
        """Save problematic domains to file"""
        try:
            if not cls.CONFIG_DIR.exists():
                cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                
            with open(cls.PROBLEMATIC_DOMAINS_FILE, "w") as f:
                json.dump(list(cls._problematic_domains), f)
            logger.info(f"Saved {len(cls._problematic_domains)} problematic domains to file")
        except Exception as e:
            logger.error(f"Error saving problematic domains: {e}")
    
    @classmethod
    def is_problematic_domain(cls, url):
        """Check if domain is known to be problematic"""
        if not url:
            return False
            
        domain = urlparse(url).netloc
        return domain in cls._problematic_domains
    
    @classmethod
    def register_domain_failure(cls, url, error_type="ssl_verification"):
        """Register a domain as having SSL problems"""
        if not url:
            return
            
        domain = urlparse(url).netloc
        if not domain:
            return
            
        # Add to problematic domains set
        if error_type == "ssl_verification" and domain not in cls._problematic_domains:
            logger.info(f"Adding {domain} to problematic domains list due to SSL verification failure")
            cls._problematic_domains.add(domain)
            cls.save_problematic_domains()
        
        # Update attempts cache
        if domain not in cls._domain_attempts:
            cls._domain_attempts[domain] = {"failures": 1, "error_type": error_type}
        else:
            cls._domain_attempts[domain]["failures"] += 1
    
    @classmethod
    async def create_session_for_url(cls, url=None, headers=None):
        """Create appropriate session based on URL"""
        if not url:
            return aiohttp.ClientSession(headers=headers)
            
        domain = urlparse(url).netloc
        
        # Check if domain is known to be problematic
        if domain in cls._problematic_domains:
            logger.info(f"Using SSL-disabled session for known problematic domain: {domain}")
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            return aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                headers=headers
            )
            
        # Use default SSL for other domains
        return aiohttp.ClientSession(headers=headers)
    
    @classmethod
    async def fetch_with_adaptive_ssl(cls, url, headers=None, method="GET", **kwargs):
        """Fetch URL with adaptive SSL handling that learns from failures"""
        if not headers:
            headers = {}
            
        try:
            # First attempt with normal SSL
            async with await cls.create_session_for_url(url, headers) as session:
                request_method = getattr(session, method.lower())
                async with request_method(url, **kwargs) as response:
                    return response
        except aiohttp.client_exceptions.ClientConnectorCertificateError as e:
            # SSL verification failed - register domain and retry
            domain = urlparse(url).netloc
            logger.warning(f"SSL verification failed for {domain}, disabling verification")
            cls.register_domain_failure(url, "ssl_verification")
            
            # Retry with SSL verification disabled
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=ssl_context),
                headers=headers
            ) as session:
                request_method = getattr(session, method.lower())
                async with request_method(url, **kwargs) as response:
                    return response
                
class GoogleScholarRateLimiter:
    """Enhanced rate limiter dengan circuit breaker pattern"""
    
    def __init__(self):
        self.last_request_time = 0
        self.request_count_today = 0
        self.blocked_until = 0
        self.session_start = time.time()
        self.consecutive_failures = 0
        self.circuit_open = False
        
        # ✅ LEBIH PERMISSIVE UNTUK TESTING
        self.MIN_DELAY = 5.0  # 5 seconds instead of 30
        self.MAX_DAILY_REQUESTS = 100  # 100 instead of 20
        self.CIRCUIT_BREAKER_THRESHOLD = 10  # 10 instead of 3
        self.CIRCUIT_RESET_TIME = 300  # 5 minutes instead of 1 hour
    
    def can_make_request(self) -> bool:
        """Check if we can make a request - COMPLETELY DISABLED FOR PRESENTATION"""
        # ✅ COMPLETELY DISABLED FOR URGENT PRESENTATION
        return True
        
        # Uncomment code below to re-enable rate limiting:
        # current_time = time.time()
        # 
        # # Check if circuit breaker is open
        # if self.circuit_open:
        #     if current_time > self.blocked_until:
        #         self.circuit_open = False
        #         self.consecutive_failures = 0
        #         logger.info("🔄 Circuit breaker reset - Google Scholar requests resumed")
        #     else:
        #         remaining = self.blocked_until - current_time
        #         logger.warning(f"🚫 Circuit breaker open - {remaining/60:.1f} minutes remaining")
        #         return False
        # 
        # # Check daily limits
        # if current_time - self.session_start > 86400:  # Reset daily counter
        #     self.session_start = current_time
        #     self.request_count_today = 0
        # 
        # if self.request_count_today >= self.MAX_DAILY_REQUESTS:
        #     logger.warning(f"🚫 Daily Google Scholar limit reached ({self.MAX_DAILY_REQUESTS} requests)")
        #     return False
        # 
        # # Check minimum delay
        # elapsed = current_time - self.last_request_time
        # if elapsed < self.MIN_DELAY:
        #     wait_time = self.MIN_DELAY - elapsed
        #     logger.info(f"⏱️ Rate limiting: need to wait {wait_time:.1f}s more")
        #     return False
        # 
        # return True
    
    async def wait_if_needed(self):
        """Wait for required delay - DISABLED"""
        # ✅ SEMENTARA DISABLE UNTUK TESTING
        pass
        
        # Uncomment code below to re-enable waiting:
        # current_time = time.time()
        # elapsed = current_time - self.last_request_time
        # 
        # if elapsed < self.MIN_DELAY:
        #     wait_time = self.MIN_DELAY - elapsed
        #     logger.info(f"🐌 Waiting {wait_time:.1f}s for rate limiting...")
        #     await asyncio.sleep(wait_time)
    
    def record_request(self, success: bool):
        """Record a request and its outcome"""
        self.last_request_time = time.time()
        self.request_count_today += 1
        
        if success:
            self.consecutive_failures = 0
        else:
            self.consecutive_failures += 1
            
            # ✅ DISABLE CIRCUIT BREAKER UNTUK TESTING
            # if self.consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
            #     self.circuit_open = True
            #     self.blocked_until = time.time() + self.CIRCUIT_RESET_TIME
            #     logger.error(f"🚫 Circuit breaker opened after {self.consecutive_failures} failures")
    
    def reset_limiter(self):
        """Reset all rate limiting counters"""
        self.last_request_time = 0
        self.request_count_today = 0
        self.blocked_until = 0
        self.session_start = time.time()
        self.consecutive_failures = 0
        self.circuit_open = False
        logger.info("🔄 Rate limiter has been reset")

# Global rate limiter instance
google_scholar_limiter = GoogleScholarRateLimiter()

def reset_google_scholar_limiter():
    """Reset the global Google Scholar rate limiter"""
    global google_scholar_limiter
    google_scholar_limiter = GoogleScholarRateLimiter()
    logger.info("🔄 Global Google Scholar rate limiter has been reset")

def reset_all_rate_limiters():
    """Reset all rate limiters for emergency testing"""
    global google_scholar_limiter
    google_scholar_limiter = GoogleScholarRateLimiter()
    PaperScraper._last_semantic_scholar_request = 0
    PaperScraper._session_counter = 0
    logger.info("🔄 ALL rate limiters have been reset for testing")

class PaperScraper:
    """Scraper for academic papers from various sources using BeautifulSoup"""
    
    # Variabel kelas untuk rate limiting
    _last_semantic_scholar_request = 0
    _semantic_scholar_cache = {}
    _cache_expiry = {}
    _pdf_url_cache = {} 
    
    # ✅ SESSION ROTATION - Helps avoid detection
    _session_counter = 0
    _max_requests_per_session = 3
    
    def __init__(self):
        self.sources = {
            'arxiv': self.scrape_arxiv,
            'semantic_scholar': self.scrape_semantic_scholar,
            'core': self.scrape_core,
            'ieee': self.scrape_ieee,
            'google_scholar': self.scrape_google_scholar
        }
        
        self.user_agents = [
            # Chrome variations - Different versions and systems
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            
            # Firefox variations
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0',
            'Mozilla/5.0 (X11; Linux x86_64; rv:122.0) Gecko/20100101 Firefox/122.0',
            
            # Safari variations
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15',
            
            # Edge variations
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
            
            # Academic-looking user agents
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Research/1.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Academic/1.0'
        ]
        
        # Inisialisasi manager SSL adaptif
        AdaptiveSSLManager.initialize()
    
    async def search_papers(self, query: str, year_filter: str = "") -> List[Dict]:
        """Search papers from multiple sources asynchronously"""
        logger.info(f"Searching papers with query: {query}, year filter: {year_filter}")
        
        # Tasks untuk semua scraper kecuali Semantic Scholar
        tasks = []
        for source, scraper in self.sources.items():
            if source != 'semantic_scholar':  # Jangan jalankan Semantic Scholar secara paralel
                tasks.append(scraper(query, year_filter))
        
        # Jalankan semua scraper lain secara paralel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Combine results and filter out any errors
        papers = []
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error in scraper: {result}")
                continue
            papers.extend(result)
        
        # Jalankan Semantic Scholar secara terpisah untuk menghindari rate limit
        try:
            semantic_papers = await self.scrape_semantic_scholar(query, year_filter)
            papers.extend(semantic_papers)
        except Exception as e:
            logger.error(f"Error in Semantic Scholar scraper: {e}")
        
        # De-duplicate and sort by year (newest first)
        unique_papers = self._deduplicate_papers(papers)
        sorted_papers = sorted(unique_papers, key=lambda x: x.get('year', 0), reverse=True)
        
        logger.info(f"Found {len(sorted_papers)} unique papers")
        return sorted_papers

    async def scrape_arxiv(self, query: str, year_filter: str = "", max_results: int = 20) -> List[Dict]:
        """Scrape papers from arXiv"""
        # Kode yang sudah ada, tidak perlu diubah
        # ...
        # Sanitize query
        query = query.replace(' ', '+')
        
        # Build URL with limited results
        url = f"https://export.arxiv.org/api/query?search_query=all:{query}&start=0&max_results={min(max_results, 20)}"
        
        try:
            headers = {'User-Agent': random.choice(self.user_agents)}
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status != 200:
                        logger.error(f"ArXiv API returned status code {response.status}")
                        return []
                    
                    content = await response.text()
                    soup = BeautifulSoup(content, 'xml')
                    
                    entries = soup.find_all('entry')
                    results = []
                    
                    for entry in entries:
                        title = entry.find('title').text.strip()
                        
                        # Authors
                        authors = entry.find_all('author')
                        author_names = [author.find('name').text for author in authors]
                        authors_str = ', '.join(author_names[:3])
                        if len(author_names) > 3:
                            authors_str += ' et al.'
                        
                        # Date and ID
                        published = entry.find('published').text
                        year = published[:4]  # Extract year from published date
                        arxiv_id = entry.find('id').text.split('/')[-1]
                        
                        # Link and summary
                        link = f"https://arxiv.org/abs/{arxiv_id}"
                        summary = entry.find('summary').text.strip()
                        summary = ' '.join(summary.split()[:30]) + '...'  # Truncate summary
                        
                        # Apply year filter if specified
                        if year_filter:
                            if '-' in year_filter:
                                start_year, end_year = year_filter.split('-')
                                if start_year and int(year) < int(start_year):
                                    continue
                                if end_year and int(year) > int(end_year):
                                    continue
                        
                        # Get PDF URL - arXiv papers always have direct PDF links
                        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                        
                        paper = {
                            'title': title,
                            'authors': authors_str,
                            'year': int(year),
                            'source': 'arXiv',
                            'link': link,
                            'summary': summary,
                            'id': f'arxiv_{arxiv_id}',
                            'pdf_url': pdf_url  # Add PDF URL
                        }
                        
                        results.append(paper)
                    
                    logger.info(f"Found {len(results)} papers from arXiv")
                    return results
                    
        except Exception as e:
            logger.error(f"Error scraping arXiv: {e}")
            return []

    async def scrape_semantic_scholar(self, query: str, year_filter: str = "", max_results: int = 20) -> List[Dict]:
        """Scrape papers from Semantic Scholar with SINGLE request strategy"""
        # Cek cache sebelum melakukan request
        cache_key = f"{query}:{year_filter}"
        
        # Jika hasil ada di cache dan belum expired
        now = datetime.now()
        if cache_key in PaperScraper._semantic_scholar_cache and cache_key in PaperScraper._cache_expiry:
            if now < PaperScraper._cache_expiry[cache_key]:
                logger.info(f"Using cached results for Semantic Scholar query: '{query}'")
                return PaperScraper._semantic_scholar_cache[cache_key]
        
        # ✅ CONSERVATIVE delay for urgent presentation - Longer intervals
        min_interval = 30.0  # 30 seconds between Semantic Scholar requests for presentation
        
        try:
            # Terapkan rate limiting
            current_time = time.time()
            elapsed = current_time - PaperScraper._last_semantic_scholar_request
            
            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                logger.info(f"Rate limiting: waiting {wait_time:.2f}s before Semantic Scholar request")
                await asyncio.sleep(wait_time)
            
            # Update waktu permintaan terakhir
            PaperScraper._last_semantic_scholar_request = time.time()
        
            # Lakukan request setelah rate limiting
            logger.info(f"Searching Semantic Scholar with query: '{query}'")
            
            # Enhanced query processing
            original_query = query
            enhanced_query = query
            
            # Deteksi jika query kemungkinan dalam Bahasa Indonesia
            common_id_words = set([
                "dan", "atau", "dengan", "untuk", "dari", "pada", "yang", "di", "ke", "ini"
            ])
            
            query_words = set(query.lower().split())
            id_word_count = len(query_words.intersection(common_id_words))
            
            if id_word_count > 0:
                # Tambahkan kata kunci umum bahasa Inggris untuk meningkatkan hasil
                medical_english_terms = "medicine medical health research science healthcare hospital clinical"
                enhanced_query = f"{query} {medical_english_terms}"
                logger.info(f"Query might be in Indonesian, enhancing with English terms: '{enhanced_query}'")
            
            # Buat URL dengan parameter yang benar menggunakan urlencode
            params = {
                "query": enhanced_query,
                "limit": min(max_results, 20),  # ✅ LIMIT to reduce load
                "fields": "title,authors,year,venue,abstract,url,citationCount,openAccessPdf,externalIds"
            }
            
            # Tambahkan filter tahun jika ada
            if year_filter and '-' in year_filter:
                start_year, end_year = year_filter.split('-')
                if start_year and end_year:
                    params["year"] = f"{start_year}-{end_year}"
            
            url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)
            
            headers = {'User-Agent': random.choice(self.user_agents)}
            
            # ✅ LONGER timeout untuk stability
            timeout = aiohttp.ClientTimeout(total=15)  # 15 seconds timeout
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    # Log untuk debugging
                    logger.debug(f"Semantic Scholar URL: {response.url}")
                    
                    if response.status != 200:
                        if response.status == 429:
                            logger.warning(f"Semantic Scholar API returned status code 429 - continuing anyway for presentation")
                            # ✅ NO BACKOFF for urgent presentation - just continue
                            # PaperScraper._last_semantic_scholar_request = time.time() + 10  # DISABLED
                            # return []  # DISABLED - try to continue
                        else:
                            logger.error(f"Semantic Scholar API returned status code {response.status}")
                            return []
                    
                    # Process successful response
                    data = await response.json()
                    papers = data.get('data', [])
                    
                    # ✅ SINGLE fallback attempt IF no results and query was enhanced
                    if not papers and enhanced_query != original_query:
                        logger.info(f"No results for enhanced query, trying original: '{original_query}'")
                        
                        # Wait a bit before fallback
                        await asyncio.sleep(2.0)
                        
                        params["query"] = original_query
                        fallback_url = "https://api.semanticscholar.org/graph/v1/paper/search?" + urlencode(params)
                        
                        async with session.get(fallback_url, headers=headers) as fallback_response:
                            if fallback_response.status == 200:
                                fallback_data = await fallback_response.json()
                                papers = fallback_data.get('data', [])
                                logger.info(f"Fallback query returned {len(papers)} papers")
                            else:
                                logger.warning(f"Fallback query also failed with status {fallback_response.status}")
                    
                    # Process results
                    results = []
                    for paper in papers:
                        try:
                            # Extract basic information
                            title = paper.get('title', 'Untitled')
                            
                            # Authors
                            authors_data = paper.get('authors', [])
                            author_names = [author.get('name', '') for author in authors_data if author.get('name')]
                            authors_str = ', '.join(author_names[:3])
                            if len(author_names) > 3:
                                authors_str += ' et al.'
                            
                            # Year
                            year = paper.get('year', 0)
                            
                            # Venue
                            venue = paper.get('venue', 'Semantic Scholar')
                            
                            # Summary/Abstract
                            summary = paper.get('abstract', 'No abstract available')
                            if summary and len(summary) > 300:
                                summary = summary[:300] + '...'
                            
                            # URL
                            url_link = paper.get('url', '')
                            
                            # Citation count
                            citation_count = paper.get('citationCount', 0)
                            
                            # PDF URL
                            pdf_url = None
                            if paper.get('openAccessPdf') and paper['openAccessPdf'].get('url'):
                                pdf_url = paper['openAccessPdf']['url']
                            
                            # Paper ID
                            paper_id = paper.get('paperId', '')
                            
                            paper_dict = {
                                'title': title,
                                'authors': authors_str,
                                'year': year,
                                'source': 'Semantic Scholar',
                                'venue': venue,
                                'link': url_link,
                                'summary': summary,
                                'id': f'ss_{paper_id}',
                                'citation_count': citation_count,
                                'pdf_url': pdf_url
                            }
                            
                            results.append(paper_dict)
                            
                        except Exception as e:
                            logger.error(f"Error processing Semantic Scholar paper: {e}")
                            continue
                    
                    # Simpan hasil di cache dengan waktu kedaluwarsa 24 jam
                    PaperScraper._semantic_scholar_cache[cache_key] = results
                    PaperScraper._cache_expiry[cache_key] = now + timedelta(hours=24)
                    
                    # Bersihkan cache lama jika terlalu besar
                    if len(PaperScraper._semantic_scholar_cache) > 50:
                        oldest_key = min(PaperScraper._cache_expiry, key=PaperScraper._cache_expiry.get)
                        if oldest_key in PaperScraper._semantic_scholar_cache:
                            del PaperScraper._semantic_scholar_cache[oldest_key]
                        if oldest_key in PaperScraper._cache_expiry:
                            del PaperScraper._cache_expiry[oldest_key]
                    
                    logger.info(f"Found {len(results)} papers from Semantic Scholar")
                    return results
                    
        except asyncio.TimeoutError:
            logger.warning(f"Semantic Scholar request timed out")
            return []
        except Exception as e:
            logger.error(f"Error during Semantic Scholar request: {e}")
            return []
        
    async def _scrape_semantic_scholar_detail_page_for_pdf(self, url: str) -> Optional[str]:
        """Scrape the paper detail page on Semantic Scholar to find PDF links with improved extraction"""
        # Cek cache dulu
        if url in PaperScraper._pdf_url_cache:
            logger.info(f"Using cached PDF URL for: {url}")
            return PaperScraper._pdf_url_cache[url]
            
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml,application/pdf',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://www.semanticscholar.org/'
            }
            
            # Tambahkan delay untuk rate limiting
            await asyncio.sleep(1.5)
            
            response = await AdaptiveSSLManager.fetch_with_adaptive_ssl(
                url,
                headers=headers
            )

            html = await response.text()
            soup = BeautifulSoup(html, 'html.parser')
            
            # Ekstrak paper ID untuk digunakan dalam pencarian tambahan
            paper_id_match = re.search(r'paper/([a-zA-Z0-9]+)(?:$|\/|#|\?)', url)
            paper_id = paper_id_match.group(1) if paper_id_match else None
                    
                    # Kumpulkan semua link potensial PDF
            pdf_links = []
                    
                    # METODE 1: Cari berbagai format link PDF yang diketahui di Semantic Scholar
                    
                    # 1.1: Cari icon button dengan data-test-id="paper-link"
            paper_links = soup.select('a[data-test-id="paper-link"]')
            for link in paper_links:
                href = link.get('href') or link.get('link') or link.get('data-url')
                if href and (href.lower().endswith('.pdf') or 'pdf' in href.lower()):
                        pdf_links.append(href)
                        logger.info(f"Found PDF link from icon button: {href}")
                    
                    # 1.2: Cari alternate sources dropdown
                alternate_source_links = soup.select('.alternate-sources__dropdown-button, [data-heap-id="paper_link_target"]')
                for link in alternate_source_links:
                        href = link.get('href') or link.get('link') or link.get('data-url')
                        if href and (href.lower().endswith('.pdf') or 'pdf' in href.lower()):
                            pdf_links.append(href)
                            logger.info(f"Found PDF link from alternate source: {href}")
                    
                    # 1.3: Cari link PDF generik di halaman
                generic_pdf_links = soup.select('a[href*=".pdf"], a[href*="pdf"], a[data-url*=".pdf"], a[data-url*="pdf"]')
                for link in generic_pdf_links:
                    href = link.get('href') or link.get('data-url')
                    if href and not href.startswith('#'):  # Abaikan anchor links
                        pdf_links.append(href)
                        logger.info(f"Found generic PDF link: {href}")
                    
                    # METODE 2: Cari dalam data JavaScript yang tersemat
                    
                    # 2.1: Cari URL PDF dalam script JSON-LD
                    script_tags = soup.select('script[type="application/ld+json"]')
                    for script in script_tags:
                        try:
                            json_data = json.loads(script.string)
                            if isinstance(json_data, dict):
                                # Cek berbagai format lokasi PDF dalam JSON-LD
                                possible_urls = []
                                
                                if "url" in json_data:
                                    possible_urls.append(json_data["url"])
                                
                                if "mainEntity" in json_data and "sameAs" in json_data["mainEntity"]:
                                    if isinstance(json_data["mainEntity"]["sameAs"], list):
                                        possible_urls.extend(json_data["mainEntity"]["sameAs"])
                                    else:
                                        possible_urls.append(json_data["mainEntity"]["sameAs"])
                                
                                for possible_url in possible_urls:
                                    if isinstance(possible_url, str) and ('.pdf' in possible_url.lower()):
                                        pdf_links.append(possible_url)
                                        logger.info(f"Found PDF link in JSON-LD: {possible_url}")
                        except:
                            pass
                    
                    # 2.2: Cari URL PDF dalam variabel JavaScript
                    script_content = ' '.join([s.string for s in soup.find_all('script') if s.string])
                    pdf_regex_patterns = [
                        r'(?:url|pdfUrl|fileUrl|downloadUrl|"url"|\'url\')(?:\s*:\s*|\s*=\s*)[\'"]([^\'"]*.pdf)[\'"]',
                        r'[\'"]([^\'"]*/pdf/[^\'"]*)[\'"]',
                        r'[\'"]([^\'"]*.pdf(?:\?[^\'"]*)?)[\'"]'
                    ]
                    
                    for pattern in pdf_regex_patterns:
                        matches = re.findall(pattern, script_content)
                        for match in matches:
                            pdf_links.append(match)
                            logger.info(f"Found PDF link in JavaScript: {match}")
                    
                    # METODE 3: Cari URL berdasarkan atribut data spesifik Semantic Scholar
                    
                    # 3.1: Cari semua elemen dengan atribut yang berisi link
                    for element in soup.find_all(attrs=True):
                        for attr_name, attr_value in element.attrs.items():
                            if isinstance(attr_value, str) and 'pdf' in attr_value.lower() and ('http' in attr_value or attr_value.startswith('/')):
                                # Filter URL yang relevan saja
                                if attr_value.lower().endswith('.pdf') or '/pdf/' in attr_value.lower():
                                    pdf_links.append(attr_value)
                                    logger.info(f"Found PDF link in attribute {attr_name}: {attr_value}")
                    
                    # METODE 4: Coba API Semantic Scholar langsung
                    if paper_id and not pdf_links:
                        try:
                            api_url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}?fields=openAccessPdf"
                            async with aiohttp.ClientSession() as session:
                                async with session.get(api_url, headers=headers) as api_response:
                                    if api_response.status == 200:
                                        api_data = await api_response.json()
                                        if api_data.get('openAccessPdf') and api_data['openAccessPdf'].get('url'):
                                            pdf_url = api_data['openAccessPdf']['url']
                                            pdf_links.append(pdf_url)
                                            logger.info(f"Found PDF link from API: {pdf_url}")
                        except Exception as e:
                            logger.error(f"Error querying Semantic Scholar API for PDF: {e}")
                    
                    # Normalisasi dan deduplikasi link PDF
                    normalized_links = []
                    for link in pdf_links:
                        # Pastikan URL lengkap
                        if link.startswith('/'):
                            link = 'https://www.semanticscholar.org' + link
                            
                        # Tambahkan ke list hanya jika belum ada
                        if link not in normalized_links:
                            normalized_links.append(link)
                    
                    # Prioritaskan link berdasarkan kriteria
                    result = None
                    
                    # 1. URL yang berakhiran .pdf dan berasal dari sumber tepercaya
                    trusted_domains = ['arxiv.org', 'researchgate.net', 'springer.com', 'ieee.org', 'acm.org', 'sciencedirect.com']
                    for link in normalized_links:
                        if link.lower().endswith('.pdf') and any(domain in link.lower() for domain in trusted_domains):
                            logger.info(f"Selected trusted direct PDF link: {link}")
                            result = link
                            break
                    
                    # 2. URL yang berakhiran .pdf
                    if not result:
                        for link in normalized_links:
                            if link.lower().endswith('.pdf'):
                                logger.info(f"Selected direct PDF link: {link}")
                                result = link
                                break
                    
                    # 3. URL dengan "pdf" dalam path
                    if not result:
                        for link in normalized_links:
                            if '/pdf/' in link.lower():
                                logger.info(f"Selected PDF path link: {link}")
                                result = link
                                break
                    
                    # 4. URL apapun dengan pdf di dalamnya
                    if not result and normalized_links:
                        logger.info(f"Selected first available PDF-like link: {normalized_links[0]}")
                        result = normalized_links[0]
                    
                    # Simpan hasil ke cache
                    PaperScraper._pdf_url_cache[url] = result
                    
                    # Batasi ukuran cache
                    if len(PaperScraper._pdf_url_cache) > 100:
                        # Hapus item random dari cache untuk mengurangi ukuran
                        keys = list(PaperScraper._pdf_url_cache.keys())
                        for _ in range(20):  # Hapus 20 item
                            if keys:
                                key = random.choice(keys)
                                del PaperScraper._pdf_url_cache[key]
                                keys.remove(key)
                                logger.debug(f"Removed PDF URL cache entry: {key}")
                    
                    return result
                    
        except Exception as e:
            logger.error(f"Error scraping Semantic Scholar detail page for PDF: {e}")
            return None  
    
    async def _find_open_access_pdf(self, doi: str) -> Optional[str]:
        """Mencoba menemukan PDF open access dari DOI menggunakan layanan seperti Unpaywall"""
        # Kode yang sudah ada, tidak perlu diubah
        # ...
        try:
            logger.info(f"Looking for open access PDF for DOI: {doi}")
            
            # Coba Unpaywall API
            async with aiohttp.ClientSession() as session:
                email = "yourapp@example.com"  # Ganti dengan email aplikasi Anda
                url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
                
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("is_oa") and data.get("best_oa_location"):
                            pdf_url = data["best_oa_location"].get("url_for_pdf")
                            if pdf_url and pdf_url.lower().endswith('.pdf'):
                                logger.info(f"Found PDF via Unpaywall: {pdf_url}")
                                return pdf_url
            
            # Jika tidak ditemukan di Unpaywall, coba cek di domain-domain umum untuk paper open access
            common_repositories = [
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/doi/{doi}/pdf",
                f"https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC{doi.split('/')[-1]}&blobtype=pdf"
            ]
            
            for repo_url in common_repositories:
                try:
                    async with session.head(repo_url, allow_redirects=True) as response:
                        if response.status == 200 and "pdf" in response.headers.get("Content-Type", ""):
                            logger.info(f"Found PDF via repository: {repo_url}")
                            return repo_url
                except:
                    continue
            
            # Tidak ditemukan PDF open access
            logger.info(f"No open access PDF found for DOI: {doi}")
            return None
        except Exception as e:
            logger.error(f"Error finding PDF for DOI {doi}: {e}")
            return None

    async def scrape_core(self, query: str, year_filter: str = "") -> List[Dict]:
        """Scrape papers from CORE API"""
        # Kode yang sudah ada, tidak perlu diubah
        # Note: Would require CORE API key for actual implementation
        logger.info("CORE API scraping not implemented yet")
        return []
    
    async def scrape_google_scholar(self, query: str, year_filter: str = "", max_results: int = 20) -> List[Dict]:
        """Scrape papers from Google Scholar with improved rate limiting"""
        
        # ✅ CHECK RATE LIMITER FIRST
        if not google_scholar_limiter.can_make_request():
            logger.warning("🚫 Google Scholar rate limit reached - skipping request")
            return []
        
        # ✅ WAIT IF NEEDED
        await google_scholar_limiter.wait_if_needed()
        
        # Sanitize query
        query = query.replace(' ', '+')
        
        # Build URL with limited results
        base_url = "https://scholar.google.com/scholar"
        params = {
            "q": query,
            "hl": "en",  # Use English for better results
            "as_sdt": "0,5",  # Include citations
            "num": min(max_results, 20)  # Limit to max 20 results
        }
        
        # Tambahkan filter tahun jika ada
        if year_filter and '-' in year_filter:
            start_year, end_year = year_filter.split('-')
            if start_year and end_year:
                params["as_ylo"] = start_year  # year low
                params["as_yhi"] = end_year    # year high
        
        try:
            # ✅ ENHANCED HEADERS - More realistic browser behavior
            base_headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': random.choice(['en-US,en;q=0.9', 'en-US,en;q=0.9,id;q=0.8', 'en;q=0.9']),
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'DNT': '1',
                'Cache-Control': 'max-age=0'
            }
            
            # ✅ ADD RANDOM REFERRER sometimes
            if random.random() < 0.3:  # 30% chance
                base_headers['Referer'] = random.choice([
                    'https://www.google.com/',
                    'https://scholar.google.com/',
                    'https://www.bing.com/academic',
                    'https://duckduckgo.com/'
                ])
            
            # ✅ VERY CONSERVATIVE DELAY - More random, longer intervals
            delay = random.uniform(8.0, 15.0)  # 8-15 seconds between requests
            logger.info(f"🕐 Waiting {delay:.1f}s before Google Scholar request for better success rate")
            await asyncio.sleep(delay)
            
            timeout = aiohttp.ClientTimeout(total=20)  # 20 second timeout for stability
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(base_url, params=params, headers=base_headers) as response:
                    success = response.status == 200
                    
                    # ✅ RECORD REQUEST OUTCOME
                    google_scholar_limiter.record_request(success)
                    
                    if response.status == 429:
                        logger.error("Google Scholar returned status code 429 - rate limited")
                        # ✅ EXPONENTIAL BACKOFF for next time
                        PaperScraper._session_counter += 5  # Heavy penalty
                        return []
                    elif response.status == 403:
                        logger.error("Google Scholar returned status code 403 - likely blocked by IP")
                        return []
                    elif response.status != 200:
                        logger.error(f"Google Scholar returned status code {response.status}")
                        return []
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Cek apakah kena CAPTCHA atau blocking
                    if any(phrase in html.lower() for phrase in [
                        "please show you're not a robot", 
                        "unusual traffic", 
                        "captcha",
                        "blocked"
                    ]):
                        logger.error("Google Scholar shows CAPTCHA or blocking - need to wait longer")
                        google_scholar_limiter.record_request(False)  # Mark as failure
                        return []
                    
                    results = []
                    
                    # Cari elemen hasil paper
                    paper_elements = soup.select('div.gs_ri')
                    
                    # ✅ LIMIT to max_results
                    for element in paper_elements[:max_results]:
                        try:
                            # Judul
                            title_elem = element.select_one('h3.gs_rt')
                            if not title_elem:
                                continue
                                
                            title = title_elem.get_text().strip()
                            title = title.replace('[PDF]', '').replace('[HTML]', '').strip()
                            
                            # Link
                            link_elem = title_elem.select_one('a')
                            link = link_elem['href'] if link_elem and 'href' in link_elem.attrs else ""
                            
                            # Author, venue, dan tahun 
                            author_venue_elem = element.select_one('.gs_a')
                            author_venue_text = author_venue_elem.get_text() if author_venue_elem else ""
                            
                            # Extract authors (biasanya sebelum tanda -)
                            authors = author_venue_text.split('-')[0].strip() if '-' in author_venue_text else ""
                            
                            # Extract year (biasanya empat digit di akhir atau dalam tanda kurung)
                            year_match = re.search(r'(\d{4})', author_venue_text)
                            year = int(year_match.group(1)) if year_match else 0
                            
                            # Extract venue (biasanya di tengah)
                            venue_parts = author_venue_text.split('-')
                            venue = venue_parts[1].strip() if len(venue_parts) > 1 else "Google Scholar"
                            
                            # Summary
                            summary_elem = element.select_one('.gs_rs')
                            summary = summary_elem.get_text().strip() if summary_elem else "No summary available"
                            
                            # Look for PDF URL - Google Scholar sometimes shows direct PDF links
                            pdf_url = None
                            pdf_link = element.select_one('a[href*=".pdf"], a:contains("[PDF]")')
                            if pdf_link and 'href' in pdf_link.attrs:
                                potential_pdf = pdf_link['href']
                                if potential_pdf.lower().endswith('.pdf') or 'pdf' in potential_pdf.lower():
                                    pdf_url = potential_pdf
                                    logger.debug(f"Found PDF link from Google Scholar: {pdf_url}")
                            
                            paper = {
                                'title': title,
                                'authors': authors,
                                'year': year,
                                'source': 'Google Scholar',
                                'venue': venue,
                                'link': link,
                                'summary': summary,
                                'id': f'gs_{hash(title)}',
                                'pdf_url': pdf_url
                            }
                            
                            results.append(paper)
                        except Exception as e:
                            logger.error(f"Error parsing Google Scholar paper: {e}")
                            continue
                    
                    logger.info(f"Found {len(results)} papers from Google Scholar")
                    return results
                    
        except asyncio.TimeoutError:
            logger.error("Google Scholar request timed out")
            google_scholar_limiter.record_request(False)
            return []
        except Exception as e:
            logger.error(f"Error scraping Google Scholar: {e}")
            google_scholar_limiter.record_request(False)
            return []
        
    async def scrape_ieee(self, query: str, year_filter: str = "") -> List[Dict]:
        """Scrape papers from IEEE Xplore"""
        # Kode yang sudah ada, tidak perlu diubah
        # ...
        try:
            # Panggil fungsi non-async IEEE scraper yang dibuat secara terpisah
            # Karena fungsi ini tidak async, kita tidak perlu await
            papers = search_ieee(query, year_filter, max_results=20)
            
            # Tambahkan pencarian PDF untuk setiap paper dari IEEE
            for paper in papers:
                if 'doi' in paper and paper['doi']:
                    doi = paper['doi']
                    # IEEE biasanya memiliki format PDF URL yang konsisten
                    ieee_pdf_url = f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={paper['id'].split('_')[-1]}"
                    paper['pdf_url'] = ieee_pdf_url
                elif 'link' in paper and paper['link']:
                    # Coba ekstrak arnumber dari link jika ada
                    arnumber_match = re.search(r'arnumber=(\d+)', paper['link'])
                    if arnumber_match:
                        arnumber = arnumber_match.group(1)
                        ieee_pdf_url = f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}"
                        paper['pdf_url'] = ieee_pdf_url
            
            return papers
        except Exception as e:
            logger.error(f"Error scraping IEEE: {e}")
            return []
    
    def _deduplicate_papers(self, papers: List[Dict]) -> List[Dict]:
        """Remove duplicate papers based on title similarity"""
        # Kode yang sudah ada, tidak perlu diubah
        # ...
        if not papers:
            return []
            
        unique_papers = []
        titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower()
            # Simplify title for comparison
            simple_title = re.sub(r'[^\w\s]', '', title)
            
            # Check if we already have a very similar title
            duplicate = False
            for existing_title in titles:
                if self._is_similar(simple_title, existing_title):
                    duplicate = True
                    break
                    
            if not duplicate:
                titles.add(simple_title)
                unique_papers.append(paper)
                
        return unique_papers
    
    def _is_similar(self, title1: str, title2: str) -> bool:
        """Check if two titles are similar"""
        # Kode yang sudah ada, tidak perlu diubah
        # ...
        # Simple check for >70% word overlap
        words1 = set(title1.split())
        words2 = set(title2.split())
        
        if not words1 or not words2:
            return False
            
        overlap = len(words1.intersection(words2))
        shorter_len = min(len(words1), len(words2))
        
        return overlap / shorter_len > 0.7
    
