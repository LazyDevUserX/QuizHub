import asyncio
import nest_asyncio
import os
import json
from telegram import Bot

# Allow nested asyncio in environments like Colab or Jupyter
nest_asyncio.apply()

# ====== CONFIGURATION ======
# Securely get token and chat_id from environment variables (like GitHub Secrets)
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
QUESTIONS_FILE = "questions.json"

# ====== FUNCTIONS ======

def load_mcqs(file_path):
    """
    Loads Multiple Choice Questions (MCQs) from a specified JSON file.
    Handles potential errors like the file not being found or invalid JSON format.
    """
    try:
        # Open and read the file with UTF-8 encoding to support all characters
        with open(file_path, 'r', encoding='utf-8') as f:
            mcqs = json.load(f)
        print(f"✅ Successfully loaded {len(mcqs)} questions from {file_path}")
        return mcqs
    except FileNotFoundError:
        print(f"❌ Error: The file {file_path} was not found.")
        return []
    except json.JSONDecodeError:
        print(f"❌ Error: The file {file_path} is not a valid JSON file. Please check its syntax.")
        return []

async def send_bulk_polls():
    """
    Initializes the bot and sends all loaded MCQs as quiz polls to the specified chat.
    """
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Error: BOT_TOKEN or CHAT_ID is not set in environment variables. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)
    mcqs_list = load_mcqs(QUESTIONS_FILE)

    if not mcqs_list:
        print("No questions were loaded. Exiting.")
        return

    print("\nStarting to send polls to the channel...")
    for i, mcq in enumerate(mcqs_list, start=1):
        print(f"--> Sending question {i} of {len(mcqs_list)}...")
        try:
            # Get the custom explanation for the question.
            # If an explanation is not provided in the JSON, use a default message.
            explanation_text = mcq.get('explanation', '✅ The correct answer is revealed after you vote.')

            await bot.send_poll(
                chat_id=CHAT_ID,
                question=f"Q{i}: {mcq['question']}",
                options=mcq["options"],
                is_anonymous=True,       # Must be True for channels
                type="quiz",             # Specifies that this is a quiz with a correct answer
                correct_option_id=mcq["correct_option"],
                explanation=explanation_text
            )
            
            # Use a longer delay (e.g., 4 seconds) to avoid Telegram's flood control limits
            await asyncio.sleep(4)

        except Exception as e:
            print(f"❌ Failed to send question {i}: {e}")
            # Optional: break the loop if one poll fails
            # break
    
    print("\n✅ Finished sending all polls.")

# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    # This block runs when the script is executed directly
    # In GitHub Actions, it's equivalent to `python send_polls.py`
    # We use asyncio.run() for modern async execution
    asyncio.run(send_bulk_polls())

