import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Security
SECRET_KEY = os.getenv("SECRET_KEY", "very_secret_key_change_this_in_production")
CSRF_SECRET_KEY = os.getenv("CSRF_SECRET_KEY", "csrf_secret_key_change_this_in_production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Database configuration
# Gunakan MySQL dengan XAMPP
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "mysql+pymysql://root:@localhost:3306/knowvera"
)

# Path settings
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # Sekarang BASE_DIR adalah root folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
STATIC_DIR = os.path.join(PROJECT_ROOT, "assets")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "views")

# OAuth settings
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback")

# Rate limiting
RATE_LIMIT_WINDOW = 60  # seconds
LOGIN_MAX_ATTEMPTS = 5  # attempts per window

# Tambahkan konfigurasi email
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "your_email@gmail.com")  # Ganti dengan email Anda
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "your_app_password")  # App Password dari Google
EMAIL_FROM = os.getenv("EMAIL_FROM", "Knowvera <your_email@gmail.com>")
EMAIL_TLS = True