#!/usr/bin/env python3
import os
import asyncio
from dotenv import load_dotenv
from news_core import main_loop, _silence_noise


def _load_env() -> tuple[str, str]:
    load_dotenv()
    if not os.getenv("BOT_TOKEN") or not os.getenv("CHAT_ID"):
        base = os.path.dirname(os.path.abspath(__file__))
        fallback = os.path.join(base, ".env")
        if os.path.exists(fallback):
            load_dotenv(fallback)
    token = os.getenv("BOT_TOKEN")
    chat = os.getenv("CHAT_ID")
    if not token or not chat:
        raise RuntimeError("BOT_TOKEN / CHAT_ID not set")
    return token, chat


if __name__ == "__main__":
    try:
        _silence_noise()
        token, chat = _load_env()
        asyncio.run(main_loop(token, chat))
    except KeyboardInterrupt:
        print("Exited cleanly.")
