import os
import http.server
import socketserver
import threading

from google import genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# =========================
# Render Port Check
# =========================

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()


threading.Thread(
    target=run_dummy_server,
    daemon=True
).start()


# =========================
# Environment Variables
# =========================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing")

if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is missing")


# =========================
# Gemini AI
# =========================

client = genai.Client(api_key=GEMINI_API_KEY)

MODEL_NAME = "gemini-2.5-flash"


# =========================
# Telegram /start
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "မင်္ဂလာပါ။ Telegram Recap Bot မှ ကြိုဆိုပါတယ်။"
    )


# =========================
# Handle Messages
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    try:
        user_text = update.message.text

        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_text
        )

        if response and response.text:
            await update.message.reply_text(response.text)
        else:
            await update.message.reply_text(
                "တုံ့ပြန်မှု မရရှိပါ။"
            )

    except Exception as e:
        print("Gemini Error:", repr(e))

        await update.message.reply_text(
            f"Error တက်သွားပါသည်:\n{str(e)}"
        )


# =========================
# Main
# =========================

if __name__ == "__main__":

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Telegram Recap Bot is running...")

    app.run_polling()
