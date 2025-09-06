import asyncio
import nest_asyncio
import os
import json
import glob
import random
import argparse  # NEW: For command-line arguments
from telegram import Bot
from telegram.error import BadRequest, RetryAfter, TimedOut, NetworkError

# Allow nested asyncio
nest_asyncio.apply()

# ====== CONFIGURATION & CONSTANTS ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# NEW: State file to track progress
STATE_FILE = "progress.json"

# NEW: Telegram API limits for validation
LIMITS = {
    "POLL_QUESTION": 300,
    "POLL_OPTION": 100,
    "POLL_EXPLANATION": 200,
    "POLL_MAX_OPTIONS": 10,
    "MESSAGE_TEXT": 4096
}

# NEW: Safer delay settings for bulk sending. Increase if rate limits persist.
# A longer delay reduces the chance of hitting flood waits.
MIN_DELAY_SECONDS = 3.0
MAX_DELAY_SECONDS = 5.0


# ====== STATE MANAGEMENT FUNCTIONS ======

def load_progress(filename=STATE_FILE):
    """Loads the index of the last successfully sent item."""
    try:
        with open(filename, 'r') as f:
            progress = json.load(f)
            index = int(progress.get('last_sent_index', 0))
            print(f"✅ Loaded progress. Resuming from index {index}.")
            return index
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        print("ℹ️ No valid progress file found. Starting from beginning.")
        return 0


def save_progress(index, filename=STATE_FILE):
    """Saves the index of the next item to be sent."""
    try:
        with open(filename, 'w') as f:
            json.dump({'last_sent_index': index}, f)
    except IOError as e:
        print(f"❌ CRITICAL: Failed to save progress to {filename}. Error: {e}")


# ====== DATA LOADING & VALIDATION ======

