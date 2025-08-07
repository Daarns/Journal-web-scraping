from app.ai.embeddings import embedding_service
from app.ai.gemini_service import gemini_service, RateLimitExceeded
from app.scrapers.paper_scraper import PaperScraper
import logging
from typing import List, Dict, Any, Optional
from app.services.pdf_services import PdfProcessor
import json
import traceback
import asyncio
import re
from datetime import datetime
from app.ai.gemini_service import GeminiService

logger = logging.getLogger(__name__)


class SearchService:
    """Service for academic paper search with enhanced author detection"""

    def __init__(self):
        self.gemini_service = GeminiService()
        self.paper_scraper = PaperScraper()

    async def search_papers(self, query: str) -> Dict[str, Any]:
        """Enhanced search dengan fixed routing untuk Indonesian queries"""
        try:
            # ✅ STEP 1: Enhanced query analysis
            search_analysis = self._analyze_search_query(query)
            
            logger.info(f"Search analysis: {search_analysis}")
            
            # ✅ STEP 2: Route to appropriate search strategy dengan proper handling
            if search_analysis["search_type"] == "author_only":
                return await self._search_author_only(search_analysis)
                
            elif search_analysis["search_type"] == "author_with_topic":
                return await self._search_author_with_topic(search_analysis)
                
            elif search_analysis["search_type"] == "title_year_search":
                return await self._search_title_year(search_analysis)
                
            elif search_analysis["search_type"] in ["general_topic", "general_topic_with_year"]:
                # ✅ ROUTE to general topic search (includes Indonesian-focused search)
                return await self._search_general_topic(search_analysis)
                
            else:  # fallback
                return await self._search_general_topic(search_analysis)
                
        except Exception as e:
            logger.error(f"Error in search_papers: {str(e)}")
            return await self._fallback_search(query)

    def _analyze_search_query(self, query: str) -> Dict[str, Any]:
        """Enhanced query analysis dengan 3-tier detection system - FIXED ROUTING"""
        
        query = query.strip()
        logger.info(f"🔍 Analyzing query: '{query}'")
        
        # ✅ TIER 1: AUTHOR SEARCH DETECTION (Highest Priority)
        author_result = self._detect_author_search(query)
        if author_result:
            return author_result
        
        # ✅ TIER 2: STRICT TITLE SEARCH DETECTION (More specific patterns only)
        title_year_result = self._detect_title_year_search_strict(query)
        if title_year_result:
            return title_year_result
        
        # ✅ TIER 3: GENERAL TOPIC SEARCH (Default - includes year-based queries)
        return self._detect_general_search(query)
    
    def _detect_title_year_search_strict(self, query: str) -> Optional[Dict[str, Any]]:
        """STRICT title/year detection - only for explicit titles, not general queries"""
        
        # ✅ EXPLICIT TITLE INDICATORS (very specific)
        explicit_title_indicators = [
            'judul', 'title', 'berjudul', 'titled', 'entitled', 'paper titled',
            'artikel berjudul', 'jurnal berjudul', 'paper dengan judul'
        ]
        
        query_lower = query.lower()
        
        # ✅ CHECK for explicit title indicators FIRST
        has_explicit_title_indicator = any(indicator in query_lower for indicator in explicit_title_indicators)
        
        # ✅ QUOTED PHRASES (definitely titles)
        is_quoted_phrase = (query.startswith('"') and query.endswith('"')) or (query.startswith("'") and query.endswith("'"))
        
        # ✅ VERY LONG DESCRIPTIVE ACADEMIC TITLES (50+ chars, specific patterns)
        is_long_academic_title = (
            len(query) >= 50 and 
            not any(general_indicator in query_lower for general_indicator in [
                'saya', 'mencari', 'cari', 'searching', 'looking for', 'find'
            ]) and
            self._is_likely_paper_title(query, query)
        )
        
        # ✅ STRICT CRITERIA: Only detect as title search if:
        # 1. Has explicit title indicator, OR
        # 2. Is quoted phrase, OR  
        # 3. Is very long academic title without search indicators
        if not (has_explicit_title_indicator or is_quoted_phrase or is_long_academic_title):
            return None
        
        # ✅ YEAR EXTRACTION (for title searches)
        year_range = self._extract_year_range(query)
        
        # ✅ ENHANCED TITLE PATTERNS (only for confirmed title queries)
        title_patterns = [
            # Explicit title patterns
            r'(?:judul|title|berjudul|titled|entitled|paper titled|artikel berjudul|jurnal berjudul|paper dengan judul)\s*[:\"]?\s*(.+)',
            
            # Quoted text (likely a title)
            r'"([^"]+)"',
            r"'([^']+)'",
            
            # Academic paper patterns (only if no general search indicators)
            r'^((?:\w+\s+){8,}(?:using|dengan|untuk|analysis|detection|classification|prediction|study|research|implementation|composition|extract|emulsion|fortification|product|development|evaluation|assessment|application|method|approach|technique|system|model|framework).*)$'
        ]
        
        # ✅ CHECK for title patterns
        for pattern in title_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                potential_title = match.group(1).strip() if len(match.groups()) >= 1 else query.strip()
                
                # Skip if it looks like author name
                if self._looks_like_author_name(potential_title):
                    continue
                
                # ✅ ENHANCED VALIDATION for title-like content
                if self._is_likely_paper_title(potential_title, query):
                    title_keywords = self._extract_title_keywords(potential_title)
                    
                    logger.info(f"🔍 STRICT TITLE SEARCH DETECTED: '{potential_title}' | Keywords: {title_keywords}")
                    return {
                        "search_type": "title_year_search",
                        "author_name": None,
                        "additional_authors": [],
                        "topic_keywords": title_keywords,
                        "potential_title": potential_title,
                        "year_range": year_range,
                        "original_query": query,
                        "search_priority": "exact_title_match",
                        "is_exact_phrase": is_quoted_phrase or is_long_academic_title
                    }
        
        return None
    
    def _detect_author_search(self, query: str) -> Optional[Dict[str, Any]]:
        """Detect if query is author-focused search - FIXED case insensitive"""
        
        # ✅ AUTHOR INDICATORS (keywords that suggest author search)
        author_indicators = [
            'penulis', 'author', 'karya', 'publikasi', 'jurnal oleh', 'paper by',
            'penelitian oleh', 'tulisan', 'makalah oleh', 'artikel oleh'
        ]
        
        # ✅ RELAXED AUTHOR PATTERNS - case insensitive
        author_patterns = [
            # Direct author indicators
            r'(?:penulis|author|karya|publikasi|jurnal|paper|penelitian|tulisan|makalah|artikel)\s+(?:oleh|by|dari)?\s*([a-zA-Z][a-zA-Z\s\.]*[a-zA-Z])',
            
            # Author with topic
            r'([a-zA-Z][a-zA-Z\s\.]*[a-zA-Z]).*(?:tentang|mengenai|about|on)\s+(.+)',
            
            # Simple name patterns (relaxed detection) - at least 2 words
            r'^([a-zA-Z]+(?:\s+[a-zA-Z]\.?)*(?:\s+[a-zA-Z]+)+)$',
            
            # Multiple authors
            r'^([a-zA-Z]+(?:\s+[a-zA-Z]*)*\s+[a-zA-Z]+)(?:\s*(?:dan|and|&|,)\s*([a-zA-Z]+(?:\s+[a-zA-Z]*)*\s+[a-zA-Z]+))+',
            
            # Academic titles
            r'^(?:dr\.?\s*|prof\.?\s*)?([a-zA-Z]+(?:\s+[a-zA-Z]*)*\s+[a-zA-Z]+)',
        ]
        
        # ✅ CHECK for author indicators first
        query_lower = query.lower()
        has_author_indicator = any(indicator in query_lower for indicator in author_indicators)
        
        # ✅ CHECK patterns with case insensitive matching
        for pattern in author_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                # Extract author and topic (if any)
                author_name = match.group(1).strip()
                topic_part = match.group(2).strip() if len(match.groups()) > 1 else ""
                
                # ✅ NORMALIZE author name (proper case)
                author_name = self._normalize_author_name(author_name)
                
                # ✅ VALIDATE author name with relaxed rules
                if self._is_valid_author_name_relaxed(author_name, has_author_indicator):
                    # Parse multiple authors if any
                    authors = self._parse_multiple_authors(author_name)
                    valid_authors = [self._normalize_author_name(author) for author in authors if self._is_valid_author_name_relaxed(author, has_author_indicator)]
                    
                    if valid_authors:
                        primary_author = valid_authors[0]
                        
                        # Determine if it's author-only or author+topic
                        if topic_part and len(topic_part.strip()) > 2:
                            topic_keywords = self._extract_topic_keywords(topic_part)
                            logger.info(f"🔍 Detected AUTHOR WITH TOPIC: '{primary_author}' + {topic_keywords}")
                            return {
                                "search_type": "author_with_topic",
                                "author_name": primary_author,
                                "additional_authors": valid_authors[1:] if len(valid_authors) > 1 else [],
                                "topic_keywords": topic_keywords,
                                "year_range": self._extract_year_range(query),
                                "original_query": query
                            }
                        else:
                            logger.info(f"🔍 Detected AUTHOR ONLY: '{primary_author}'")
                            return {
                                "search_type": "author_only", 
                                "author_name": primary_author,
                                "additional_authors": valid_authors[1:] if len(valid_authors) > 1 else [],
                                "topic_keywords": [],
                                "year_range": self._extract_year_range(query),
                                "original_query": query
                            }
        
        return None
    
    def _normalize_author_name(self, name: str) -> str:
        """Normalize author name to proper case"""
        if not name:
            return ""
        
        # Split by spaces and normalize each word
        words = []
        for word in name.split():
            word = word.strip()
            if not word:
                continue
                
            # Handle initials (keep uppercase)
            if len(word) <= 2 and word.endswith('.'):
                words.append(word.upper())
            elif len(word) == 1:
                words.append(word.upper())
            # Handle normal words (title case)
            else:
                words.append(word.capitalize())
        
        return " ".join(words)

    def _is_valid_author_name_relaxed(self, name: str, has_context_indicator: bool = False) -> bool:
        """Relaxed author name validation - no strict capitalization required"""
        name = name.strip()
        
        # Basic checks
        if len(name) < 3 or len(name) > 60:
            return False
        
        # Must have at least 2 words for full names
        words = name.split()
        if len(words) < 2:
            return False
        
        # ✅ RELAXED VALIDATION 
        if has_context_indicator:
            # If we have "penulis", "author", etc., be very permissive
            return all(len(word) > 0 and word.replace('.', '').isalpha() for word in words)
        
        # ✅ CHECK each word is reasonable (letters only, reasonable length)
        for word in words:
            # Remove dots for initials check
            clean_word = word.replace('.', '')
            
            # Must be alphabetic
            if not clean_word.isalpha():
                return False
            
            # Must be reasonable length (1-20 chars)
            if len(clean_word) < 1 or len(clean_word) > 20:
                return False
        
        # ✅ EXCLUDE obvious non-author terms (case insensitive)
        excluded_patterns = [
            r'\b(?:artificial|intelligence|machine|learning|deep|neural|network|algorithm|computer|vision|data|mining|processing|analysis|research|study|paper|journal|article|review|survey|classification|detection|prediction|implementation|evaluation|optimization|framework|system|method|approach|technique|application|development|novel|improved|enhanced|advanced|efficient|robust|automatic|real|time|based|using|with|for|from|through|via|toward|towards)\b',
            r'\b(?:jurnal|penelitian|analisis|studi|kajian|evaluasi|implementasi|pengembangan|penerapan|perancangan|pembangunan|teknologi|sistem|metode|algoritma|jaringan|kecerdasan|buatan|pembelajaran|mesin|pengolahan|informasi|data)\b',
            r'\b\d{4}\b',  # Years
            r'\b(?:covid|ai|ml|dl|nlp|cnn|rnn|lstm|bert|gpt)\b',  # Acronyms
        ]
        
        name_lower = name.lower()
        for pattern in excluded_patterns:
            if re.search(pattern, name_lower):
                return False
        
        # ✅ CHECK for academic field terms
        academic_terms = [
            'learning', 'intelligence', 'network', 'detection', 'classification',
            'analysis', 'research', 'study', 'medical', 'clinical', 'healthcare'
        ]
        
        if any(term in name_lower for term in academic_terms):
            return False
        
        return True
    
    def _extract_topic_keywords(self, topic_part: str) -> list:
        """Extract topic keywords for author+topic search"""
        if not topic_part:
            return []
        
        # Remove common stopwords
        stopwords = {
            'tentang', 'mengenai', 'about', 'on', 'in', 'di', 'pada', 'yang', 
            'dan', 'atau', 'untuk', 'dengan', 'dari', 'the', 'a', 'an', 'and', 'or'
        }
        
        # Extract meaningful words
        words = re.findall(r'\b[a-zA-Z]+\b', topic_part.lower())
        keywords = []
        
        for word in words:
            if word not in stopwords and len(word) >= 2:
                # Skip years
                if not re.match(r'^\d{4}$', word):
                    keywords.append(word)
        
        # Keep original order and limit to 4 keywords max
        return keywords[:4]
    
    def _is_likely_paper_title(self, text: str, original_query: str) -> bool:
        """Enhanced validation untuk detect paper titles - exclude Indonesian search queries"""
        if not text or len(text) < 20:  # Too short for academic title
            return False
        
        # ✅ EXCLUDE GENERAL SEARCH PATTERNS (Indonesian & English)
        general_search_indicators = [
            # Indonesian search patterns
            'saya sedang mencari', 'saya mencari', 'mencari jurnal', 'cari jurnal',
            'saya ingin', 'saya butuh', 'tolong carikan', 'bantuan mencari',
            
            # English search patterns  
            'i am looking for', 'i need', 'searching for', 'looking for',
            'can you find', 'help me find', 'i want to find'
        ]
        
        text_lower = original_query.lower()  # Check original query, not just extracted text
        
        # If contains general search indicators, it's NOT a title
        if any(indicator in text_lower for indicator in general_search_indicators):
            logger.debug(f"Rejected as title - contains search indicators: '{text}'")
            return False
        
        # ✅ ACADEMIC TITLE INDICATORS (keep existing logic)
        academic_indicators = [
            # Research methodology terms
            'analysis', 'study', 'research', 'investigation', 'evaluation', 'assessment',
            'comparison', 'development', 'implementation', 'application', 'optimization',
            
            # Technical terms
            'composition', 'extract', 'emulsion', 'fortification', 'product', 'system',
            'method', 'approach', 'technique', 'model', 'framework', 'algorithm',
            'detection', 'classification', 'prediction', 'optimization',
            
            # Scientific domains
            'nutritional', 'chemical', 'biological', 'medical', 'clinical', 'pharmaceutical',
            'engineering', 'technological', 'computational', 'environmental',
            
            # Academic action words
            'using', 'dengan', 'untuk', 'based', 'improved', 'enhanced', 'novel',
            'efficient', 'effective', 'automatic', 'intelligent'
        ]
        
        # Count academic indicators
        text_lower_clean = text.lower()
        academic_score = sum(1 for indicator in academic_indicators if indicator in text_lower_clean)
        
        # ✅ STRUCTURE INDICATORS
        has_proper_structure = (
            len(text.split()) >= 6 and  # At least 6 words
            any(char.isupper() for char in text) and  # Has capital letters
            not text.islower()  # Not all lowercase
        )
        
        # ✅ TECHNICAL DOMAIN INDICATORS
        technical_domains = [
            'nano', 'micro', 'bio', 'eco', 'neuro', 'geo', 'hydro', 'electro',
            'photo', 'thermo', 'spectro', 'chromo', 'radio'
        ]
        
        has_technical_prefix = any(prefix in text_lower_clean for prefix in technical_domains)
        
        # ✅ DECISION LOGIC (stricter criteria)
        if len(original_query.split()) >= 10:  # Very long query
            return academic_score >= 3 or has_technical_prefix  # Higher threshold
        elif academic_score >= 4:  # Very strong academic indicators
            return True
        elif has_proper_structure and academic_score >= 3:  # Good structure + strong indicators
            return True
        
        return False
    
    def _is_likely_paper_title(self, text: str, original_query: str) -> bool:
        """Enhanced validation untuk detect paper titles"""
        if not text or len(text) < 20:  # Too short for academic title
            return False
        
        # ✅ ACADEMIC TITLE INDICATORS
        academic_indicators = [
            # Research methodology terms
            'analysis', 'study', 'research', 'investigation', 'evaluation', 'assessment',
            'comparison', 'development', 'implementation', 'application', 'optimization',
            
            # Technical terms
            'composition', 'extract', 'emulsion', 'fortification', 'product', 'system',
            'method', 'approach', 'technique', 'model', 'framework', 'algorithm',
            'detection', 'classification', 'prediction', 'optimization',
            
            # Scientific domains
            'nutritional', 'chemical', 'biological', 'medical', 'clinical', 'pharmaceutical',
            'engineering', 'technological', 'computational', 'environmental',
            
            # Academic action words
            'using', 'dengan', 'untuk', 'based', 'improved', 'enhanced', 'novel',
            'efficient', 'effective', 'automatic', 'intelligent'
        ]
        
        # Count academic indicators
        text_lower = text.lower()
        academic_score = sum(1 for indicator in academic_indicators if indicator in text_lower)
        
        # ✅ STRUCTURE INDICATORS
        has_proper_structure = (
            len(text.split()) >= 6 and  # At least 6 words
            any(char.isupper() for char in text) and  # Has capital letters
            not text.islower()  # Not all lowercase
        )
        
        # ✅ TECHNICAL DOMAIN INDICATORS
        technical_domains = [
            'nano', 'micro', 'bio', 'eco', 'neuro', 'geo', 'hydro', 'electro',
            'photo', 'thermo', 'spectro', 'chromo', 'radio'
        ]
        
        has_technical_prefix = any(prefix in text_lower for prefix in technical_domains)
        
        # ✅ DECISION LOGIC
        if len(original_query.split()) >= 8:  # Long query likely a title
            return academic_score >= 2 or has_technical_prefix
        elif academic_score >= 3:  # Strong academic indicators
            return True
        elif has_proper_structure and academic_score >= 2:  # Good structure + some indicators
            return True
        
        return False
    
    def _detect_general_search(self, query: str) -> Dict[str, Any]:
        """Enhanced general topic search detection - includes year-based queries"""
        
        topic_keywords = self._extract_general_keywords(query)
        year_range = self._extract_year_range(query)
        
        # ✅ DETERMINE search type based on content
        search_type = "general_topic"
        
        # Check if it's a year-focused search within general topic
        if year_range and any(indicator in query.lower() for indicator in [
            'tahun', 'year', 'antara tahun', 'between', 'dari tahun', 'since'
        ]):
            search_type = "general_topic_with_year"
        
        logger.info(f"🔍 Detected GENERAL TOPIC SEARCH: Keywords: {topic_keywords} | Year: {year_range}")
        
        return {
            "search_type": search_type,
            "author_name": None,
            "additional_authors": [],
            "topic_keywords": topic_keywords,
            "potential_title": None,
            "year_range": year_range,
            "original_query": query
        }
    
    def _is_valid_author_name_enhanced(self, name: str, has_context_indicator: bool = False) -> bool:
        """Enhanced author name validation with context awareness - FIXED capitalization"""
        name = name.strip()
        
        # Basic checks
        if len(name) < 3 or len(name) > 60:
            return False
        
        # Must have at least 2 words for full names
        words = name.split()
        if len(words) < 2:
            return False
        
        # ✅ RELAXED VALIDATION if context indicators present
        if has_context_indicator:
            # If we have "penulis", "author", etc., be more permissive
            return all(len(word) > 1 for word in words)  # Just check word length
        
        # ✅ RELAXED VALIDATION for pattern-only detection
        # Remove strict capitalization requirement
        
        # ✅ EXCLUDE obvious non-author terms
        excluded_patterns = [
            r'\b(?:artificial|intelligence|machine|learning|deep|neural|network|algorithm|computer|vision|data|mining|processing|analysis|research|study|paper|journal|article|review|survey|classification|detection|prediction|implementation|evaluation|optimization|framework|system|method|approach|technique|application|development|novel|improved|enhanced|advanced|efficient|robust|automatic|real|time|based|using|with|for|from|through|via|toward|towards)\b',
            r'\b(?:jurnal|penelitian|analisis|studi|kajian|evaluasi|implementasi|pengembangan|penerapan|perancangan|pembangunan|teknologi|sistem|metode|algoritma|jaringan|kecerdasan|buatan|pembelajaran|mesin|pengolahan|informasi|data)\b',
            r'\b\d{4}\b',  # Years
            r'\b(?:covid|ai|ml|dl|nlp|cnn|rnn|lstm|bert|gpt)\b',  # Acronyms
        ]
        
        name_lower = name.lower()
        for pattern in excluded_patterns:
            if re.search(pattern, name_lower):
                return False
        
        # ✅ CHECK for academic field terms
        academic_terms = [
            'learning', 'intelligence', 'network', 'detection', 'classification',
            'analysis', 'research', 'study', 'medical', 'clinical', 'healthcare'
        ]
        
        if any(term in name_lower for term in academic_terms):
            return False
        
        # ✅ SIMPLE CHECK: each word should be reasonable length and not all numbers
        for word in words:
            if len(word) < 2 or word.isdigit():
                return False
        
        return True
    
    def _looks_like_author_name(self, text: str) -> bool:
        """Quick check if text looks like author name"""
        if not text:
            return False
        
        words = text.strip().split()
        if len(words) != 2:  # Most author names are 2 words in detection
            return False
        
        # Both words should be capitalized and reasonable length
        return all(
            word[0].isupper() and word[1:].islower() and 2 <= len(word) <= 15
            for word in words
        )
    
    def _extract_title_keywords(self, title_text: str) -> list:
        """Extract keywords specifically for title matching"""
        if not title_text:
            return []
        
        # Remove common title words but keep technical terms
        title_stopwords = {
            'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
            'using', 'dengan', 'untuk', 'dalam', 'pada', 'dari', 'terhadap', 'sebagai'
        }
        
        # Extract meaningful words
        words = re.findall(r'\b[a-zA-Z]+\b', title_text.lower())
        keywords = []
        
        for word in words:
            if word not in title_stopwords and len(word) >= 3:
                # Skip years
                if not re.match(r'^\d{4}$', word):
                    keywords.append(word)
        
        # Keep original order and limit to 8 keywords for title search
        return keywords[:8]
    
    async def _search_title_year(self, analysis: dict) -> dict:
        """Enhanced title/year search dengan exact phrase matching"""
        potential_title = analysis.get("potential_title")
        topic_keywords = analysis["topic_keywords"]
        year_range = analysis.get("year_range", {})
        search_priority = analysis.get("search_priority", "title_match")
        original_query = analysis.get("original_query", "")
        is_exact_phrase = analysis.get("is_exact_phrase", False)
        
        logger.info(f"🔍 Executing TITLE/YEAR search")
        logger.info(f"📋 Title: '{potential_title}'")
        logger.info(f"🔑 Keywords: {topic_keywords}")
        logger.info(f"📅 Year: {year_range}")
        logger.info(f"🎯 Priority: {search_priority}")
        logger.info(f"📝 Exact phrase: {is_exact_phrase}")
        
        all_papers = []
        
        # ✅ DETECT LANGUAGE for title/year search
        query_language = self._detect_language(original_query)
        logger.info(f"🌐 Detected language: {query_language}")
        
        # ✅ BUILD ENHANCED SEARCH QUERIES
        search_queries = []
        
        if search_priority == "exact_title_match" and potential_title:
            # ✅ STRATEGY 1: EXACT PHRASE SEARCH (highest priority)
            if is_exact_phrase:
                exact_phrase_query = f'"{potential_title}"'
                search_queries.append(exact_phrase_query)
                logger.info(f"🎯 Added exact phrase search: {exact_phrase_query}")
            
            # ✅ STRATEGY 2: TITLE SEGMENTS (medium priority)
            # Split long title into meaningful segments
            title_segments = self._extract_title_segments(potential_title)
            for segment in title_segments[:2]:  # Top 2 segments
                search_queries.append(f'"{segment}"')
                logger.info(f"🧩 Added segment search: \"{segment}\"")
            
            # ✅ STRATEGY 3: KEY PHRASES from title
            key_phrases = self._extract_key_phrases(potential_title)
            for phrase in key_phrases[:2]:  # Top 2 key phrases
                search_queries.append(phrase)
                logger.info(f"🔑 Added key phrase: {phrase}")
            
            # ✅ STRATEGY 4: KEYWORD COMBINATION
            if topic_keywords and len(topic_keywords) >= 3:
                keyword_query = " ".join(topic_keywords[:4])
                search_queries.append(keyword_query)
                logger.info(f"📝 Added keyword search: {keyword_query}")
        
        elif search_priority == "title_match" and potential_title:
            # Original title matching logic
            search_queries.append(f'"{potential_title}"')
            if topic_keywords:
                title_query = " ".join(topic_keywords[:4])
                search_queries.append(title_query)
        
        elif search_priority == "year_filter":
            # Year-focused search logic
            if topic_keywords:
                recent_query = f"recent {' '.join(topic_keywords[:3])}"
                search_queries.append(recent_query)
                plain_query = " ".join(topic_keywords[:4])
                search_queries.append(plain_query)
        
        else:
            # Default: keyword-based search
            if topic_keywords:
                search_queries.append(" ".join(topic_keywords[:4]))
        
        # ✅ EXECUTE SEARCHES dengan enhanced exact matching
        for i, search_query in enumerate(search_queries[:4]):  # Top 4 strategies
            logger.info(f"🔍 Title search strategy {i+1}: '{search_query}'")
            
            if query_language == "id":
                # Indonesian: Google Scholar first (best for local content)
                try:
                    scholar_papers = await self.paper_scraper.scrape_google_scholar(search_query, max_results=20)
                    all_papers.extend(scholar_papers)
                    logger.info(f"   📚 Google Scholar: {len(scholar_papers)} papers")
                except Exception as e:
                    logger.error(f"Google Scholar error: {e}")
                
                try:
                    semantic_papers = await self.paper_scraper.scrape_semantic_scholar(search_query, max_results=20)
                    all_papers.extend(semantic_papers)
                    logger.info(f"   📚 Semantic Scholar: {len(semantic_papers)} papers")
                except Exception as e:
                    logger.error(f"Semantic Scholar error: {e}")
                
                try:
                    arxiv_papers = await self.paper_scraper.scrape_arxiv(search_query, max_results=20)
                    all_papers.extend(arxiv_papers)
                    logger.info(f"   📚 ArXiv: {len(arxiv_papers)} papers")
                except Exception as e:
                    logger.error(f"ArXiv error: {e}")
                
                try:
                    scholar_papers = await self.paper_scraper.scrape_google_scholar(search_query, max_results=20)
                    all_papers.extend(scholar_papers)
                    logger.info(f"   📚 Google Scholar: {len(scholar_papers)} papers")
                except Exception as e:
                    logger.error(f"Google Scholar error: {e}")
            
            else:
                # English: Semantic Scholar and ArXiv first (better for international content)
                try:
                    semantic_papers = await self.paper_scraper.scrape_semantic_scholar(search_query, max_results=20)
                    all_papers.extend(semantic_papers)
                    logger.info(f"   📚 Semantic Scholar: {len(semantic_papers)} papers")
                except Exception as e:
                    logger.error(f"Semantic Scholar error: {e}")
                
                try:
                    arxiv_papers = await self.paper_scraper.scrape_arxiv(search_query, max_results=20)
                    all_papers.extend(arxiv_papers)
                    logger.info(f"   📚 ArXiv: {len(arxiv_papers)} papers")
                except Exception as e:
                    logger.error(f"ArXiv error: {e}")
                
                try:
                    scholar_papers = await self.paper_scraper.scrape_google_scholar(search_query, max_results=20)
                    all_papers.extend(scholar_papers)
                    logger.info(f"   📚 Google Scholar: {len(scholar_papers)} papers")
                except Exception as e:
                    logger.error(f"Google Scholar error: {e}")
                    logger.error(f"ArXiv error: {e}")
                
                try:
                    scholar_papers = await self.paper_scraper.scrape_google_scholar(search_query, max_results=20)
                    all_papers.extend(scholar_papers)
                    logger.info(f"   📚 Google Scholar: {len(scholar_papers)} papers")
                except Exception as e:
                    logger.error(f"Google Scholar error: {e}")
            
            # ✅ EARLY BREAK if exact match found
            if is_exact_phrase and i == 0:  # After exact phrase search
                exact_matches = self._find_exact_title_matches(all_papers, potential_title)
                if exact_matches:
                    logger.info(f"🎯 Found {len(exact_matches)} exact title matches, prioritizing")
                    all_papers = exact_matches + [p for p in all_papers if p not in exact_matches]
            
            # Break if sufficient results
            if len(all_papers) >= 50:
                logger.info(f"✅ Sufficient results obtained ({len(all_papers)} papers)")
                break
        
        # ✅ SPECIALIZED RANKING for title search
        unique_papers = self._deduplicate_and_rank_by_title_year(
            all_papers, potential_title, topic_keywords, year_range, query_language
        )
        
        # ✅ GENERATE TITLE-SPECIFIC SUGGESTIONS
        suggested_queries = await self._generate_title_year_suggestions(
            potential_title, topic_keywords, year_range, query_language
        )
        
        logger.info(f"📋 Final title search results: {len(unique_papers)} papers, {len(suggested_queries)} suggestions")
        
        return {"papers": unique_papers[:50], "suggested_queries": suggested_queries}
    
    def _extract_title_segments(self, title: str) -> list:
        """Extract meaningful segments from long title"""
        if not title or len(title) < 30:
            return [title] if title else []
        
        # ✅ SPLIT by common academic title patterns
        segments = []
        
        # Split by conjunctions and prepositions
        conjunctions = [' with ', ' using ', ' for ', ' in ', ' of ', ' and ', ' as ']
        
        current_segment = title
        for conj in conjunctions:
            if conj in current_segment.lower():
                parts = current_segment.split(conj, 1)
                if len(parts[0].strip()) >= 20:  # Meaningful length
                    segments.append(parts[0].strip())
                if len(parts) > 1 and len(parts[1].strip()) >= 15:
                    current_segment = parts[1].strip()
                else:
                    break
            
        # Add remaining part if meaningful
        if current_segment and len(current_segment.strip()) >= 15:
            segments.append(current_segment.strip())
        
        # ✅ FALLBACK: split by length if no good segments
        if not segments:
            words = title.split()
            if len(words) >= 8:
                mid_point = len(words) // 2
                segments.append(' '.join(words[:mid_point]))
                segments.append(' '.join(words[mid_point:]))
            else:
                segments.append(title)
        
        logger.debug(f"Title segments extracted: {segments}")
        return segments[:3]  # Max 3 segments
    
    def _extract_key_phrases(self, title: str) -> list:
        """Extract key phrases from title"""
        if not title:
            return []
        
        # ✅ TECHNICAL PHRASE PATTERNS
        phrase_patterns = [
            # Multi-word technical terms
            r'\b(?:nano\s+emulsion|micro\s+encapsulation|active\s+compounds|bioactive\s+compounds)\b',
            r'\b(?:nutritional\s+composition|chemical\s+analysis|sensory\s+evaluation)\b',
            r'\b(?:machine\s+learning|artificial\s+intelligence|neural\s+network)\b',
            r'\b(?:systematic\s+review|meta\s+analysis|clinical\s+trial)\b',
            
            # Domain + method patterns
            r'\b\w+\s+(?:extract|emulsion|fortification|composition|analysis|detection)\b',
            r'\b(?:improved|enhanced|novel|effective)\s+\w+\b',
        ]
        
        key_phrases = []
        title_lower = title.lower()
        
        for pattern in phrase_patterns:
            matches = re.findall(pattern, title_lower, re.IGNORECASE)
            key_phrases.extend(matches)
        
        # ✅ FALLBACK: extract important word combinations
        if not key_phrases:
            words = title.split()
            important_words = []
            
            # Filter important words
            stopwords = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'as'}
            for word in words:
                clean_word = re.sub(r'[^\w]', '', word.lower())
                if clean_word not in stopwords and len(clean_word) >= 4:
                    important_words.append(clean_word)
            
            # Create 2-3 word phrases from important words
            for i in range(len(important_words) - 1):
                if i + 2 < len(important_words):
                    phrase = f"{important_words[i]} {important_words[i+1]} {important_words[i+2]}"
                    key_phrases.append(phrase)
                else:
                    phrase = f"{important_words[i]} {important_words[i+1]}"
                    key_phrases.append(phrase)
        
        logger.debug(f"Key phrases extracted: {key_phrases}")
        return key_phrases[:4]  # Max 4 phrases
    
    def _find_exact_title_matches(self, papers: list, target_title: str) -> list:
        """Find papers with exact or very close title matches"""
        if not papers or not target_title:
            return []
        
        exact_matches = []
        target_clean = self._clean_title_for_comparison(target_title)
        
        for paper in papers:
            paper_title = paper.get('title', '')
            paper_clean = self._clean_title_for_comparison(paper_title)
            
            # ✅ EXACT MATCH (case insensitive, punctuation normalized)
            if target_clean == paper_clean:
                paper['exact_title_match'] = True
                paper['title_similarity'] = 1.0
                exact_matches.append(paper)
            
            # ✅ VERY HIGH SIMILARITY (>95%)
            elif self._calculate_title_similarity(target_clean, paper_clean) >= 0.95:
                paper['exact_title_match'] = False
                paper['title_similarity'] = self._calculate_title_similarity(target_clean, paper_clean)
                exact_matches.append(paper)
        
        # Sort by similarity
        exact_matches.sort(key=lambda p: p.get('title_similarity', 0), reverse=True)
        
        logger.info(f"🎯 Found {len(exact_matches)} exact/near-exact title matches")
        
        return exact_matches
    
    def _clean_title_for_comparison(self, title: str) -> str:
        """Clean title untuk exact comparison"""
        if not title:
            return ""
        
        # Convert to lowercase
        cleaned = title.lower()
        
        # Remove punctuation and extra spaces
        cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Remove common title prefixes/suffixes
        prefixes = ['a ', 'an ', 'the ']
        for prefix in prefixes:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):]
        
        return cleaned.strip()
    
    def _calculate_title_similarity(self, title1: str, title2: str) -> float:
        """Calculate similarity between two titles"""
        if not title1 or not title2:
            return 0.0
        
        # Word-based similarity
        words1 = set(title1.split())
        words2 = set(title2.split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        jaccard_similarity = intersection / union if union > 0 else 0.0
        
        # Length-based adjustment
        length_diff = abs(len(title1) - len(title2))
        max_length = max(len(title1), len(title2))
        length_penalty = length_diff / max_length if max_length > 0 else 0.0
        
        final_similarity = jaccard_similarity * (1.0 - length_penalty * 0.3)
        
        return final_similarity
    
    def _deduplicate_and_rank_by_title_year(
        self, papers: list, potential_title: str, topic_keywords: list, 
        year_range: dict, language: str
    ) -> list:
        """Specialized ranking for title/year searches"""
        if not papers:
            return []
        
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:60]
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                
                # ✅ CALCULATE specialized relevance scores
                paper['title_relevance'] = self._calculate_title_relevance(paper, potential_title, topic_keywords)
                paper['year_relevance'] = self._calculate_year_relevance(paper, year_range)
                paper['language_relevance'] = self._calculate_language_relevance(paper, language)
                unique_papers.append(paper)
        
        # ✅ SPECIALIZED SORTING for title/year search
        def sort_key(paper):
            title_rel = paper.get('title_relevance', 0.0)
            year_rel = paper.get('year_relevance', 0.0)
            lang_rel = paper.get('language_relevance', 0.0)
            citations = int(paper.get('citation_count', 0)) if paper.get('citation_count') else 0
            
            # Normalize citations
            citation_score = min(1.0, citations / 50)
            
            # Weighted scoring: 40% title + 25% year + 20% language + 15% citations
            return (title_rel * 0.4) + (year_rel * 0.25) + (lang_rel * 0.2) + (citation_score * 0.15)
        
        unique_papers.sort(key=sort_key, reverse=True)
        
        logger.info(f"📊 Title/Year ranking results: {len(unique_papers)} unique papers")
        if unique_papers:
            top_paper = unique_papers[0]
            logger.info(f"🏆 Top paper: '{top_paper.get('title', '')[:80]}'")
            logger.info(f"    Title relevance: {top_paper.get('title_relevance', 0):.2f}")
            logger.info(f"    Year relevance: {top_paper.get('year_relevance', 0):.2f}")
        
        return unique_papers
    
    def _calculate_title_relevance(self, paper: dict, potential_title: str, topic_keywords: list) -> float:
        """Enhanced title relevance dengan exact matching priority"""
        paper_title = paper.get('title', '').lower()
        
        if not paper_title:
            return 0.0
        
        relevance = 0.0
        
        # ✅ EXACT TITLE MATCHING (highest priority)
        if potential_title:
            potential_title_clean = self._clean_title_for_comparison(potential_title)
            paper_title_clean = self._clean_title_for_comparison(paper_title)
            
            # Perfect exact match
            if potential_title_clean == paper_title_clean:
                relevance += 2.0  # Doubled for exact match
                logger.info(f"🎯 EXACT TITLE MATCH found: '{paper.get('title', '')}'")
            
            # Very high similarity
            elif self._calculate_title_similarity(potential_title_clean, paper_title_clean) >= 0.9:
                similarity = self._calculate_title_similarity(potential_title_clean, paper_title_clean)
                relevance += similarity * 1.8  # High bonus for near-exact
                logger.info(f"🎯 NEAR-EXACT TITLE MATCH ({similarity:.2f}): '{paper.get('title', '')}'")
            
            # Partial title matching
            elif potential_title.lower() in paper_title or paper_title in potential_title.lower():
                relevance += 1.5
            
            else:
                # Word-by-word matching
                title_words = set(potential_title.lower().split())
                paper_words = set(paper_title.split())
                overlap = len(title_words.intersection(paper_words))
                if title_words:
                    word_match_score = (overlap / len(title_words)) * 1.2
                    relevance += word_match_score
        
        # ✅ KEYWORD MATCHING in title (lower priority than exact match)
        if topic_keywords:
            keyword_matches = 0
            total_keyword_weight = 0
            
            for keyword in topic_keywords:
                keyword_lower = keyword.lower()
                if keyword_lower in paper_title:
                    # Weight longer keywords higher
                    weight = min(2.0, len(keyword) / 5.0)
                    keyword_matches += weight
                    total_keyword_weight += weight
            
            if topic_keywords:
                keyword_score = (keyword_matches / len(topic_keywords)) * 0.8  # Reduced from 0.6
                relevance += keyword_score
        
        # ✅ BONUS for papers marked as exact matches
        if paper.get('exact_title_match'):
            relevance += 0.5
        
        # ✅ TITLE STRUCTURE BONUS (academic papers have specific patterns)
        if self._has_academic_title_structure(paper_title):
            relevance += 0.2
        
        return min(2.5, relevance)  # Increased max from 1.0 to 2.5 untuk exact matches
    
    def _has_academic_title_structure(self, title: str) -> bool:
        """Check if title has academic paper structure"""
        if not title:
            return False
        
        title_lower = title.lower()
        
        # Academic structure indicators
        academic_patterns = [
            r'\b(?:study|analysis|investigation|evaluation|assessment|review|survey)\b',
            r'\b(?:development|implementation|application|optimization|improvement)\b',
            r'\b(?:effect|impact|influence|relationship|correlation|comparison)\b',
            r'\b(?:using|based|through|via|with|for|in|of)\b.*\b(?:method|approach|technique|system|model)\b',
            r':\s*(?:a|an)\s+\w+',  # Colon followed by article
        ]
        
        return any(re.search(pattern, title_lower) for pattern in academic_patterns)
    
    def _calculate_year_relevance(self, paper: dict, year_range: dict) -> float:
        """Calculate relevance based on year matching"""
        if not year_range:
            return 0.5  # Neutral if no year specified
        
        paper_year = paper.get('year')
        if not paper_year:
            return 0.3  # Lower score for papers without year
        
        try:
            paper_year = int(paper_year)
        except (ValueError, TypeError):
            return 0.3
        
        start_year = year_range.get('start')
        end_year = year_range.get('end', start_year)
        
        if start_year and end_year:
            if start_year <= paper_year <= end_year:
                return 1.0  # Perfect match
            else:
                # Gradual decrease based on distance
                if paper_year < start_year:
                    distance = start_year - paper_year
                else:
                    distance = paper_year - end_year
                
                # Decrease by 0.1 per year distance, minimum 0.1
                return max(0.1, 1.0 - (distance * 0.1))
        
        return 0.5
    
    async def _generate_title_year_suggestions(
        self, potential_title: str, topic_keywords: list, year_range: dict, language: str
    ) -> list:
        """Generate suggestions for title/year searches"""
        suggestions = []
        
        if topic_keywords:
            main_topic = topic_keywords[0]
            
            if language == "id":
                suggestions.extend([
                    f"penelitian {main_topic} terbaru",
                    f"studi {main_topic} tahun ini",
                    f"analisis {main_topic} terkini",
                    f"review {main_topic} Indonesia",
                    f"implementasi {main_topic}",
                    f"evaluasi {main_topic}"
                ])
            else:
                suggestions.extend([
                    f"recent {main_topic} research",
                    f"{main_topic} systematic review",
                    f"latest {main_topic} developments",
                    f"{main_topic} state of the art",
                    f"advances in {main_topic}",
                    f"{main_topic} survey"
                ])
        
        # Add year-specific suggestions
        if year_range:
            start_year = year_range.get('start')
            if start_year:
                current_year = datetime.now().year
                if start_year < current_year - 1:
                    suggestions.append(f"papers since {start_year}")
                
        return suggestions[:8]
    
    def _parse_multiple_authors(self, author_string: str) -> list:
        """Parse string yang mungkin mengandung multiple authors"""
        if not author_string:
            return []
        
        # ✅ SPLIT by common separators
        separators = [' dan ', ' and ', ' & ', ', ', ';']
        
        authors = [author_string]  # Start dengan full string
        
        for sep in separators:
            new_authors = []
            for author in authors:
                if sep in author:
                    new_authors.extend([a.strip() for a in author.split(sep) if a.strip()])
                else:
                    new_authors.append(author)
            authors = new_authors
        
        # ✅ CLEAN and validate each author
        cleaned_authors = []
        for author in authors:
            author = author.strip()
            # Remove common prefixes that might be attached
            author = re.sub(r'^(?:dr\.?\s*|prof\.?\s*)', '', author, flags=re.IGNORECASE).strip()
            
            if author and len(author) > 3:
                cleaned_authors.append(author)
        
        logger.debug(f"Parsed authors from '{author_string}': {cleaned_authors}")
        
        return cleaned_authors
    
    def _is_valid_author_name(self, name: str) -> bool:
        """Validate if name looks like real author name"""
        # Check basic format
        words = name.strip().split()
        if len(words) < 2:
            return False

        # Check for invalid patterns
        invalid_patterns = [
            r"\b(?:jurnal|paper|research|artikel|ai|machine|learning|deep|neural)\b",
            r"\b(?:tahun|year|bidang|field|tentang|about)\b",
            r"^\d+",  # Starts with number
        ]

        for pattern in invalid_patterns:
            if re.search(pattern, name.lower()):
                return False

        # Check if all words start with capital (author name pattern)
        return all(
            word[0].isupper() and word[1:].islower() for word in words if len(word) > 1
        )

    def _extract_general_keywords(self, query: str) -> list:
        """Language-aware keyword extraction - preserves original language context"""
        
        # ✅ EXTRACT original keywords first (preserve user's language)
        original_keywords = []
        
        # Remove stopwords but keep meaningful terms
        stopwords = {
            'saya', 'sedang', 'mencari', 'jurnal', 'tentang', 'di', 'bidang', 'antara', 
            'tahun', 'sampai', 'dari', 'untuk', 'dengan', 'pada', 'yang', 'dan', 'atau'
        }
        
        # Extract meaningful words from original query
        words = re.findall(r'\b[a-zA-Z]+\b', query.lower())
        for word in words:
            if word not in stopwords and len(word) >= 2:
                if not re.match(r'^\d{4}$', word):  # Skip years
                    original_keywords.append(word)
        
        # ✅ SMART EXPANSION based on detected language
        query_language = self._detect_language(query)
        expanded_keywords = set()
        
        # Add original keywords first
        expanded_keywords.update(original_keywords)
        
        # ✅ LANGUAGE-SPECIFIC EXPANSION
        if query_language == "id":  # Indonesian
            id_expansions = {
                'ai': ['ai', 'kecerdasan buatan', 'artificial intelligence'],
                'kecerdasan': ['kecerdasan buatan', 'ai', 'artificial intelligence'],
                'buatan': ['kecerdasan buatan', 'ai', 'artificial intelligence'],
                'kedokteran': ['kedokteran', 'medis', 'kesehatan', 'medical'],
                'kesehatan': ['kesehatan', 'kedokteran', 'medis', 'health'],
                'pendidikan': ['pendidikan', 'edukasi', 'pembelajaran', 'education'],
                'teknologi': ['teknologi', 'teknik', 'technology'],
                'penelitian': ['penelitian', 'riset', 'studi', 'research'],
                'analisis': ['analisis', 'kajian', 'evaluasi', 'analysis'],
                'sistem': ['sistem', 'system'],
                'data': ['data', 'informasi', 'database'],
                'pembelajaran': ['pembelajaran', 'machine learning', 'belajar mesin'],
                'jaringan': ['jaringan', 'network', 'neural network'],
                'komputer': ['komputer', 'computer', 'komputasi'],
            }
            
            # Expand Indonesian terms
            for word in original_keywords:
                if word in id_expansions:
                    # Add Indonesian terms first, then English equivalents
                    expanded_keywords.update(id_expansions[word])
        
        else:  # English
            en_expansions = {
                'ai': ['ai', 'artificial intelligence', 'machine learning'],
                'artificial': ['artificial intelligence', 'ai', 'machine learning'],
                'intelligence': ['artificial intelligence', 'ai', 'machine learning'],
                'machine': ['machine learning', 'artificial intelligence', 'ai'],
                'learning': ['machine learning', 'artificial intelligence', 'deep learning'],
                'deep': ['deep learning', 'neural networks', 'ai'],
                'neural': ['neural networks', 'deep learning', 'artificial intelligence'],
                'medical': ['medical', 'healthcare', 'clinical', 'medicine'],
                'healthcare': ['healthcare', 'medical', 'clinical', 'health'],
                'education': ['education', 'educational', 'learning'],
                'technology': ['technology', 'tech', 'technological'],
                'research': ['research', 'study', 'investigation'],
                'analysis': ['analysis', 'evaluation', 'assessment'],
                'system': ['system', 'framework'],
                'data': ['data', 'information', 'database'],
                'computer': ['computer', 'computing', 'computational'],
            }
            
            # Expand English terms
            for word in original_keywords:
                if word in en_expansions:
                    expanded_keywords.update(en_expansions[word])
        
        # ✅ EXTRACT compound terms
        compound_patterns = [
            r'\b(artificial intelligence|machine learning|deep learning|neural network)\b',
            r'\b(computer vision|natural language processing|data mining)\b',
            r'\b(kecerdasan buatan|pembelajaran mesin|jaringan saraf)\b',
            r'\b(pengolahan bahasa|analisis data|sistem informasi)\b',
        ]
        
        for pattern in compound_patterns:
            matches = re.findall(pattern, query.lower())
            for match in matches:
                expanded_keywords.add(match)
        
        # ✅ PRIORITIZE keywords based on language context
        prioritized_keywords = []
        
        # Convert to list and remove duplicates
        final_keywords = list(expanded_keywords)
        
        # ✅ SORT by importance and language preference
        def keyword_priority(keyword):
            score = 0
            
            # Higher priority for original query words
            if keyword in original_keywords:
                score += 100
            
            # Technology terms priority
            if any(tech in keyword.lower() for tech in ['ai', 'artificial', 'machine', 'deep', 'kecerdasan']):
                score += 50
            
            # Domain terms priority  
            if any(domain in keyword.lower() for domain in ['medical', 'kedokteran', 'kesehatan', 'health']):
                score += 40
            
            # Language preference (Indonesian query prefers Indonesian terms first)
            if query_language == "id":
                if any(id_term in keyword.lower() for id_term in ['kedokteran', 'kesehatan', 'kecerdasan', 'pembelajaran']):
                    score += 30
            else:
                if any(en_term in keyword.lower() for en_term in ['medical', 'artificial', 'machine', 'research']):
                    score += 30
            
            return score
        
        # Sort by priority
        final_keywords.sort(key=keyword_priority, reverse=True)
        
        # ✅ LIMIT to optimal count (prioritize diversity)
        result = []
        seen_roots = set()
        
        for keyword in final_keywords:
            # Avoid too similar keywords
            keyword_root = keyword.split()[0] if ' ' in keyword else keyword
            if keyword_root not in seen_roots:
                seen_roots.add(keyword_root)
                result.append(keyword)
            
            if len(result) >= 6:  # Optimal keyword count
                break
        
        logger.info(f"📝 Language-aware keyword extraction from '{query}': {result}")
        logger.info(f"🌐 Query language: {query_language}")
        
        return result

    def _extract_year_range(self, query: str) -> dict:
        """Extract year range from query"""
        # Year range pattern
        year_range_match = re.search(
            r"(?:antara|between)\s+(?:tahun\s+)?(\d{4})\s+(?:sampai|hingga|to|until|dan|and|-)\s+(\d{4})",
            query,
            re.IGNORECASE,
        )
        if year_range_match:
            return {
                "start": int(year_range_match.group(1)),
                "end": int(year_range_match.group(2)),
            }

        # Single year
        single_year_match = re.search(r"(?:tahun|year)\s+(\d{4})", query, re.IGNORECASE)
        if single_year_match:
            year = int(single_year_match.group(1))
            return {"start": year, "end": year}

        return {}

    async def _search_author_only(self, analysis: dict) -> dict:
        """Enhanced search strategy 1: Author only dengan support multiple authors"""
        primary_author = analysis["author_name"]
        additional_authors = analysis.get("additional_authors", [])
        year_range = analysis.get("year_range", {})
        
        all_authors = [primary_author] + additional_authors
        
        logger.info(f"Executing author-only search for: Primary='{primary_author}', Additional={additional_authors}")
        
        all_papers = []
        
        # ✅ SEARCH untuk primary author (highest priority)
        try:
            primary_papers = await self._search_semantic_scholar_author(
                primary_author, [], year_range
            )
            all_papers.extend(primary_papers)
            logger.info(f"Found {len(primary_papers)} papers for primary author: {primary_author}")
        except Exception as e:
            logger.error(f"Error searching primary author {primary_author}: {e}")
        
        # ✅ SEARCH untuk additional authors
        for author in additional_authors:
            try:
                author_papers = await self._search_semantic_scholar_author(
                    author, [], year_range
                )
                # Tag papers dengan author info untuk later processing
                for paper in author_papers:
                    paper['matched_author'] = author
                    paper['is_additional_author'] = True
                
                all_papers.extend(author_papers)
                logger.info(f"Found {len(author_papers)} papers for additional author: {author}")
            except Exception as e:
                logger.error(f"Error searching additional author {author}: {e}")
        
        # ✅ SEARCH other sources dengan combined author strategy
        combined_authors_query = " OR ".join([f'"{author}"' for author in all_authors])
        
        try:
            arxiv_papers = await self.paper_scraper.scrape_arxiv(combined_authors_query)
            all_papers.extend(arxiv_papers)
            logger.info(f"Found {len(arxiv_papers)} papers from ArXiv")
        except Exception as e:
            logger.error(f"ArXiv error: {e}")
        
        try:
            scholar_papers = await self.paper_scraper.scrape_google_scholar(combined_authors_query, max_results=20)
            all_papers.extend(scholar_papers)
            logger.info(f"Found {len(scholar_papers)} papers from Google Scholar")
        except Exception as e:
            logger.error(f"Google Scholar error: {e}")
        
        # ✅ ENHANCED DEDUPLICATION dan RANKING untuk multiple authors
        unique_papers = self._deduplicate_and_rank_by_multiple_authors(all_papers, all_authors)
        
        logger.info(f"📊 Total unique papers found: {len(unique_papers)}")
        
        return {
            "papers": unique_papers[:50],
            "suggested_queries": [],  # No suggestions untuk author-only search
        }
    
    def _deduplicate_and_rank_by_multiple_authors(self, papers: list, all_authors: list) -> list:
        """Enhanced deduplication dan ranking untuk multiple authors"""
        if not papers or not all_authors:
            return []
        
        primary_author = all_authors[0]
        additional_authors = all_authors[1:] if len(all_authors) > 1 else []
        
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:50]
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                
                # ✅ CALCULATE relevance untuk each author
                authors_string = paper.get('authors', '')
                
                # Primary author relevance (highest weight)
                primary_relevance = self._calculate_author_relevance(authors_string, primary_author)
                
                # Additional authors relevance
                additional_relevance = 0.0
                if additional_authors:
                    additional_scores = []
                    for author in additional_authors:
                        score = self._calculate_author_relevance(authors_string, author)
                        additional_scores.append(score)
                    
                    if additional_scores:
                        additional_relevance = max(additional_scores)
                
                # ✅ COMBINED SCORING
                # Primary author: 70% weight, Additional authors: 30% weight
                combined_relevance = (primary_relevance * 0.7) + (additional_relevance * 0.3)
                
                # ✅ COLLABORATION BONUS - if paper contains multiple target authors
                collaboration_bonus = 0.0
                matched_authors_count = 0
                
                for author in all_authors:
                    if self._verify_author_match(authors_string, author):
                        matched_authors_count += 1
                
                if matched_authors_count > 1:
                    collaboration_bonus = 0.1 * (matched_authors_count - 1)  # 0.1 per additional match
                
                final_relevance = min(1.0, combined_relevance + collaboration_bonus)
                
                paper['author_relevance'] = final_relevance
                paper['matched_authors_count'] = matched_authors_count
                paper['primary_author_match'] = primary_relevance > 0.5
                
                unique_papers.append(paper)
        
        # ✅ ENHANCED SORTING
        def sort_key(paper):
            author_rel = paper.get('author_relevance', 0.0)
            matched_count = paper.get('matched_authors_count', 0)
            primary_match = paper.get('primary_author_match', False)
            citations = int(paper.get('citation_count', 0)) if paper.get('citation_count') else 0
            year = int(paper.get('year', 0)) if paper.get('year') else 0
            
            # Normalize scores
            citation_score = min(1.0, citations / 100)
            year_score = max(0.0, (year - 2010) / 14) if year > 2010 else 0.0
            
            # Primary author match gets significant boost
            primary_boost = 0.2 if primary_match else 0.0
            
            # Multiple author match bonus
            collaboration_boost = 0.1 if matched_count > 1 else 0.0
            
            # Final score: 50% author relevance + 15% primary boost + 10% collaboration + 15% citations + 10% year
            return (author_rel * 0.5) + primary_boost + collaboration_boost + (citation_score * 0.15) + (year_score * 0.1)
        
        unique_papers.sort(key=sort_key, reverse=True)
        
        logger.info(f"📊 Multiple authors deduplication results: {len(unique_papers)} unique papers")
        if unique_papers:
            top_paper = unique_papers[0]
            logger.info(f"🏆 Top paper: '{top_paper.get('title', '')[:80]}'")
            logger.info(f"    Author relevance: {top_paper.get('author_relevance', 0):.3f}")
            logger.info(f"    Matched authors: {top_paper.get('matched_authors_count', 0)}")
            logger.info(f"    Primary author match: {top_paper.get('primary_author_match', False)}")
        
        return unique_papers

    async def _search_author_with_topic(self, analysis: dict) -> dict:
        """Search strategy 2: Author + Topic - "Bayu Sutawijaya tentang TCP" """
        author_name = analysis["author_name"]
        topic_keywords = analysis["topic_keywords"]
        year_range = analysis.get("year_range", {})

        logger.info(
            f"Executing author+topic search for: {author_name} + {topic_keywords}"
        )

        all_papers = []

        # ✅ SEARCH dengan author + topic
        try:
            semantic_papers = await self._search_semantic_scholar_author(
                author_name, topic_keywords, year_range
            )
            all_papers.extend(semantic_papers)
        except Exception as e:
            logger.error(f"Semantic Scholar error: {e}")

        try:
            arxiv_papers = await self._search_arxiv_author(
                author_name, topic_keywords, year_range
            )
            all_papers.extend(arxiv_papers)
        except Exception as e:
            logger.error(f"ArXiv error: {e}")

        try:
            scholar_papers = await self._search_google_scholar_author(
                author_name, topic_keywords, year_range
            )
            all_papers.extend(scholar_papers)
        except Exception as e:
            logger.error(f"Google Scholar error: {e}")

        # ✅ DEDUPLICATE dan SMART RANKING
        author_papers = self._deduplicate_and_rank_by_author_and_topic(
            all_papers, author_name, topic_keywords
        )

        # ✅ GENERATE TOPIC-BASED SUGGESTIONS (termasuk dari author lain)
        suggested_queries = await self._generate_topic_suggestions_with_authors(
            topic_keywords, author_name
        )

        return {"papers": author_papers[:50], "suggested_queries": suggested_queries}

    async def _search_general_topic(self, analysis: dict) -> dict:
        """Enhanced search strategy 3: General topic dengan language-based search"""
        topic_keywords = analysis["topic_keywords"]
        year_range = analysis.get("year_range", {})
        original_query = analysis.get("original_query", "")
        
        # ✅ DETECT LANGUAGE dari original query
        query_language = self._detect_language(original_query)
        logger.info(f"🌐 Detected language: {query_language} for query: '{original_query}'")
        
        logger.info(f"🔍 Executing language-based general topic search for: {topic_keywords}")
        
        all_papers = []
        
        # ✅ LANGUAGE-BASED SEARCH STRATEGIES
        if query_language == "id":  # Indonesian
            logger.info("🇮🇩 Executing Indonesian-focused search strategy")
            all_papers = await self._search_indonesian_focused(topic_keywords, year_range, original_query)
        else:  # English
            logger.info("🇺🇸 Executing English/International-focused search strategy")
            all_papers = await self._search_international_focused(topic_keywords, year_range, original_query)
        
        logger.info(f"📊 Total papers collected: {len(all_papers)}")
        
        # ✅ DEDUPLICATION dan RANKING berdasarkan language preference
        unique_papers = self._deduplicate_and_rank_by_language(all_papers, topic_keywords, query_language)
        
        # ✅ GENERATE SUGGESTIONS berdasarkan language
        suggested_queries = await self._generate_language_based_suggestions(
            topic_keywords, unique_papers, query_language, original_query
        )
        
        logger.info(f"📋 Final results: {len(unique_papers)} unique papers, {len(suggested_queries)} suggestions")
        
        return {"papers": unique_papers[:50], "suggested_queries": suggested_queries}
    
    def _detect_language(self, query: str) -> str:
        """Enhanced language detection - more accurate with stronger Indonesian indicators"""
        query_lower = query.lower()
        
        # ✅ VERY STRONG INDONESIAN INDICATORS
        very_strong_id_indicators = [
            'saya sedang mencari', 'saya mencari', 'mencari jurnal', 'jurnal tentang',
            'di bidang', 'antara tahun', 'sampai tahun', 'penelitian tentang',
            'kajian tentang', 'analisis tentang', 'studi tentang'
        ]
        
        # ✅ STRONG INDONESIAN INDICATORS
        strong_id_indicators = [
            'saya', 'sedang', 'mencari', 'jurnal', 'tentang', 'di', 'bidang',
            'antara', 'tahun', 'sampai', 'dari', 'untuk', 'dengan', 'pada',
            'yang', 'dan', 'atau', 'adalah', 'akan', 'dapat', 'sudah',
            'penelitian', 'karya', 'publikasi', 'artikel', 'ilmiah',
            'kedokteran', 'kesehatan', 'pendidikan', 'teknologi',
            'kecerdasan', 'buatan', 'pembelajaran', 'mesin', 'jaringan',
            'analisis', 'kajian', 'evaluasi', 'implementasi', 'pengembangan',
            'perancangan', 'pembangunan', 'penerapan', 'penggunaan'
        ]
        
        # ✅ STRONG ENGLISH INDICATORS
        strong_en_indicators = [
            'research', 'study', 'analysis', 'paper', 'journal', 'article',
            'investigation', 'survey', 'review', 'systematic', 'meta',
            'artificial', 'intelligence', 'machine', 'learning', 'deep',
            'neural', 'network', 'algorithm', 'computer', 'vision',
            'medical', 'healthcare', 'clinical', 'education', 'engineering',
            'recent', 'latest', 'state of the art', 'advances in'
        ]
        
        # ✅ COUNT indicators with different weights
        very_strong_id_count = sum(1 for phrase in very_strong_id_indicators if phrase in query_lower)
        strong_id_count = sum(1 for word in strong_id_indicators if f' {word} ' in f' {query_lower} ' or query_lower.startswith(f'{word} ') or query_lower.endswith(f' {word}'))
        en_strong_count = sum(1 for word in strong_en_indicators if f' {word} ' in f' {query_lower} ' or query_lower.startswith(f'{word} ') or query_lower.endswith(f' {word}'))
        
        # ✅ DECISION logic dengan prioritas sangat tinggi untuk Indonesian
        if very_strong_id_count >= 1:  # Sangat kuat: "saya sedang mencari jurnal"
            logger.info(f"🇮🇩 VERY STRONG Indonesian detected: {very_strong_id_count} very strong indicators")
            return "id"
        elif strong_id_count >= 3 or (strong_id_count >= 2 and en_strong_count == 0):
            logger.info(f"🇮🇩 STRONG Indonesian detected: {strong_id_count} strong indicators vs {en_strong_count} English")
            return "id"
        elif en_strong_count >= 2 and en_strong_count > strong_id_count:
            logger.info(f"🇺🇸 English detected: {en_strong_count} English indicators vs {strong_id_count} Indonesian")
            return "en"
        elif strong_id_count > 0 and en_strong_count == 0:
            logger.info(f"🇮🇩 Default Indonesian: {strong_id_count} Indonesian indicators, no English")
            return "id"
        else:
            # ✅ FALLBACK: check for common patterns
            if any(pattern in query_lower for pattern in ['jurnal', 'penelitian', 'tentang', 'di bidang']):
                logger.info("🇮🇩 Fallback Indonesian: common Indonesian patterns found")
                return "id"
            elif any(pattern in query_lower for pattern in ['research', 'paper', 'study', 'using']):
                logger.info("🇺🇸 Fallback English: common English patterns found")
                return "en"
            else:
                logger.info("🇮🇩 Default to Indonesian")
                return "id"  # Default to Indonesian for this system
        
    async def _search_indonesian_focused(self, topic_keywords: list, year_range: dict, original_query: str) -> list:
        """ENHANCED Indonesian-focused search - STRICT priority untuk jurnal lokal Indonesia"""
        all_papers = []
        
        logger.info(f"🇮🇩 EXECUTING INDONESIAN-FOCUSED SEARCH")
        logger.info(f"🔍 Keywords: {topic_keywords}")
        logger.info(f"📅 Year range: {year_range}")
        
        # ✅ INDONESIAN QUERY CONSTRUCTION - prioritas untuk konteks Indonesia
        
        # Separate Indonesian, English, and mixed terms
        indonesian_terms = []
        english_terms = []
        mixed_terms = []
        indonesian_technical_terms = []
        
        for keyword in topic_keywords:
            keyword_lower = keyword.lower()
            
            # ✅ INDONESIAN TECHNICAL TERMS
            if keyword_lower in ['ai', 'kecerdasan buatan', 'artificial intelligence']:
                indonesian_technical_terms.extend(['AI', 'kecerdasan buatan', 'artificial intelligence'])
            elif keyword_lower in ['machine learning', 'pembelajaran mesin', 'ml']:
                indonesian_technical_terms.extend(['machine learning', 'pembelajaran mesin', 'ML'])
            elif keyword_lower in ['deep learning', 'pembelajaran mendalam']:
                indonesian_technical_terms.extend(['deep learning', 'pembelajaran mendalam'])
            
            # Check if it's an Indonesian domain term
            elif any(id_indicator in keyword_lower for id_indicator in [
                'kedokteran', 'kesehatan', 'medis', 'klinik', 'rumah sakit',
                'pendidikan', 'pembelajaran', 'pendidikan', 'sekolah', 'universitas',
                'pertanian', 'perikanan', 'kehutanan', 'perkebunan',
                'ekonomi', 'keuangan', 'bisnis', 'manajemen',
                'teknologi', 'teknik', 'informatika', 'komputer',
                'penelitian', 'analisis', 'kajian', 'evaluasi'
            ]):
                indonesian_terms.append(keyword)
            
            # Check if it's an English technical term
            elif any(en_indicator in keyword_lower for en_indicator in [
                'artificial', 'intelligence', 'machine', 'learning', 'deep',
                'neural', 'network', 'algorithm', 'computer', 'data',
                'medical', 'healthcare', 'clinical', 'diagnosis', 'treatment',
                'education', 'educational', 'teaching', 'training',
                'agriculture', 'farming', 'crop', 'soil',
                'economic', 'financial', 'business', 'management',
                'technology', 'engineering', 'software', 'system'
            ]):
                english_terms.append(keyword)
            
            # Universal terms
            elif keyword_lower in ['ai', 'ml', 'dl', 'data', 'system', 'iot', 'blockchain']:
                mixed_terms.append(keyword)
            else:
                # Default ke Indonesian terms untuk query Indonesia
                indonesian_terms.append(keyword)
        
        # ✅ INDONESIAN SEARCH STRATEGIES - prioritas tinggi untuk jurnal Indonesia
        search_queries = []
        
        # Strategy 1: PURE INDONESIAN query dengan Indonesia context
        indonesian_query_parts = []
        if indonesian_technical_terms:
            indonesian_query_parts.extend(indonesian_technical_terms[:2])
        if indonesian_terms:
            indonesian_query_parts.extend(indonesian_terms[:2])
        if mixed_terms:
            indonesian_query_parts.extend(mixed_terms[:1])
        
        if indonesian_query_parts:
            # Add explicit Indonesian context
            indonesian_query = f"{' '.join(indonesian_query_parts)} Indonesia"
            search_queries.append(indonesian_query)
            
            # Also search without "Indonesia" for broader Indonesian content
            search_queries.append(' '.join(indonesian_query_parts[:3]))
        
        # Strategy 2: Indonesian university/institution specific
        if indonesian_query_parts:
            indonesian_institution_query = f"{' '.join(indonesian_query_parts[:2])} universitas Indonesia"
            search_queries.append(indonesian_institution_query)
        
        # Strategy 3: Indonesian domain-specific dengan bahasa Indonesia
        if indonesian_terms and (mixed_terms or indonesian_technical_terms):
            domain_query = f"{' '.join((mixed_terms + indonesian_technical_terms)[:2])} {' '.join(indonesian_terms[:2])}"
            search_queries.append(domain_query)
        
        # ✅ EXECUTE SEARCHES dengan STRICT Indonesian priority
        for i, search_query in enumerate(search_queries[:4]):  # Increased to 4 strategies
            logger.info(f"🇮🇩 Indonesian search strategy {i+1}: '{search_query}'")
            
            # ✅ GOOGLE SCHOLAR FIRST - BEST for Indonesian content
            try:
                # Add Indonesian-specific search modifiers
                enhanced_query = search_query
                if 'indonesia' not in search_query.lower():
                    enhanced_query = f"{search_query} site:ac.id OR Indonesia OR universitas"
                
                scholar_papers = await self.paper_scraper.scrape_google_scholar(enhanced_query, max_results=20)
                indonesian_papers = self._filter_indonesian_papers(scholar_papers)
                all_papers.extend(indonesian_papers)
                
                logger.info(f"   📚 Google Scholar: {len(scholar_papers)} total, {len(indonesian_papers)} Indonesian papers")
            except Exception as e:
                logger.error(f"Google Scholar error for query '{search_query}': {e}")
            
            # ✅ SEMANTIC SCHOLAR - dengan Indonesian filtering
            try:
                semantic_papers = await self.paper_scraper.scrape_semantic_scholar(search_query)
                
                # Filter untuk Indonesian authors/institutions
                indonesian_semantic = self._filter_indonesian_papers(semantic_papers)
                all_papers.extend(indonesian_semantic)
                
                logger.info(f"   📚 Semantic Scholar: {len(semantic_papers)} total, {len(indonesian_semantic)} Indonesian papers")
            except Exception as e:
                logger.error(f"Semantic Scholar error for query '{search_query}': {e}")
            
            # ✅ SKIP ArXiv untuk Indonesian search (mostly international)
            # ArXiv umumnya berisi paper internasional, skip untuk Indonesian search
            
            # Break early if sufficient LOCAL results
            indonesian_count = len([p for p in all_papers if self._is_indonesian_paper(p)])
            if indonesian_count >= 30:
                logger.info(f"✅ Sufficient Indonesian results obtained ({indonesian_count} Indonesian papers)")
                break
        
        # ✅ FINAL FILTERING - prioritas absolut untuk jurnal Indonesia
        filtered_papers = []
        indonesian_papers = []
        other_papers = []
        
        for paper in all_papers:
            if self._is_indonesian_paper(paper):
                indonesian_papers.append(paper)
            else:
                other_papers.append(paper)
        
        # ✅ PRIORITIZE Indonesian papers, add minimal international papers only if needed
        filtered_papers.extend(indonesian_papers)
        
        # Only add international papers if we have very few Indonesian papers
        if len(indonesian_papers) < 10:
            logger.info(f"⚠️ Only {len(indonesian_papers)} Indonesian papers found, adding some international papers")
            filtered_papers.extend(other_papers[:10])  # Very limited international papers
        
        logger.info(f"🇮🇩 Final Indonesian-focused results: {len(filtered_papers)} papers ({len(indonesian_papers)} Indonesian, {len(other_papers[:10]) if len(indonesian_papers) < 10 else 0} international)")
        
        return filtered_papers
    
    def _filter_indonesian_papers(self, papers: list) -> list:
        """Filter papers untuk prioritas Indonesian content"""
        indonesian_papers = []
        
        for paper in papers:
            if self._is_indonesian_paper(paper):
                # Add Indonesian scoring
                paper['indonesian_score'] = self._calculate_indonesian_score(paper)
                indonesian_papers.append(paper)
        
        # Sort by Indonesian relevance
        indonesian_papers.sort(key=lambda x: x.get('indonesian_score', 0), reverse=True)
        
        return indonesian_papers
    
    def _is_indonesian_paper(self, paper: dict) -> bool:
        """Check if paper is from Indonesian source/authors"""
        if not paper:
            return False
            
        # ✅ SAFE extraction with None checks
        title = (paper.get('title') or '').lower()
        authors = (paper.get('authors') or '').lower()
        source = (paper.get('source') or '').lower()
        summary = (paper.get('summary') or '').lower()
        
        # ✅ STRONG Indonesian indicators
        strong_indonesian_indicators = [
            # Institutions
            'universitas', 'institut', 'politeknik', 'sekolah tinggi',
            'itb', 'ui', 'ugm', 'its', 'unpad', 'undip', 'unair', 'ub',
            'binus', 'telkom university', 'gunadarma', 'trisakti',
            
            # Locations
            'indonesia', 'jakarta', 'bandung', 'surabaya', 'yogyakarta',
            'medan', 'makassar', 'palembang', 'semarang', 'malang',
            'bogor', 'depok', 'tangerang', 'bekasi',
            
            # Domains
            '.ac.id', '.go.id', '.or.id',
            
            # Indonesian academic terms
            'jurnal', 'penelitian', 'kajian', 'analisis', 'studi',
            'pengaruh', 'penerapan', 'pengembangan', 'implementasi',
            'evaluasi', 'perancangan', 'pembangunan',
            
            # Indonesian technical domains
            'kedokteran indonesia', 'kesehatan indonesia', 'teknologi indonesia',
            'pendidikan indonesia', 'pertanian indonesia'
        ]
        
        # Check dalam title, authors, source, summary
        text_combined = f"{title} {authors} {source} {summary}"
        
        indonesian_score = sum(1 for indicator in strong_indonesian_indicators if indicator in text_combined)
        
        # ✅ THRESHOLD untuk Indonesian classification
        return indonesian_score >= 1  # At least 1 strong indicator
    
    def _calculate_indonesian_score(self, paper: dict) -> float:
        """Calculate Indonesian relevance score"""
        if not paper:
            return 0.0
            
        # ✅ SAFE extraction with None checks
        title = (paper.get('title') or '').lower()
        authors = (paper.get('authors') or '').lower()
        source = (paper.get('source') or '').lower()
        summary = (paper.get('summary') or '').lower()
        
        score = 0.0
        
        # ✅ INDONESIAN INSTITUTION SCORING
        indonesian_institutions = [
            'universitas indonesia', 'institut teknologi bandung', 'universitas gadjah mada',
            'institut teknologi sepuluh nopember', 'universitas padjadjaran', 'universitas diponegoro',
            'universitas airlangga', 'universitas brawijaya', 'binus university',
            'telkom university', 'universitas gunadarma', 'universitas trisakti'
        ]
        
        for institution in indonesian_institutions:
            if institution in authors or institution in source:
                score += 3.0
            elif institution.split()[-1] in authors:  # e.g., "indonesia", "bandung"
                score += 1.5
        
        # ✅ LOCATION SCORING
        indonesian_locations = ['indonesia', 'jakarta', 'bandung', 'surabaya', 'yogyakarta']
        for location in indonesian_locations:
            if location in authors:
                score += 2.0
            elif location in source:
                score += 1.5
            elif location in title:
                score += 1.0
        
        # ✅ DOMAIN SCORING
        if '.ac.id' in source or '.go.id' in source:
            score += 2.5
        
        # ✅ LANGUAGE SCORING
        indonesian_terms = ['jurnal', 'penelitian', 'kajian', 'analisis', 'pengaruh', 'penerapan']
        for term in indonesian_terms:
            if term in title:
                score += 1.0
            elif term in summary:
                score += 0.5
        
        return score
    
    async def _search_international_focused(self, topic_keywords: list, year_range: dict, original_query: str) -> list:
        """ENHANCED International search - STRICT priority untuk jurnal internasional high-impact"""
        all_papers = []
        
        logger.info(f"🇺🇸 EXECUTING INTERNATIONAL-FOCUSED SEARCH")
        logger.info(f"🔍 Keywords: {topic_keywords}")
        logger.info(f"📅 Year range: {year_range}")
        
        # ✅ INTERNATIONAL QUERY CONSTRUCTION - fokus pada high-impact journals
        
        # Clean and enhance keywords untuk international search
        english_keywords = []
        for keyword in topic_keywords:
            keyword_lower = keyword.lower()
            
            # Convert Indonesian terms to English equivalents
            if keyword_lower in ['ai', 'kecerdasan buatan']:
                english_keywords.extend(['artificial intelligence', 'AI', 'machine learning'])
            elif keyword_lower in ['pembelajaran mesin', 'ml']:
                english_keywords.extend(['machine learning', 'artificial intelligence'])
            elif keyword_lower in ['pembelajaran mendalam', 'deep learning']:
                english_keywords.extend(['deep learning', 'neural networks'])
            elif keyword_lower in ['kedokteran', 'medis']:
                english_keywords.extend(['medical', 'healthcare', 'clinical'])
            elif keyword_lower in ['kesehatan']:
                english_keywords.extend(['healthcare', 'health', 'medical'])
            elif keyword_lower in ['pendidikan']:
                english_keywords.extend(['education', 'educational', 'learning'])
            elif keyword_lower in ['teknologi']:
                english_keywords.extend(['technology', 'technological'])
            elif keyword_lower in ['penelitian']:
                english_keywords.extend(['research', 'study', 'investigation'])
            elif keyword_lower in ['analisis']:
                english_keywords.extend(['analysis', 'analytical'])
            else:
                english_keywords.append(keyword)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_keywords = []
        for kw in english_keywords:
            if kw.lower() not in seen:
                seen.add(kw.lower())
                unique_keywords.append(kw)
        
        # ✅ INTERNATIONAL SEARCH STRATEGIES - high-impact focus
        search_queries = []
        
        # Strategy 1: Core academic terms untuk high-impact journals
        if unique_keywords:
            primary_query = " ".join(unique_keywords[:4])
            search_queries.append(primary_query)
        
        # Strategy 2: High-impact journal targeting
        if unique_keywords:
            high_impact_query = f"{' '.join(unique_keywords[:3])} ieee OR nature OR science OR springer"
            search_queries.append(high_impact_query)
        
        # Strategy 3: Research methodology focus
        tech_terms = [kw for kw in unique_keywords if any(tech in kw.lower() for tech in [
            'artificial', 'machine', 'deep', 'neural', 'computer', 'algorithm', 'data'
        ])]
        domain_terms = [kw for kw in unique_keywords if any(domain in kw.lower() for domain in [
            'medical', 'healthcare', 'education', 'engineering', 'science', 'research'
        ])]
        
        if tech_terms and domain_terms:
            methodology_query = f"{tech_terms[0]} {domain_terms[0]} research"
            search_queries.append(methodology_query)
        
        # Strategy 4: Recent research focus untuk cutting-edge papers
        if unique_keywords:
            recent_query = f"recent {unique_keywords[0]} research 2023 2024"
            search_queries.append(recent_query)
        
        # ✅ EXECUTE SEARCHES dengan international journal priority
        for i, search_query in enumerate(search_queries[:4]):
            logger.info(f"🇺🇸 International search strategy {i+1}: '{search_query}'")
            
            # ✅ SEMANTIC SCHOLAR FIRST - best untuk high-impact international journals
            try:
                semantic_papers = await self.paper_scraper.scrape_semantic_scholar(search_query)
                
                # Filter untuk international high-impact papers
                international_papers = self._filter_international_papers(semantic_papers)
                all_papers.extend(international_papers)
                
                logger.info(f"   📚 Semantic Scholar: {len(semantic_papers)} total, {len(international_papers)} high-impact papers")
            except Exception as e:
                logger.error(f"Semantic Scholar error for query '{search_query}': {e}")
            
            # ✅ ARXIV - tinggi prioritas untuk cutting-edge research
            try:
                arxiv_papers = await self.paper_scraper.scrape_arxiv(search_query)
                
                # ArXiv papers generally international, minimal filtering needed
                international_arxiv = self._filter_international_papers(arxiv_papers)
                all_papers.extend(international_arxiv)
                
                logger.info(f"   📚 ArXiv: {len(arxiv_papers)} total, {len(international_arxiv)} international papers")
            except Exception as e:
                logger.error(f"ArXiv error for query '{search_query}': {e}")
            
            # ✅ GOOGLE SCHOLAR - dengan international filtering
            try:
                # Add international-specific search modifiers
                enhanced_query = f"{search_query} -site:ac.id -Indonesia"  # Exclude Indonesian sites
                
                scholar_papers = await self.paper_scraper.scrape_google_scholar(enhanced_query, max_results=20)
                international_scholar = self._filter_international_papers(scholar_papers)
                all_papers.extend(international_scholar)
                
                logger.info(f"   📚 Google Scholar: {len(scholar_papers)} total, {len(international_scholar)} international papers")
            except Exception as e:
                logger.error(f"Google Scholar error for query '{search_query}': {e}")
            
            # Break early if sufficient international results
            international_count = len([p for p in all_papers if self._is_international_paper(p)])
            if international_count >= 40:
                logger.info(f"✅ Sufficient international results obtained ({international_count} papers)")
                break
        
        # ✅ FINAL FILTERING - prioritas absolut untuk jurnal internasional
        filtered_papers = []
        international_papers = []
        local_papers = []
        
        for paper in all_papers:
            if self._is_international_paper(paper):
                international_papers.append(paper)
            else:
                local_papers.append(paper)
        
        # ✅ STRICT international priority
        filtered_papers.extend(international_papers)
        
        # Minimal local papers hanya jika sangat sedikit international papers
        if len(international_papers) < 15:
            logger.info(f"⚠️ Only {len(international_papers)} international papers found, adding minimal local papers")
            filtered_papers.extend(local_papers[:5])  # Very minimal local papers
        
        logger.info(f"🇺🇸 Final international-focused results: {len(filtered_papers)} papers ({len(international_papers)} international, {len(local_papers[:5]) if len(international_papers) < 15 else 0} local)")
        
        return filtered_papers
    
    def _filter_international_papers(self, papers: list) -> list:
        """Filter papers untuk prioritas international high-impact content"""
        international_papers = []
        
        for paper in papers:
            if self._is_international_paper(paper):
                # Add international scoring
                paper['international_score'] = self._calculate_international_score(paper)
                international_papers.append(paper)
        
        # Sort by international relevance
        international_papers.sort(key=lambda x: x.get('international_score', 0), reverse=True)
        
        return international_papers
    
    def _is_international_paper(self, paper: dict) -> bool:
        """Check if paper is from international high-impact source"""
        title = paper.get('title', '').lower()
        authors = paper.get('authors', '').lower()
        source = paper.get('source', '').lower()
        summary = paper.get('summary', '').lower()
        
        # ✅ HIGH-IMPACT international indicators
        high_impact_indicators = [
            # Top-tier journals/conferences
            'ieee', 'acm', 'springer', 'elsevier', 'nature', 'science', 'cell',
            'lancet', 'nejm', 'jama', 'plos', 'arxiv', 'neurips', 'icml',
            'aaai', 'ijcai', 'iccv', 'cvpr', 'nips', 'iclr', 'emnlp',
            
            # Quality indicators
            'impact factor', 'indexed', 'scopus', 'web of science', 'pubmed',
            'doi:', 'issn:', 'volume', 'issue',
            
            # International institutions
            'mit', 'stanford', 'harvard', 'cambridge', 'oxford', 'toronto',
            'berkeley', 'carnegie mellon', 'university college london',
            'eth zurich', 'max planck', 'google research', 'microsoft research',
            
            # International terms
            'university', 'college', 'institute', 'research center',
            'laboratory', 'international', 'global', 'worldwide'
        ]
        
        # ✅ EXCLUDE Indonesian indicators
        indonesian_exclusions = [
            'universitas', 'institut', '.ac.id', '.go.id', 'indonesia',
            'jakarta', 'bandung', 'surabaya', 'jurnal'
        ]
        
        text_combined = f"{title} {authors} {source} {summary}"
        
        international_score = sum(1 for indicator in high_impact_indicators if indicator in text_combined)
        indonesian_score = sum(1 for exclusion in indonesian_exclusions if exclusion in text_combined)
        
        # Must have international indicators AND minimal Indonesian indicators
        return international_score >= 1 and indonesian_score == 0
    
    def _calculate_international_score(self, paper: dict) -> float:
        """Calculate international high-impact relevance score"""
        title = paper.get('title', '').lower()
        authors = paper.get('authors', '').lower()
        source = paper.get('source', '').lower()
        summary = paper.get('summary', '').lower()
        citations = int(paper.get('citation_count', 0)) if paper.get('citation_count') else 0
        
        score = 0.0
        
        # ✅ TOP-TIER JOURNAL SCORING
        top_tier_journals = [
            'nature', 'science', 'cell', 'lancet', 'nejm', 'ieee transactions',
            'acm transactions', 'springer', 'neurips', 'icml', 'aaai'
        ]
        
        for journal in top_tier_journals:
            if journal in source:
                score += 5.0
            elif any(word in source for word in journal.split()):
                score += 2.0
        
        # ✅ HIGH-IMPACT INSTITUTION SCORING
        top_institutions = [
            'mit', 'stanford', 'harvard', 'cambridge', 'oxford', 'berkeley',
            'carnegie mellon', 'eth zurich', 'max planck', 'google research'
        ]
        
        for institution in top_institutions:
            if institution in authors:
                score += 3.0
        
        # ✅ CITATION SCORING
        if citations > 100:
            score += 2.0
        elif citations > 50:
            score += 1.5
        elif citations > 20:
            score += 1.0
        
        # ✅ RESEARCH QUALITY INDICATORS
        quality_indicators = ['systematic review', 'meta-analysis', 'randomized controlled', 'peer-reviewed']
        for indicator in quality_indicators:
            if indicator in title or indicator in summary:
                score += 1.5
        
        # ✅ RECENT RESEARCH BONUS
        year = int(paper.get('year', 0)) if paper.get('year') else 0
        if year >= 2022:
            score += 1.0
        elif year >= 2020:
            score += 0.5
        
        return score
    
    def _deduplicate_and_rank_by_language(self, papers: list, topic_keywords: list, language: str) -> list:
        """Enhanced ranking dengan STRICT language preference"""
        if not papers:
            return []
        
        # ✅ DEDUPLICATION
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:60]
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                
                # ✅ CALCULATE enhanced language relevance
                if language == "id":
                    paper['language_relevance'] = self._calculate_indonesian_relevance_enhanced(paper)
                else:
                    paper['language_relevance'] = self._calculate_international_relevance_enhanced(paper)
                
                paper['topic_relevance'] = self._calculate_topic_relevance_simple(paper, topic_keywords)
                unique_papers.append(paper)
        
        # ✅ STRICT LANGUAGE-BASED FILTERING
        if language == "id":
            # For Indonesian queries: PRIORITIZE Indonesian papers heavily
            indonesian_papers = [p for p in unique_papers if p.get('language_relevance', 0) >= 0.3]
            other_papers = [p for p in unique_papers if p.get('language_relevance', 0) < 0.3]
            
            # Sort Indonesian papers first
            indonesian_papers.sort(key=lambda p: (
                p.get('language_relevance', 0) * 0.6 +
                p.get('topic_relevance', 0) * 0.3 +
                min(1.0, int(p.get('citation_count', 0)) / 50) * 0.1
            ), reverse=True)
            
            # Sort other papers
            other_papers.sort(key=lambda p: (
                p.get('topic_relevance', 0) * 0.5 +
                min(1.0, int(p.get('citation_count', 0)) / 100) * 0.3 +
                max(0.0, (int(p.get('year', 0)) - 2010) / 14) * 0.2
            ), reverse=True)
            
            # Combine: Indonesian papers first, then minimal international papers
            final_papers = indonesian_papers + other_papers[:5]  # Very limited international papers
            
        else:
            # For English queries: PRIORITIZE international papers heavily
            international_papers = [p for p in unique_papers if p.get('language_relevance', 0) >= 0.3]
            local_papers = [p for p in unique_papers if p.get('language_relevance', 0) < 0.3]
            
            # Sort international papers first
            international_papers.sort(key=lambda p: (
                p.get('language_relevance', 0) * 0.5 +
                p.get('topic_relevance', 0) * 0.3 +
                min(1.0, int(p.get('citation_count', 0)) / 100) * 0.2
            ), reverse=True)
            
            # Sort local papers
            local_papers.sort(key=lambda p: (
                p.get('topic_relevance', 0) * 0.6 +
                min(1.0, int(p.get('citation_count', 0)) / 50) * 0.4
            ), reverse=True)
            
            # Combine: International papers first, then minimal local papers
            final_papers = international_papers + local_papers[:3]  # Very limited local papers
        
        logger.info(f"📊 Language-based ranking results: {len(final_papers)} unique papers")
        if final_papers:
            top_paper = final_papers[0]
            logger.info(f"🏆 Top paper: '{top_paper.get('title', '')[:80]}'")
            logger.info(f"    Language relevance: {top_paper.get('language_relevance', 0):.2f}")
            logger.info(f"    Topic relevance: {top_paper.get('topic_relevance', 0):.2f}")
            
            if language == "id":
                indonesian_count = len([p for p in final_papers if self._is_indonesian_paper(p)])
                logger.info(f"    Indonesian papers: {indonesian_count}/{len(final_papers)}")
            else:
                international_count = len([p for p in final_papers if self._is_international_paper(p)])
                logger.info(f"    International papers: {international_count}/{len(final_papers)}")
        
        return final_papers

    def _calculate_indonesian_relevance_enhanced(self, paper: dict) -> float:
        """Enhanced Indonesian relevance calculation"""
        if self._is_indonesian_paper(paper):
            base_score = self._calculate_indonesian_score(paper)
            return min(1.0, base_score / 5.0)  # Normalize to 0-1
        else:
            return 0.0  # Zero score for non-Indonesian papers

    def _calculate_international_relevance_enhanced(self, paper: dict) -> float:
        """Enhanced international relevance calculation"""
        if self._is_international_paper(paper):
            base_score = self._calculate_international_score(paper)
            return min(1.0, base_score / 8.0)  # Normalize to 0-1
        else:
            return 0.0  # Zero score for non-international papers
    
    async def _generate_language_based_suggestions(
        self, topic_keywords: list, papers: list, language: str, original_query: str
    ) -> list:
        """Enhanced suggestions berdasarkan detected language dengan konteks yang sesuai"""
        suggestions = []
        
        if not topic_keywords:
            return suggestions
        
        main_topic = topic_keywords[0] if topic_keywords else ""
        
        if language == "id":  # Indonesian suggestions dengan konteks Indonesia
            suggestions.extend([
                f"penelitian terbaru {main_topic} di Indonesia",
                f"jurnal Indonesia tentang {main_topic}",
                f"analisis {main_topic} dalam konteks Indonesia",
                f"studi {main_topic} universitas Indonesia",
                f"implementasi {main_topic} di Indonesia",
                f"pengembangan {main_topic} Indonesia",
                f"evaluasi {main_topic} dalam negeri",
                f"kajian {main_topic} lokal Indonesia"
            ])
            
            # Add domain-specific Indonesian suggestions
            if any(term in main_topic.lower() for term in ['ai', 'artificial', 'kecerdasan']):
                suggestions.extend([
                    "AI untuk kesehatan Indonesia",
                    "kecerdasan buatan dalam pendidikan Indonesia",
                    "implementasi AI di rumah sakit Indonesia"
                ])
            elif any(term in main_topic.lower() for term in ['medis', 'kedokteran', 'kesehatan']):
                suggestions.extend([
                    "telemedicine Indonesia",
                    "sistem kesehatan nasional",
                    "kedokteran tradisional Indonesia"
                ])
                
        else:  # English suggestions dengan konteks internasional
            suggestions.extend([
                f"recent international research in {main_topic}",
                f"{main_topic} systematic review",
                f"global advances in {main_topic}",
                f"{main_topic} state of the art international",
                f"latest international {main_topic} developments",
                f"{main_topic} applications worldwide",
                f"future of {main_topic} research",
                f"international {main_topic} survey"
            ])
            
            # Add high-impact journal suggestions
            if topic_keywords:
                suggestions.extend([
                    f"{main_topic} IEEE transactions",
                    f"{main_topic} Nature research",
                    f"{main_topic} Springer publications"
                ])
        
        return suggestions[:8]
    
    def _calculate_language_relevance(self, paper: dict, target_language: str) -> float:
        """Enhanced language relevance calculation"""
        title = paper.get('title', '').lower()
        abstract = paper.get('summary', '').lower()
        source = paper.get('source', '').lower()
        authors = paper.get('authors', '').lower()
        
        if target_language == "id":  # Indonesian preference
            indonesian_indicators = [
                # Strong Indonesian indicators
                'universitas', 'institut', 'politeknik', 'indonesia', 'jakarta', 
                'bandung', 'surabaya', 'yogyakarta', 'medan', 'makassar', 'bali',
                
                # Indonesian academic terms
                'jurnal', 'penelitian', 'analisis', 'pengaruh', 'penerapan',
                'pengembangan', 'evaluasi', 'studi', 'kajian', 'implementasi',
                'perancangan', 'pembangunan', 'penggunaan', 'aplikasi',
                
                # Indonesian technical terms
                'kecerdasan buatan', 'pembelajaran mesin', 'jaringan saraf',
                'pengolahan data', 'sistem informasi', 'teknologi informasi',
                
                # Indonesian domains
                'kedokteran', 'kesehatan', 'pendidikan', 'teknologi', 'ekonomi',
                'pertanian', 'perikanan', 'kehutanan', 'industri'
            ]
            
            score = 0.0
            text_combined = f"{title} {abstract} {source} {authors}"
            
            # Weight different parts differently
            for indicator in indonesian_indicators:
                if indicator in title:
                    score += 0.3  # Title has higher weight
                elif indicator in abstract:
                    score += 0.2  # Abstract medium weight
                elif indicator in source:
                    score += 0.25  # Source high weight for journal names
                elif indicator in authors:
                    score += 0.15  # Authors lower weight
            
            # ✅ BONUS for Indonesian journal patterns
            if any(pattern in source for pattern in [
                'jurnal', 'indonesia', 'nusantara', 'archipelago', 'indonesian',
                'fakultas', 'universitas', '.id', 'itb', 'ui', 'ugm', 'its'
            ]):
                score += 0.4
            
            # ✅ BONUS for Indonesian author names
            indonesian_name_patterns = [
                r'\b(sari|dewi|putra|putri|adi|budi|indra|rizki|fitri|ayu)\b',
                r'\b(sutanto|wijaya|santoso|pratama|kusuma|permana)\b'
            ]
            for pattern in indonesian_name_patterns:
                if re.search(pattern, authors):
                    score += 0.2
                    break
            
            return min(1.0, score)
        
        else:  # English/International preference
            international_indicators = [
                # High-impact journals/conferences
                'ieee', 'acm', 'springer', 'elsevier', 'nature', 'science', 'cell',
                'lancet', 'nejm', 'jama', 'plos', 'arxiv', 'neurips', 'icml',
                
                # Quality indicators
                'impact factor', 'indexed', 'scopus', 'web of science', 'pubmed',
                'doi', 'issn', 'volume', 'issue',
                
                # International terms
                'university', 'college', 'institute', 'research', 'department',
                'laboratory', 'center', 'international', 'global', 'worldwide'
            ]
            
            score = 0.0
            text_combined = f"{title} {abstract} {source} {authors}"
            
            for indicator in international_indicators:
                if indicator in title:
                    score += 0.2
                elif indicator in abstract:
                    score += 0.15
                elif indicator in source:
                    score += 0.25
                elif indicator in authors:
                    score += 0.1
            
            # ✅ BONUS for high-impact sources
            if any(term in source for term in [
                'ieee', 'acm', 'nature', 'science', 'springer', 'elsevier',
                'lancet', 'nejm', 'cell', 'plos'
            ]):
                score += 0.5
            
            # ✅ BONUS for international author affiliations
            if any(term in authors for term in [
                'university', 'institute', 'mit', 'stanford', 'harvard', 
                'cambridge', 'oxford', 'toronto', 'berkeley'
            ]):
                score += 0.3
            
            return min(1.0, score)
    
    def _calculate_topic_relevance_simple(self, paper: dict, topic_keywords: list) -> float:
        """Simple topic relevance calculation"""
        if not topic_keywords:
            return 0.0
        
        title = paper.get('title', '').lower()
        abstract = paper.get('summary', '').lower()
        
        relevance_score = 0.0
        for keyword in topic_keywords:
            keyword_lower = keyword.lower()
            
            if keyword_lower in title:
                relevance_score += 2.0
            elif keyword_lower in abstract:
                relevance_score += 1.0
            elif any(part in title for part in keyword_lower.split() if len(part) > 3):
                relevance_score += 1.0
        
        return min(1.0, relevance_score / (len(topic_keywords) * 2.0))

    def _deduplicate_and_rank_by_author_and_topic(
        self, papers: list, author_name: str, topic_keywords: list
    ) -> list:
        """Smart ranking for author+topic search - relevant papers first, then other author papers"""
        if not papers:
            return []

        # ✅ SEPARATE papers menjadi 2 kategori
        topic_relevant_papers = []
        other_author_papers = []

        for paper in papers:
            # Verify author match
            if not self._verify_author_match(paper.get("authors", ""), author_name):
                continue

            # Check topic relevance in title/abstract
            title_abstract = (
                f"{paper.get('title', '')} {paper.get('summary', '')}".lower()
            )
            topic_relevance = sum(
                1 for keyword in topic_keywords if keyword.lower() in title_abstract
            )

            paper["topic_relevance"] = topic_relevance
            paper["author_relevance"] = self._calculate_author_relevance(
                paper.get("authors", ""), author_name
            )

            if topic_relevance > 0:
                topic_relevant_papers.append(paper)
            else:
                other_author_papers.append(paper)

        # ✅ SORT each category
        # Topic-relevant papers: by topic relevance first, then author relevance
        topic_relevant_papers.sort(
            key=lambda x: (
                x["topic_relevance"] * 2,  # Topic relevance weight
                x["author_relevance"],
                int(x.get("citation_count", 0)) if x.get("citation_count") else 0,
            ),
            reverse=True,
        )

        # Other author papers: by author relevance and citations
        other_author_papers.sort(
            key=lambda x: (
                x["author_relevance"],
                int(x.get("citation_count", 0)) if x.get("citation_count") else 0,
            ),
            reverse=True,
        )

        # ✅ COMBINE: topic-relevant first, then other papers
        final_papers = []
        seen_titles = set()

        # Add topic-relevant papers first
        for paper in topic_relevant_papers:
            title = paper.get("title", "").lower().strip()
            title_clean = re.sub(r"[^\w\s]", "", title)[:50]
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                final_papers.append(paper)

        # Add other author papers
        for paper in other_author_papers:
            title = paper.get("title", "").lower().strip()
            title_clean = re.sub(r"[^\w\s]", "", title)[:50]
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                final_papers.append(paper)

        return final_papers

    async def _generate_topic_suggestions_with_authors(
        self, topic_keywords: list, current_author: str
    ) -> list:
        """Generate suggestions untuk author+topic search - include other authors"""
        suggestions = []

        if not topic_keywords:
            return suggestions

        main_topic = topic_keywords[0] if topic_keywords else ""

        # ✅ TOPIC VARIATIONS dari author lain
        suggestions.extend(
            [
                f"recent research in {main_topic}",
                f"{main_topic} review papers",
                f"latest {main_topic} developments",
                f"state of the art {main_topic}",
                f"{main_topic} survey papers",
            ]
        )

        # ✅ CROSS-AUTHOR suggestions
        if len(topic_keywords) >= 2:
            second_topic = topic_keywords[1]
            suggestions.extend(
                [
                    f"{main_topic} and {second_topic}",
                    f"{second_topic} in {main_topic}",
                ]
            )

        return suggestions[:5]

    async def _generate_general_suggestions_with_authors(
        self, topic_keywords: list, papers: list
    ) -> list:
        """Generate suggestions untuk general search - include author names dari results"""
        suggestions = []

        if not topic_keywords:
            return suggestions

        main_topic = topic_keywords[0] if topic_keywords else ""

        # ✅ TOPIC-BASED suggestions
        suggestions.extend(
            [
                f"recent research in {main_topic}",
                f"{main_topic} review 2024",
                f"state of the art {main_topic}",
                f"{main_topic} applications",
                f"future of {main_topic}",
            ]
        )

        # ✅ EXTRACT prominent authors dari results untuk suggestions
        author_counts = {}
        for paper in papers[:10]:  # Only top 10 papers
            authors_str = paper.get("authors", "")
            if authors_str:
                # Extract individual author names
                authors = [author.strip() for author in authors_str.split(",")]
                for author in authors[:2]:  # Only first 2 authors per paper
                    if author and len(author.split()) >= 2:  # Full name
                        author_counts[author] = author_counts.get(author, 0) + 1

        # ✅ ADD AUTHOR-BASED suggestions dari prominent authors
        prominent_authors = sorted(
            author_counts.items(), key=lambda x: x[1], reverse=True
        )[:2]
        for author, count in prominent_authors:
            if count >= 2:  # Author appears in multiple papers
                suggestions.append(f"research by {author}")

        return suggestions[:5]

    # ✅ EXISTING helper methods (keep all existing implementations)
    async def _search_semantic_scholar_author(
        self, author_name: str, keywords: list, year_range: dict
    ) -> list:
        """Search Semantic Scholar specifically for author"""
        try:
            query_parts = [f'author:"{author_name}"']

            if keywords:
                topic_query = " ".join(keywords)
                query_parts.append(topic_query)

            if year_range.get("start"):
                query_parts.append(
                    f"year:{year_range['start']}-{year_range.get('end', datetime.now().year)}"
                )

            search_query = " ".join(query_parts)
            logger.info(f"Semantic Scholar query: {search_query}")

            papers = await self.paper_scraper.scrape_semantic_scholar(search_query)

            filtered_papers = []
            for paper in papers:
                if self._verify_author_match(paper.get("authors", ""), author_name):
                    paper["author_relevance"] = self._calculate_author_relevance(
                        paper.get("authors", ""), author_name
                    )
                    filtered_papers.append(paper)

            return filtered_papers

        except Exception as e:
            logger.error(f"Error in Semantic Scholar author search: {str(e)}")
            return []

    async def _search_arxiv_author(
        self, author_name: str, keywords: list, year_range: dict
    ) -> list:
        """Search ArXiv specifically for author"""
        try:
            query_parts = [f'au:"{author_name}"']

            if keywords:
                for keyword in keywords[:2]:
                    query_parts.append(f"all:{keyword}")

            search_query = " AND ".join(query_parts)
            logger.info(f"ArXiv query: {search_query}")

            papers = await self.paper_scraper.scrape_arxiv(search_query)

            filtered_papers = []
            for paper in papers:
                if self._verify_author_match(paper.get("authors", ""), author_name):
                    paper["author_relevance"] = self._calculate_author_relevance(
                        paper.get("authors", ""), author_name
                    )
                    filtered_papers.append(paper)

            return filtered_papers

        except Exception as e:
            logger.error(f"Error in ArXiv author search: {str(e)}")
            return []

    async def _search_google_scholar_author(
        self, author_name: str, keywords: list, year_range: dict
    ) -> list:
        """Search Google Scholar specifically for author"""
        try:
            query_parts = [f'author:"{author_name}"']

            if keywords:
                topic_query = " ".join(keywords)
                query_parts.append(topic_query)

            search_query = " ".join(query_parts)
            logger.info(f"Google Scholar query: {search_query}")

            papers = await self.paper_scraper.scrape_google_scholar(search_query, max_results=20)

            filtered_papers = []
            for paper in papers:
                if self._verify_author_match(paper.get("authors", ""), author_name):
                    paper["author_relevance"] = self._calculate_author_relevance(
                        paper.get("authors", ""), author_name
                    )
                    filtered_papers.append(paper)

            return filtered_papers

        except Exception as e:
            logger.error(f"Error in Google Scholar author search: {str(e)}")
            return []

    def _basic_parameter_extraction(self, query: str) -> Dict[str, Any]:
        """Ekstraksi parameter dasar tanpa AI"""
        params = {"query": query, "keywords": [], "topic": ""}

        # Extract year range
        year_range_match = re.search(
            r"(?:tahun|dari tahun|between|antara)\s+(\d{4})\s+(?:sampai|hingga|to|until|dan|and|-)\s+(\d{4})",
            query,
            re.IGNORECASE,
        )
        if year_range_match:
            params["start_year"] = int(year_range_match.group(1))
            params["end_year"] = int(year_range_match.group(2))
        else:
            # Single year
            year_match = re.search(
                r"(?:tahun|dari tahun|from|in)\s+(\d{4})", query, re.IGNORECASE
            )
            if year_match:
                params["start_year"] = params["end_year"] = int(year_match.group(1))

        # Extract basic keywords
        keywords = []
        topic_match = re.search(
            r"(?:tentang|about|mengenai)\s+(.+?)(?:\s+(?:di|in|pada|at|for|untuk|dari|from|antara|between|tahun|year)|\s*$)",
            query,
            re.IGNORECASE,
        )
        if topic_match:
            topic = topic_match.group(1).strip()
            params["topic"] = topic
            keywords.append(topic)

        # Add field keywords if found
        field_match = re.search(
            r"(?:di bidang|di|dalam|in|in the field of|field of)\s+(\w+)",
            query,
            re.IGNORECASE,
        )
        if field_match:
            field = field_match.group(1).strip()
            keywords.append(field)
            params["fields"] = [field]

        params["keywords"] = keywords
        return params
    
    def _verify_author_match(self, authors_string: str, target_author: str) -> bool:
        """Enhanced verification untuk multiple authors - case insensitive"""
        if not authors_string or not target_author:
            return False
        
        # ✅ NORMALIZE untuk case insensitive matching
        authors_clean = authors_string.lower().strip()
        target_clean = target_author.lower().strip()
        
        # ✅ MULTIPLE AUTHOR DETECTION STRATEGIES
        
        # Strategy 1: Exact match (case insensitive)
        if target_clean in authors_clean:
            return True
        
        # Strategy 2: Split authors dan check individual names
        separators = [',', ';', ' and ', ' & ', ' dan ', '\n']
        
        # Split authors menggunakan multiple separators
        author_list = [authors_clean]
        for sep in separators:
            new_list = []
            for author in author_list:
                new_list.extend([a.strip() for a in author.split(sep) if a.strip()])
            author_list = new_list
        
        # ✅ CHECK each individual author (case insensitive)
        target_parts = target_clean.split()
        if len(target_parts) < 2:
            return False  # Need at least first + last name
        
        target_first = target_parts[0]
        target_last = target_parts[-1]
        
        for author in author_list:
            author = author.strip()
            if not author:
                continue
                
            # Strategy 2a: Full name match (case insensitive)
            if target_clean in author or author in target_clean:
                return True
            
            # Strategy 2b: First + Last name match (case insensitive)
            author_parts = author.split()
            if len(author_parts) >= 2:
                author_first = author_parts[0]
                author_last = author_parts[-1]
                
                # Check if first and last names match (case insensitive)
                if (target_first == author_first and target_last == author_last):
                    return True
                
                # Check reversed order (Last, First) (case insensitive)
                if (target_first == author_last and target_last == author_first):
                    return True
        
        # Strategy 3: Handle abbreviated names (case insensitive)
        for author in author_list:
            author = author.strip()
            if not author:
                continue
                
            if self._match_with_initials(author, target_clean):
                return True
        
        # Strategy 4: Fuzzy matching untuk typos atau variations
        for author in author_list:
            author = author.strip()
            if not author:
                continue
                
            if self._fuzzy_author_match(author, target_clean):
                return True
        
        return False
    
    def _match_with_initials(self, author: str, target: str) -> bool:
        """Match author dengan initial patterns"""
        import re
        
        # Pattern untuk J. Smith, Smith J., J Smith, Smith J
        initial_patterns = [
            r'^([A-Z])\.?\s+([A-Za-z]+)$',  # J. Smith atau J Smith
            r'^([A-Za-z]+),?\s+([A-Z])\.?$',  # Smith J. atau Smith, J
            r'^([A-Z])\.?\s+([A-Z])\.?\s+([A-Za-z]+)$',  # J. K. Smith
        ]
        
        target_parts = target.split()
        if len(target_parts) < 2:
            return False
        
        target_first = target_parts[0]
        target_last = target_parts[-1]
        
        for pattern in initial_patterns:
            match = re.match(pattern, author)
            if match:
                groups = match.groups()
                
                if len(groups) == 2:
                    # Two parts: initial and name
                    part1, part2 = groups
                    
                    # Check both possible orders
                    if (len(part1) == 1 and part1.upper() == target_first[0].upper() and 
                        part2.lower() == target_last.lower()):
                        return True
                    
                    if (len(part2) == 1 and part2.upper() == target_first[0].upper() and 
                        part1.lower() == target_last.lower()):
                        return True
                
                elif len(groups) == 3:
                    # Three parts: first initial, middle initial, last name
                    first_init, middle_init, last_name = groups
                    if (first_init.upper() == target_first[0].upper() and 
                        last_name.lower() == target_last.lower()):
                        return True
        
        return False
    
    def _fuzzy_author_match(self, author: str, target: str, threshold: float = 0.8) -> bool:
        """Fuzzy matching untuk handle typos atau variations"""
        # Simple Levenshtein distance-based similarity
        def levenshtein_ratio(s1: str, s2: str) -> float:
            if len(s1) == 0:
                return 0.0 if len(s2) == 0 else 1.0
            if len(s2) == 0:
                return 1.0
            
            # Create matrix
            matrix = [[0] * (len(s2) + 1) for _ in range(len(s1) + 1)]
            
            # Initialize first row and column
            for i in range(len(s1) + 1):
                matrix[i][0] = i
            for j in range(len(s2) + 1):
                matrix[0][j] = j
            
            # Fill matrix
            for i in range(1, len(s1) + 1):
                for j in range(1, len(s2) + 1):
                    if s1[i-1] == s2[j-1]:
                        cost = 0
                    else:
                        cost = 1
                    
                    matrix[i][j] = min(
                        matrix[i-1][j] + 1,      # deletion
                        matrix[i][j-1] + 1,      # insertion
                        matrix[i-1][j-1] + cost  # substitution
                    )
            
            # Calculate similarity ratio
            max_len = max(len(s1), len(s2))
            distance = matrix[len(s1)][len(s2)]
            return 1.0 - (distance / max_len)
        
        # Check similarity
        similarity = levenshtein_ratio(author.lower(), target.lower())
        return similarity >= threshold

    def _calculate_author_relevance(self, authors_string: str, target_author: str) -> float:
        """Enhanced calculation untuk multiple authors - case insensitive"""
        if not authors_string or not target_author:
            return 0.0
        
        # ✅ NORMALIZE untuk case insensitive
        authors_clean = authors_string.lower().strip()
        target_clean = target_author.lower().strip()
        
        # ✅ MULTIPLE AUTHOR RELEVANCE SCORING
        max_score = 0.0
        
        # Split authors menggunakan berbagai separator
        separators = [',', ';', ' and ', ' & ', ' dan ', '\n']
        author_list = [authors_clean]
        
        for sep in separators:
            new_list = []
            for author in author_list:
                new_list.extend([a.strip() for a in author.split(sep) if a.strip()])
            author_list = new_list
        
        # ✅ SCORING SYSTEM untuk each author position (case insensitive)
        for i, author in enumerate(author_list):
            author = author.strip()
            if not author:
                continue
            
            score = 0.0
            
            # Base scoring berdasarkan match quality (case insensitive)
            if target_clean == author:
                score = 1.0  # Perfect match
            elif target_clean in author or author in target_clean:
                score = 0.9  # Partial match
            elif self._match_with_initials(author, target_clean):
                score = 0.8  # Initial match
            elif self._fuzzy_author_match(author, target_clean, threshold=0.85):
                score = 0.7  # Fuzzy match
            elif self._fuzzy_author_match(author, target_clean, threshold=0.75):
                score = 0.6  # Loose fuzzy match
            
            # ✅ POSITION WEIGHTING - first author gets higher weight
            if score > 0:
                position_weight = 1.0 - (i * 0.1)  # First author: 1.0, second: 0.9, etc.
                position_weight = max(position_weight, 0.3)  # Minimum weight 0.3
                
                final_score = score * position_weight
                max_score = max(max_score, final_score)
        
        # ✅ AUTHOR COUNT BONUS - prefer papers dengan fewer authors (lebih focused)
        total_authors = len(author_list)
        if total_authors <= 3:
            author_count_bonus = 1.0
        elif total_authors <= 5:
            author_count_bonus = 0.95
        elif total_authors <= 8:
            author_count_bonus = 0.9
        else:
            author_count_bonus = 0.85
        
        final_relevance = max_score * author_count_bonus
        
        logger.debug(f"Author relevance for '{target_author}' in '{authors_string}': {final_relevance:.3f}")
        
        return min(1.0, final_relevance)

    # ✅ ADD METHOD: _deduplicate_and_rank_by_author
    def _deduplicate_and_rank_by_author(self, papers: list, author_name: str) -> list:
        """Remove duplicates and rank by author relevance"""
        if not papers:
            return []
        
        # ✅ DEDUPLICATE by title similarity
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:50]  # First 50 chars, alphanumeric only
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                unique_papers.append(paper)
        
        # ✅ SORT by author relevance + citation count
        def sort_key(paper):
            author_rel = paper.get('author_relevance', 0.0)
            citations = int(paper.get('citation_count', 0)) if paper.get('citation_count') else 0
            citation_score = min(1.0, citations / 100)  # Normalize citations
            
            # Combined score: 70% author relevance + 30% citations
            return (author_rel * 0.7) + (citation_score * 0.3)
        
        unique_papers.sort(key=sort_key, reverse=True)
        
        return unique_papers

    # ✅ ADD METHOD: _deduplicate_and_rank_by_topic
    def _deduplicate_and_rank_by_topic(self, papers: list, topic_keywords: list) -> list:
        """Remove duplicates and rank by topic relevance"""
        if not papers:
            return []
        
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:50]
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                unique_papers.append(paper)
        
        # Sort by citation count or year
        unique_papers.sort(key=lambda x: (
            int(x.get('citation_count', 0)) if x.get('citation_count') else 0,
            int(x.get('year', 0)) if x.get('year') else 0
        ), reverse=True)
        
        return unique_papers

    # ✅ ADD METHOD: _fallback_search
    async def _fallback_search(self, query: str) -> dict:
        """Fallback search when everything else fails"""
        try:
            logger.info(f"Executing fallback search for: {query}")
            
            # Simple search across all sources
            all_papers = []
            
            try:
                semantic_papers = await self.paper_scraper.scrape_semantic_scholar(query, max_results=20)
                all_papers.extend(semantic_papers)
            except Exception as e:
                logger.error(f"Semantic Scholar fallback error: {e}")
            
            try:
                arxiv_papers = await self.paper_scraper.scrape_arxiv(query, max_results=15)
                all_papers.extend(arxiv_papers)
            except Exception as e:
                logger.error(f"ArXiv fallback error: {e}")
            
            try:
                scholar_papers = await self.paper_scraper.scrape_google_scholar(query, max_results=15)
                all_papers.extend(scholar_papers)
            except Exception as e:
                logger.error(f"Google Scholar fallback error: {e}")
            
            # Basic deduplication
            unique_papers = self._remove_basic_duplicates(all_papers)
            
            # Generate basic suggestions
            suggested_queries = self._generate_basic_suggestions(query)
            
            return {
                "papers": unique_papers[:30],
                "suggested_queries": suggested_queries
            }
            
        except Exception as e:
            logger.error(f"Fallback search failed: {str(e)}")
            return {
                "papers": [],
                "suggested_queries": [f"recent {query} research", f"{query} review", f"latest {query}"]
            }

    # ✅ ADD METHOD: _remove_basic_duplicates
    def _remove_basic_duplicates(self, papers: list) -> list:
        """Basic duplicate removal by title"""
        if not papers:
            return []
        
        unique_papers = []
        seen_titles = set()
        
        for paper in papers:
            title = paper.get('title', '').lower().strip()
            title_clean = re.sub(r'[^\w\s]', '', title)[:50]
            
            if title_clean not in seen_titles and len(title_clean) > 10:
                seen_titles.add(title_clean)
                unique_papers.append(paper)
        
        return unique_papers

    # ✅ ADD METHOD: _generate_basic_suggestions
    def _generate_basic_suggestions(self, query: str) -> list:
        """Generate basic search suggestions"""
        suggestions = []
        
        # Extract main keywords
        words = query.lower().split()
        main_keywords = [word for word in words if len(word) > 3]
        
        if main_keywords:
            main_keyword = main_keywords[0]
            suggestions.extend([
                f"recent research in {main_keyword}",
                f"{main_keyword} review papers",
                f"latest {main_keyword} developments",
                f"state of the art {main_keyword}",
                f"{main_keyword} applications"
            ])
        
        return suggestions[:5]

    async def generate_simulated_results(
        self, search_params: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate simulated paper results using AI when scraping fails"""
        topic = search_params.get("topic", "")
        keywords = search_params.get("keywords", [])
        fields = search_params.get("fields", [])
        start_year = search_params.get("start_year", 2010)
        end_year = search_params.get("end_year", 2023)

        # Default to recent years if not specified
        if not start_year:
            start_year = 2010
        if not end_year:
            end_year = 2023

        prompt = f"""
        Generate 5 realistic academic paper entries on the topic: {topic}
        Related to fields: {', '.join(fields) if fields else 'any field'}
        Including keywords: {', '.join(keywords) if keywords else 'any relevant keywords'}
        Published between years: {start_year} and {end_year}
        
        For each paper, include:
        1. A realistic title
        2. 2-4 author names
        3. Publication year between {start_year} and {end_year}
        4. A realistic journal or conference name
        5. A DOI link (format: https://doi.org/10.XXXX/XXXXX)
        6. A 1-2 sentence summary of the paper
        
        Return the results as a JSON array of objects with the following structure:
        [
            {{
                "title": "Paper Title",
                "authors": "Author1, Author2, et al.",
                "year": 2022,
                "source": "Journal or Conference Name",
                "link": "https://doi.org/10.XXXX/XXXXX",
                "summary": "Brief summary of the paper",
                "id": "sim1"
            }},
            ...
        ]
        """

        try:
            logger.info("Generating simulated paper results")
            try:
                response_text = gemini_service.generate_content(prompt)
                result = gemini_service.extract_json_from_text(response_text)
            except RateLimitExceeded:
                logger.warning(
                    "Rate limit hit when generating simulated results, using OpenRouter"
                )
                # Fallback ke OpenRouter
                from .openrouter_service import openrouter_service

                response_text = await openrouter_service.generate_with_fallback(prompt)

                # Coba ekstrak JSON dari response
                import re
                import json

                # Pattern untuk mencari JSON array
                json_match = re.search(r"\[\s*{.+}\s*\]", response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    try:
                        result = json.loads(json_str)
                    except json.JSONDecodeError:
                        logger.warning("Failed to parse JSON from OpenRouter response")
                        result = []
                else:
                    result = []

            # Add simulation flag for transparency
            papers = []
            if isinstance(result, list):
                for i, paper in enumerate(result):
                    paper["id"] = f"sim{i+1}"
                    paper["simulated"] = True
                    papers.append(paper)

            logger.info(f"Generated {len(papers)} simulated papers")
            return papers

        except Exception as e:
            logger.error(f"Error generating simulated results: {e}")
            return []

    async def generate_paper_summary(
        self,
        paper_id: str,
        title: str,
        content: Optional[str] = None,
        is_full_paper: bool = False,
    ) -> str:
        """Generate comprehensive summary of a paper with fallback"""
        try:
            logger.info(f"Generating summary for paper: {title}")

            if not content or not content.strip():
                return "Tidak dapat membuat ringkasan karena tidak ada konten yang tersedia."

            # Generate summary dengan parameter yang sesuai
            try:
                summary = gemini_service.generate_paper_summary(
                    title, content, is_full_paper
                )
                return summary
            except RateLimitExceeded:
                # Fallback ke OpenRouter
                logger.warning(
                    "Rate limit hit when generating summary, trying OpenRouter"
                )
                from .openrouter_service import openrouter_service

                summary = await openrouter_service.generate_paper_summary(
                    title, content, is_full_paper
                )
                return summary

        except Exception as e:
            logger.error(f"Error generating paper summary: {e}")
            # Raise kembali exception untuk ditangkap oleh endpoint
            raise e

    async def answer_question(
        self,
        question: str,
        context: Optional[str] = None,
        full_text: Optional[str] = None,
    ) -> str:
        """Answer a question about research papers with fallback"""
        try:
            # Jika ada full_text, gunakan itu langsung
            if full_text:
                try:
                    return gemini_service.answer_question_from_full_text(
                        question, full_text
                    )
                except RateLimitExceeded:
                    logger.warning(
                        "Rate limit hit when answering from full text, trying OpenRouter"
                    )
                    from .openrouter_service import openrouter_service

                    return await openrouter_service.answer_question(
                        question, context=None, full_text=full_text
                    )
                except Exception as e:
                    logger.error(f"Error answering from full text: {e}")
                    # Fallback to context

            # Jika tidak, gunakan context biasa (hanya abstrak)
            papers_context = []
            if context:
                try:
                    papers_context = json.loads(context)
                    logger.info(
                        f"Context loaded, contains {len(papers_context)} papers"
                    )
                except:
                    logger.warning("Failed to parse context JSON")
                    papers_context = []

            try:
                return gemini_service.answer_question_with_context(
                    question, papers_context
                )
            except RateLimitExceeded:
                logger.warning(
                    "Rate limit hit when answering with context, trying OpenRouter"
                )
                from .openrouter_service import openrouter_service

                # Konversi context ke format yang sesuai
                context_str = "\n\n".join(
                    [
                        f"Title: {p['title']}\nAbstract: {p['summary']}"
                        for p in papers_context
                    ]
                )
                return await openrouter_service.answer_question(
                    question, context=context_str
                )

        except Exception as e:
            logger.error(f"Error answering question: {str(e)}")
            tb = traceback.format_exc()
            logger.error(f"Traceback: {tb}")
            return f"Maaf, terjadi kesalahan saat menjawab pertanyaan Anda: {str(e)}"

    async def generate_keywords(self, query: str) -> List[str]:
        """Generate keyword suggestions for search query"""
        try:
            logger.info(f"Generating keywords for query: {query}")
            try:
                keywords = gemini_service.generate_suggested_keywords(query)
                return keywords
            except RateLimitExceeded:
                # Fallback ke OpenRouter
                logger.warning(
                    "Rate limit hit when generating keywords, trying OpenRouter"
                )
                from .openrouter_service import openrouter_service

                keywords = await openrouter_service.generate_keywords(query)
                return keywords
        except Exception as e:
            logger.error(f"Error generating keywords: {e}")
            return []


# Singleton instance
search_service = SearchService()
