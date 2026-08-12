import os
import asyncio
import logging
import base64
import re
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

# =========================================================
# IMPORTANT
# =========================================================
# Use Gemini 3.6 Flash for:
# - Text chat
# - Audio understanding
# - Movie recap
#
# DO NOT use gemini-3.1-flash-image
# because your image quota is currently 0.
# =========================================================

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
        "Flask health server started on port %s",
        PORT
    )


# =========================================================
# TELEGRAM LONG MESSAGE
# =========================================================

TELEGRAM_MAX_LENGTH = 4000


def split_text_safely(
    text: str,
    max_length: int = TELEGRAM_MAX_LENGTH
):

    """
    Split long text without cutting words or
    Myanmar sentences unnecessarily.

    Priority:
    1. Paragraph / newline
    2. Sentence punctuation
    3. Space
    4. Hard split
    """

    if not text:
        return []

    text = text.strip()

    if len(text) <= max_length:
        return [text]

    chunks = []

    remaining = text

    while len(remaining) > max_length:

        candidate = remaining[:max_length]

        split_position = -1

        # -------------------------------------------------
        # 1. Prefer newline
        # -------------------------------------------------

        newline_positions = [
            candidate.rfind("\n\n"),
            candidate.rfind("\n"),
        ]

        for position in newline_positions:

            if position > max_length * 0.50:

                split_position = position

                break

        # -------------------------------------------------
        # 2. Prefer Myanmar / English punctuation
        # -------------------------------------------------

        if split_position == -1:

            punctuation_positions = []

            for punctuation in [
                "။",
                "!",
                "?",
                "၊",
                ".",
                ",",
                ";",
                ":",
            ]:

                position = candidate.rfind(
                    punctuation
                )

                if position > max_length * 0.50:

                    punctuation_positions.append(
                        position + 1
                    )

            if punctuation_positions:

                split_position = max(
                    punctuation_positions
                )

        # -------------------------------------------------
        # 3. Prefer space
        # -------------------------------------------------

        if split_position == -1:

            space_position = candidate.rfind(
                " "
            )

            if space_position > max_length * 0.50:

                split_position = (
                    space_position
                )

        # -------------------------------------------------
        # 4. Hard split
        # -------------------------------------------------

        if split_position == -1:

            split_position = max_length

        chunk = remaining[
            :split_position
        ].strip()

        if chunk:

            chunks.append(
                chunk
            )

        remaining = remaining[
            split_position:
        ].strip()

    if remaining:

        chunks.append(
            remaining
        )

    return chunks


async def send_long_message(
    update: Update,
    text: str
):

    if not text:
        return

    chunks = split_text_safely(
        text,
        TELEGRAM_MAX_LENGTH
    )

    for index, chunk in enumerate(
        chunks
    ):

        try:

            await update.message.reply_text(
                chunk
            )

        except Exception as error:

            logger.error(
                "Telegram message send failed: %s",
                error
            )

            # Fallback hard split
            if len(chunk) > 4000:

                for start in range(
                    0,
                    len(chunk),
                    3900
                ):

                    await update.message.reply_text(
                        chunk[
                            start:start + 3900
                        ]
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

        "🤖 Gemini Movie Recap Bot ဖြစ်ပါတယ်။\n\n"

        "🎬 MP3 / Voice ပို့ရင် —\n\n"

        "1️⃣ Audio ကို Gemini နားထောင်မယ်\n"
        "2️⃣ မြန်မာ Movie Recap ပြန်ရေးမယ်\n"
        "3️⃣ မြန်မာ MP3 ပြုလုပ်မယ်\n"
        "4️⃣ SRT Subtitle ပြုလုပ်မယ်\n"
        "5️⃣ Thumbnail Prompt ထုတ်မယ်\n\n"

        "💬 စာပို့ရင် —\n"
        "Gemini ကို အကြောင်းအရာမရွေး မေးနိုင်ပါတယ်။\n\n"

        "📝 စာရှည်ရင်လည်း Telegram limit "
        "အတိုင်း အလိုအလျောက်ခွဲပို့ပေးပါမယ်။\n\n"

        "🖼️ ပုံပို့ပြီး ပုံပြင်ခိုင်းနိုင်ပါတယ်။\n"
        "သို့သော် လက်ရှိ Image API quota မရှိသေးလို့ "
        "ပုံတကယ်ပြင်တဲ့ function ကို မဖွင့်ထားပါ။\n\n"

        "📌 MP3 ဖိုင်ပို့ပြီး စမ်းကြည့်ပါ။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# TEXT CHAT
# =========================================================

async def handle_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user_text = (
        update.message.text or ""
    ).strip()

    if not user_text:
        return

    status = None

    try:

        status = await update.message.reply_text(
            "🤖 Gemini စဉ်းစားနေပါတယ်..."
        )

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=user_text,
        )

        answer = (
            response.text
            if response.text
            else ""
        )

        if not answer.strip():

            raise RuntimeError(
                "Gemini returned an empty response."
            )

        try:

            await status.delete()

        except Exception:

            pass

        await send_long_message(
            update,
            answer
        )

    except Exception as error:

        logger.exception(
            "Text chat error"
        )

        error_text = str(error)

        try:

            if status:

                await status.edit_text(
                    "❌ Gemini Error\n\n"
                    + error_text
                )

            else:

                await update.message.reply_text(
                    "❌ Gemini Error\n\n"
                    + error_text
                )

        except Exception:

            pass


