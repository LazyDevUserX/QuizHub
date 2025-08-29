import os
import time
import re

from telegram import Bot

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")  # fallback if not extracted from link
bot = Bot(token=BOT_TOKEN)

RANGE_FILE = "telegram_bulk_delete/ranges/delete_range.txt"

def extract_ids_from_link(link: str):
    """
    Works with links like:
    - https://t.me/c/123456789/456
    - https://t.me/YourGroup/456
    Returns (chat_id, message_id).
    """
    m = re.search(r"t\.me/(?:c/)?([a-zA-Z0-9_]+)/(\d+)", link.strip())
    if not m:
        raise ValueError(f"Invalid Telegram link format: {link}")
    
    chat_part, msg_id = m.groups()
    msg_id = int(msg_id)

    # If it's a private group (numeric id), prepend -100
    if chat_part.isdigit():
        chat_id = f"-100{chat_part}"
    else:
        chat_id = CHAT_ID or chat_part  # fallback to env

    return chat_id, msg_id

def read_range_from_file():
    start_link = None
    end_link = None
    with open(RANGE_FILE, "r") as f:
        for line in f:
            if line.startswith("START="):
                start_link = line.split("=", 1)[1].strip()
            elif line.startswith("END="):
                end_link = line.split("=", 1)[1].strip()
    if not start_link or not end_link:
        raise ValueError("delete_range.txt must contain START=... and END=... lines")
    return start_link, end_link

def bulk_delete(start_link, end_link):
    chat_id, start_id = extract_ids_from_link(start_link)
    _, end_id = extract_ids_from_link(end_link)

    print(f"🚨 Deleting messages {start_id} → {end_id} in chat {chat_id}")

    for msg_id in range(start_id, end_id + 1):
        try:
            bot.delete_message(chat_id=chat_id, message_id=msg_id)
            print(f"✅ Deleted {msg_id}")
        except Exception as e:
            print(f"⚠️ Could not delete {msg_id}: {e}")
        time.sleep(0.5)  # avoid rate limits

if __name__ == "__main__":
    start, end = read_range_from_file()
    bulk_delete(start, end)
