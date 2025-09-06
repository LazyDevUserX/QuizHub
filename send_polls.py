import asyncio
import nest_asyncio
import os
import json
import random
import argparse
import logging
from telegram import Bot
from telegram.error import BadRequest, RetryAfter, TimedOut, NetworkError

# Allow nested asyncio
nest_asyncio.apply()

# ====== CONFIGURATION & CONSTANTS ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID") 

STATE_FILE = "progress.json"
LOG_FILE = "bot.log"
QUESTION_PREFIX = "[MediX]\n"

LIMITS = {
    "POLL_QUESTION": 300,
    "POLL_OPTION": 100,
    "POLL_EXPLANATION": 200,
    "POLL_MAX_OPTIONS": 10,
    "MESSAGE_TEXT": 4096
}

MIN_DELAY_SECONDS = 3.0
MAX_DELAY_SECONDS = 5.0

# ====== LOGGING SETUP ======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# ====== STATE MANAGEMENT ======
def load_progress(filename=STATE_FILE):
    try:
        with open(filename, 'r') as f:
            progress = json.load(f)
            index = int(progress.get('last_sent_index', 0))
            logging.info(f"Loaded progress. Resuming from index {index}.")
            return index
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        logging.info("No valid progress file found. Starting from beginning.")
        return 0

def save_progress(index, filename=STATE_FILE):
    try:
        with open(filename, 'w') as f:
            json.dump({'last_sent_index': index}, f)
    except IOError as e:
        logging.critical(f"Failed to save progress to {filename}. Error: {e}")

# ====== DATA LOADING & VALIDATION ======
def load_items(file_path):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            items = json.load(f)
        logging.info(f"Successfully loaded {len(items)} items from {file_path}")
        return items
    except FileNotFoundError:
        logging.error(f"The file {file_path} was not found.")
        return None
    except json.JSONDecodeError:
        logging.error(f"The file {file_path} is not a valid JSON file.")
        return None

def validate_data(item_list):
    logging.info("Starting pre-validation process...")
    errors = []
    for i, item in enumerate(item_list):
        content_type = item.get('type', 'poll')
        if content_type == 'poll':
            question, options, explanation = item.get('question',''), item.get('options',[]), item.get('explanation','')
            prefixed_question_len = len(QUESTION_PREFIX) + len(question)
            
            if not question: errors.append(f"Item #{i+1}: Poll question is empty.")
            if prefixed_question_len > LIMITS["POLL_QUESTION"]: 
                errors.append(f"Item #{i+1}: Prefixed question length ({prefixed_question_len}) > limit ({LIMITS['POLL_QUESTION']}). Original length: {len(question)}.")
            if len(options) > LIMITS["POLL_MAX_OPTIONS"]: errors.append(f"Item #{i+1}: Option count ({len(options)}) > limit ({LIMITS['POLL_MAX_OPTIONS']}).")
            if len(options) < 2: errors.append(f"Item #{i+1}: Poll must have at least 2 options.")
            for o_idx, opt in enumerate(options):
                if len(opt) > LIMITS["POLL_OPTION"]: errors.append(f"Item #{i+1} Option #{o_idx+1}: Length ({len(opt)}) > limit ({LIMITS['POLL_OPTION']}).")
            if explanation and len(explanation) > LIMITS["POLL_EXPLANATION"]: 
                logging.warning(f"Item #{i+1}: Explanation length ({len(explanation)}) > limit ({LIMITS['POLL_EXPLANATION']}). Will be auto-trimmed if sent.")
        elif content_type == 'message':
            text = item.get('text', '')
            if not text: errors.append(f"Item #{i+1}: Message text is empty.")
            if len(text) > LIMITS["MESSAGE_TEXT"]: errors.append(f"Item #{i+1}: Message length ({len(text)}) > limit ({LIMITS['MESSAGE_TEXT']}).")

    if errors:
        for error in errors: logging.error(f"Validation Error: {error}")
        return False, "\n".join(errors)
    else:
        logging.info("Validation successful. All items conform to basic limits.")
        return True, ""

# ====== TELEGRAM API CORE FUNCTIONS ======
async def send_log_to_telegram(bot, message, level="INFO"):
    if not LOG_CHANNEL_ID: return
    level_icon = {"INFO": "ℹ️", "WARNING": "⚠️", "ERROR": "❌", "CRITICAL": "🔥"}.get(level, "🤖")
    try:
        safe_message = f"{level_icon} {level}\n\n<pre>{message[:4000]}</pre>"
        await bot.send_message(chat_id=LOG_CHANNEL_ID, text=safe_message, parse_mode='HTML')
    except Exception as e:
        logging.error(f"CRITICAL: Failed to send log message to Telegram log channel: {e}")

