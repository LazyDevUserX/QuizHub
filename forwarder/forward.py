import asyncio
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
RANGE_FILE = "forwarder/forwardrange.txt"

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

def parse_range_file():
    content = open(RANGE_FILE, "r").read()
    matches = LINK_RE.findall(content)
    if len(matches) < 2:
        raise Exception(f"{RANGE_FILE} must contain at least 2 message links from the same channel")
    (user1, id1), (user2, id2) = matches[0], matches[1]
    if user1 != user2:
        raise Exception("Both links must be from the same channel")
    start_id, end_id = min(int(id1), int(id2)), max(int(id1), int(id2))
    return f"@{user1}", start_id, end_id

async def send_log(bot, text):
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text)
        except:
            pass

async def main():
    source_chat, start_id, end_id = parse_range_file()
    sent, skipped, failed = 0, 0, 0
    start_time = datetime.now()

    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 Starting forward: {source_chat} [{start_id}..{end_id}] → {DEST_CHANNEL_ID}\nStart time: {start_time}")

        current = start_id
        while current <= end_id:
            success = False
            while not success:
                try:
                    await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=source_chat, message_id=current)
                    sent += 1
                    success = True
                except TelegramBadRequest:
                    # Skip only if message type truly unsupported (rare)
                    skipped += 1
                    success = True
                except TelegramAPIError as e:
                    if getattr(e, "retry_after", None):
                        await send_log(bot, f"⏳ FloodWait: sleeping {e.retry_after}s at ID {current}")
                        await asyncio.sleep(e.retry_after + 1)
                    else:
                        failed += 1
                        await send_log(bot, f"⚠️ API error at {current}: {e}")
                        await asyncio.sleep(1)
                except Exception as e:
                    failed += 1
                    await send_log(bot, f"💥 Unexpected error at {current}: {e}")
                    await asyncio.sleep(1)

            if sent % 50 == 0 and sent > 0:
                await send_log(bot, f"✅ Progress: sent={sent}, skipped={skipped}, failed={failed}, last_id={current}")

            current += 1

        end_time = datetime.now()
        total_time = end_time - start_time
        await send_log(bot, f"🎉 Forward complete!\nSent={sent}, Skipped={skipped}, Failed={failed}\nStart: {start_time}\nEnd: {end_time}\nTotal time: {total_time}")

if __name__ == "__main__":
    asyncio.run(main())
