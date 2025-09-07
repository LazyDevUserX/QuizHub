import asyncio
import os
import re
import json
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
RANGE_FILE = "forwarder/forwardrange.txt"
STATE_FILE = "forwarder/progress.json"

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

# ----- HELPERS -----
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
            pass

# ----- MAIN -----
async def main():
    source_chat, start_id, end_id = parse_range_file()
    state = load_state()
    current = max(state.get("last_done", start_id - 1) + 1, start_id)
    sent = 0

    start_time = datetime.now()

    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 Starting forward: {source_chat} [{start_id}..{end_id}] → {DEST_CHANNEL_ID}\nStart time: {start_time}")

        while current <= end_id:
            success = False
            while not success:
                try:
                    await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=source_chat, message_id=current)
                    success = True
                except TelegramBadRequest:
                    # fallback: fetch original message and resend as text (simplest universal fallback)
                    try:
                        msg = await bot.get_message(chat_id=source_chat, message_id=current)
                        if msg.text or msg.caption:
                            content = msg.text or msg.caption
                            await bot.send_message(chat_id=DEST_CHANNEL_ID, text=content)
                        else:
                            # for media without text, resend as is
                            await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=source_chat, message_id=current)
                        success = True
                    except Exception as e:
                        await asyncio.sleep(1)  # small delay before retrying
                except TelegramAPIError as e:
                    if getattr(e, "retry_after", None):
                        await asyncio.sleep(e.retry_after + 1)
                    else:
                        await asyncio.sleep(1)

            sent += 1
            state["last_done"] = current
            save_state(state)
            current += 1

            if sent % 50 == 0:
                await send_log(bot, f"✅ Progress: sent={sent}, last_id={current-1}")

        end_time = datetime.now()
        total_time = end_time - start_time
        await send_log(bot, f"🎉 Forward complete!\nSent={sent}\nStart: {start_time}\nEnd: {end_time}\nTotal time: {total_time}")

if __name__ == "__main__":
    asyncio.run(main())
