import asyncio
import nest_asyncio
import os
import json
from telegram import Bot

# Allow nested asyncio
nest_asyncio.apply()

# ====== CONFIGURATION ======
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
QUESTIONS_FILE = "questions.json"

# ====== FUNCTIONS ======

def load_mcqs(file_path):
    """Loads MCQs from a specified JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            mcqs = json.load(f)
        print(f"✅ Successfully loaded {len(mcqs)} questions from {file_path}")
        return mcqs
    except FileNotFoundError:
        print(f"❌ Error: The file {file_path} was not found.")
        return []
    except json.JSONDecodeError:
        print(f"❌ Error: The file {file_path} is not a valid JSON file.")
        return []

async def send_bulk_polls():
    """Initializes the bot and sends all loaded MCQs as quiz polls."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Error: BOT_TOKEN or CHAT_ID is not set. Aborting.")
        return

    bot = Bot(token=BOT_TOKEN)
    mcqs_list = load_mcqs(QUESTIONS_FILE)

    if not mcqs_list:
        print("No questions loaded. Exiting.")
        return

    print("\nStarting to send polls...")
    # The 'i' from enumerate is now only used for logging purposes
    for i, mcq in enumerate(mcqs_list, start=1):
        print(f"--> Sending question {i} of {len(mcqs_list)}...")
        try:
            explanation_text = mcq.get('explanation', '✅ The correct answer is revealed after you vote.')
            
            # ** MODIFIED LINE **
            # Prepend [MCQHELL] to the question from the JSON file
            question_text = f"[MediX]\n{mcq['question']}"

            await bot.send_poll(
                chat_id=CHAT_ID,
                question=question_text, # Use the newly formatted question text
                options=mcq["options"],
                is_anonymous=True,
                type="quiz",
                correct_option_id=mcq["correct_option"],
                explanation=explanation_text
            )
            
            await asyncio.sleep(4) # Delay to avoid flood control limits

        except Exception as e:
            print(f"❌ Failed to send question {i}: {e}")
    
    print("\n✅ Finished sending all polls.")

# ====== MAIN EXECUTION BLOCK ======
if __name__ == "__main__":
    asyncio.run(send_bulk_polls())
    
