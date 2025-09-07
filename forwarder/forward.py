import asyncio
import os
import re
import json # <-- Added for JSON indexing
from datetime import datetime
from aiogram import Bot
from aiogram.client.bot import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

# --- Configuration ---
# Loaded from environment variables for security and flexibility
API_TOKEN = os.getenv("BOT_TOKEN")
DEST_CHANNEL_ID = int(os.getenv("DEST_CHANNEL_ID", "0"))
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0"))

# --- File Paths ---
# Placed in a subfolder as per your original setup
RANGE_FILE = "forwarder/forwardrange.txt"
INDEX_FILE = "indexed_messages.json" # <-- For saving text messages

# Regular expression to parse Telegram message links
LINK_RE = re.compile(r"https?://t\.me/([A-Za-z0-9_]+)/([0-9]+)")

def parse_range_file():
    """Reads the range file and extracts the source channel, start ID, and end ID."""
    # Use 'with open' for safe file handling
    with open(RANGE_FILE, "r") as f:
        content = f.read()

    matches = LINK_RE.findall(content)
    if len(matches) < 2:
        raise Exception(f"{RANGE_FILE} must contain at least 2 message links from the same channel")

    (user1, id1), (user2, id2) = matches[0], matches[1]
    if user1 != user2:
        raise Exception("Both links in the range file must be from the same channel")

    start_id, end_id = min(int(id1), int(id2)), max(int(id1), int(id2))
    # Return the clean username, which is more flexible
    return user1, start_id, end_id

async def send_log(bot, text):
    """Sends a message to the log channel, ignoring any errors."""
    if LOG_CHANNEL_ID:
        try:
            await bot.send_message(LOG_CHANNEL_ID, text, disable_web_page_preview=True)
        except:
            # Fire-and-forget logging
            pass

async def main():
    """Main function to run the forwarder bot."""
    source_user, start_id, end_id = parse_range_file()
    source_chat = f"@{source_user}" # The format needed for API calls

    # --- Counters and Data Collectors ---
    sent, skipped, failed = 0, 0, 0
    skipped_links = []
    indexed_messages = [] # <-- List to hold text messages for indexing

    start_time = datetime.now()
    async with Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML")) as bot:
        await send_log(bot, f"🚀 **Starting Forwarder**\n**From:** `{source_chat}`\n**Range:** `{start_id}` to `{end_id}`\n**To:** `{DEST_CHANNEL_ID}`")

        current = start_id
        # Proactive delay to avoid hitting rate limits. The key to speed and stability.
        DELAY_BETWEEN_MESSAGES = 1.2

        while current <= end_id:
            success = False
            try:
                # --- Main Copy Operation ---
                # Capture the returned message object for indexing
                new_message = await bot.copy_message(
                    chat_id=DEST_CHANNEL_ID,
                    from_chat_id=source_chat,
                    message_id=current
                )
                sent += 1
                success = True

                # --- JSON Indexing Logic ---
                # Check if the new message has text or a caption
                message_text = new_message.text or new_message.caption
                if message_text:
                    # Construct the link for a private channel
                    chat_id_for_link = str(DEST_CHANNEL_ID).replace('-100', '')
                    link = f"https://t.me/c/{chat_id_for_link}/{new_message.message_id}"

                    # Add the data to our list for later saving
                    indexed_messages.append({
                        "text": message_text,
                        "link": link
                    })

            except TelegramBadRequest as e:
                # --- Intelligent Skip Handling ---
                error_text = str(e).lower()
                skipped_link = f"https://t.me/{source_user}/{current}"

                if "message to copy not found" in error_text:
                    await send_log(bot, f"🗑️ Skipped (Deleted): {skipped_link}")
                elif "can't be copied" in error_text:
                    await send_log(bot, f"⏭️ Skipped (Uncopyable): {skipped_link}")
                else:
                    await send_log(bot, f"❓ Skipped (Other Reason): {skipped_link}\n`{e}`")

                skipped += 1
                skipped_links.append(skipped_link)
                success = True # Mark as success to move to the next message

            except TelegramAPIError as e:
                # --- Flood Wait Safety Net ---
                if getattr(e, "retry_after", None):
                    wait_time = e.retry_after
                    await send_log(bot, f"⏳ FloodWait: sleeping `{wait_time}s` at ID `{current}`")
                    await asyncio.sleep(wait_time)
                    # Loop will retry the same message ID after sleeping
                else:
                    failed += 1
                    await send_log(bot, f"⚠️ API Error at `{current}`: `{e}`")
                    await asyncio.sleep(1) # Brief pause on other API errors

            except Exception as e:
                failed += 1
                await send_log(bot, f"💥 Unexpected Error at `{current}`: `{e}`")
                await asyncio.sleep(1) # Brief pause

            # --- Progress Update and Loop Control ---
            if success:
                # Log progress every 50 successful sends
                if sent > 0 and sent % 50 == 0:
                    await send_log(bot, f"✅ **Progress:**\n- Sent: `{sent}`\n- Skipped: `{skipped}`\n- Failed: `{failed}`\n- Last ID: `{current}`")
                current += 1

            # The proactive delay happens after every attempt
            await asyncio.sleep(DELAY_BETWEEN_MESSAGES)

        end_time = datetime.now()

        # --- Save Indexed Data to JSON File ---
        if indexed_messages:
            await send_log(bot, f"📝 Saving `{len(indexed_messages)}` text messages to `{INDEX_FILE}`...")
            try:
                existing_data = []
                if os.path.exists(INDEX_FILE):
                    with open(INDEX_FILE, "r", encoding="utf-8") as f:
                        try:
                            existing_data = json.load(f)
                        except json.JSONDecodeError:
                            pass # File is empty or corrupt, start fresh

                existing_data.extend(indexed_messages)

                with open(INDEX_FILE, "w", encoding="utf-8") as f:
                    json.dump(existing_data, f, ensure_ascii=False, indent=4)
            except Exception as e:
                await send_log(bot, f"🔥 Failed to write index file: `{e}`")

        # --- Final Report ---
        total_time = end_time - start_time
        skipped_report = "\n".join(skipped_links) if skipped_links else "None"
        await send_log(
            bot,
            f"🎉 **Forwarding Complete!**\n\n"
            f"**Sent:** `{sent}`\n"
            f"**Skipped:** `{skipped}`\n"
            f"**Failed:** `{failed}`\n\n"
            f"**Total Time:** `{total_time}`\n\n"
            f"**Skipped Message Links:**\n`{skipped_report}`"
        )

if __name__ == "__main__":
    # Load environment variables from a .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("dotenv library not found, skipping. Make sure environment variables are set.")
    
    asyncio.run(main())
                
