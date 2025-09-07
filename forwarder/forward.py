import asyncio
import os
import re
import json
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import FSInputFile # <-- Import for sending files

# --- Configuration ---
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# --- File Paths ---
RANGE_FILE = "forwardrange.txt"
INDEX_FILE = "indexed_messages.json" # <-- File to be created and sent

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

def parse_range_file():
    with open(RANGE_FILE, "r") as f:
        content = f.read()
    matches = LINK_RE.findall(content)
    if len(matches) < 2:
        raise Exception(f"{RANGE_FILE} must contain at least 2 message links")
    (user1, id1), (user2, id2) = matches[0], matches[1]
    if user1 != user2:
        raise Exception("Both links must be from the same channel")
    start_id, end_id = min(int(id1), int(id2)), max(int(id1), int(id2))
    return user1, start_id, end_id

async def send_log(bot, text):
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text, disable_web_page_preview=True)
        except:
            pass

def create_progress_bar(progress, total, length=10):
    filled_length = int(length * progress // total)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar

async def main():
    source_user, start_id, end_id = parse_range_file()
    source_chat = f"@{source_user}"
    sent, skipped, failed = 0, 0, 0
    skipped_links = []
    indexed_messages = [] # <-- List to hold text messages for indexing

    start_time = datetime.now()
    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        start_message = (
            f"🚀 <b>Forwarder Initialized</b> 🚀\n"
            f"━━━━━━━━━━━━━━━\n"
            f"➤ <b>Source:</b> <code>{source_chat}</code>\n"
            f"➤ <b>Range:</b> <code>{start_id}</code> to <code>{end_id}</code>\n"
            f"➤ <b>Destination:</b> <code>{DEST_CHANNEL_ID}</code>\n"
            f"━━━━━━━━━━━━━━━"
        )
        await send_log(bot, start_message)
        
        current = start_id
        DELAY_BETWEEN_MESSAGES = 1.2

        while current <= end_id:
            try:
                # --- MODIFIED: Using forward_message to get message content ---
                forwarded_message = await bot.forward_message(
                    chat_id=DEST_CHANNEL_ID,
                    from_chat_id=source_chat,
                    message_id=current
                )
                sent += 1

                # --- RE-ENABLED: Working indexing logic ---
                message_text = forwarded_message.text or forwarded_message.caption
                if message_text:
                    chat_id_for_link = str(DEST_CHANNEL_ID).replace('-100', '')
                    link = f"https://t.me/c/{chat_id_for_link}/{forwarded_message.message_id}"
                    indexed_messages.append({
                        "text": message_text,
                        "link": link
                    })

            except TelegramBadRequest as e:
                # ... (error handling remains the same)
                skipped += 1
            except TelegramAPIError as e:
                # ... (error handling remains the same)
                continue
            except Exception as e:
                failed += 1
            
            # ... (progress update logic remains the same)
            
            current += 1
            await asyncio.sleep(DELAY_BETWEEN_MESSAGES)

        end_time = datetime.now()
        
        # --- NEW: Save index locally and send to Telegram ---
        if indexed_messages:
            # 1. Save the index file to the runner's local disk
            try:
                with open(INDEX_FILE, "w", encoding="utf-8") as f:
                    json.dump(indexed_messages, f, ensure_ascii=False, indent=4)
                
                # 2. Send the newly created file to the log channel
                await send_log(bot, f"📦 Preparing to send index file with <code>{len(indexed_messages)}</code> entries...")
                index_file_obj = FSInputFile(INDEX_FILE)
                await bot.send_document(
                    chat_id=LOG_CHANNEL_ID,
                    document=index_file_obj,
                    caption=f"Attached is the index of {len(indexed_messages)} text messages from the latest run."
                )
            except Exception as e:
                await send_log(bot, f"🔥 <b>Error sending index file:</b> <code>{e}</code>")

        # --- Final Report (UI remains the same) ---
        # ...

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
                    
