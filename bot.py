import os
import asyncio
import logging
import urllib.parse
from threading import Thread
from flask import Flask
from google import genai
import edge_tts
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
# =========================================================
# LOGGING
# =========================================================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", "10000"))
# =========================================================
# CHECK API KEYS
# =========================================================
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing")
# =========================================================
# GEMINI
# =========================================================
client = genai.Client(
    api_key=GEMINI_API_KEY
)
# =========================================================
# FLASK HEALTH SERVER
# =========================================================
web_app = Flask(__name__)
@web_app.route("/")
def home():
    return "Telegram Recap Bot is running!"
@web_app.route("/health")
def health():
    return "OK"
def run_flask():
    web_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )
def start_web_server():
    thread = Thread(
        target=run_flask,
        daemon=True
    )
    thread.start()
    logger.info(
        f"Flask server started on port {PORT}"
    )
# =========================================================
# START COMMAND
# =========================================================
async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    welcome = (
        "မင်္ဂလာပါ 👋\n\n"
        "🎬 Movie Recap & Translation Bot ဖြစ်ပါတယ်။\n\n"
        "📥 MP3 / Voice ဖိုင် ပို့ပေးပါ။\n\n"
        "ကျွန်တော်က —\n\n"
        "1️⃣ အသံကို နားထောင်မယ်\n"
        "2️⃣ မြန်မာလို Recap ပြန်ရေးမယ်\n"
        "3️⃣ SRT Subtitle ပြုလုပ်မယ်\n"
        "4️⃣ မြန်မာ MP3 အသံဖိုင် ပြုလုပ်မယ်\n"
        "5️⃣ Thumbnail Prompt ထုတ်ပေးမယ်\n\n"
        "📌 MP3 ဖိုင်ကို ပို့လိုက်ပါ။"
    )
    await update.message.reply_text(welcome)
