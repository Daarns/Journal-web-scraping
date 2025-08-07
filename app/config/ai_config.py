from dotenv import load_dotenv
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import logging
import time

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# API Keys with validation
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# Validate required API keys
if not GOOGLE_API_KEY:
    logger.warning("GOOGLE_API_KEY not found in environment variables!")
    GOOGLE_API_KEY = "your_google_api_key_here"  # Placeholder

if GOOGLE_API_KEY == "your_google_api_key_here":
    logger.error("Please set your actual GOOGLE_API_KEY in .env file!")

# Tracking last failure time untuk fast fail
_last_gemini_failure = None
_failure_cooldown = 60  # 1 menit - durasi lebih pendek untuk pengujian

# Model configurations dengan prioritas berdasarkan kebutuhan Anda
GEMINI_MODELS = {
    "primary": "gemini-2.5-flash-lite-preview-06-17",
    "lite": "gemini-2.0-flash",
    "experimental": "gemini-1.5-flash",
    "fallback": "gemini-1.5-flash-8b-latest",
}

# Tracking failures per model
_model_failures = {
    "gemini-2.5-flash-lite-preview-06-17": None,
    "gemini-2.0-flash": None,
    "gemini-1.5-flash": None,
    "gemini-1.5-flash-8b-latest": None
}

def init_gemini(model_name=None):
    """Initialize Google Gemini API dengan support multiple model"""
    global _model_failures
    
    # Validate API key first
    if not GOOGLE_API_KEY or GOOGLE_API_KEY == "your_google_api_key_here":
        raise ValueError("GOOGLE_API_KEY is not properly configured. Please check your .env file.")
    
    # Gunakan primary model jika tidak dispesifikasi
    if not model_name:
        model_name = GEMINI_MODELS["primary"]
    
    # Check cooldown period untuk model spesifik
    if (_model_failures.get(model_name) and 
        (time.time() - _model_failures[model_name]) < _failure_cooldown):
        logger.warning(f"Skipping {model_name} initialization during cooldown period")
        raise Exception(f"{model_name} initialization in cooldown after recent failure")
    
    genai.configure(api_key=GOOGLE_API_KEY)
    
    try:
        # Safety settings yang lebih permisif
        safety_settings = [
            {
                "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE
            },
            {
                "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                "threshold": HarmBlockThreshold.BLOCK_NONE
            },
            {
                "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                "threshold": HarmBlockThreshold.BLOCK_NONE
            },
            {
                "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE
            }
        ]
        
        model = genai.GenerativeModel(
            model_name=model_name,
            safety_settings=safety_settings
        )
        
        # Test model dengan prompt sederhana
        response = model.generate_content("test")
        
        # Reset status failure jika berhasil
        _model_failures[model_name] = None
        logger.info(f"Gemini model {model_name} initialized successfully with relaxed safety settings")
        return model
        
    except Exception as e:
        # Record failure time
        _model_failures[model_name] = time.time()
        logger.error(f"Failed to initialize Gemini model {model_name}: {e}")
        raise e

def get_available_gemini_model():
    """Get available Gemini model, trying in order of preference"""
    models_to_try = [
        GEMINI_MODELS["primary"],
        GEMINI_MODELS["lite"], 
        GEMINI_MODELS["experimental"],
        GEMINI_MODELS["fallback"]
    ]
    
    for model_name in models_to_try:
        try:
            # Check if model is in cooldown
            if (_model_failures.get(model_name) and 
                (time.time() - _model_failures[model_name]) < _failure_cooldown):
                continue
                
            model = init_gemini(model_name)
            logger.info(f"Successfully initialized {model_name}")
            return model
            
        except Exception as e:
            logger.warning(f"Failed to initialize {model_name}: {e}")
            continue
    
    # If all models failed
    logger.error("All Gemini models failed to initialize")
    raise Exception("No available Gemini models")

def get_model_for_task(task_type="general"):
    """Get the best model for specific task type"""
    task_models = {
        "search": GEMINI_MODELS["primary"],
        "summary": GEMINI_MODELS["lite"], 
        "citation": GEMINI_MODELS["experimental"],
        "chat": GEMINI_MODELS["primary"],
        "general": GEMINI_MODELS["primary"]
    }
    
    preferred_model = task_models.get(task_type, GEMINI_MODELS["primary"])
    
    try:
        return init_gemini(preferred_model)
    except Exception as e:
        logger.warning(f"Failed to get preferred model {preferred_model} for {task_type}, falling back")
        return get_available_gemini_model()

# Model names/paths for Hugging Face
EMBEDDING_MODEL = "sentence-transformers/paraphrase-MiniLM-L6-v2"