# =========================================================
# IMAGE HANDLER
# =========================================================

async def handle_image(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    """
    Image editing is intentionally disabled.

    Reason:
    gemini-3.1-flash-image currently has
    free-tier quota = 0 for this API key.

    This prevents repeated 429 errors.
    """

    await update.message.reply_text(
        "🖼️ ပုံကို လက်ခံရရှိပါပြီ။\n\n"
        "⚠️ လက်ရှိ Gemini Image API quota = 0 "
        "ဖြစ်နေတဲ့အတွက် ဒီ Bot ထဲကနေ ပုံကို "
        "တကယ်ပြင်ပြီး ပြန်ထုတ်ပေးတဲ့ function "
        "ကို ယာယီပိတ်ထားပါတယ်။\n\n"
        "🧠 Gemini 3.6 Flash Text/Audio function "
        "တွေကတော့ ဆက်အလုပ်လုပ်ပါတယ်။\n\n"
        "Image API quota ရလာတဲ့အခါ "
        "image-editing function ကို ထည့်နိုင်ပါတယ်။"
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

    try:

        data = response.json()

    except Exception as error:

        raise RuntimeError(
            "TTS server returned invalid JSON: "
            + str(error)
        )

    audio_base64 = data.get(
        "audio_base64"
    )

    if not audio_base64:

        raise RuntimeError(
            "TTS server response does not "
            "contain audio_base64."
        )

    word_boundaries = data.get(
        "word_boundaries",
        []
    )

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

        if len(current) >= 6:

            should_break = True

        if text.endswith(
            punctuation
        ):

            if len(current) >= 3:

                should_break = True

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

        if next_word is None:

            should_break = True

        if should_break:

            groups.append(
                current
            )

            current = []

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
        "📥 Audio ဖိုင်ကို လက်ခံရရှိပါပြီ...\n\n"
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

        # -------------------------------------------------
        # FILE PATHS
        # -------------------------------------------------

        safe_id = re.sub(
            r"[^a-zA-Z0-9_-]",
            "_",
            file_id
        )

        input_path = (
            f"input_{safe_id}.mp3"
        )

        srt_path = (
            f"subtitle_{safe_id}.srt"
        )

        mp3_path = (
            f"burmese_{safe_id}.mp3"
        )

        # -------------------------------------------------
        # DOWNLOAD
        # -------------------------------------------------

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

        # -------------------------------------------------
        # GEMINI UPLOAD
        # -------------------------------------------------

        await status.edit_text(
            "🎙️ Gemini Audio ကို "
            "နားထောင်နေပါတယ်..."
        )

        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )

        # -------------------------------------------------
        # RECAP PROMPT
        # -------------------------------------------------

        prompt = """
You are a professional movie recap translator.

Listen to the uploaded audio carefully.

Understand the complete story.

TASK:

1. Understand all important events.
2. Identify dialogue and narration.
3. Translate important information naturally
   into Myanmar.
4. Create an engaging Myanmar movie recap.
5. Do not invent events.
6. Keep character names and story details accurate.
7. Write naturally for Myanmar TikTok
   and YouTube movie recap viewers.
8. Make the recap easy to understand.
9. Do not add information that is not present
   in the uploaded audio.

IMPORTANT:

Write the recap in natural Myanmar language.

Use paragraphs and newline breaks.

Do NOT return one giant paragraph.

Return ONLY:

===RECAP_START===

Myanmar movie recap

===RECAP_END===
"""

        # -------------------------------------------------
        # GEMINI
        # -------------------------------------------------

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

        # -------------------------------------------------
        # EXTRACT RECAP
        # -------------------------------------------------

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

        # -------------------------------------------------
        # TTS
        # -------------------------------------------------

        await status.edit_text(
            "🔊 မြန်မာ MP3 အသံဖိုင် "
            "ပြုလုပ်နေပါတယ်...\n\n"
            "⏳ ခဏစောင့်ပေးပါ..."
        )

        audio_bytes, word_boundaries = (
            await call_tts_server(
                text=recap_text,
                voice="my-MM-ThihaNeural",
                rate="+30%",
                pitch="+0Hz",
            )
        )

        # -------------------------------------------------
        # SAVE MP3
        # -------------------------------------------------

        with open(
            mp3_path,
            "wb"
        ) as mp3_file:

            mp3_file.write(
                audio_bytes
            )

        # -------------------------------------------------
        # BUILD SRT
        # -------------------------------------------------

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

        # -------------------------------------------------
        # THUMBNAIL PROMPT
        # -------------------------------------------------

        await status.edit_text(
            "🖼️ Thumbnail Prompt "
            "ပြုလုပ်နေပါတယ်..."
        )

        thumbnail_request = f"""
Create ONE cinematic English prompt
for a movie recap thumbnail.

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
            "high detail, 16:9"
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

        await send_long_message(
            update,
            "🎬 မြန်မာ Movie Recap\n\n"
            + recap_text
        )

        # -------------------------------------------------
        # SEND SRT
        # -------------------------------------------------

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
        # THUMBNAIL
        # -------------------------------------------------
        #
        # IMPORTANT:
        # This uses Pollinations instead of
        # gemini-3.1-flash-image.
        #
        # Therefore the Gemini image quota=0
        # will NOT cause a Gemini 429 error here.
        # -------------------------------------------------

        try:

            import urllib.parse

            encoded_prompt = (
                urllib.parse.quote(
                    thumbnail_prompt
                )
            )

            thumbnail_url = (
                "https://image.pollinations.ai/prompt/"
                + encoded_prompt
                + "?width=1280"
                + "&height=720"
                + "&nologo=true"
            )

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

            await send_long_message(
                update,
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
                    "Gemini file delete failed: %s",
                    delete_error
                )

    except Exception as error:

        logger.exception(
            "Audio processing error"
        )

        error_message = str(error)

        try:

            await status.edit_text(
                "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                + error_message
            )

        except Exception:

            try:

                await update.message.reply_text(
                    "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                    + error_message
                )

            except Exception:

                pass

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
# CREATE TELEGRAM APPLICATION
# =========================================================

def create_application():

    application = (
        ApplicationBuilder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )

    # -----------------------------------------------------
    # START
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # -----------------------------------------------------
    # AUDIO
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.AUDIO
            |
            filters.VOICE,
            handle_audio
        )
    )

    # -----------------------------------------------------
    # IMAGE
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_image
        )
    )

    # -----------------------------------------------------
    # TEXT CHAT
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            handle_text
        )
    )

    # -----------------------------------------------------
    # ERROR
    # -----------------------------------------------------

    application.add_error_handler(
        error_handler
    )

    return application


# =========================================================
# MAIN
# =========================================================

def main():

    # Flask health server
    start_web_server()

    # Telegram MUST stay in main thread

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
        "Text Chat: ENABLED"
    )

    logger.info(
        "Audio Recap: ENABLED"
    )

    logger.info(
        "SRT: ENABLED"
    )

    logger.info(
        "Thumbnail: POLLINATIONS"
    )

    logger.info(
        "Gemini Image API: DISABLED"
    )

    logger.info(
        "========================================"
    )

    # IMPORTANT:
    # Prevent Render/thread set_wakeup_fd error.

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