# =========================================================
# AUDIO HANDLER
# =========================================================
async def handle_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    status = await update.message.reply_text(
        "📥 MP3 ဖိုင်ကို လက်ခံရရှိပါပြီ...\n\n"
        "⏳ Processing စတင်နေပါတယ်။"
    )
    file_id = None
    input_path = None
    srt_path = None
    mp3_path = None
    audio_file = None
    try:
        # -------------------------------------------------
        # GET FILE ID
        # -------------------------------------------------
        if update.message.audio:
            file_id = update.message.audio.file_id
        elif update.message.voice:
            file_id = update.message.voice.file_id
        else:
            await status.edit_text(
                "❌ Audio ဖိုင် မတွေ့ပါ။"
            )
            return
        # -------------------------------------------------
        # FILE PATHS
        # -------------------------------------------------
        input_path = f"input_{file_id}.mp3"
        srt_path = f"subtitle_{file_id}.srt"
        mp3_path = f"burmese_{file_id}.mp3"
        # -------------------------------------------------
        # DOWNLOAD TELEGRAM FILE
        # -------------------------------------------------
        await status.edit_text(
            "📥 Audio ဖိုင်ကို Download လုပ်နေပါတယ်..."
        )
        telegram_file = await context.bot.get_file(
            file_id
        )
        await telegram_file.download_to_drive(
            input_path
        )
        # -------------------------------------------------
        # UPLOAD TO GEMINI
        # -------------------------------------------------
        await status.edit_text(
            "🎙️ Gemini AI က Audio ကို နားထောင်နေပါတယ်..."
        )
        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )
        # -------------------------------------------------
        # GEMINI PROMPT
        # -------------------------------------------------
        prompt = """
You are a professional movie recap translator.
Listen to the uploaded audio carefully.
TASK:
1. Understand the complete audio.
2. Translate the important dialogue/narration naturally into Myanmar.
3. Create a standard SRT subtitle.
4. Create an engaging Myanmar movie recap.
5. Do not invent events that are not present in the audio.
SRT REQUIREMENTS:
- Use standard SRT format.
- Number subtitles sequentially.
- Use timestamps like:
00:00:00,000 --> 00:00:05,000
- Keep timestamps sequential.
- Keep subtitle sentences short and readable.
IMPORTANT:
Return ONLY the following structure:
===SRT_START===
1
00:00:00,000 --> 00:00:05,000
မြန်မာစာ
2
00:00:05,000 --> 00:00:10,000
မြန်မာစာ
===SRT_END===
===RECAP_START===
မြန်မာလို Movie Recap
===RECAP_END===
"""
        # -------------------------------------------------
        # GEMINI GENERATION
        # -------------------------------------------------
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=[
                audio_file,
                prompt,
            ],
        )
        result = response.text or ""
        if not result.strip():
            raise RuntimeError(
                "Gemini returned an empty response."
            )
        # -------------------------------------------------
        # EXTRACT SRT
        # -------------------------------------------------
        srt_content = ""
        if (
            "===SRT_START===" in result
            and
            "===SRT_END===" in result
        ):
            srt_content = (
                result
                .split("===SRT_START===", 1)[1]
                .split("===SRT_END===", 1)[0]
                .strip()
            )
        # -------------------------------------------------
        # EXTRACT RECAP
        # -------------------------------------------------
        recap_text = ""
        if (
            "===RECAP_START===" in result
            and
            "===RECAP_END===" in result
        ):
            recap_text = (
                result
                .split("===RECAP_START===", 1)[1]
                .split("===RECAP_END===", 1)[0]
                .strip()
            )
        else:
            recap_text = result.strip()
        if not recap_text:
            raise RuntimeError(
                "Myanmar recap text is empty."
            )
        # -------------------------------------------------
        # SAVE SRT
        # -------------------------------------------------
        if srt_content:
            with open(
                srt_path,
                "w",
                encoding="utf-8"
            ) as file:
                file.write(srt_content)
        # -------------------------------------------------
        # TEXT TO SPEECH
        # -------------------------------------------------
        await status.edit_text(
            "🔊 မြန်မာ MP3 အသံဖိုင် ပြုလုပ်နေပါတယ်..."
        )
        voice = "my-MM-ThihaNeural"
        communicate = edge_tts.Communicate(
            recap_text,
            voice
        )
        await communicate.save(
            mp3_path
        )
        # -------------------------------------------------
        # THUMBNAIL PROMPT
        # -------------------------------------------------
        await status.edit_text(
            "🖼️ Thumbnail Prompt ပြုလုပ်နေပါတယ်..."
        )
        thumbnail_request = f"""
Create one cinematic English prompt for a
YouTube movie recap thumbnail.
Use ONLY the story information from this recap:
{recap_text}
Requirements:
- cinematic movie poster
- dramatic lighting
- emotional characters
- realistic faces
- high detail
- dramatic composition
- 16:9
- no text
- no subtitles
- no watermark
Return ONLY the English image prompt.
"""
        prompt_response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=thumbnail_request
        )
        thumbnail_prompt = (
            prompt_response.text.strip()
            if prompt_response.text
            else
            "cinematic emotional movie recap poster, "
            "dramatic lighting, realistic characters, "
            "16:9"
        )
        # -------------------------------------------------
        # DELETE STATUS
        # -------------------------------------------------
        try:
            await status.delete()
        except Exception:
            pass
        # -------------------------------------------------
        # SEND RECAP
        # -------------------------------------------------
        await update.message.reply_text(
            "🎬 မြန်မာ Movie Recap\n\n"
            + recap_text
        )
        # -------------------------------------------------
        # SEND SRT
        # -------------------------------------------------
        if srt_content:
            with open(
                srt_path,
                "rb"
            ) as srt_file:
                await update.message.reply_document(
                    document=srt_file,
                    filename="subtitle.srt",
                    caption="📄 Myanmar SRT Subtitle"
                )
        # -------------------------------------------------
        # SEND MP3
        # -------------------------------------------------
        with open(
            mp3_path,
            "rb"
        ) as audio_output:
            await update.message.reply_audio(
                audio=audio_output,
                filename="burmese_recap.mp3",
                caption="🎧 မြန်မာဘာသာပြန် MP3"
            )
        # -------------------------------------------------
        # THUMBNAIL URL
        # -------------------------------------------------
        encoded_prompt = urllib.parse.quote(
            thumbnail_prompt
        )
        thumbnail_url = (
            "https://image.pollinations.ai/prompt/"
            + encoded_prompt
            + "?width=1280"
            + "&height=720"
            + "&nologo=true"
        )
        # -------------------------------------------------
        # SEND THUMBNAIL
        # -------------------------------------------------
        try:
            await update.message.reply_photo(
                photo=thumbnail_url,
                caption=(
                    "🖼️ Generated Thumbnail\n\n"
                    + thumbnail_prompt
                )
            )
        except Exception as image_error:
            logger.warning(
                f"Thumbnail failed: {image_error}"
            )
            await update.message.reply_text(
                "⚠️ Thumbnail ပုံ မထုတ်နိုင်ပါ။\n\n"
                "Thumbnail Prompt:\n"
                + thumbnail_prompt
            )
        # -------------------------------------------------
        # DELETE GEMINI FILE
        # -------------------------------------------------
        if audio_file:
            try:
                await asyncio.to_thread(
                    client.files.delete,
                    name=audio_file.name
                )
            except Exception as delete_error:
                logger.warning(
                    f"Gemini file delete failed: "
                    f"{delete_error}"
                )
    except Exception as error:
        logger.exception(
            "Audio processing error"
        )
        try:
            await status.edit_text(
                "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                + str(error)
            )
        except Exception:
            try:
                await update.message.reply_text(
                    "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                    + str(error)
                )
            except Exception:
                pass
    finally:
        # -------------------------------------------------
        # CLEAN TEMP FILES
        # -------------------------------------------------
        for path in [
            input_path,
            srt_path,
            mp3_path,
        ]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
# =========================================================
# MAIN
# =========================================================
def main():
    # Start Flask server first
    start_web_server()
    # Create Telegram application
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )
    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )
    # Audio / Voice
    application.add_handler(
        MessageHandler(
            filters.AUDIO | filters.VOICE,
            handle_audio
        )
    )
    logger.info(
        "🤖 Telegram Recap Bot Started..."
    )
    # Start Telegram polling
    application.run_polling(
        drop_pending_updates=True
    )
# =========================================================
# RUN
# =========================================================
if __name__ == "__main__":
    main()
