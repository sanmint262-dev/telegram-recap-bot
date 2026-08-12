import os
import asyncio
import logging
import urllib.parse
import base64
from threading import Thread

import httpx
from flask import Flask
from google import genai

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

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)

# IMPORTANT:
# Current Gemini model
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

# Existing TTS server
TTS_URL = (
    "https://student-recap-tts.onrender.com/tts-srt"
)


# =========================================================
# CHECK ENVIRONMENT
# =========================================================

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is missing"
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is missing"
    )


# =========================================================
# GEMINI CLIENT
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

    return (
        "Telegram Recap Bot is running!"
    )


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
        "Flask health server started "
        "on port %s",
        PORT
    )


# =========================================================
# /START
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
        "1️⃣ Audio ကို နားထောင်မယ်\n"
        "2️⃣ မြန်မာလို Recap ပြန်ရေးမယ်\n"
        "3️⃣ SRT Subtitle ပြုလုပ်မယ်\n"
        "4️⃣ မြန်မာ MP3 အသံဖိုင် ပြုလုပ်မယ်\n"
        "5️⃣ Thumbnail Prompt ထုတ်ပေးမယ်\n\n"
        "📌 MP3 ဖိုင်ကို ပို့လိုက်ပါ။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# TTS SERVER
# =========================================================

async def call_tts_server(
    text: str,
    voice: str = "my-MM-ThihaNeural",
    rate: str = "+30%",
    pitch: str = "+0Hz",
):

    payload = {
        "text": text,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
    }

    timeout = httpx.Timeout(
        connect=30.0,
        read=180.0,
        write=30.0,
        pool=30.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout
    ) as http:

        response = await http.post(
            TTS_URL,
            json=payload
        )

    # =====================================================
    # HTTP ERROR
    # =====================================================

    if response.status_code != 200:

        try:

            error_data = response.json()

            error_message = (
                error_data.get("error")
                or error_data.get("message")
                or str(error_data)
            )

        except Exception:

            error_message = response.text

        raise RuntimeError(
            f"TTS Server HTTP "
            f"{response.status_code}: "
            f"{error_message}"
        )

    # =====================================================
    # JSON
    # =====================================================

    try:

        data = response.json()

    except Exception as error:

        raise RuntimeError(
            "TTS server returned invalid JSON: "
            + str(error)
        )

    # =====================================================
    # AUDIO
    # =====================================================

    audio_base64 = data.get(
        "audio_base64"
    )

    if not audio_base64:

        raise RuntimeError(
            "TTS server response does not "
            "contain audio_base64."
        )

    # =====================================================
    # WORD BOUNDARIES
    # =====================================================

    word_boundaries = data.get(
        "word_boundaries",
        []
    )

    # =====================================================
    # DECODE AUDIO
    # =====================================================

    try:

        audio_bytes = base64.b64decode(
            audio_base64
        )

    except Exception as error:

        raise RuntimeError(
            "Could not decode audio_base64: "
            + str(error)
        )

    return (
        audio_bytes,
        word_boundaries
    )


# =========================================================
# SRT TIMESTAMP
# =========================================================

def srt_timestamp(
    milliseconds
):

    milliseconds = max(
        0,
        int(milliseconds)
    )

    hours = (
        milliseconds // 3600000
    )

    milliseconds %= 3600000

    minutes = (
        milliseconds // 60000
    )

    milliseconds %= 60000

    seconds = (
        milliseconds // 1000
    )

    milliseconds %= 1000

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d},"
        f"{milliseconds:03d}"
    )


# =========================================================
# BUILD SRT
# =========================================================

