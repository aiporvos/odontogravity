import os
import asyncio
from langchain_openai import ChatOpenAI

async def main():
    try:
        # Pone tu API KEY de Groq temporalmente para probar, 
        # o deja que la saque de alguna otra forma. 
        # Como no tenemos la api key del usuario, no puedo probarlo.
        pass
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())
