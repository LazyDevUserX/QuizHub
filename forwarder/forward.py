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
RANGE_FILE = "forwarder/forwardrange.txt"

# ... (parse_range_file, send_log, create_progress_bar functions remain the same) ...

async def main():
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
        # --- NEW: Burst and Pause Configuration ---
        # Short delay between individual messages in a burst
        DELAY_BETWEEN_MESSAGES = 0.2 
        # Number of messages to send before pausing
        BURST_SIZE = 18
        # Seconds to pause after a burst to cool down
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
                # ... (error handling remains the same) ...
                skipped += 1
                skipped_links.append(f"https://t.me/{source_user}/{current}")
            except TelegramAPIError as e:
                # This is now a safety net; it ideally shouldn't be triggered.
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
            
            # --- NEW: Burst and Pause Logic ---
            if processed_count > 0 and processed_count % BURST_SIZE == 0:
                await send_log(bot, f"⏱️ <b>Burst complete.</b> Pausing for <code>{BURST_PAUSE_DURATION}s</code> to cool down...")
                await asyncio.sleep(BURST_PAUSE_DURATION)
            
            # Progress update logic (now triggers every 25 messages)
            if processed_count > 0 and processed_count % 25 == 0:
                # ... (progress update log message remains the same) ...
                pass # The full progress log can be pasted here if you want it
            
            current += 1
            await asyncio.sleep(DELAY_BETWEEN_MESSAGES)

        # ... (Final report logic remains the same) ...

if __name__ == "__main__":
    # ... (__main__ block remains the same) ...
