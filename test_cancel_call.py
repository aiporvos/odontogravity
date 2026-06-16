import httpx

try:
    print("Testing /api/bot/cancel directly...")
    # we need the key
    from backend.database import SessionLocal
    from backend.models.config import AppConfig
    db = SessionLocal()
    key = db.query(AppConfig).filter(AppConfig.key == "BOT_API_KEY").first()
    if key:
        print(f"Key: {key.value}")
        r = httpx.post("http://localhost:8000/api/bot/cancel", json={"dni": "24785465"}, headers={"x-bot-key": key.value})
        print(f"Status: {r.status_code}")
        print(f"Response: {r.text}")
    else:
        print("No BOT_API_KEY")
except Exception as e:
    print(f"Error: {e}")