def load_items(file_path):
    """Loads items from a specified JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            items = json.load(f)
        print(f"✅ Successfully loaded {len(items)} items from {file_path}")
        return items
    except FileNotFoundError:
        print(f"❌ Error: The file {file_path} was not found.")
        return None
    except json.JSONDecodeError:
        print(f"❌ Error: The file {file_path} is not a valid JSON file.")
        return None


def validate_data(item_list):
    """Pre-validates all items against Telegram API limits."""
    print("\n🔍 Starting pre-validation process...")
    errors = []
    for i, item in enumerate(item_list):
        content_type = item.get('type', 'poll')

        if content_type == 'poll':
            question = item.get('question', '')
            options = item.get('options', [])
            explanation = item.get('explanation', '')

            if not question:
                errors.append(f"Item #{i+1}: Poll question is empty.")
            if len(question) > LIMITS["POLL_QUESTION"]:
                errors.append(f"Item #{i+1}: Question length ({len(question)}) exceeds limit ({LIMITS['POLL_QUESTION']}).")
            if len(options) > LIMITS["POLL_MAX_OPTIONS"]:
                errors.append(f"Item #{i+1}: Option count ({len(options)}) exceeds limit ({LIMITS['POLL_MAX_OPTIONS']}).")
            if len(options) < 2:
                errors.append(f"Item #{i+1}: Poll must have at least 2 options.")
            for opt_idx, option in enumerate(options):
                if len(option) > LIMITS["POLL_OPTION"]:
                    errors.append(f"Item #{i+1} Option #{opt_idx+1}: Length ({len(option)}) exceeds limit ({LIMITS['POLL_OPTION']}).")
            if explanation and len(explanation) > LIMITS["POLL_EXPLANATION"]:
                # Note: safe_send can trim this, but it's good to flag it early.
                print(f"⚠️ Warning (Item #{i+1}): Explanation length ({len(explanation)}) exceeds limit ({LIMITS['POLL_EXPLANATION']}). Will be trimmed automatically.")

        elif content_type == 'message':
            text = item.get('text', '')
            if not text:
                errors.append(f"Item #{i+1}: Message text is empty.")
            if len(text) > LIMITS["MESSAGE_TEXT"]:
                errors.append(f"Item #{i+1}: Message length ({len(text)}) exceeds limit ({LIMITS['MESSAGE_TEXT']}).")

    if errors:
        print(f"❌ Validation failed with {len(errors)} critical errors:")
        for error in errors:
            print(f"  - {error}")
        return False, "\n".join(errors)
    else:
        print("✅ Validation successful. All items conform to basic limits.")
        return True, ""


# ====== TELEGRAM APICORE FUNCTIONS ======

async def send_error_to_telegram(bot, error_message):
    """Sends a formatted error message to the Telegram channel."""
    try:
        # Truncate message if it's too long for a single Telegram message
        safe_message = error_message[:4000]
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"🤖 BOT ERROR 🤖\n\n<pre>{safe_message}</pre>",
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"❌ CRITICAL: Failed to send error message to Telegram: {e}")


async def safe_send(bot, func, *args, retries=5, **kwargs):
    """Safely send Telegram requests with retry, flood control, and dynamic error handling."""
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:
            wait_time = int(e.retry_after) + 1
            print(f"⏳ Flood control: received RetryAfter({e.retry_after}s). Waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        except (TimedOut, NetworkError) as e:
            wait_seconds = 3 * attempt
            print(f"⚠️ Network issue on attempt {attempt}: {e}. Retrying in {wait_seconds}s...")
            await asyncio.sleep(wait_seconds)
        except BadRequest as e:
            error_text = str(e).lower()
            if "explanation" in kwargs and ("message is too long" in error_text or "too long" in error_text):
                explanation = kwargs.get("explanation", "")
                if explanation:
                    # Trim to a very safe length to ensure success on retry
                    trimmed = explanation[:LIMITS["POLL_EXPLANATION"] - 10]
                    print(f"⚠️ Explanation auto-trimmed from {len(explanation)} to {len(trimmed)} chars due to API error.")
                    kwargs["explanation"] = trimmed
                    continue  # Retry immediately with trimmed text
            # If error is not a known fixable issue, raise it to be caught by the main loop.
            print(f"❌ Unrecoverable BadRequest on attempt {attempt}: {e}")
            raise e
        except Exception as e:
            print(f"⚠️ Unexpected error on attempt {attempt}: {e}")
            if attempt == retries:
                raise e
            await asyncio.sleep(2 * attempt)
    raise Exception(f"Failed to send message after {retries} attempts.")


# ====== MAIN PROCESSING LOGIC ======

async def process_content(json_file_path):
    """Main function to validate, process, and send all content."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Error: BOT_TOKEN or CHAT_ID environment variables are not set. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)

    # 1. Load Data
    item_list = load_items(json_file_path)
    if not item_list:
        return

    # 2. Pre-validate Data
    is_valid, error_summary = validate_data(item_list)
    if not is_valid:
        await send_error_to_telegram(bot, f"Pre-validation failed. Fix errors in source file.\n\nErrors:\n{error_summary}")
        return

    # 3. Load Progress and Prepare Item Queue
    start_index = load_progress()
    items_to_process = item_list[start_index:]
    total_new = len(items_to_process)

    if total_new == 0:
        print("\n✅ All items have already been sent according to progress file.")
        return

    print(f"\n🚀 Starting to send {total_new} new items...")

    # 4. Process and Send Items
    for i, item in enumerate(items_to_process):
        absolute_index = start_index + i
        content_type = item.get('type', 'poll')
        print(f"--> Processing item {absolute_index + 1} of {len(item_list)} (type: {content_type})...")

        try:
            if content_type == 'message':
                await safe_send(bot, bot.send_message, chat_id=CHAT_ID, text=item['text'], parse_mode='HTML')

            elif content_type == 'poll':
                question_text = f"[MediX]\n{item['question']}" # Add your prefix here if desired
                poll_kwargs = {
                    "chat_id": CHAT_ID,
                    "question": question_text,
                    "options": item["options"],
                    "is_anonymous": True,
                }
                correct_option_id = item.get('correct_option')

                if correct_option_id is not None:
                    poll_kwargs.update({
                        "type": "quiz",
                        "correct_option_id": correct_option_id,
                        "explanation": item.get('explanation')
                    })
                else:
                    poll_kwargs.update({"type": "regular"})
                
                await safe_send(bot, bot.send_poll, **poll_kwargs)

            # NEW: Save progress *after* successful send
            save_progress(absolute_index + 1)
            print(f"    Item {absolute_index + 1} sent successfully. Progress saved.")

            # NEW: Apply proactive delay to avoid rate limits
            delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
            await asyncio.sleep(delay)

        except Exception as e:
            error_details = f"Failed to send item #{absolute_index + 1}.\nType: {content_type}\nError: {e}"
            print(f"❌ {error_details}")
            await send_error_to_telegram(bot, error_details)
            print("🛑 Script halted due to unrecoverable error during sending. Fix issue and re-run to resume progress.")
            return

    print("\n✅ Finished sending all content.")


# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    # NEW: Argument parser to accept JSON file path
    parser = argparse.ArgumentParser(description="Telegram Poll Bot with Resumability")
    parser.add_argument("json_file", help="Path to the source JSON file containing polls/messages.")
    args = parser.parse_args()

    asyncio.run(process_content(args.json_file))
