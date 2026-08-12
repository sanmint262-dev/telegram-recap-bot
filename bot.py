import os
import asyncio
import logging
import base64
import time

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
# ENVIRONMENT
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY"
)

# =========================================================
# GEMINI MODEL
# =========================================================
#
# Low-cost Flash-Lite model
#
# You can override this in Render Environment Variables:
#
# GEMINI_MODEL=gemini-3.5-flash-lite
#
# =========================================================

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)


# =========================================================
# PORT
# =========================================================

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)


# =========================================================
# TTS SERVER
# =========================================================

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
        "Telegram Movie Recap Bot is running!"
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
        "Flask health server started on port %s",
        PORT
    )


# =========================================================
# SEND LONG TELEGRAM MESSAGE
# =========================================================

async def send_long_message(
    update: Update,
    text: str,
    max_length: int = 3900
):

    if not text:
        return

    text = text.strip()

    while text:

        if len(text) <= max_length:

            await update.message.reply_text(
                text
            )

            break

        chunk = text[:max_length]

        split_position = chunk.rfind(
            "\n"
        )

        if split_position < (
            max_length * 0.5
        ):

            split_position = chunk.rfind(
                " "
            )

        if split_position <= 0:

            split_position = max_length

        part = text[
            :split_position
        ].strip()

        if part:

            await update.message.reply_text(
                part
            )

        text = text[
            split_position:
        ].strip()


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

        "🎬 Audio / Voice ပို့ရင် —\n\n"

        "1️⃣ Gemini က Audio ကို နားထောင်မယ်\n"
        "2️⃣ မြန်မာ Movie Recap ပြန်ရေးမယ်\n"
        "3️⃣ မြန်မာ MP3 ပြုလုပ်မယ်\n"
        "4️⃣ Myanmar SRT ပြုလုပ်မယ်\n\n"

        "💬 စာပို့ရင် —\n"
        "Gemini ကို မေးနိုင်ပါတယ်။\n\n"

        "📌 Audio / Voice ဖိုင်ပို့ပြီး စတင်ပါ။\n\n"

        "⚡ Thumbnail generation မပါပါ။\n"
        "⚡ Gemini request ကို လျှော့ထားပါတယ်။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# GEMINI REQUEST
# =========================================================

