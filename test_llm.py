import os
import json
from bot.ai_agent import get_agent, chat

# Set up environment
from dotenv import load_dotenv
load_dotenv()

def test_providers():
    providers = []
    
    # Check DB for priorities (simulated)
    from backend.database import SessionLocal
    from backend.models.config import AppConfig
    db = SessionLocal()
    for i in range(1, 4):
        conf = db.query(AppConfig).filter(AppConfig.key == f"AI_PROVIDER_{i}").first()
        if conf and conf.value:
            providers.append(conf.value)
    
    print(f"Providers from DB: {providers}")
    if not providers:
        providers = ["openai", "gemini", "groq"]

    for provider in providers:
        print(f"\n--- Testing {provider} ---")
        try:
            agent = get_agent(provider)
            if not agent:
                print("No agent initialized (missing API key?)")
                continue
            
            # Use simple invoke
            result = agent.invoke({
                "input": "Hola, esto es una prueba", 
                "chat_history": [],
                "today": "2024-06-12 09:00",
                "insurances": "PAMI, OSDE"
            })
            print(f"Success! Response: {result['output'][:50]}...")
        except Exception as e:
            print(f"Error: {e}")

test_providers()
