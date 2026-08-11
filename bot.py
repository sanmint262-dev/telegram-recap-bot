import os
import asyncio
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
# Render Web Server
# =========================

class HealthHandler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Telegram Recap Bot is running!")

    def log_message(self, format, *args):
        pass


def run_web_server():
    port = int(os.getenv("PORT", 10000))

    server = socketserver.TCPServer(
        ("0.0.0.0", port),
        HealthHandler
    )

    print(f"Web server running on port {port}")

    server.serve_forever()


threading.Thread(
    target=run_web_server,
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

client = genai.Client(
    api_key=GEMINI_API_KEY
)

# Current stable Gemini model
MODEL_NAME = "gemini-3.6-flash"


# =========================
# Telegram /start
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "မင်္ဂလာပါ။ Telegram Recap Bot မှ ကြိုဆိုပါတယ်။"
    )


# =========================
# Gemini Response
# =========================

def generate_response(text):

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=text
    )

    if response and response.text:
        return response.text

    return None


# =========================
# Handle Telegram Messages
# =========================

async def handle_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message or not update.message.text:
        return

    user_text = update.message.text

    try:

        # Gemini API ကို background thread မှာ run လုပ်မယ်
        answer = await asyncio.to_thread(
            generate_response,
            user_text
        )

        if answer:

            # Telegram message limit ကန့်သတ်ချက်အတွက်
            # စာရှည်ရင် အပိုင်းခွဲပို့မယ်
            max_length = 4000

            for i in range(0, len(answer), max_length):

                await update.message.reply_text(
                    answer[i:i + max_length]
                )

        else:

            await update.message.reply_text(
                "တုံ့ပြန်မှု မရရှိပါ။"
            )

    except Exception as e:

        print("Gemini Error:", repr(e))

        await update.message.reply_text(
            "Error တက်သွားပါသည်။\n\n"
            f"{str(e)}"
        )


# =========================
# Main
# =========================

def main():

    print("================================")
    print("Starting Telegram Recap Bot...")
    print(f"Gemini Model: {MODEL_NAME}")
    print("================================")

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # /start command
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # Normal text messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message
        )
    )

    print("Telegram Recap Bot is running...")

    app.run_polling()


# =========================
# Start Bot
# =========================

if __name__ == "__main__":
    main()
