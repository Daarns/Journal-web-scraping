import spacy
import re
from typing import Dict, Any, List, Optional
import os
from pathlib import Path

# Lazy loading models untuk memori lebih efisien
_en_nlp = None
_id_nlp = None

def get_en_model():
    """Lazy load English model"""
    global _en_nlp
    if _en_nlp is None:
        try:
            _en_nlp = spacy.load("en_core_web_md")
        except OSError:
            print("Warning: English model not found. Installing smaller model...")
            _en_nlp = spacy.load("en_core_web_sm")
    return _en_nlp

def get_id_model():
    """Lazy load Indonesian model"""
    global _id_nlp
    if _id_nlp is None:
        try:
            _id_nlp = spacy.load("id_core_news_md")
        except OSError:
            print("Warning: Indonesian model not found. Using English model as fallback.")
            _id_nlp = get_en_model()
    return _id_nlp

def detect_language(text: str) -> str:
    """Deteksi bahasa dari input text (id/en)"""
    # Simple detection based on common words
    id_keywords = ['saya', 'adalah', 'sedang', 'mencari', 'jurnal', 'tentang', 
                  'dari', 'tahun', 'sampai', 'bidang', 'karya', 'pada', 'untuk']
    
    text_lower = text.lower()
    id_count = sum(1 for word in id_keywords if word in text_lower.split())
    
    # Threshold for Indonesian detection
    return "id" if id_count >= 2 else "en"

def extract_search_parameters(query: str) -> Dict[str, Any]:
    """Extract search parameters from natural language query"""
    # Detect language
    lang = detect_language(query)
    
    # Select appropriate NLP model
    nlp = get_id_model() if lang == "id" else get_en_model()
    
    # Process query
    doc = nlp(query)
    
    params = {
        "topics": [],
        "field": None,
        "start_year": None,
        "end_year": None,
        "author": None,
        "language": lang
    }
    
    # Extract years with regex (works for both languages)
    year_pattern = r"(?:19|20)\d{2}"
    years = re.findall(year_pattern, query)
    if len(years) >= 2:
        params["start_year"] = min(int(y) for y in years)
        params["end_year"] = max(int(y) for y in years)
    elif len(years) == 1:
        params["start_year"] = int(years[0])
    
    # Field indicators for both languages
    field_indicators = {
        "id": ["bidang", "di", "tentang", "mengenai", "pada", "seputar"],
        "en": ["field", "in", "about", "area", "on", "regarding", "domain"]
    }
    
    # Select appropriate indicators
    indicators = field_indicators["id"] if lang == "id" else field_indicators["en"]
    
    # Extract field of study
    for token in doc:
        if token.text.lower() in indicators and token.i + 1 < len(doc):
            # Take chunk after keyword
            potential_field = []
            for i in range(token.i + 1, min(token.i + 5, len(doc))):
                if doc[i].pos_ in ["NOUN", "PROPN"] and not doc[i].is_stop:
                    potential_field.append(doc[i].text)
            
            if potential_field:
                params["field"] = " ".join(potential_field)
                break
    
    # Common stop words to exclude
    stop_words = {
        "id": ["saya", "anda", "mencari", "cari", "jurnal", "paper", "artikel", "tentang", "dari"],
        "en": ["i", "am", "looking", "for", "papers", "journals", "articles", "about", "from"]
    }
    
    selected_stops = stop_words["id"] if lang == "id" else stop_words["en"]
    
    # Extract topics (important noun chunks)
    topics = []
    for chunk in doc.noun_chunks:
        # Filter out common stop phrases
        if not any(word in selected_stops for word in chunk.text.lower().split()):
            if len(chunk.text.split()) <= 3:  # Limit topic length
                topics.append(chunk.text)
    
    # Filter topics to ensure no duplicates or substrings
    filtered_topics = []
    for topic in topics:
        if not any(topic in t for t in filtered_topics if topic != t):
            filtered_topics.append(topic)
    
    params["topics"] = filtered_topics[:5]  # Limit number of topics
    
    # If no topics detected, use entities
    if not params["topics"]:
        for ent in doc.ents:
            if ent.label_ in ["ORG", "PRODUCT", "WORK_OF_ART", "PERSON"]:
                params["topics"].append(ent.text)
    
    return params