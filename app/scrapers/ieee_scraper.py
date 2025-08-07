import os
import requests
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# Konfigurasi logging
logger = logging.getLogger(__name__)

# Variable untuk rate limiting
ieee_request_count = 0
ieee_last_reset_date = datetime.now().date()
ieee_last_request_time = 0

def parse_year_filter(year_filter: Optional[str]) -> tuple:
    """
    Parse filter tahun dari string (misalnya "2020-2024") ke tuple (tahun_awal, tahun_akhir)
    
    Args:
        year_filter: String filter tahun dalam format "start-end" atau "all"
        
    Returns:
        tuple: (tahun_awal, tahun_akhir) atau (None, None) jika format tidak valid
    """
    if not year_filter or year_filter.lower() == "all":
        return None, None
    
    try:
        parts = year_filter.split("-")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except Exception as e:
        logger.warning(f"Format filter tahun tidak valid: {year_filter}")
    
    return None, None

def search_ieee(query: str, year_filter: Optional[str] = None, max_results: int = 20) -> List[Dict[str, Any]]:
    """
    Cari jurnal dari IEEE Xplore menggunakan IEEE API
    
    Args:
        query: Kata kunci pencarian
        year_filter: Filter tahun dalam format "2020-2024" atau "all"
        max_results: Jumlah maksimum hasil yang dikembalikan
        
    Returns:
        List[Dict]: Daftar jurnal dengan format yang seragam
    """
    global ieee_request_count, ieee_last_reset_date, ieee_last_request_time
    
    try:
        logger.info(f"Mencari jurnal IEEE dengan query: {query}")
        
        # Reset counter harian jika tanggal berganti
        current_date = datetime.now().date()
        if current_date > ieee_last_reset_date:
            ieee_request_count = 0
            ieee_last_reset_date = current_date
        
        # Cek daily limit (200 calls per day)
        if ieee_request_count >= 200:
            logger.warning("Batas harian IEEE API (200) tercapai. Melewati pencarian IEEE.")
            return []
        
        # Cek rate limit (10 calls per second)
        current_time = time.time()
        time_since_last_request = current_time - ieee_last_request_time
        if time_since_last_request < 0.1:  # Minimal 0.1 detik antar request (max 10/detik)
            sleep_time = 0.1 - time_since_last_request
            logger.debug(f"Rate limiting IEEE API, delay selama {sleep_time:.3f}s")
            time.sleep(sleep_time)
        
        # Update waktu request terakhir
        ieee_last_request_time = time.time()
        
        # Increment counter harian
        ieee_request_count += 1
        
        # Ambil API key dari environment variable
        ieee_api_key = os.getenv("IEEE_API_KEY")
        if not ieee_api_key:
            logger.error("IEEE API key tidak ditemukan di environment variables")
            return []
        
        # Log status counter
        logger.info(f"Penggunaan IEEE API hari ini: {ieee_request_count}/200")
        
        # Endpoint IEEE API
        base_url = "http://ieeexploreapi.ieee.org/api/v1/search/articles"
        
        # Parameter query
        params = {
            "apikey": ieee_api_key,
            "querytext": query,
            "max_records": max_results,
            "format": "json",
            "start_record": 1
        }
        
        # Tambahkan filter tahun jika ada
        if year_filter and year_filter != "all":
            year_start, year_end = parse_year_filter(year_filter)
            if year_start and year_end:
                params["start_year"] = str(year_start)
                params["end_year"] = str(year_end)
        
        # Log request detail untuk debugging
        logger.debug(f"IEEE API request: {base_url} dengan params: {params}")
        
        # Kirim request ke API dengan timeout
        response = requests.get(base_url, params=params, timeout=10)
        response.raise_for_status()  # Raise exception untuk response non-2xx
        
        # Parse hasil
        data = response.json()
        
        # Log info response
        logger.debug(f"IEEE API response status: {response.status_code}")
        logger.debug(f"IEEE API response size: {len(response.text)} bytes")
        
        papers = []
        
        # Ekstrak hasil jika ada
        if "articles" in data and data["articles"]:
            for article in data["articles"]:
                # Ekstrak authors
                authors = ""
                if "authors" in article and "authors" in article["authors"]:
                    authors_list = article["authors"]["authors"]
                    authors = ", ".join([a.get("full_name", "") for a in authors_list])
                
                # Tentukan link (DOI atau URL)
                link = ""
                if "doi" in article and article["doi"]:
                    link = f"https://doi.org/{article['doi']}"
                elif "html_url" in article and article["html_url"]:
                    link = article["html_url"]
                elif "pdf_url" in article and article["pdf_url"]:
                    link = article["pdf_url"]
                
                # Buat objek paper dengan format standar
                paper = {
                    "title": article.get("title", "Untitled"),
                    "authors": authors,
                    "year": article.get("publication_year", ""),
                    "source": "IEEE",
                    "link": link,
                    "summary": article.get("abstract", "No abstract available"),
                    "venue": article.get("publication_title", "IEEE Publication"),
                    "id": article.get("article_number", "") or article.get("doi", "")
                }
                papers.append(paper)
                
        logger.info(f"Ditemukan {len(papers)} jurnal dari IEEE")
        return papers
        
    except Exception as e:
        logger.error(f"Error pada IEEE scraper: {str(e)}")
        return []