def build_srt(
    word_boundaries
):

    if not word_boundaries:
        return ""

    groups = []

    current = []

    punctuation = (
        "။",
        ".",
        "!",
        "?",
        "၊",
        ",",
        ";",
        ":",
    )

    for index, word in enumerate(
        word_boundaries
    ):

        text = str(
            word.get(
                "text",
                ""
            )
        ).strip()

        if not text:
            continue

        current.append(
            word
        )

        offset = int(
            word.get(
                "offset",
                0
            )
        )

        duration = int(
            word.get(
                "duration",
                0
            )
        )

        end_time = (
            offset + duration
        )

        next_word = None

        if index + 1 < len(
            word_boundaries
        ):

            next_word = (
                word_boundaries[
                    index + 1
                ]
            )

        should_break = False

        # Maximum 6 words
        if len(current) >= 6:

            should_break = True

        # Punctuation
        if text.endswith(
            punctuation
        ):

            if len(current) >= 3:

                should_break = True

        # Natural pause
        if next_word:

            next_offset = int(
                next_word.get(
                    "offset",
                    0
                )
            )

            pause = (
                next_offset
                - end_time
            )

            if (
                pause >= 600
                and len(current) >= 3
            ):

                should_break = True

        # Last word
        if next_word is None:

            should_break = True

        if should_break:

            groups.append(
                current
            )

            current = []

    # =====================================================
    # SRT OUTPUT
    # =====================================================

    lines = []

    subtitle_number = 1

    for group in groups:

        if not group:
            continue

        start = int(
            group[0].get(
                "offset",
                0
            )
        )

        last = group[-1]

        end = (
            int(
                last.get(
                    "offset",
                    0
                )
            )
            +
            int(
                last.get(
                    "duration",
                    0
                )
            )
        )

        subtitle_text = " ".join(
            str(
                item.get(
                    "text",
                    ""
                )
            ).strip()
            for item in group
        ).strip()

        lines.append(
            str(subtitle_number)
        )

        lines.append(
            f"{srt_timestamp(start)} --> "
            f"{srt_timestamp(end)}"
        )

        lines.append(
            subtitle_text
        )

        lines.append("")

        subtitle_number += 1

    return "\n".join(
        lines
    )


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

        # =================================================
        # GET FILE ID
        # =================================================

        if update.message.audio:

            file_id = (
                update.message.audio.file_id
            )

        elif update.message.voice:

            file_id = (
                update.message.voice.file_id
            )

        else:

            await status.edit_text(
                "❌ Audio ဖိုင် မတွေ့ပါ။"
            )

            return

        # =================================================
        # FILE PATHS
        # =================================================

        input_path = (
            f"input_{file_id}.mp3"
        )

        srt_path = (
            f"subtitle_{file_id}.srt"
        )

        mp3_path = (
            f"burmese_{file_id}.mp3"
        )

        # =================================================
        # DOWNLOAD TELEGRAM FILE
        # =================================================

        await status.edit_text(
            "📥 Audio ဖိုင်ကို Download "
            "လုပ်နေပါတယ်..."
        )

        telegram_file = (
            await context.bot.get_file(
                file_id
            )
        )

        await telegram_file.download_to_drive(
            input_path
        )

        # =================================================
        # GEMINI FILE UPLOAD
        # =================================================

        await status.edit_text(
            "🎙️ Gemini 3.6 Flash က "
            "Audio ကို နားထောင်နေပါတယ်..."
        )

        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )

        # =================================================
        # GEMINI PROMPT
        # =================================================

        prompt = """
You are a professional movie recap translator.

Listen to the uploaded audio carefully.

Your job is to understand the entire audio
and create a natural Myanmar movie recap.

TASK:

1. Understand the complete audio.
2. Identify the important story events.
3. Translate dialogue and narration naturally
   into Myanmar when needed.
4. Create an engaging Myanmar movie recap.
5. Do not invent events that are not present.
6. Keep names and important story details accurate.
7. Make the Myanmar language natural and easy
   to understand for TikTok / YouTube viewers.

IMPORTANT:

Return ONLY this structure:

===RECAP_START===

Myanmar movie recap here.

===RECAP_END===
"""

        # =================================================
        # GEMINI 3.6 FLASH
        # =================================================

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=[
                audio_file,
                prompt,
            ],
        )

        result = (
            response.text
            if response.text
            else ""
        )

        if not result.strip():

            raise RuntimeError(
                "Gemini returned an empty response."
            )

        # =================================================
        # EXTRACT RECAP
        # =================================================

        if (
            "===RECAP_START===" in result
            and
            "===RECAP_END===" in result
        ):

            recap_text = (
                result
                .split(
                    "===RECAP_START===",
                    1
                )[1]
                .split(
                    "===RECAP_END===",
                    1
                )[0]
                .strip()
            )

        else:

            recap_text = result.strip()

        if not recap_text:

            raise RuntimeError(
                "Myanmar recap text is empty."
            )

        # =================================================
        # TTS
        # =================================================

        await status.edit_text(
            "🔊 မြန်မာ MP3 အသံဖိုင် "
            "ပြုလုပ်နေပါတယ်...\n\n"
            "⏳ Generating voice, this may "
            "take up to a minute..."
        )

        voice = (
            "my-MM-ThihaNeural"
        )

        rate = "+30%"

        pitch = "+0Hz"

        (
            audio_bytes,
            word_boundaries
        ) = await call_tts_server(
            text=recap_text,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )

        # =================================================
        # SAVE MP3
        # =================================================

        with open(
            mp3_path,
            "wb"
        ) as mp3_file:

            mp3_file.write(
                audio_bytes
            )

        # =================================================
        # BUILD SRT
        # =================================================

        generated_srt = build_srt(
            word_boundaries
        )

        if generated_srt:

            with open(
                srt_path,
                "w",
                encoding="utf-8"
            ) as srt_file:

                srt_file.write(
                    generated_srt
                )

        # =================================================
        # THUMBNAIL PROMPT
        # =================================================

        await status.edit_text(
            "🖼️ Thumbnail Prompt "
            "ပြုလုပ်နေပါတယ်..."
        )

        thumbnail_request = f"""
Create one cinematic English prompt
for a YouTube movie recap thumbnail.

Use ONLY the story information
from this Myanmar recap:

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

        thumbnail_response = (
            await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=thumbnail_request
            )
        )

        thumbnail_prompt = (
            thumbnail_response.text.strip()
            if thumbnail_response.text
            else
            "cinematic emotional movie recap poster, "
            "dramatic lighting, realistic characters, "
            "16:9"
        )

        # =================================================
        # DELETE STATUS
        # =================================================

        try:

            await status.delete()

        except Exception:

            pass

        # =================================================
        # SEND RECAP
        # =================================================

        await update.message.reply_text(
            "🎬 မြန်မာ Movie Recap\n\n"
            + recap_text
        )

        # =================================================
        # SEND SRT
        # =================================================

        if generated_srt:

            with open(
                srt_path,
                "rb"
            ) as srt_file:

                await update.message.reply_document(
                    document=srt_file,
                    filename="subtitle.srt",
                    caption="📄 Myanmar SRT Subtitle"
                )

        # =================================================
        # SEND MP3
        # =================================================

        with open(
            mp3_path,
            "rb"
        ) as audio_output:

            await update.message.reply_audio(
                audio=audio_output,
                filename="burmese_recap.mp3",
                caption="🎧 မြန်မာဘာသာပြန် MP3"
            )

        # =================================================
        # THUMBNAIL
        # =================================================

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
                "Thumbnail failed: %s",
                image_error
            )

            await update.message.reply_text(
                "⚠️ Thumbnail ပုံ မထုတ်နိုင်ပါ။\n\n"
                "Thumbnail Prompt:\n"
                + thumbnail_prompt
            )

        # =================================================
        # DELETE GEMINI FILE
        # =================================================

        if audio_file:

            try:

                await asyncio.to_thread(
                    client.files.delete,
                    name=audio_file.name
                )

            except Exception as delete_error:

                logger.warning(
                    "Gemini file delete failed: %s",
                    delete_error
                )

    # =====================================================
    # ERROR
    # =====================================================

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

    # =====================================================
    # CLEANUP
    # =====================================================

    finally:

        for path in [
            input_path,
            srt_path,
            mp3_path,
        ]:

            if (
                path
                and
                os.path.exists(path)
            ):

                try:

                    os.remove(path)

                except Exception:

                    pass


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Telegram error: %s",
        context.error
    )


# =========================================================
# CREATE TELEGRAM APP
# =========================================================

def create_application():

    application = (
        ApplicationBuilder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        MessageHandler(
            filters.AUDIO
            |
            filters.VOICE,
            handle_audio
        )
    )

    application.add_error_handler(
        error_handler
    )

    return application


# =========================================================
# MAIN
# =========================================================

def main():

    # Flask runs in background.
    # Telegram MUST remain in main thread.

    start_web_server()

    application = (
        create_application()
    )

    logger.info(
        "========================================"
    )

    logger.info(
        "🤖 Telegram Recap Bot Started"
    )

    logger.info(
        "Gemini Model: %s",
        GEMINI_MODEL
    )

    logger.info(
        "TTS Server: %s",
        TTS_URL
    )

    logger.info(
        "========================================"
    )

    # IMPORTANT:
    # stop_signals=None prevents the
    # set_wakeup_fd main-thread error
    # when deployed through a threaded
    # environment.

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
