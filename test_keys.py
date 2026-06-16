from backend.database import SessionLocal
from backend.models.config import AppConfig

def run():
    try:
        db = SessionLocal()
        keys = db.query(AppConfig).all()
        for k in keys:
            print(k.key)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run()
