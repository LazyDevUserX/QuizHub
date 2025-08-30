import asyncio
import nest_asyncio
import os
import json
import glob
from telegram import Bot
from telegram.error import BadRequest
from telegram.helpers import escape_markdown # NEW: Import the escape function

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
        await bot.send_message(chat_id=CHAT_ID, text=f"🤖 BOT ERROR 🤖\n\n<pre>{error_message}</pre>", parse_mode='HTML')
    except Exception as e:
        print(f"❌ CRITICAL: Failed to send error message to Telegram: {e}")

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

    print("\nStarting to send content...")
    for i, item in enumerate(item_list, start=1):
        content_type = item.get('type', 'poll')
        print(f"--> Processing item {i} of {len(item_list)} (type: {content_type})...")

        try:
            if content_type == 'message':
                await bot.send_message(chat_id=CHAT_ID, text=item['text'], parse_mode='HTML')
            
            elif content_type == 'poll':
                question_text = f"[MediX]\n{item['question']}"
                explanation_text = item.get('explanation')
                correct_option_id = item.get('correct_option')

                # CASE 1: It's a QUIZ poll (a correct answer is provided)
                if correct_option_id is not None:
                    print("    Type: Quiz Poll")
                    try:
                        await bot.send_poll(
                            chat_id=CHAT_ID,
                            question=question_text,
                            options=item["options"],
                            is_anonymous=True,
                            type="quiz",
                            correct_option_id=correct_option_id,
                            explanation=explanation_text
                        )
                    except BadRequest as e:
                        if "message is too long" in str(e).lower() and explanation_text:
                            print("    ⚠️ Warning: Explanation is too long. Sending as a separate message.")
                            await bot.send_poll(
                                chat_id=CHAT_ID,
                                question=question_text,
                                options=item["options"],
                                is_anonymous=True,
                                type="quiz",
                                correct_option_id=correct_option_id,
                                explanation=None
                            )
                            # MODIFIED: Escape the explanation text to prevent parsing errors
                            escaped_explanation = escape_markdown(explanation_text, version=2)
                            full_text = f"_*Explanation:*_\n{escaped_explanation}"
                            
                            await bot.send_message(
                                chat_id=CHAT_ID,
                                text=full_text,
                                parse_mode='MarkdownV2' # MODIFIED: Use MarkdownV2 for better escaping
                            )
                        else:
                            raise 
                
                # CASE 2: It's a REGULAR poll (correct_option is null)
                else:
                    print("    Type: Regular Poll")
                    await bot.send_poll(
                        chat_id=CHAT_ID,
                        question=question_text,
                        options=item["options"],
                        is_anonymous=True,
                        type="regular" 
                    )

                    if explanation_text:
                        explanation_header = "❌ *No Correct Option*" 
                        # MODIFIED: Escape the explanation text to prevent parsing errors
                        escaped_explanation = escape_markdown(explanation_text, version=2)
                        full_explanation = f"{explanation_header}\n\n{escaped_explanation}"
                        
                        print("    Sending separate explanation message.")
                        await bot.send_message(
                            chat_id=CHAT_ID,
                            text=full_explanation,
                            parse_mode='MarkdownV2' # MODIFIED: Use MarkdownV2 for better escaping
                        )

            await asyncio.sleep(4)

        except Exception as e:
            error_details = f"Failed to send item #{i}.\nType: {content_type}\nError: {e}"
            print(f"❌ {error_details}")
            await send_error_to_telegram(bot, error_details)

    print("\n✅ Finished sending all content.")

# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    asyncio.run(process_content())
