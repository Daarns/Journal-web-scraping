import pymysql
from app.config.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

def setup_database():
    # Koneksi ke MySQL server
    connection = pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        port=int(DB_PORT)
    )
    
    try:
        with connection.cursor() as cursor:
            # Buat database jika belum ada
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_NAME} DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            print(f"Database {DB_NAME} berhasil dibuat atau sudah ada.")
    finally:
        connection.close()

if __name__ == "__main__":
    setup_database()
    print("Setup database selesai.")