async def gemini_generate(
    contents,
    retries=2
):

    last_error = None

    for attempt in range(
        retries
    ):

        try:

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_MODEL,
                contents=contents,
            )

            return response

        except Exception as error:

            last_error = error

            error_text = str(error)

            logger.error(
                "Gemini request failed: %s",
                error_text
            )

            # =================================================
            # 429 QUOTA
            # =================================================

            if (
                "429" in error_text
                or
                "RESOURCE_EXHAUSTED"
                in error_text
                or
                "quota"
                in error_text.lower()
            ):

                raise RuntimeError(
                    "Gemini quota/rate limit "
                    "ပြည့်နေပါတယ်။\n\n"
                    "ခဏစောင့်ပြီး ပြန်စမ်းပါ။\n\n"
                    + error_text
                )


            # =================================================
            # 404 MODEL ERROR
            # =================================================

            if (
                "404" in error_text
                or
                "NOT_FOUND"
                in error_text
            ):

                raise RuntimeError(
                    "Gemini model မရနိုင်ပါ။\n\n"
                    f"Current model: {GEMINI_MODEL}\n\n"
                    "Render Environment Variables "
                    "ထဲမှာ GEMINI_MODEL ကို စစ်ပါ။\n\n"
                    + error_text
                )


            # =================================================
            # TEMPORARY SERVER ERROR
            # =================================================

            temporary_error = (
                "503" in error_text
                or
                "UNAVAILABLE"
                in error_text
                or
                "500" in error_text
                or
                "INTERNAL"
                in error_text
            )


            if temporary_error:

                if attempt < retries - 1:

                    wait_time = (
                        5 * (attempt + 1)
                    )

                    logger.warning(
                        "Temporary Gemini error. "
                        "Retrying in %s seconds...",
                        wait_time
                    )

                    await asyncio.sleep(
                        wait_time
                    )

                    continue


            # =================================================
            # OTHER ERROR
            # =================================================

            raise RuntimeError(
                "Gemini request failed.\n\n"
                + error_text
            )


    raise RuntimeError(
        "Gemini request failed after retries.\n\n"
        + str(last_error)
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

        response = await gemini_generate(
            user_text
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

        error_message = str(error)

        try:

            if status:

                await status.edit_text(
                    "❌ Gemini Error\n\n"
                    + error_message
                )

            else:

                await update.message.reply_text(
                    "❌ Gemini Error\n\n"
                    + error_message
                )

        except Exception:

            pass


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

            data = response.json()

            error_message = (
                data.get("error")
                or
                data.get("message")
                or
                str(data)
            )

        except Exception:

            error_message = response.text

        raise RuntimeError(
            "TTS Server Error:\n\n"
            f"HTTP {response.status_code}\n"
            f"{error_message}"
        )


    # =====================================================
    # JSON
    # =====================================================

    try:

        data = response.json()

    except Exception as error:

        raise RuntimeError(
            "TTS server returned invalid JSON:\n"
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
            "TTS response does not contain "
            "audio_base64."
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
            "Could not decode audio_base64:\n"
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


        # -------------------------------------------------
        # Maximum 6 words
        # -------------------------------------------------

        if len(current) >= 6:

            should_break = True


        # -------------------------------------------------
        # Punctuation
        # -------------------------------------------------

        if text.endswith(
            punctuation
        ):

            if len(current) >= 3:

                should_break = True


        # -------------------------------------------------
        # Natural pause
        # -------------------------------------------------

        if next_word:

            next_offset = int(
                next_word.get(
                    "offset",
                    0
                )
            )

            pause = (
                next_offset - end_time
            )

            if (
                pause >= 600
                and
                len(current) >= 3
            ):

                should_break = True


        # -------------------------------------------------
        # Last word
        # -------------------------------------------------

        if next_word is None:

            should_break = True


        if should_break:

            groups.append(
                current
            )

            current = []


    # =====================================================
    # CREATE SRT
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

    if not update.message:

        return


    status = await update.message.reply_text(
        "📥 Audio ဖိုင်ကို လက်ခံရရှိပါပြီ။\n\n"
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
        # SAFE FILE NAME
        # =================================================

        safe_id = (
            file_id
            .replace("/", "_")
            .replace("\\", "_")
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


        # =================================================
        # DOWNLOAD FROM TELEGRAM
        # =================================================

        await status.edit_text(
            "📥 Audio ဖိုင် Download "
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
        # UPLOAD TO GEMINI
        # =================================================

        await status.edit_text(
            "🎙️ Gemini 3.5 Flash-Lite က "
            "Audio ကို နားထောင်နေပါတယ်..."
        )


        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )


        # =================================================
        # RECAP PROMPT
        # =================================================

        recap_prompt = """
You are a professional Myanmar movie recap writer.

Listen to the uploaded audio carefully.

Understand the complete story before writing.

TASK:

1. Understand all important events.
2. Identify important dialogue and narration.
3. Translate the story naturally into Myanmar.
4. Create an engaging Myanmar movie recap.
5. Keep character names accurate.
6. Keep important story details accurate.
7. Do NOT invent events.
8. Do NOT add information that is not present
   in the uploaded audio.
9. Make the narration natural for Myanmar
   TikTok and YouTube movie recap viewers.
10. Do not mention that you are an AI.
11. Do not explain your process.
12. Do not create a thumbnail prompt.
13. Do not create an image.

Write ONLY the Myanmar movie recap.

Use natural Myanmar language.

Use clear paragraphs.

Return ONLY:

===RECAP_START===

Myanmar movie recap here.

===RECAP_END===
"""


        # =================================================
        # GEMINI
        #
        # ONE GEMINI REQUEST FOR AUDIO RECAP
        # =================================================

        response = await gemini_generate(
            [
                audio_file,
                recap_prompt,
            ]
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
            "ပြုလုပ်နေပါတယ်..."
        )


        (
            audio_bytes,
            word_boundaries
        ) = await call_tts_server(
            text=recap_text,
            voice="my-MM-ThihaNeural",
            rate="+30%",
            pitch="+0Hz",
        )


        # =================================================
        # SAVE MP3
        # =================================================

        with open(
            mp3_path,
            "wb"
        ) as output_file:

            output_file.write(
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
        # DELETE STATUS
        # =================================================

        try:

            await status.delete()

        except Exception:

            pass


        # =================================================
        # SEND RECAP
        # =================================================

        await send_long_message(
            update,
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

        else:

            await update.message.reply_text(
                "⚠️ SRT timestamp မရရှိလို့ "
                "SRT ဖိုင် မထုတ်နိုင်ပါ။"
            )


        # =================================================
        # SEND MP3
        # =================================================

        with open(
            mp3_path,
            "rb"
        ) as mp3_file:

            await update.message.reply_audio(
                audio=mp3_file,
                filename="burmese_recap.mp3",
                caption="🎧 မြန်မာဘာသာပြန် MP3"
            )


        # =================================================
        # SUCCESS
        # =================================================

        await update.message.reply_text(
            "✅ အားလုံးပြီးပါပြီ။\n\n"
            "🎬 Myanmar Recap — ✅\n"
            "🎧 Myanmar MP3 — ✅\n"
            "📄 Myanmar SRT — ✅\n\n"
            "🖼️ Thumbnail — မသုံးထားပါ။"
        )


    # =====================================================
    # ERROR
    # =====================================================

    except Exception as error:

        logger.exception(
            "Audio processing error"
        )


        error_message = str(
            error
        )


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


    # =====================================================
    # CLEANUP
    # =====================================================

    finally:

        # -------------------------------------------------
        # Delete Gemini uploaded file
        # -------------------------------------------------

        if audio_file:

            try:

                await asyncio.to_thread(
                    client.files.delete,
                    name=audio_file.name
                )

            except Exception as error:

                logger.warning(
                    "Gemini file delete failed: %s",
                    error
                )


        # -------------------------------------------------
        # Delete local files
        # -------------------------------------------------

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

    error = context.error

    logger.error(
        "Telegram error: %s",
        error
    )


# =========================================================
# CREATE APPLICATION
# =========================================================

def create_application():

    application = (
        ApplicationBuilder()
        .token(
            TELEGRAM_BOT_TOKEN
        )
        .build()
    )


    # =====================================================
    # START
    # =====================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    # =====================================================
    # AUDIO / VOICE
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.AUDIO
            |
            filters.VOICE,
            handle_audio
        )
    )


    # =====================================================
    # TEXT CHAT
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            handle_text
        )
    )


    # =====================================================
    # ERROR
    # =====================================================

    application.add_error_handler(
        error_handler
    )


    return application


# =========================================================
# MAIN
# =========================================================

def main():

    # =====================================================
    # START FLASK
    # =====================================================

    start_web_server()


    # =====================================================
    # CREATE TELEGRAM APPLICATION
    # =====================================================

    application = create_application()


    # =====================================================
    # LOG
    # =====================================================

    logger.info(
        "========================================"
    )

    logger.info(
        "🤖 Telegram Movie Recap Bot Started"
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
        "Audio Recap: ENABLED"
    )

    logger.info(
        "Myanmar MP3: ENABLED"
    )

    logger.info(
        "Myanmar SRT: ENABLED"
    )

    logger.info(
        "Thumbnail Generation: DISABLED"
    )

    logger.info(
        "Thumbnail Gemini Request: DISABLED"
    )

    logger.info(
        "========================================"
    )


    # =====================================================
    # TELEGRAM POLLING
    # =====================================================

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