async def safe_send(bot, func, *args, **kwargs):
    for attempt in range(1, 6):
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:
            wait_time = int(e.retry_after) + 1
            logging.warning(f"Flood control: received RetryAfter({e.retry_after}s). Waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        
        # FIX: Catch BadRequest separately for any truly malformed requests
        except BadRequest as e:
            logging.error(f"Unrecoverable BadRequest on attempt {attempt}: {e}")
            raise e

        # FIX: Catch generic errors, but inspect the message to find our specific "too long" problem.
        except (TimedOut, NetworkError) as e:
            error_text = str(e).lower()
            if "too long" in error_text:
                if 'question' in kwargs and len(kwargs['question']) > LIMITS["POLL_QUESTION"]:
                    original_len = len(kwargs['question'])
                    kwargs['question'] = kwargs['question'][:LIMITS["POLL_QUESTION"]]
                    logging.warning(f"Caught '{error_text}'. Question auto-trimmed from {original_len} to {len(kwargs['question'])}. Retrying.")
                    continue
                
                elif 'explanation' in kwargs and kwargs.get('explanation') and len(kwargs['explanation']) > LIMITS["POLL_EXPLANATION"]:
                    original_len = len(kwargs['explanation'])
                    kwargs['explanation'] = kwargs['explanation'][:LIMITS["POLL_EXPLANATION"] - 5]
                    logging.warning(f"Caught '{error_text}'. Explanation auto-trimmed from {original_len} to {len(kwargs['explanation'])}. Retrying.")
                    continue
            
            # If it's a real network error, wait and retry
            wait_seconds = 3 * attempt
            logging.warning(f"Network issue on attempt {attempt}: {e}. Retrying in {wait_seconds}s...")
            await asyncio.sleep(wait_seconds)

        except Exception as e:
            logging.error(f"Unexpected error on attempt {attempt}: {e}")
            if attempt == 5: raise e
            await asyncio.sleep(2 * attempt)
            
    raise Exception(f"Failed to send message after 5 attempts.")

# ====== MAIN PROCESSING LOGIC ======
async def process_batch(json_file_path, batch_size):
    if not BOT_TOKEN or not CHAT_ID:
        logging.critical("BOT_TOKEN or CHAT_ID environment variables are not set. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)
    await send_log_to_telegram(bot, "Bot script started a new run.", "INFO")

    item_list = load_items(json_file_path)
    if not item_list: return

    start_index = load_progress()
    if start_index == 0:
        is_valid, error_summary = validate_data(item_list)
        if not is_valid:
            await send_log_to_telegram(bot, f"Pre-validation failed. Fix errors in source file.\n\nErrors:\n{error_summary}", "CRITICAL")
            raise SystemExit("Validation failed. Halting execution.")

    items_to_process = item_list[start_index : start_index + batch_size]
    total_new_in_batch = len(items_to_process)
    
    if total_new_in_batch == 0:
        logging.info("All items have already been sent according to progress file.")
        await send_log_to_telegram(bot, "🎉 All items sent successfully! Task complete.", "INFO")
        return

    logging.info(f"Starting to send batch of {total_new_in_batch} new items...")
    await send_log_to_telegram(bot, f"Processing batch of {total_new_in_batch} items, starting from item #{start_index + 1}.")

    for i, item in enumerate(items_to_process):
        absolute_index = start_index + i
        content_type = item.get('type', 'poll')
        logging.info(f"Processing item {absolute_index + 1} of {len(item_list)} (type: {content_type})...")

        try:
            if content_type == 'message':
                await safe_send(bot, bot.send_message, chat_id=CHAT_ID, text=item['text'], parse_mode='HTML')
            elif content_type == 'poll':
                question_text = f"{QUESTION_PREFIX}{item['question']}"
                poll_kwargs = {"chat_id": CHAT_ID, "question": question_text, "options": item["options"], "is_anonymous": True}
                if item.get('correct_option') is not None:
                    poll_kwargs.update({"type": "quiz", "correct_option_id": item['correct_option'], "explanation": item.get('explanation')})
                else:
                    poll_kwargs.update({"type": "regular"})
                await safe_send(bot, bot.send_poll, **poll_kwargs)

            save_progress(absolute_index + 1)
            logging.info(f"Item {absolute_index + 1} sent successfully. Progress saved.")

            delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
            await asyncio.sleep(delay)

        except Exception as e:
            error_details = f"Failed to send item #{absolute_index + 1}.\nType: {content_type}\nError: {e}"
            logging.critical(error_details)
            await send_log_to_telegram(bot, error_details, "CRITICAL")
            raise SystemExit("Halting due to unrecoverable error during sending.")

    logging.info(f"Batch of {total_new_in_batch} items sent successfully.")
    await send_log_to_telegram(bot, f"✅ Batch complete. {total_new_in_batch} items sent.", "INFO")

# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Poll Bot with Batch Processing and Logging")
    parser.add_argument("json_file", help="Path to the source JSON file.")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of items to process in a single run.")
    args = parser.parse_args()

    asyncio.run(process_batch(args.json_file, args.batch_size))

