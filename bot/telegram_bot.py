"""Telegram bot integration using Aiogram 3 with webhook support."""
import os
import json
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import asyncio

from bot.ai_agent import chat
from backend.database import SessionLocal
from backend.models.chat_session import ChatSession, ChatMessage, ChatPlatform, MessageRole

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("TELEGRAM_WEBHOOK_URL", "")
BOT_PORT = int(os.getenv("BOT_PORT", "8443"))

bot = Bot(token=TELEGRAM_TOKEN) if TELEGRAM_TOKEN else None
dp = Dispatcher()


def get_or_create_session(db, platform_user_id: str):
    session = db.query(ChatSession).filter(
        ChatSession.platform == ChatPlatform.telegram,
        ChatSession.platform_user_id == platform_user_id,
        ChatSession.is_active == True,
    ).first()
    if not session:
        session = ChatSession(
            platform=ChatPlatform.telegram,
            platform_user_id=platform_user_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def load_history(db, session_id) -> list[dict]:
    """Load chat history from database."""
    messages = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id
    ).order_by(ChatMessage.created_at).limit(20).all()
    return [{"role": m.role.value, "content": m.content} for m in messages]


def save_message(db, session_id, role: MessageRole, content: str):
    msg = ChatMessage(session_id=session_id, role=role, content=content)
    db.add(msg)
    db.commit()


@dp.message()
async def handle_message(message: types.Message):
    if not message.text:
        await message.reply("Solo puedo procesar mensajes de texto por ahora. 📝")
        return

    db = SessionLocal()
    try:
        session = get_or_create_session(db, str(message.from_user.id))
        history = load_history(db, session.id)

        # Save user message
        save_message(db, session.id, MessageRole.user, message.text)

        # Get AI response
        response = chat(message.text, history)

        # Save AI response
        save_message(db, session.id, MessageRole.assistant, response)

        await message.reply(response)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await message.reply("Disculpá, tuve un problema. ¿Podés repetir tu consulta? 🙏")
    finally:
        db.close()


async def on_startup():
    if WEBHOOK_URL and bot:
        await bot.set_webhook(WEBHOOK_URL)
        logger.info(f"Webhook set to {WEBHOOK_URL}")


async def main():
    """Run bot in polling mode (development)."""
    if not TELEGRAM_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN not set, bot not starting")
        return
    dp.startup.register(on_startup)
    if WEBHOOK_URL:
        app = web.Application()
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
        handler.register(app, path="/webhook")
        setup_application(app, dp, bot=bot)
        await web._run_app(app, port=BOT_PORT)
    else:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
