import os
import asyncio
import logging
import urllib.parse
import base64
from threading import Thread

import httpx
from flask import Flask
from google import genai
from google.genai import types

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

# Main Gemini model
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

# Image generation / editing model
GEMINI_IMAGE_MODEL = os.getenv(
    "GEMINI_IMAGE_MODEL",
    "gemini-3.1-flash-image"
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
# SMART LONG MESSAGE SPLITTER
# =========================================================

def split_long_text(
    text: str,
    max_length: int = 4000
):

    if not text:
        return []

    text = str(text)

    chunks = []

    remaining = text

    while len(remaining) > max_length:

        # -------------------------------------------------
        # Prefer newline
        # -------------------------------------------------

        cut = remaining.rfind(
            "\n",
            0,
            max_length
        )

        # -------------------------------------------------
        # Then space
        # -------------------------------------------------

        if cut < int(max_length * 0.60):

            cut = remaining.rfind(
                " ",
                0,
                max_length
            )

        # -------------------------------------------------
        # If no good break point
        # -------------------------------------------------

        if cut < 1:

            cut = max_length

        chunk = remaining[
            :cut
        ].strip()

        if chunk:

            chunks.append(
                chunk
            )

        remaining = remaining[
            cut:
        ].lstrip()

    if remaining.strip():

        chunks.append(
            remaining.strip()
        )

    return chunks


# =========================================================
# SEND LONG TELEGRAM MESSAGE
# =========================================================

async def send_long_message(
    update: Update,
    text: str,
    max_length: int = 4000
):

    if not text:
        return

    chunks = split_long_text(
        text,
        max_length
    )

    for chunk in chunks:

        await update.message.reply_text(
            chunk
        )

        await asyncio.sleep(
            0.15
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
        "5️⃣ Thumbnail ထုတ်ပေးမယ်\n\n"

        "💬 စာပို့ရင် —\n"
        "Gemini ကို အကြောင်းအရာမရွေး မေးနိုင်ပါတယ်။\n\n"

        "🖼️ ပုံပို့ပြီး Caption ထည့်ရင် —\n"
        "AI နဲ့ ပုံပြင်နိုင်ပါတယ်။\n\n"

        "📌 ဥပမာ —\n"
        "ပုံပို့ → \"နောက်ခံကို ဖယ်ပေးပါ\"\n\n"

        "သို့မဟုတ် —\n"
        "\"ဒီပုံကို 9:16 Movie Poster လုပ်ပေးပါ\"\n\n"

        "🚀 စတင်အသုံးပြုနိုင်ပါပြီ။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# TEXT CHAT HANDLER
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
            "🤖 Gemini 3.6 Flash စဉ်းစားနေပါတယ်..."
        )

        # -------------------------------------------------
        # GEMINI TEXT
        # -------------------------------------------------

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

        # -------------------------------------------------
        # DELETE STATUS
        # -------------------------------------------------

        try:

            await status.delete()

        except Exception:

            pass

        # -------------------------------------------------
        # SEND ANSWER
        # -------------------------------------------------

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
# PHOTO EDIT HANDLER
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.photo:
        return

    # -----------------------------------------------------
    # Get highest resolution photo
    # -----------------------------------------------------

    photo = (
        update.message.photo[-1]
    )

    # -----------------------------------------------------
    # Caption = editing instruction
    # -----------------------------------------------------

    edit_prompt = (
        update.message.caption or ""
    ).strip()

    if not edit_prompt:

        edit_prompt = (
            "Improve this image naturally. "
            "Keep the main subject recognizable "
            "and preserve the important details."
        )

    status = await update.message.reply_text(
        "🖼️ ပုံကို လက်ခံရရှိပါပြီ...\n\n"
        "🎨 AI က ပုံကို ပြင်နေပါတယ်..."
    )

    input_path = None
    output_path = None

    try:

        # =================================================
        # DOWNLOAD PHOTO
        # =================================================

        telegram_file = (
            await context.bot.get_file(
                photo.file_id
            )
        )

        input_path = (
            f"input_image_{photo.file_id}.jpg"
        )

        await telegram_file.download_to_drive(
            input_path
        )

        # =================================================
        # READ IMAGE
        # =================================================

        with open(
            input_path,
            "rb"
        ) as image_file:

            image_bytes = (
                image_file.read()
            )

        # =================================================
        # MIME TYPE
        # =================================================

        mime_type = (
            "image/jpeg"
        )

        # =================================================
        # IMAGE EDIT PROMPT
        # =================================================

        final_prompt = f"""
Edit the provided image according to the user's instruction.

USER INSTRUCTION:
{edit_prompt}

IMPORTANT:
- Follow the user's requested edit precisely.
- Preserve the original subject identity when requested.
- Do not unnecessarily change unrelated objects.
- Keep realistic lighting and natural proportions.
- If the user asks to change only one element,
  keep everything else as close to the original as possible.
"""

        # =================================================
        # GEMINI IMAGE EDIT
        # =================================================

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_IMAGE_MODEL,
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                ),
                final_prompt,
            ],
            config=types.GenerateContentConfig(
                response_modalities=[
                    "TEXT",
                    "IMAGE"
                ],
                response_format={
                    "image": {
                        "aspect_ratio": "1:1",
                        "image_size": "1K"
                    }
                }
            )
        )

        # =================================================
        # FIND IMAGE
        # =================================================

        generated_image = None

        for part in response.parts:

            if part.inline_data is not None:

                try:

                    generated_image = (
                        part.as_image()
                    )

                except Exception:

                    generated_image = None

                if generated_image:

                    break

        if generated_image is None:

            raise RuntimeError(
                "Gemini က edited image "
                "ပြန်မထုတ်နိုင်ပါ။"
            )

        # =================================================
        # SAVE IMAGE
        # =================================================

        output_path = (
            f"edited_{photo.file_id}.png"
        )

        generated_image.save(
            output_path
        )

        # =================================================
        # DELETE STATUS
        # =================================================

        try:

            await status.delete()

        except Exception:

            pass

        # =================================================
        # SEND EDITED IMAGE
        # =================================================

        with open(
            output_path,
            "rb"
        ) as image_file:

            await update.message.reply_photo(
                photo=image_file,
                caption=(
                    "🎨 ပုံပြင်ပြီးပါပြီ။\n\n"
                    "📝 ပြင်ခိုင်းထားတာ:\n"
                    + edit_prompt
                )
            )

    except Exception as error:

        logger.exception(
            "Image edit error"
        )

        try:

            await status.edit_text(
                "❌ ပုံပြင်ရာမှာ Error ဖြစ်သွားပါတယ်။\n\n"
                + str(error)
            )

        except Exception:

            pass

    finally:

        # -------------------------------------------------
        # CLEANUP
        # -------------------------------------------------

        for path in [
            input_path,
            output_path
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
    # AUDIO BASE64
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

        # -------------------------------------------------
        # MAX 6 WORDS
        # -------------------------------------------------

        if len(current) >= 6:

            should_break = True

        # -------------------------------------------------
        # PUNCTUATION
        # -------------------------------------------------

        if text.endswith(
            punctuation
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

        # =================================================
        # FILE ID
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
        # PATHS
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
        # DOWNLOAD
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
        # GEMINI AUDIO UPLOAD
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
        # MOVIE RECAP PROMPT
        # =================================================

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
9. Do not add information that is not in
   the uploaded audio.

Write the recap with natural paragraphs.

Do NOT use unnecessary headings.

Return ONLY:

===RECAP_START===

Myanmar movie recap here.

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

            recap_text = (
                result.strip()
            )

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
            "⏳ Generating voice..."
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
            "🖼️ Thumbnail ပြုလုပ်နေပါတယ်..."
        )

        thumbnail_request = f"""
Create one cinematic English prompt
for a movie recap thumbnail.

Use ONLY the story information
from this recap:

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
        # GENERATE THUMBNAIL WITH GEMINI IMAGE MODEL
        # =================================================

        thumbnail_image = None

        try:

            thumbnail_response = await asyncio.to_thread(
                client.models.generate_content,
                model=GEMINI_IMAGE_MODEL,
                contents=[
                    thumbnail_prompt
                ],
                config=types.GenerateContentConfig(
                    response_modalities=[
                        "TEXT",
                        "IMAGE"
                    ],
                    response_format={
                        "image": {
                            "aspect_ratio": "16:9",
                            "image_size": "1K"
                        }
                    }
                )
            )

            for part in thumbnail_response.parts:

                if part.inline_data is not None:

                    try:

                        thumbnail_image = (
                            part.as_image()
                        )

                    except Exception:

                        thumbnail_image = None

                    if thumbnail_image:

                        break

        except Exception as thumbnail_error:

            logger.warning(
                "Gemini thumbnail generation failed: %s",
                thumbnail_error
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
        # SEND THUMBNAIL
        # =================================================

        if thumbnail_image:

            thumbnail_path = (
                f"thumbnail_{file_id}.png"
            )

            try:

                thumbnail_image.save(
                    thumbnail_path
                )

                with open(
                    thumbnail_path,
                    "rb"
                ) as thumbnail_file:

                    await update.message.reply_photo(
                        photo=thumbnail_file,
                        caption=(
                            "🖼️ Gemini AI Thumbnail\n\n"
                            + thumbnail_prompt
                        )
                    )

            finally:

                if os.path.exists(
                    thumbnail_path
                ):

                    try:

                        os.remove(
                            thumbnail_path
                        )

                    except Exception:

                        pass

        else:

            # Fallback: send prompt
            await send_long_message(
                update,
                "⚠️ Thumbnail ပုံ မထုတ်နိုင်ပါ။\n\n"
                "Thumbnail Prompt:\n"
                + thumbnail_prompt
            )

        # =================================================
        # DELETE GEMINI AUDIO FILE
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
    # PHOTO
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # -----------------------------------------------------
    # AUDIO / VOICE
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
        "Gemini Text/Audio Model: %s",
        GEMINI_MODEL
    )

    logger.info(
        "Gemini Image Model: %s",
        GEMINI_IMAGE_MODEL
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
        "Photo Editing: ENABLED"
    )

    logger.info(
        "Thumbnail Generation: ENABLED"
    )

    logger.info(
        "========================================"
    )

    # Important for Render
    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
