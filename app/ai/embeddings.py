from sentence_transformers import SentenceTransformer
import numpy as np
from app.config.ai_config import EMBEDDING_MODEL, HUGGINGFACE_API_KEY
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class EmbeddingService:
    """Service for creating and comparing vector embeddings with Hugging Face models"""
    
    def __init__(self):
        self._model = None
        # Set HuggingFace token env var if available
        if HUGGINGFACE_API_KEY:
            os.environ["HUGGINGFACE_TOKEN"] = HUGGINGFACE_API_KEY
    
    @property
    def model(self):
        """Lazy initialization of the embedding model"""
        if self._model is None:
            try:
                logger.info(f"Loading embedding model: {EMBEDDING_MODEL}")
                self._model = SentenceTransformer(EMBEDDING_MODEL)
                logger.info("Embedding model loaded successfully")
            except Exception as e:
                logger.error(f"Error loading embedding model: {e}")
                raise
        return self._model
    
    def get_embedding(self, text: str) -> np.ndarray:
        """Get embedding vector for a text"""
        if not text:
            return np.zeros(384)  # Default dimension for paraphrase-MiniLM-L6-v2
        
        return self.model.encode(text)
    
    def get_embeddings(self, texts: List[str]) -> np.ndarray:
        """Get embedding vectors for multiple texts"""
        if not texts:
            return np.array([])
        
        return self.model.encode(texts)
    
    def rank_by_similarity(self, 
                          query: str, 
                          items: List[Dict[str, Any]], 
                          text_key: str = "text") -> List[Dict[str, Any]]:
        """
        Rank items by similarity to query
        
        Args:
            query: The search query
            items: List of dictionaries containing items to rank
            text_key: The dictionary key containing text to compare against
            
        Returns:
            List of items with similarity scores, sorted by relevance
        """
        if not items:
            return []
        
        # Extract text from items
        texts = [item.get(text_key, "") for item in items]
        
        # Get embeddings
        query_embedding = self.get_embedding(query)
        item_embeddings = self.get_embeddings(texts)
        
        if len(item_embeddings) == 0:
            return items
        
        # Calculate cosine similarity
        similarities = np.dot(item_embeddings, query_embedding) / (
            np.linalg.norm(item_embeddings, axis=1) * np.linalg.norm(query_embedding)
        )
        
        # Add similarity scores to items
        for i, item in enumerate(items):
            item["similarity_score"] = float(similarities[i])
        
        # Sort by similarity
        ranked_items = sorted(items, key=lambda x: x.get("similarity_score", 0), reverse=True)
        
        return ranked_items

# Singleton instance
embedding_service = EmbeddingService()