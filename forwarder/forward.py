import asyncio
import logging
import os
import re
import sys
import json
from aiogram import Bot
from aiogram.utils.exceptions import MessageToForwardNotFound, RetryAfter, TelegramAPIError

API_TOKEN = os.getenv("BOT_TOKEN")  # from GitHub Secrets
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

RANGE_FILE = os.getenv("RANGE_FILE", "forwarder/forwardrange.txt")
STATE_FILE = os.getenv("STATE_FILE", "forwarder/progress.json")

LINK_RE = re.compile(r"https?://t\\.me/([A-Za-z0-9_]+)/([0-9]+)")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def send_log(bot: Bot, text: str):
    """Send logs to log channel (if available)."""
    if LOG_CHANNEL_ID and LOG_CHANNEL_ID != 0:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text)
        except Exception as e:
            logging.warning(f"Failed to send log: {e}")
    else:
        logging.info(f"LOG >> {text}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def parse_range_file(path: str):
    if not os.path.exists(path):
        return None
    content = open(path, "r", encoding="utf-8").read()
    matches = LINK_RE.findall(content)
    if len(matches) < 2:
        return None
    (user1, id1), (user2, id2) = matches[0], matches[1]
    if user1 != user2:
        return None
    start_id = min(int(id1), int(id2))
    end_id = max(int(id1), int(id2))
    return "@" + user1, start_id, end_id


async def forward_range():
    if not (API_TOKEN and DEST_CHANNEL_ID and LOG_CHANNEL_ID):
        print("❌ BOT_TOKEN, DEST_CHANNEL_ID, LOG_CHANNEL_ID must be set")
        sys.exit(1)

    parsed = parse_range_file(RANGE_FILE)
    if not parsed:
        print("❌ forwardrange.txt must contain at least 2 message links from the same channel")
        sys.exit(1)

    source_chat, start_id, end_id = parsed
    state = load_state()
    last_done = int(state.get("last_done", start_id - 1))
    current = max(last_done + 1, start_id)

    sent, skipped, failed = 0, 0, 0

    async with Bot(token=API_TOKEN, parse_mode="HTML") as bot:
        await send_log(bot, f"🚀 Starting copy: {source_chat} [{start_id}..{end_id}] → {DEST_CHANNEL_ID}")

        while current <= end_id:
            try:
                await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=source_chat, message_id=current)
                sent += 1
            except MessageToForwardNotFound:
                skipped += 1
            except RetryAfter as e:
                await send_log(bot, f"⏳ FloodWait: sleeping {e.timeout}s at ID {current}")
                await asyncio.sleep(e.timeout + 1)
                continue
            except TelegramAPIError as e:
                failed += 1
                await send_log(bot, f"⚠️ API error at {current}: {e}")
            except Exception as e:
                failed += 1
                await send_log(bot, f"💥 Unexpected error at {current}: {e}")
            finally:
                state["last_done"] = current
                save_state(state)
                current += 1

            if sent % 500 == 0 and sent > 0:
                await send_log(bot, f"✅ Progress: {sent} copied, {skipped} skipped, {failed} failed. Last ID: {current}")

        await send_log(bot, f"🎉 Copy complete\nSent: {sent}\nSkipped: {skipped}\nFailed: {failed}")


if __name__ == "__main__":
    asyncio.run(forward_range())
