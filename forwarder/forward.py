import asyncio
import os
import re
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# --- Configuration ---
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# --- File Paths ---
# Corrected path for running within the 'forwarder' working directory
RANGE_FILE = "forwardrange.txt"

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

def parse_range_file():
    """Reads the range file and extracts the source channel, start ID, and end ID."""
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
    """Sends a message to the log channel, ignoring any errors."""
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text, disable_web_page_preview=True)
        except:
            pass

def create_progress_bar(progress, total, length=10):
    """Creates a text-based progress bar."""
    if total <= 0: return '░' * length
    filled_length = int(length * progress // total)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return bar

async def main():
    """Main function to run the forwarder bot."""
    source_user, start_id, end_id = parse_range_file()
    source_chat = f"@{source_user}"
    sent, skipped, failed = 0, 0, 0
    skipped_links = []

    start_time = datetime.now()
    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        start_message = (
            f"🚀 <b>Forwarder Initialized (Burst Mode)</b> 🚀\n"
            f"━━━━━━━━━━━━━━━\n"
            f"➤ <b>Source:</b> <code>{source_chat}</code>\n"
            f"➤ <b>Range:</b> <code>{start_id}</code> to <code>{end_id}</code>\n"
            f"➤ <b>Destination:</b> <code>{DEST_CHANNEL_ID}</code>\n"
            f"━━━━━━━━━━━━━━━"
        )
        await send_log(bot, start_message)
        
        current = start_id
        # --- Burst and Pause Configuration ---
        DELAY_BETWEEN_MESSAGES = 0.2 
        BURST_SIZE = 18
        BURST_PAUSE_DURATION = 35

        while current <= end_id:
            try:
                await bot.copy_message(
                    chat_id=DEST_CHANNEL_ID,
                    from_chat_id=source_chat,
                    message_id=current
                )
                sent += 1
            except TelegramBadRequest as e:
                error_text = str(e).lower()
                skipped_link = f"https://t.me/{source_user}/{current}"
                if "message to copy not found" in error_text:
                    await send_log(bot, f"🗑️ <b>Skipped (Deleted):</b> {skipped_link}")
                else:
                    await send_log(bot, f"⏭️ <b>Skipped (Uncopyable):</b> {skipped_link}")
                skipped += 1
                skipped_links.append(skipped_link)
            except TelegramAPIError as e:
                if getattr(e, "retry_after", None):
                    wait_time = e.retry_after
                    await send_log(bot, f"💥 <b>Unexpected FloodWait:</b> Sleeping for <code>{wait_time}s</code> at ID <code>{current}</code>")
                    await asyncio.sleep(wait_time)
                    continue 
                else:
                    failed += 1
                    await send_log(bot, f"⚠️ <b>API Error at ID {current}:</b> <code>{e}</code>")
            except Exception as e:
                failed += 1
                await send_log(bot, f"💥 <b>Unexpected Error at ID {current}:</b> <code>{e}</code>")

            processed_count = sent + skipped
            
            if processed_count > 0 and processed_count % BURST_SIZE == 0:
                await send_log(bot, f"⏱️ <b>Burst complete.</b> Pausing for <code>{BURST_PAUSE_DURATION}s</code> to cool down...")
                await asyncio.sleep(BURST_PAUSE_DURATION)
            
            if processed_count > 0 and processed_count % 25 == 0:
                total_messages = end_id - start_id + 1
                percentage = (processed_count / total_messages) * 100
                progress_bar = create_progress_bar(processed_count, total_messages)
                progress_message = (
                    f"⏳ <b>Progress Update</b>\n"
                    f"<code>[{progress_bar}] {percentage:.1f}%</code>\n\n"
                    f"- <b>Sent:</b> <code>{sent}</code>\n"
                    f"- <b>Skipped:</b> <code>{skipped}</code>\n"
                    f"- <b>Failed:</b> <code>{failed}</code>\n"
                    f"- <b>Last ID:</b> <code>{current}</code>"
                )
                await send_log(bot, progress_message)
            
            current += 1
            await asyncio.sleep(DELAY_BETWEEN_MESSAGES)

        end_time = datetime.now()
        
        total_time = end_time - start_time
        skipped_report = "\n".join(skipped_links) if skipped_links else "None"
        final_report = (
            f"🎉 <b>Forwarding Complete!</b> 🎉\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📊 <b>Final Statistics</b>\n"
            f"➤ <b>Sent:</b> <code>{sent}</code>\n"
            f"➤ <b>Skipped:</b> <code>{skipped}</code>\n"
            f"➤ <b>Failed:</b> <code>{failed}</code>\n"
            f"➤ <b>Total Processed:</b> <code>{sent + skipped + failed}</code>\n\n"
            f"⏱️ <b>Time Information</b>\n"
            f"➤ <b>Started:</b> <code>{start_time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            f"➤ <b>Finished:</b> <code>{end_time.strftime('%Y-%m-%d %H:%M:%S')}</code>\n"
            f"➤ <b>Duration:</b> <code>{str(total_time).split('.')[0]}</code>\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📋 <b>Skipped Messages</b>\n"
            f"{skipped_report}"
        )
        await send_log(bot, final_report)

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())
                    
