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

# --- EDIT YOUR SETTINGS HERE ---
# The number of polls to send in each batch.
BATCH_SIZE = 19
# The pause in seconds between each batch.
BATCH_DELAY_SECONDS = 20
# --- END OF SETTINGS ---

LOG_FILE = "bot.log"
QUESTION_PREFIX = "[MediX]\n"

LIMITS = {
    "POLL_QUESTION": 300,
    "POLL_OPTION": 100,
    "POLL_EXPLANATION": 200,
    "POLL_MAX_OPTIONS": 10,
    "MESSAGE_TEXT": 4096
}

# Delay between each individual poll to avoid rate limits
MIN_DELAY_SECONDS = 1.0
MAX_DELAY_SECONDS = 2.0

# ====== LOGGING SETUP ======
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

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
        
        except BadRequest as e:
            error_text = str(e).lower()
            if "too long" in error_text:
                if 'question' in kwargs and len(kwargs['question']) > LIMITS["POLL_QUESTION"]:
                    original_len = len(kwargs['question'])
                    kwargs['question'] = kwargs['question'][:LIMITS["POLL_QUESTION"]]
                    logging.warning(f"Caught BadRequest. Question auto-trimmed from {original_len} to {len(kwargs['question'])}. Retrying.")
                    continue
                elif 'explanation' in kwargs and kwargs.get('explanation') and len(kwargs['explanation']) > LIMITS["POLL_EXPLANATION"]:
                    original_len = len(kwargs['explanation'])
                    kwargs['explanation'] = kwargs['explanation'][:LIMITS["POLL_EXPLANATION"] - 5]
                    logging.warning(f"Caught BadRequest. Explanation auto-trimmed from {original_len} to {len(kwargs['explanation'])}. Retrying.")
                    continue
            
            logging.error(f"Unrecoverable BadRequest on attempt {attempt}: {e}")
            raise e

        except (TimedOut, NetworkError) as e:
            error_text = str(e).lower()
            if "too long" in error_text:
                if 'question' in kwargs and len(kwargs['question']) > LIMITS["POLL_QUESTION"]:
                    original_len = len(kwargs['question'])
                    kwargs['question'] = kwargs['question'][:LIMITS["POLL_QUESTION"]]
                    logging.warning(f"Caught NetworkError wrapping 'too long'. Question auto-trimmed from {original_len} to {len(kwargs['question'])}. Retrying.")
                    continue
                elif 'explanation' in kwargs and kwargs.get('explanation') and len(kwargs['explanation']) > LIMITS["POLL_EXPLANATION"]:
                    original_len = len(kwargs['explanation'])
                    kwargs['explanation'] = kwargs['explanation'][:LIMITS["POLL_EXPLANATION"] - 5]
                    logging.warning(f"Caught NetworkError wrapping 'too long'. Explanation auto-trimmed from {original_len} to {len(kwargs['explanation'])}. Retrying.")
                    continue
            
            wait_seconds = 3 * attempt
            logging.warning(f"Network issue on attempt {attempt}: {e}. Retrying in {wait_seconds}s...")
            await asyncio.sleep(wait_seconds)

        except Exception as e:
            logging.error(f"Unexpected error on attempt {attempt}: {e}")
            if attempt == 5: raise e
            await asyncio.sleep(2 * attempt)
            
    raise Exception(f"Failed to send message after 5 attempts.")

# ====== MAIN PROCESSING LOGIC ======
async def process_items_in_batches(json_file_path):
    if not BOT_TOKEN or not CHAT_ID:
        logging.critical("BOT_TOKEN or CHAT_ID environment variables are not set. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)
    await send_log_to_telegram(bot, "Bot script started a new run.", "INFO")

    item_list = load_items(json_file_path)
    if not item_list: return

    is_valid, error_summary = validate_data(item_list)
    if not is_valid:
        await send_log_to_telegram(bot, f"Pre-validation failed. Fix errors in source file.\n\nErrors:\n{error_summary}", "CRITICAL")
        raise SystemExit("Validation failed. Halting execution.")

    total_items = len(item_list)
    logging.info(f"Starting to send all {total_items} items in batches of {BATCH_SIZE}...")
    await send_log_to_telegram(bot, f"Processing {total_items} items from {json_file_path} in batches of {BATCH_SIZE}.")

    for i, item in enumerate(item_list):
        content_type = item.get('type', 'poll')
        logging.info(f"Processing item {i + 1} of {total_items} (type: {content_type})...")

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

            logging.info(f"Item {i + 1} sent successfully.")

            # Short delay between each message
            delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
            await asyncio.sleep(delay)
            
            # Check if a batch is complete and apply the long delay
            # We use (i + 1) because 'i' is 0-indexed.
            # We also check that this is not the very last item in the list to avoid a pointless final pause.
            if (i + 1) % BATCH_SIZE == 0 and (i + 1) < total_items:
                log_message = f"✅ Batch of {BATCH_SIZE} complete ({i + 1}/{total_items} sent). Pausing for {BATCH_DELAY_SECONDS} seconds."
                logging.info(log_message)
                await send_log_to_telegram(bot, log_message, "INFO")
                await asyncio.sleep(BATCH_DELAY_SECONDS)

        except Exception as e:
            error_details = f"Failed to send item #{i + 1}.\nType: {content_type}\nError: {e}"
            logging.critical(error_details)
            await send_log_to_telegram(bot, error_details, "CRITICAL")
            raise SystemExit("Halting due to unrecoverable error during sending.")

    logging.info(f"Successfully sent all {total_items} items.")
    await send_log_to_telegram(bot, f"🎉 All {total_items} items sent successfully! Task complete.", "INFO")

# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telegram Poll Bot with Batch Sending")
    parser.add_argument("json_file", help="Path to the source JSON file.")
    args = parser.parse_args()

    asyncio.run(process_items_in_batches(args.json_file))
