import os
import argparse
import subprocess
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def create_migration(message="Database migration"):
    """Create a new migration revision."""
    try:
        subprocess.run(["alembic", "revision", "--autogenerate", "-m", message], check=True)
        print(f"✅ Migration revision created: {message}")
    except Exception as e:
        print(f"❌ Failed to create migration: {str(e)}")
        return False
    return True

def apply_migrations():
    """Apply all pending migrations."""
    try:
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        print("✅ Database successfully migrated to latest version")
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        return False
    return True

def setup_database():
    """Create database if not exists."""
    try:
        from app.config.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME
        import pymysql
        
        # Connect to MySQL server
        conn = pymysql.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            port=int(DB_PORT)
        )
        
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"✅ Database '{DB_NAME}' created or already exists")
        
        conn.close()
    except Exception as e:
        print(f"❌ Database setup failed: {str(e)}")
        return False
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Knowvera Database Migration Tool")
    parser.add_argument("--message", "-m", default="Database migration", help="Migration message")
    parser.add_argument("--setup", "-s", action="store_true", help="Setup database before migration")
    parser.add_argument("--create-only", "-c", action="store_true", help="Only create migration file without applying")
    
    args = parser.parse_args()
    
    if args.setup:
        if not setup_database():
            exit(1)
            
    if create_migration(args.message) and not args.create_only:
        apply_migrations()