import json
from typing import List, Optional, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from pydantic import BaseModel, validator

from ..core.database import get_db
from app.db.models import UserActivity, Collection, CollectionPaper, Citation, User
from .auth_utils import get_current_user, get_current_user_optional

router = APIRouter()


# Models untuk request dan response
class ActivityCreate(BaseModel):
    paper_id: str
    activity_type: str
    activity_data: Optional[dict] = None


class ActivityResponse(BaseModel):
    id: int
    paper_id: str
    activity_type: str
    timestamp: datetime
    activity_data: Optional[dict] = None


class CollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None


class CollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CollectionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime  # Field tambahan ini
    paper_count: int = 0


class CollectionPaperResponse(BaseModel):
    id: int
    paper_id: str
    title: str
    authors: Optional[str] = None
    year: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    added_at: datetime


class CollectionDetailResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    paper_count: int
    papers: List[CollectionPaperResponse]


class CollectionPaperAdd(BaseModel):
    paper_id: str
    title: str
    authors: Optional[str] = None
    year: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None


class CitationRequest(BaseModel):
    paper_id: str
    paper_title: str
    authors: str
    year: Any
    source: Optional[str] = None
    style: str  # e.g. "APA", "MLA", etc.

    @validator("year")
    def validate_year(cls, v):
        if v is None:
            return ""
        # Terima string atau angka untuk year
        if isinstance(v, int):
            return str(v)
        return v


class CitationResponse(BaseModel):
    id: int
    paper_id: str
    style: str
    citation_text: str
    generated_at: datetime

class CollectionPaperUpdate(BaseModel):
    notes: Optional[str] = None


