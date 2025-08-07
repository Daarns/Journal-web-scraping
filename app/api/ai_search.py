# app/api/ai_search.py
import google.generativeai as genai
from fastapi import APIRouter, Depends, Body, HTTPException
import os
import json
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

router = APIRouter(prefix="/api/ai", tags=["ai"])

@router.post("/search")
async def search_papers(query: Dict[str, str] = Body(...)):
    """Search for academic papers based on user query"""
    search_query = query.get("query", "")
    
    if not search_query:
        raise HTTPException(status_code=400, detail="Query tidak boleh kosong")
    
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
        Saya mencari paper akademis tentang: {search_query}
        
        Berikan 5-8 paper akademis yang relevan. Untuk setiap paper, sertakan:
        1. Judul paper
        2. Penulis
        3. Tahun publikasi
        4. Nama jurnal/konferensi
        5. Link DOI jika tersedia
        6. Ringkasan singkat 1-2 kalimat
        
        Format output sebagai JSON:
        {{
            "papers": [
                {{
                    "title": "Judul paper",
                    "authors": "Daftar penulis",
                    "year": "Tahun publikasi",
                    "source": "Nama jurnal/konferensi",
                    "link": "DOI link",
                    "summary": "Ringkasan singkat"
                }}
            ],
            "suggested_queries": ["Query terkait 1", "Query terkait 2", "Query terkait 3"]
        }}
        """
        
        response = model.generate_content(prompt)
        
        # Ekstrak JSON dari respons
        result_text = response.text
        
        # Cari bagian JSON dalam respons
        json_start = result_text.find('{')
        json_end = result_text.rfind('}') + 1
        
        if json_start >= 0 and json_end > json_start:
            json_str = result_text[json_start:json_end]
            try:
                result_json = json.loads(json_str)
                return result_json
            except:
                return {"result": result_text}
        else:
            return {"result": result_text}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/question")
async def answer_question(query: Dict[str, str] = Body(...)):
    """Answer questions about research papers"""
    question = query.get("question", "")
    context = query.get("context", "")  # Optional paper context
    
    if not question:
        raise HTTPException(status_code=400, detail="Pertanyaan tidak boleh kosong")
    
    try:
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
        {context}
        
        Pertanyaan: {question}
        
        Berikan jawaban yang informatif, akademis, dan berdasarkan penelitian ilmiah. 
        Jika pertanyaan memerlukan referensi, sertakan referensi.
        """
        
        response = model.generate_content(prompt)
        
        return {"answer": response.text}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))