import asyncio
import os
import re
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.types import Message, Poll
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# ----- CONFIG -----
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))
RANGE_FILE = "forwarder/forwardrange.txt"

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

async def send_log(bot, text):
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text)
        except:
            pass

# ----- FORWARD -----
async def forward_message(bot: Bot, msg: Message):
    """Forward any message, try copy first, then fallback by type"""
    try:
        await bot.copy_message(chat_id=DEST_CHANNEL_ID, from_chat_id=msg.chat.id, message_id=msg.message_id)
        return True
    except TelegramBadRequest:
        # fallback by type
        try:
            if msg.text:
                await bot.send_message(DEST_CHANNEL_ID, msg.text)
            elif msg.poll:
                p: Poll = msg.poll
                await bot.send_poll(
                    DEST_CHANNEL_ID,
                    question=p.question,
                    options=[o.text for o in p.options],
                    type=p.type,
                    is_anonymous=p.is_anonymous,
                    allows_multiple_answers=p.allows_multiple_answers
                )
            elif msg.photo:
                await bot.send_photo(DEST_CHANNEL_ID, photo=msg.photo[-1].file_id, caption=msg.caption or "")
            elif msg.video:
                await bot.send_video(DEST_CHANNEL_ID, video=msg.video.file_id, caption=msg.caption or "")
            elif msg.document:
                await bot.send_document(DEST_CHANNEL_ID, document=msg.document.file_id, caption=msg.caption or "")
            elif msg.audio:
                await bot.send_audio(DEST_CHANNEL_ID, audio=msg.audio.file_id, caption=msg.caption or "")
            elif msg.voice:
                await bot.send_voice(DEST_CHANNEL_ID, voice=msg.voice.file_id, caption=msg.caption or "")
            elif msg.sticker:
                await bot.send_sticker(DEST_CHANNEL_ID, sticker=msg.sticker.file_id)
            else:
                # cannot forward unsupported message types
                return False
            return True
        except TelegramAPIError:
            return False
    except TelegramAPIError:
        return False

# ----- MAIN -----
async def main():
    source_chat, start_id, end_id = parse_range_file()
    sent, skipped = 0, 0
    start_time = datetime.now()

    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 Starting forward: {source_chat} [{start_id}..{end_id}] → {DEST_CHANNEL_ID}\nStart time: {start_time}")

        for message_id in range(start_id, end_id + 1):
            msg = None
            try:
                msg = await bot.get_message(chat_id=source_chat, message_id=message_id)
            except TelegramAPIError as e:
                if getattr(e, "retry_after", None):
                    await asyncio.sleep(e.retry_after + 1)
                else:
                    skipped += 1
                    continue
            except Exception:
                skipped += 1
                continue

            if msg:
                success = await forward_message(bot, msg)
                if success:
                    sent += 1
                else:
                    skipped += 1

            if sent % 50 == 0:
                await send_log(bot, f"✅ Progress: sent={sent}, skipped={skipped}, last_id={message_id}")

        end_time = datetime.now()
        total_time = end_time - start_time
        await send_log(bot, f"🎉 Forward complete!\nSent={sent}, Skipped={skipped}\nStart: {start_time}\nEnd: {end_time}\nTotal time: {total_time}")

if __name__ == "__main__":
    asyncio.run(main())