# Endpoint untuk merekam aktivitas
@router.post("/activity", status_code=status.HTTP_201_CREATED)
async def record_activity(
    activity: ActivityCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Record user activity like viewing paper, summarizing, asking questions"""
    user_id = current_user.id if current_user else None

    # Hanya rekam aktivitas untuk user yang login
    if user_id:
        db_activity = UserActivity(
            user_id=user_id,
            paper_id=activity.paper_id,
            activity_type=activity.activity_type,
            activity_data=(
                json.dumps(activity.activity_data) if activity.activity_data else None
            ),
        )
        db.add(db_activity)
        db.commit()
        db.refresh(db_activity)

    return {"success": True}


# Endpoint untuk mendapatkan riwayat aktivitas pengguna
@router.get("/activity-history", response_model=List[ActivityResponse])
async def get_activity_history(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get user activity history"""
    activities = (
        db.query(UserActivity)
        .filter(UserActivity.user_id == current_user.id)
        .order_by(desc(UserActivity.timestamp))
        .offset(skip)
        .limit(limit)
        .all()
    )

    # Parse activity_data JSON jika ada
    result = []
    for activity in activities:
        item = {
            "id": activity.id,
            "paper_id": activity.paper_id,
            "activity_type": activity.activity_type,
            "timestamp": activity.timestamp,
            "activity_data": (
                json.loads(activity.activity_data) if activity.activity_data else None
            ),
        }
        result.append(item)

    return result


# Endpoint untuk mendapatkan paper yang sering dilihat
@router.get("/most-viewed-papers")
async def get_most_viewed_papers(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get most frequently viewed papers"""
    query = (
        db.query(UserActivity.paper_id, func.count(UserActivity.id).label("view_count"))
        .filter(
            UserActivity.user_id == current_user.id,
            UserActivity.activity_type == "view",
        )
        .group_by(UserActivity.paper_id)
        .order_by(desc("view_count"))
        .limit(limit)
    )

    results = query.all()

    return [{"paper_id": r.paper_id, "view_count": r.view_count} for r in results]


# CRUD untuk collections
@router.post(
    "/collections",
    response_model=CollectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    collection: CollectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new collection"""
    db_collection = Collection(
        user_id=current_user.id,
        name=collection.name,
        description=collection.description,
    )
    db.add(db_collection)
    db.commit()
    db.refresh(db_collection)

    return {
        "id": db_collection.id,
        "name": db_collection.name,
        "description": db_collection.description,
        "created_at": db_collection.created_at,
        "updated_at": db_collection.updated_at,  # Tambahkan ini
        "paper_count": 0,
    }


@router.get("/collections", response_model=List[CollectionResponse])
async def get_collections(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    """Get all user collections"""
    collections = (
        db.query(Collection).filter(Collection.user_id == current_user.id).all()
    )

    result = []
    for coll in collections:
        # Count papers in collection
        paper_count = (
            db.query(func.count(CollectionPaper.id))
            .filter(CollectionPaper.collection_id == coll.id)
            .scalar()
        )

        result.append(
            {
                "id": coll.id,
                "name": coll.name,
                "description": coll.description,
                "created_at": coll.created_at,
                "updated_at": coll.updated_at,  # Tambahkan ini
                "paper_count": paper_count,
            }
        )

    return result


@router.get("/collections/{collection_id}", response_model=CollectionDetailResponse)
async def get_collection_detail(
    collection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get collection details including all papers"""
    # Verify collection exists and belongs to user
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get papers in collection
    papers = (
        db.query(CollectionPaper)
        .filter(CollectionPaper.collection_id == collection_id)
        .all()
    )

    # Prepare response
    return {
        "id": db_collection.id,
        "name": db_collection.name,
        "description": db_collection.description,
        "created_at": db_collection.created_at,
        "updated_at": db_collection.updated_at,
        "paper_count": len(papers),
        "papers": [
            {
                "id": paper.id,
                "paper_id": paper.paper_id,
                "title": paper.title,
                "authors": paper.authors,
                "year": paper.year,
                "source": paper.source,
                "notes": paper.notes,
                "added_at": paper.added_at,
            }
            for paper in papers
        ],
    }


@router.put("/collections/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: int,
    collection: CollectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update collection details"""
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Update fields if provided
    if collection.name:
        db_collection.name = collection.name
    if collection.description is not None:  # Allow empty string
        db_collection.description = collection.description

    db.commit()
    db.refresh(db_collection)

    # Count papers
    paper_count = (
        db.query(func.count(CollectionPaper.id))
        .filter(CollectionPaper.collection_id == db_collection.id)
        .scalar()
    )

    return {
        "id": db_collection.id,
        "name": db_collection.name,
        "description": db_collection.description,
        "created_at": db_collection.created_at,
        "updated_at": db_collection.updated_at,
        "paper_count": paper_count,
    }

@router.put("/collections/{collection_id}/papers/{paper_id}")
async def update_paper_in_collection(
    collection_id: int,
    paper_id: str,
    paper_update: CollectionPaperUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update paper details in a collection (currently only supports notes)"""
    # Verify collection exists and belongs to user
    db_collection = db.query(Collection).filter(
        Collection.id == collection_id,
        Collection.user_id == current_user.id
    ).first()
    
    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")
        
    # Find paper in collection
    db_paper = db.query(CollectionPaper).filter(
        CollectionPaper.collection_id == collection_id,
        CollectionPaper.id == paper_id  # Notice we're using the internal ID here, not paper_id
    ).first()
    
    if not db_paper:
        raise HTTPException(status_code=404, detail="Paper not found in collection")
        
    # Update notes
    if paper_update.notes is not None:  # Allow empty string
        db_paper.notes = paper_update.notes
        
    db.commit()
    db.refresh(db_paper)
    
    return {
        "id": db_paper.id,
        "paper_id": db_paper.paper_id,
        "title": db_paper.title,
        "notes": db_paper.notes,
        "updated": True
    }

@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a collection"""
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Delete collection (cascade will delete collection papers)
    db.delete(db_collection)
    db.commit()

    return None


# Collection paper management
@router.post("/collections/{collection_id}/papers", status_code=status.HTTP_201_CREATED)
async def add_paper_to_collection(
    collection_id: int,
    paper: CollectionPaperAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a paper to collection"""
    # Verify collection exists and belongs to user
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Check if paper already exists in this collection
    existing = (
        db.query(CollectionPaper)
        .filter(
            CollectionPaper.collection_id == collection_id,
            CollectionPaper.paper_id == paper.paper_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=400, detail="Paper already exists in this collection"
        )

    # Add paper to collection
    db_paper = CollectionPaper(
        collection_id=collection_id,
        paper_id=paper.paper_id,
        title=paper.title,
        authors=paper.authors,
        year=paper.year,
        source=paper.source,
        notes=paper.notes,
    )
    db.add(db_paper)
    db.commit()

    return {"success": True, "message": "Paper added to collection"}


@router.get("/collections/{collection_id}/papers")
async def get_papers_in_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all papers in a collection"""
    # Verify collection exists and belongs to user
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Get papers
    papers = (
        db.query(CollectionPaper)
        .filter(CollectionPaper.collection_id == collection_id)
        .all()
    )

    return [
        {
            "id": paper.id,
            "paper_id": paper.paper_id,
            "title": paper.title,
            "authors": paper.authors,
            "year": paper.year,
            "source": paper.source,
            "notes": paper.notes,
            "added_at": paper.added_at,
        }
        for paper in papers
    ]


@router.delete(
    "/collections/{collection_id}/papers/{paper_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_paper_from_collection(
    collection_id: int,
    paper_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a paper from collection"""
    # Verify collection exists and belongs to user
    db_collection = (
        db.query(Collection)
        .filter(Collection.id == collection_id, Collection.user_id == current_user.id)
        .first()
    )

    if not db_collection:
        raise HTTPException(status_code=404, detail="Collection not found")

    # Find paper in collection
    db_paper = (
        db.query(CollectionPaper)
        .filter(
            CollectionPaper.collection_id == collection_id,
            CollectionPaper.paper_id == paper_id,
        )
        .first()
    )

    if not db_paper:
        raise HTTPException(status_code=404, detail="Paper not found in collection")

    # Remove paper
    db.delete(db_paper)
    db.commit()

    return None


# Citation generation endpoint
@router.post("/generate-citation", response_model=CitationResponse)
async def generate_citation(
    request: CitationRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Generate citation for a paper in specified style"""
    try:
        # Log untuk debugging
        print(f"CitationRequest received: {request.dict()}")

        # Import service
        try:
            from app.ai.gemini_service import gemini_service
        except ImportError as e:
            print(f"Error importing gemini_service: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Server configuration error: {str(e)}",
            )

        # Validasi nilai masukan
        if not request.paper_title or not request.authors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Paper title and authors are required",
            )

        # Validasi style sitasi
        valid_styles = ["APA", "MLA", "Chicago", "Harvard", "Vancouver", "IEEE"]
        if request.style not in valid_styles:
            request.style = "APA"  # Default ke APA jika style tidak valid

        # Pastikan year dikonversi dengan benar
        year_str = str(request.year) if request.year else "n.d."

        # Generate citation
        citation_text = gemini_service.generate_citation(
            title=request.paper_title,
            authors=request.authors,
            year=year_str,
            source=request.source or "",
            style=request.style,
        )

        # Jangan gunakan validasi panjang teks - bisa mengganti hasil yang benar
        # Implementasi ini lebih baik mengandalkan kualitas dari gemini_service.py

        # Simpan ke database jika user login
        current_time = datetime.now()
        db_citation_id = None

        if current_user:
            db_citation = Citation(
                user_id=current_user.id,
                paper_id=request.paper_id,
                style=request.style,
                citation_text=citation_text,
                generated_at=current_time,
            )
            db.add(db_citation)
            db.commit()
            db.refresh(db_citation)
            db_citation_id = db_citation.id

        # Kembalikan hasil
        return CitationResponse(
            id=db_citation_id or 0,
            paper_id=request.paper_id,
            style=request.style,
            citation_text=citation_text,
            generated_at=current_time,
        )

    except Exception as e:
        # Log error lengkap di console server
        import traceback

        traceback.print_exc()
        print(f"Citation error details: {str(e)}")

        # Return error yang lebih informatif
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generating citation: {str(e)}",
        )


# Fungsi untuk menghasilkan sitasi fallback jika hasil dari Gemini tidak memadai
def generate_fallback_citation(
    title: str, authors: str, year: str, source: str, style: str
):
    """Generate fallback citation if AI-generated citation fails"""
    if style == "APA":
        return f"{authors} ({year}). {title}. {source}."
    elif style == "MLA":
        return f'{authors}. "{title}." {source}, {year}.'
    elif style == "Chicago":
        return f'{authors}. "{title}." {source} ({year}).'
    elif style == "Harvard":
        return f"{authors} ({year}). '{title}', {source}."
    elif style == "Vancouver":
        return f"{authors}. {title}. {source}. {year}."
    elif style == "IEEE":
        return f'{authors}, "{title}," {source}, {year}.'
    else:
        return f"{authors} ({year}). {title}. {source}."
