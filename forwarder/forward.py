import asyncio
import os
import re
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# --- Configuration ---
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
RANGE_FILE = "forwardrange.txt"

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
            await bot.send_message(LOG_CHANNEL_ID, text, parse_mode=None) # No parse mode
        except:
            pass

async def main():
    source_user, start_id, end_id = parse_range_file()
    source_chat = f"@{source_user}"
    
    burst_count = 0
    start_time = datetime.now()

    async with Bot(token=API_TOKEN, default=DefaultBotProperties()) as bot:
        await send_log(bot, f"--- Starting Rate Limit Test ---\nSource: {source_chat}\nRange: {start_id}-{end_id}")

        current = start_id
        while current <= end_id:
            try:
                await bot.copy_message(
                    chat_id=DEST_CHANNEL_ID,
                    from_chat_id=source_chat,
                    message_id=current
                )
                burst_count += 1
                current += 1

            except TelegramAPIError as e:
                if getattr(e, "retry_after", None):
                    wait_time = e.retry_after
                    now = datetime.now()
                    log_message = (
                        f"[{now.strftime('%H:%M:%S')}] FLOOD WAIT HIT.\n"
                        f"  - Messages in burst: {burst_count}\n"
                        f"  - Cooldown required: {wait_time} seconds"
                    )
                    await send_log(bot, log_message)
                    
                    await asyncio.sleep(wait_time)
                    burst_count = 0 # Reset counter after waiting
                    await send_log(bot, f"[{datetime.now().strftime('%H:%M:%S')}] Resuming...")
                    continue # Retry the same message
                else:
                    await send_log(bot, f"API Error at {current}: {e}")
                    current += 1 # Skip this message on other API errors
            except Exception as e:
                await send_log(bot, f"Unexpected Error at {current}: {e}")
                current += 1 # Skip this message on other errors
            
            # No delay here to push the API to its limit
            await asyncio.sleep(0) 

        end_time = datetime.now()
        await send_log(bot, f"--- Test Complete ---\nTotal time: {end_time - start_time}")

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
    
