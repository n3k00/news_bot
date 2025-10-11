# debug_channel_send.py  (PTB v21+)
import os, asyncio
from telegram import Bot
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from dotenv import load_dotenv

async def main():
    load_dotenv()
    token = os.getenv("BOT_TOKEN")
    chat  = os.getenv("CHAT_ID")  # @name သို့ -100...
    print("BOT_TOKEN_LEN:", len(token) if token else None)
    print("RAW CHAT_ID:", chat)

    try:
        async with Bot(token=token) as bot:
            me = await bot.get_me()
            print("BOT USERNAME:", me.username, "BOT ID:", me.id)

            # @username ဆိုရင် numeric ID ပြောင်း
            if chat and chat.startswith("@"):
                try:
                    ch = await bot.get_chat(chat)
                    chat = str(ch.id)
                    print("RESOLVED CHANNEL ID:", chat)
                except TelegramError as e:
                    print("get_chat error:", e)
                    return

            # bot membership စစ်
            try:
                cm = await bot.get_chat_member(chat, me.id)
                print("BOT STATUS IN CHANNEL:", cm.status)
                if cm.status != ChatMemberStatus.ADMINISTRATOR:
                    print("=> Bot ကို Channel admin + Post Messages ပေးပါ")
                    return
            except TelegramError as e:
                print("get_chat_member error:", e)
                return

            # ပို့ပေးပြီး result စာဖြင့် အောင်မြင်မှုစစ်
            try:
                msg = await bot.send_message(chat_id=chat, text="✅ Channel test message")
                print("SENT OK. message_id:", msg.message_id)
            except TelegramError as e:
                print("send_message error:", e)

    except Exception as e:
        print("FATAL:", repr(e))

if __name__ == "__main__":
    asyncio.run(main())
