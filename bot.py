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

# Existing TTS Server
TTS_URL = "https://student-recap-tts.onrender.com/tts-srt"

# Gemini Model
GEMINI_MODEL = "gemini-3.6-flash"


# =========================================================
# CHECK ENVIRONMENT
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
        daemon=True,
    )

    thread.start()

    logger.info(
        f"Flask health server started on port {PORT}"
    )


# =========================================================
# START COMMAND
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
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

    await update.message.reply_text(welcome)


# =========================================================
# TTS SERVER CALL
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
            json=payload,
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
            f"TTS Server HTTP {response.status_code}: "
            f"{error_message}"
        )

    # =====================================================
    # JSON RESPONSE
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

    audio_base64 = data.get("audio_base64")

    if not audio_base64:

        raise RuntimeError(
            "TTS server response does not contain "
            "audio_base64."
        )

    # =====================================================
    # WORD BOUNDARIES
    # =====================================================

    word_boundaries = data.get(
        "word_boundaries",
        [],
    )

    # =====================================================
    # DECODE BASE64
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

    return audio_bytes, word_boundaries


# =========================================================
# SRT TIMESTAMP
# =========================================================

def srt_timestamp(milliseconds):

    milliseconds = max(
        0,
        int(milliseconds),
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

def build_srt(word_boundaries):

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
                "",
            )
        ).strip()

        offset = int(
            word.get(
                "offset",
                0,
            )
        )

        duration = int(
            word.get(
                "duration",
                0,
            )
        )

        end_time = offset + duration

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

        # =================================================
        # 3-6 WORD CHUNKS
        # =================================================

        if len(current) >= 6:
            should_break = True

        # =================================================
        # PUNCTUATION
        # =================================================

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

        # =================================================
        # NATURAL PAUSE
        # =================================================

        if next_word:

            next_offset = int(
                next_word.get(
                    "offset",
                    0,
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

        # =================================================
        # END
        # =================================================

        if next_word is None:
            should_break = True

        if should_break:

            groups.append(current)

            current = []

    # =====================================================
    # BUILD SRT
    # =====================================================

    srt_lines = []

    for number, group in enumerate(
        groups,
        start=1,
    ):

        if not group:
            continue

        start = int(
            group[0].get(
                "offset",
                0,
            )
        )

        last = group[-1]

        end = (
            int(
                last.get(
                    "offset",
                    0,
                )
            )
            +
            int(
                last.get(
                    "duration",
                    0,
                )
            )
        )

        subtitle_text = " ".join(
            str(
                item.get(
                    "text",
                    "",
                )
            ).strip()
            for item in group
        ).strip()

        srt_lines.append(
            str(number)
        )

        srt_lines.append(
            f"{srt_timestamp(start)} --> "
            f"{srt_timestamp(end)}"
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
    context: ContextTypes.DEFAULT_TYPE,
):

    status = await update.message.reply_text(
        "📥 MP3 ဖိုင်ကို လက်ခံရရှိပါပြီ...\n\n"
        "⏳ Processing စတင်နေပါတယ်။"
    )

    file_id = None
    input_path = None
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
        # FILE PATH
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
        # GEMINI AUDIO
        # =================================================

        await status.edit_text(
            "🎙️ Gemini 3.6 Flash က Audio ကို "
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
2. Translate important dialogue/narration naturally into Myanmar.
3. Create an engaging Myanmar movie recap.
4. Do not invent events that are not present in the audio.

IMPORTANT:

The SRT generated later by the TTS server will use
word boundaries from the Myanmar voiceover.

Therefore focus on producing a clean, natural,
well-written Myanmar recap.

Return ONLY this structure:

===RECAP_START===

မြန်မာလို Movie Recap

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

        result = response.text or ""

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
            "🔊 မြန်မာ MP3 အသံဖိုင် ပြုလုပ်နေပါတယ်...\n\n"
            "⏳ Generating voice, this may take "
            "up to a minute..."
        )

        voice = "my-MM-ThihaNeural"

        rate = "+30%"

        pitch = "+0Hz"

        (
            audio_bytes,
            word_boundaries,
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
                encoding="utf-8",
            ) as srt_file:

                srt_file.write(
                    generated_srt
                )

        # =================================================
        # THUMBNAIL PROMPT
        # =================================================

        await status.edit_text(
            "🖼️ Gemini 3.6 Flash နဲ့ "
            "Thumbnail Prompt ပြုလုပ်နေပါတယ်..."
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
            contents=thumbnail_request,
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
                f"Thumbnail failed: {image_error}"
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

        # =================================================
        # CLEAN TEMP FILES
        # =================================================

        for path in [
            input_path,

            (
                f"subtitle_{file_id}.srt"
                if file_id
                else None
            ),

            (
                f"burmese_{file_id}.mp3"
                if file_id
                else None
            ),
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

    # Flask health server
    start_web_server()

    # Telegram application
    application = (
        ApplicationBuilder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
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

    # IMPORTANT:
    # Only ONE instance of this bot may run.

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
