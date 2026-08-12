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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

PORT = int(os.getenv("PORT", "10000"))

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash"
)

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
# FLASK WEB SERVER
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


# =========================================================
# TELEGRAM BOT
# =========================================================

telegram_application = None


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    welcome = (
        "မင်္ဂလာပါ 👋\n\n"
        "🎬 Movie Recap & Translation Bot ဖြစ်ပါတယ်။\n\n"
        "📥 MP3 / Voice ဖိုင် ပို့ပေးပါ။\n\n"
        "ကျွန်တော်က\n\n"
        "1. Audio ကို နားထောင်မယ်\n"
        "2. မြန်မာလို Recap ပြန်ရေးမယ်\n"
        "3. SRT Subtitle ပြုလုပ်မယ်\n"
        "4. မြန်မာ MP3 အသံဖိုင် ပြုလုပ်မယ်\n"
        "5. Thumbnail Prompt ထုတ်ပေးမယ်\n\n"
        "📌 MP3 ဖိုင်ကို ပို့လိုက်ပါ။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# CALL TTS SERVER
# =========================================================

async def call_tts_server(
    text,
    voice="my-MM-ThihaNeural",
    rate="+30%",
    pitch="+0Hz",
):
    payload = {
        "text": text,
        "voice": voice,
        "rate": rate,
        "pitch": pitch,
    }

    timeout = httpx.Timeout(
        connect=60.0,
        read=180.0,
        write=60.0,
        pool=60.0,
    )

    async with httpx.AsyncClient(
        timeout=timeout
    ) as http:

        response = await http.post(
            TTS_URL,
            json=payload,
        )

    # -----------------------------------------------------
    # HTTP ERROR
    # -----------------------------------------------------

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
            "TTS Server Error - HTTP "
            + str(response.status_code)
            + ": "
            + str(error_message)
        )

    # -----------------------------------------------------
    # JSON
    # -----------------------------------------------------

    try:
        data = response.json()

    except Exception as error:
        raise RuntimeError(
            "TTS server returned invalid JSON: "
            + str(error)
        )

    # -----------------------------------------------------
    # AUDIO BASE64
    # -----------------------------------------------------

    audio_base64 = data.get(
        "audio_base64"
    )

    if not audio_base64:
        raise RuntimeError(
            "TTS server response does not contain "
            "audio_base64."
        )

    # -----------------------------------------------------
    # WORD BOUNDARIES
    # -----------------------------------------------------

    word_boundaries = data.get(
        "word_boundaries",
        []
    )

    # -----------------------------------------------------
    # DECODE MP3
    # -----------------------------------------------------

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

def srt_timestamp(milliseconds):

    milliseconds = max(
        0,
        int(milliseconds)
    )

    hours = milliseconds // 3600000

    milliseconds %= 3600000

    minutes = milliseconds // 60000

    milliseconds %= 60000

    seconds = milliseconds // 1000

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

    for index, word in enumerate(
        word_boundaries
    ):

        current.append(word)

        text = str(
            word.get(
                "text",
                ""
            )
        ).strip()

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

        # -------------------------------------------------
        # MAX 6 WORDS
        # -------------------------------------------------

        if len(current) >= 6:
            should_break = True

        # -------------------------------------------------
        # PUNCTUATION
        # -------------------------------------------------

        if text.endswith(
            (
                "။",
                ".",
                "!",
                "?",
                "၊",
                ",",
                ";",
                ":",
            )
        ):

            if len(current) >= 3:
                should_break = True

        # -------------------------------------------------
        # NATURAL PAUSE
        # -------------------------------------------------

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

        # -------------------------------------------------
        # LAST WORD
        # -------------------------------------------------

        if next_word is None:
            should_break = True

        if should_break:

            groups.append(
                current
            )

            current = []

    # -----------------------------------------------------
    # BUILD SRT
    # -----------------------------------------------------

    srt_lines = []

    for number, group in enumerate(
        groups,
        start=1
    ):

        if not group:
            continue

        start_time = int(
            group[0].get(
                "offset",
                0
            )
        )

        last_word = group[-1]

        end_time = (
            int(
                last_word.get(
                    "offset",
                    0
                )
            )
            +
            int(
                last_word.get(
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

            if str(
                item.get(
                    "text",
                    ""
                )
            ).strip()
        )

        srt_lines.append(
            str(number)
        )

        srt_lines.append(
            srt_timestamp(
                start_time
            )
            + " --> "
            + srt_timestamp(
                end_time
            )
        )

        srt_lines.append(
            subtitle_text
        )

        srt_lines.append("")

    return "\n".join(
        srt_lines
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
        "⏳ Processing စတင်နေပါတယ်..."
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
        # DOWNLOAD TELEGRAM AUDIO
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
        # UPLOAD AUDIO TO GEMINI
        # =================================================

        await status.edit_text(
            "🎙️ Gemini AI က Audio ကို "
            "နားထောင်နေပါတယ်..."
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

TASK:

1. Understand the complete audio.
2. Translate important dialogue and narration naturally into Myanmar.
3. Create a Myanmar movie recap.
4. Do not invent events that are not present in the audio.
5. Make the Myanmar recap natural and suitable for voiceover.

IMPORTANT:

Return ONLY this structure:

===RECAP_START===

Myanmar movie recap text here.

===RECAP_END===
"""

        # =================================================
        # GEMINI
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
        # TTS SERVER
        # =================================================

        await status.edit_text(
            "🔊 မြန်မာ MP3 အသံဖိုင် "
            "ပြုလုပ်နေပါတယ်...\n\n"
            "⏳ Generating voice, this may "
            "take up to a minute..."
        )

        voice = "my-MM-ThihaNeural"

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
            model=GEMINI_MODEL,
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
        # THUMBNAIL URL
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

        # =================================================
        # SEND THUMBNAIL
        # =================================================

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

        error_text = (
            "❌ Error ဖြစ်သွားပါတယ်။\n\n"
            + str(error)
        )

        try:

            await status.edit_text(
                error_text
            )

        except Exception:

            try:

                await update.message.reply_text(
                    error_text
                )

            except Exception:
                pass

    # =====================================================
    # CLEAN FILES
    # =====================================================

    finally:

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
# START TELEGRAM BOT
# =========================================================

def start_telegram_bot():

    global telegram_application

    try:

        telegram_application = (
            ApplicationBuilder()
            .token(
                TELEGRAM_BOT_TOKEN
            )
            .build()
        )

        telegram_application.add_handler(
            CommandHandler(
                "start",
                start
            )
        )

        telegram_application.add_handler(
            MessageHandler(
                filters.AUDIO
                | filters.VOICE,
                handle_audio
            )
        )

        logger.info(
            "Telegram bot starting..."
        )

        telegram_application.run_polling(
            drop_pending_updates=True
        )

    except Exception as error:

        logger.exception(
            "Telegram bot stopped: %s",
            error
        )


# =========================================================
# START BOT IN BACKGROUND THREAD
# =========================================================

bot_thread = Thread(
    target=start_telegram_bot,
    daemon=True
)

bot_thread.start()


# =========================================================
# GUNICORN ENTRY POINT
# =========================================================

if __name__ == "__main__":

    web_app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False
    )
