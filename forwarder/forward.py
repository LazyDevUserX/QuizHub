import asyncio
import os
import re
import json
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

# ----- CONFIG -----
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
RANGE_FILE = "forwarder/forwardrange.txt"
STATE_FILE = "forwarder/progress.json"

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

# ----- HELPERS -----
def parse_range_file():
    """Return (source_chat, start_id, end_id)"""
    if not os.path.exists(RANGE_FILE):
        raise Exception(f"{RANGE_FILE} not found")
    content = open(RANGE_FILE, "r").read()
    matches = LINK_RE.findall(content)
    if len(matches) < 2:
        raise Exception(f"{RANGE_FILE} must contain at least 2 message links from the same channel")
    (user1, id1), (user2, id2) = matches[0], matches[1]
    if user1 != user2:
        raise Exception("Both links must be from the same channel")
    start_id, end_id = min(int(id1), int(id2)), max(int(id1), int(id2))
    return f"@{user1}", start_id, end_id

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

async def send_log(bot, text):
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text)
        except:
            pass  # ignore log errors

# ----- MAIN -----
async def main():
    if not all([API_TOKEN, DEST_CHANNEL_ID, LOG_CHANNEL_ID]):
        print("❌ BOT_TOKEN, DEST_CHANNEL_ID, LOG_CHANNEL_ID must be set")
        return

    source_chat, start_id, end_id = parse_range_file()
    state = load_state()
    current = max(state.get("last_done", start_id - 1) + 1, start_id)
    sent, skipped, failed = 0, 0, 0

    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 Starting forward: {source_chat} [{start_id}..{end_id}] → {DEST_CHANNEL_ID}")

        while current <= end_id:
            try:
                await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=source_chat, message_id=current)
                sent += 1
            except TelegramAPIError as e:
                if getattr(e, "retry_after", None):
                    await send_log(bot, f"⏳ FloodWait: sleeping {e.retry_after}s at ID {current}")
                    await asyncio.sleep(e.retry_after + 1)
                    continue
                if e.error_code == 400 and "message to forward not found" in e.description.lower():
                    skipped += 1
                else:
                    failed += 1
                    await send_log(bot, f"⚠️ API error at {current}: {e}")
            except Exception as e:
                failed += 1
                await send_log(bot, f"💥 Unexpected error at {current}: {e}")
            finally:
                state["last_done"] = current
                save_state(state)
                current += 1

            if sent % 100 == 0 and sent > 0:
                await send_log(bot, f"✅ Progress: sent={sent}, skipped={skipped}, failed={failed}, last_id={current}")

        await send_log(bot, f"🎉 Done! Sent={sent}, Skipped={skipped}, Failed={failed}")

if __name__ == "__main__":
    asyncio.run(main())
