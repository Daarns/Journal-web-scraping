from fastapi import APIRouter, Depends, Body, HTTPException, BackgroundTasks
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from ..core.database import get_db
from ..ai.search_service import search_service
from .auth_utils import get_current_user_optional
from ..db.models import User
from ..db.search_history import save_search_history, SearchHistory
from sqlalchemy.orm import Session
import logging
import re
from ..ai.gemini_service import RateLimitExceeded

logger = logging.getLogger(__name__)

# Define Pydantic models
class SearchQuery(BaseModel):
    query: str

# Initialize router
router = APIRouter(prefix="/api", tags=["search"])

@router.post("/search")
async def search_papers(
    query: SearchQuery,
    background_tasks: BackgroundTasks,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: Session = Depends(get_db)
):
    """Lakukan pencarian dengan query"""
    try:
        # Coba ekstrak parameter pencarian dengan AI
        try:
            search_results = await search_service.search_papers(query.query)
        except RateLimitExceeded:
            # Jika rate limit, gunakan fallback ke ekstraksi parameter basic
            logger.warning("Using basic search parameter extraction due to AI rate limit")
            # Implementasi ekstraksi parameter dasar tanpa AI
            params = extract_basic_search_parameters(query.query)
            search_results = await search_service.search_papers_with_params(params)
        
        # search_results sekarang berisi {"papers": [...], "suggested_queries": [...]}
        papers = search_results.get("papers", [])
        suggested_queries = search_results.get("suggested_queries", [])
        
        # Hitung jumlah hasil yang ditemukan
        results_count = len(papers)
        
        # Simpan history jika user login
        if current_user:
            try:
                search_history = SearchHistory(
                    user_id=current_user.id,
                    query=query.query,
                    results_count=results_count
                )
                db.add(search_history)
                db.commit()
                db.refresh(search_history)
                logger.info(f"Saved search history for user {current_user.id}: {query.query[:30]}... with {results_count} results")
            except Exception as e:
                logger.error(f"Error saving search history: {str(e)}")
                db.rollback()
        
        # Format respons sesuai ekspektasi frontend
        response_data = {
            "papers": papers,
            "count": results_count,
            "suggested_queries": suggested_queries
        }
        
        logger.info(f"Returning {results_count} search results")
        return response_data
    except Exception as e:
        logger.error(f"Search error: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error processing search: {str(e)}")

def extract_basic_search_parameters(query):
    """Extract search parameters without using AI"""
    # Simple regex-based parameter extraction
    params = {"query": query, "keywords": []}
    
    # Extract year range
    year_range_match = re.search(r"(?:tahun|dari tahun|between|antara)\s+(\d{4})\s+(?:sampai|hingga|to|until|dan|and|-)\s+(\d{4})", query, re.IGNORECASE)
    if year_range_match:
        params["min_year"] = int(year_range_match.group(1))
        params["max_year"] = int(year_range_match.group(2))
    else:
        # Single year
        year_match = re.search(r"(?:tahun|dari tahun|from|in)\s+(\d{4})", query, re.IGNORECASE)
        if year_match:
            params["min_year"] = params["max_year"] = int(year_match.group(1))
    
    # Extract basic keywords
    keywords = []
    topic_match = re.search(r"(?:tentang|about|mengenai)\s+(.+?)(?:\s+(?:di|in|pada|at|for|untuk|dari|from|antara|between|tahun|year)|\s*$)", query, re.IGNORECASE)
    if topic_match:
        topic = topic_match.group(1).strip()
        keywords.append(topic)
    
    # Add field keywords if found
    field_match = re.search(r"(?:di bidang|di|dalam|in|in the field of|field of)\s+(\w+)", query, re.IGNORECASE)
    if field_match:
        field = field_match.group(1).strip()
        keywords.append(field)
    
    params["keywords"] = keywords
    return params