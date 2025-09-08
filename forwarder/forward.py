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
RANGE_FILE = "forwardrange.txt"

LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

def parse_range_file():
    """
    Parses the range file for multiple ranges and text messages,
    returning an ordered list of tasks.
    """
    tasks = []
    current_range_links = []

    with open(RANGE_FILE, "r") as f:
        lines = f.readlines()

    def process_pending_range():
        if not current_range_links:
            return

        source_user = current_range_links[0][0]
        for user, _ in current_range_links:
            if user != source_user:
                raise Exception("All links in a single range must be from the same channel.")
        
        ids = [int(msg_id) for _, msg_id in current_range_links]
        start_id, end_id = min(ids), max(ids)
        
        tasks.append({
            "type": "forward",
            "source": f"@{source_user}",
            "source_user": source_user,
            "start": start_id,
            "end": end_id
        })
        current_range_links.clear()

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        match = LINK_RE.search(line)
        if match:
            current_range_links.append(match.groups())
        else:
            process_pending_range()
            tasks.append({"type": "text", "content": line})

    process_pending_range() # Process any remaining range at the end of the file
    return tasks

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
    tasks = parse_range_file()
    if not tasks:
        print("No tasks found in range file. Exiting.")
        return

    sent, skipped, failed = 0, 0, 0
    skipped_links = []
    
    # Calculate total messages for progress bar across all forward tasks
    total_messages_to_forward = sum(
        (task['end'] - task['start'] + 1) for task in tasks if task['type'] == 'forward'
    )

    start_time = datetime.now()
    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 <b>Multi-Task Forwarder Initialized</b> 🚀\nFound <code>{len(tasks)}</code> tasks to execute.")
        
        # --- Data-Driven Burst Configuration ---
        DELAY_BETWEEN_MESSAGES = 0.2
        BURST_SIZE = 20
        BURST_PAUSE_DURATION = 42

        for i, task in enumerate(tasks, 1):
            await send_log(bot, f"▶️ Starting Task {i}/{len(tasks)}: <code>{task['type'].upper()}</code>")

            if task['type'] == 'text':
                try:
                    await bot.send_message(DEST_CHANNEL_ID, task['content'])
                    await send_log(bot, f"  ✍️ Sent custom text: \"{task['content'][:50]}...\"")
                except Exception as e:
                    await send_log(bot, f"  💥 Failed to send text: {e}")
                await asyncio.sleep(1) # Small delay after sending text

            elif task['type'] == 'forward':
                source_chat = task['source']
                source_user = task['source_user']
                start_id = task['start']
                end_id = task['end']
                
                current = start_id
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

                    processed_forwarded_count = sent + skipped
                    
                    if processed_forwarded_count > 0 and processed_forwarded_count % BURST_SIZE == 0 and current < end_id:
                        await send_log(bot, f"⏱️ <b>Burst complete.</b> Pausing for <code>{BURST_PAUSE_DURATION}s</code>...")
                        await asyncio.sleep(BURST_PAUSE_DURATION)
                    
                    if processed_forwarded_count > 0 and processed_forwarded_count % 25 == 0:
                        percentage = (processed_forwarded_count / total_messages_to_forward) * 100
                        progress_bar = create_progress_bar(processed_forwarded_count, total_messages_to_forward)
                        progress_message = (
                            f"⏳ <b>Overall Progress</b>\n"
                            f"<code>[{progress_bar}] {percentage:.1f}%</code>\n\n"
                            f"- <b>Sent:</b> <code>{sent}</code>\n"
                            f"- <b>Skipped:</b> <code>{skipped}</code>\n"
                            f"- <b>Failed:</b> <code>{failed}</code>\n"
                            f"- <b>Last ID:</b> <code>{current}</code>"
                        )
                        await send_log(bot, progress_message)
                    
                    current += 1
                    await asyncio.sleep(DELAY_BETWEEN_MESSAGES)
            
            await send_log(bot, f"✅ Task {i}/{len(tasks)} complete.")

        end_time = datetime.now()
        total_time = end_time - start_time
        skipped_report = "\n".join(skipped_links) if skipped_links else "None"
        final_report = (
            f"🎉 <b>All Tasks Complete!</b> 🎉\n"
            # ... (Final report format is the same)
        )
        await send_log(bot, final_report)

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    asyncio.run(main())

