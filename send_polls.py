import asyncio
import os
import json
import glob
from telegram import Bot
from telegram.error import BadRequest, RetryAfter
from telegram.helpers import escape_markdown

# ====== CONFIGURATION ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
PROGRESS_FILE = "progress.txt"

if not BOT_TOKEN or not CHAT_ID:
    raise EnvironmentError("❌ BOT_TOKEN or CHAT_ID is not set in environment variables.")

# ====== HELPERS ======

def find_json_file():
    """Finds the first .json file in the repository's root directory."""
    json_files = glob.glob("*.json")
    if json_files:
        print(f"✅ Found JSON file: {json_files[0]}")
        return json_files[0]
    print("❌ No .json file found in the repository.")
    return None


def load_items(file_path):
    """Loads items (polls or messages) from a specified JSON file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        print(f"✅ Successfully loaded {len(items)} items from {file_path}")
        return items
    except FileNotFoundError:
        return []
    except json.JSONDecodeError:
        print(f"❌ Error: The file {file_path} is not a valid JSON file.")
        return []


def split_text(text, max_length=4000):
    """Splits long text into chunks within Telegram’s 4096 char limit."""
    return [text[i:i + max_length] for i in range(0, len(text), max_length)]


def log_error_locally(message):
    """Saves errors to a local log file for debugging."""
    with open("logs.txt", "a", encoding="utf-8") as log_file:
        log_file.write(message + "\n")


def save_progress(i):
    """Save last successfully sent item index."""
    with open(PROGRESS_FILE, "w") as f:
        f.write(str(i))


def load_progress():
    """Load last successfully sent item index."""
    try:
        with open(PROGRESS_FILE, "r") as f:
            return int(f.read().strip())
    except:
        return 0


async def send_error_to_telegram(bot, error_message):
    """Sends a formatted error message to the Telegram channel."""
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"🤖 BOT ERROR 🤖\n\n<pre>{error_message}</pre>",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"❌ CRITICAL: Failed to send error message to Telegram: {e}")
    finally:
        log_error_locally(error_message)


# ====== RATE CONTROL ======
base_delay = 1  # start very fast
max_delay = 10  # cap backoff
current_delay = base_delay

async def safe_send(action, *args, **kwargs):
    """Wrapper to safely send messages/polls with flood control & adaptive delay."""
    global current_delay
    while True:
        try:
            result = await action(*args, **kwargs)
            # Success → gently decrease delay towards base
            if current_delay > base_delay:
                current_delay -= 1
            await asyncio.sleep(current_delay)
            return result
        except RetryAfter as e:
            wait_time = int(e.retry_after) + 1
            current_delay = min(current_delay + 2, max_delay)
            print(f"⏳ Flood control triggered. Waiting {wait_time}s (delay now {current_delay}s)...")
            await asyncio.sleep(wait_time)
        except Exception as e:
            current_delay = min(current_delay + 2, max_delay)
            raise e


# ====== MAIN PROCESS ======

async def process_content():
    """Main function to process and send all content from the JSON file."""
    bot = Bot(token=BOT_TOKEN)
    json_file = find_json_file()

    if not json_file:
        await send_error_to_telegram(bot, "Could not find any .json file to process.")
        return

    item_list = load_items(json_file)
    if not item_list:
        await send_error_to_telegram(bot, f"File '{json_file}' is empty or invalid.")
        return

    start_index = load_progress()
    total_items = len(item_list)

    print(f"\n🚀 Starting to send content (resuming from item {start_index+1}/{total_items})...")

    for i, item in enumerate(item_list[start_index:], start=start_index + 1):
        content_type = item.get("type", "poll")
        print(f"--> Processing item {i} of {total_items} (type: {content_type})...")

        try:
            # =============== MESSAGES ===============
            if content_type == "message":
                if "text" not in item:
                    raise ValueError(f"Invalid message structure at item #{i}")
                for chunk in split_text(item["text"]):
                    await safe_send(bot.send_message, chat_id=CHAT_ID, text=chunk, parse_mode="HTML")

            # =============== POLLS ===============
            elif content_type == "poll":
                if "question" not in item or "options" not in item:
                    raise ValueError(f"Invalid poll structure at item #{i}")

                question_text = f"[MediX]\n{item['question']}"
                if len(question_text) > 300:
                    question_text = question_text[:297] + "..."

                if any(len(opt) > 100 for opt in item["options"]):
                    raise ValueError(f"Poll options too long at item #{i}")

                explanation_text = item.get("explanation")
                correct_option_id = item.get("correct_option")

                # QUIZ POLL
                if correct_option_id is not None:
                    print("    Type: Quiz Poll")
                    try:
                        await safe_send(
                            bot.send_poll,
                            chat_id=CHAT_ID,
                            question=question_text,
                            options=item["options"],
                            is_anonymous=True,
                            type="quiz",
                            correct_option_id=correct_option_id,
                            explanation=explanation_text,
                        )
                    except BadRequest as e:
                        if "message is too long" in str(e).lower() and explanation_text:
                            print("    ⚠️ Explanation too long, sending separately.")
                            await safe_send(
                                bot.send_poll,
                                chat_id=CHAT_ID,
                                question=question_text,
                                options=item["options"],
                                is_anonymous=True,
                                type="quiz",
                                correct_option_id=correct_option_id,
                                explanation=None,
                            )

                            # Escape & format as spoiler
                            escaped_explanation = escape_markdown(explanation_text, version=2)
                            full_text = f"||{escaped_explanation}||"
                            await asyncio.sleep(2)  # small delay before explanation
                            for chunk in split_text(full_text):
                                await safe_send(
                                    bot.send_message,
                                    chat_id=CHAT_ID,
                                    text=chunk,
                                    parse_mode="MarkdownV2",
                                )
                        else:
                            raise

                # REGULAR POLL
                else:
                    print("    Type: Regular Poll")
                    await safe_send(
                        bot.send_poll,
                        chat_id=CHAT_ID,
                        question=question_text,
                        options=item["options"],
                        is_anonymous=True,
                        type="regular",
                    )

                    if explanation_text:
                        escaped_explanation = escape_markdown(explanation_text, version=2)
                        full_explanation = f"❌ *No Correct Option*\n\n||{escaped_explanation}||"
                        print("    Sending separate explanation message.")
                        await asyncio.sleep(2)  # small delay before explanation
                        for chunk in split_text(full_explanation):
                            await safe_send(
                                bot.send_message,
                                chat_id=CHAT_ID,
                                text=chunk,
                                parse_mode="MarkdownV2",
                            )

            else:
                raise ValueError(f"Unknown content type '{content_type}' at item #{i}")

            # Save progress after successful send
            save_progress(i)

        except Exception as e:
            error_details = f"Failed to send item #{i}.\nType: {content_type}\nError: {e}"
            print(f"❌ {error_details}")
            await send_error_to_telegram(bot, error_details)

    print("\n✅ Finished sending all content.")


# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    asyncio.run(process_content())
