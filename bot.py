import os
import http.server
import socketserver
import threading
from google import genai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# Render Port check
def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Google GenAI Client
client = genai.Client(api_key=GEMINI_API_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("မင်္ဂလာပါ။ Telegram Recap Bot မှ ကြိုဆိုပါတယ်။")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=update.message.text
        )
        if response and response.text:
            await update.message.reply_text(response.text)
        else:
            await update.message.reply_text("တုံ့ပြန်မှု မရရှိပါ။")
    except Exception as e:
        await update.message.reply_text(f"Error တက်သွားပါသည်: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()
