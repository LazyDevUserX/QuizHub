import asyncio
import nest_asyncio
import os
import json
import glob
import random
from telegram import Bot
from telegram.error import BadRequest, RetryAfter, TimedOut, NetworkError

# Allow nested asyncio
nest_asyncio.apply()

# ====== CONFIGURATION ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ====== FUNCTIONS ======

def find_json_file():
    """Finds the first .json file in the repository's root directory."""
    json_files = glob.glob('*.json')
    if json_files:
        print(f"✅ Found JSON file: {json_files[0]}")
        return json_files[0]
    else:
        print("❌ No .json file found in the repository.")
        return None


def load_items(file_path):
    """Loads items (polls or messages) from a specified JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            items = json.load(f)
        print(f"✅ Successfully loaded {len(items)} items from {file_path}")
        return items
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        print(f"❌ Error: The file {file_path} is not a valid JSON file.")
        return []


async def send_error_to_telegram(bot, error_message):
    """Sends a formatted error message to the Telegram channel."""
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"🤖 BOT ERROR 🤖\n\n<pre>{error_message}</pre>",
            parse_mode='HTML'
        )
    except Exception as e:
        print(f"❌ CRITICAL: Failed to send error message to Telegram: {e}")


async def safe_send(bot, func, *args, retries=5, **kwargs):
    """Safely send Telegram requests with retry, flood control, and error handling."""
    for attempt in range(1, retries + 1):
        try:
            return await func(*args, **kwargs)
        except RetryAfter as e:
            wait_time = int(e.retry_after) + 1
            print(f"⏳ Flood control: waiting {wait_time}s...")
            await asyncio.sleep(wait_time)
        except (TimedOut, NetworkError):
            print(f"⚠️ Network issue on attempt {attempt}, retrying...")
            await asyncio.sleep(3 * attempt)
        except BadRequest as e:
            # Handle explanation too long by trimming
            if "explanation" in kwargs and "message is too long" in str(e).lower():
                explanation = kwargs.get("explanation", "")
                if explanation:
                    trimmed = explanation[:190]  # Telegram limit ~200 chars
                    print(f"⚠️ Explanation trimmed from {len(explanation)} → {len(trimmed)} chars")
                    kwargs["explanation"] = trimmed
                    continue  # retry with trimmed text
            raise
        except Exception as e:
            print(f"⚠️ Unexpected error on attempt {attempt}: {e}")
            if attempt == retries:
                raise
            await asyncio.sleep(2 * attempt)


async def process_content():
    """Main function to process and send all content from the JSON file."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Error: BOT_TOKEN or CHAT_ID is not set. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)
    json_file = find_json_file()

    if not json_file:
        await send_error_to_telegram(bot, "Could not find any .json file to process.")
        return

    item_list = load_items(json_file)
    if not item_list:
        await send_error_to_telegram(bot, f"File '{json_file}' is empty or invalid.")
        return

    print("\n🚀 Starting to send content...")

    for i, item in enumerate(item_list, start=1):
        content_type = item.get('type', 'poll')
        print(f"--> Processing item {i} of {len(item_list)} (type: {content_type})...")

        try:
            if content_type == 'message':
                await safe_send(bot, bot.send_message, chat_id=CHAT_ID, text=item['text'], parse_mode='HTML')

            elif content_type == 'poll':
                question_text = f"[MediX]\n{item['question']}"
                explanation_text = item.get('explanation')
                correct_option_id = item.get('correct_option')

                # QUIZ poll
                if correct_option_id is not None:
                    print("   Type: Quiz Poll")
                    await safe_send(
                        bot,
                        bot.send_poll,
                        chat_id=CHAT_ID,
                        question=question_text,
                        options=item["options"],
                        is_anonymous=True,
                        type="quiz",
                        correct_option_id=correct_option_id,
                        explanation=explanation_text
                    )
                else:
                    # REGULAR poll
                    print("   Type: Regular Poll")
                    await safe_send(
                        bot,
                        bot.send_poll,
                        chat_id=CHAT_ID,
                        question=question_text,
                        options=item["options"],
                        is_anonymous=True,
                        type="regular"
                    )

            # Randomized safe delay (1–2s jitter)
            await asyncio.sleep(random.uniform(1.0, 2.0))

        except Exception as e:
            error_details = f"Failed to send item #{i}.\nType: {content_type}\nError: {e}"
            print(f"❌ {error_details}")
            await send_error_to_telegram(bot, error_details)

    print("\n✅ Finished sending all content.")


# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    asyncio.run(process_content())
