import os
import asyncio
import logging
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
# ENVIRONMENT
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# TEXT / AUDIO MODEL
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

# IMAGE MODEL
IMAGE_MODEL = os.getenv(
    "IMAGE_MODEL",
    "gemini-3.1-flash-image"
)

PORT = int(os.getenv("PORT", "10000"))

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
        "Flask server started on port %s",
        PORT
    )


# =========================================================
# TELEGRAM LONG MESSAGE
# =========================================================

async def send_long_message(
    update: Update,
    text: str,
    max_length: int = 4000
):

    if not text:
        return

    remaining = text.strip()

    while len(remaining) > max_length:

        cut = remaining.rfind(
            "\n",
            0,
            max_length
        )

        if cut < 1000:
            cut = remaining.rfind(
                " ",
                0,
                max_length
            )

        if cut < 1000:
            cut = max_length

        chunk = remaining[:cut].strip()

        if chunk:

            await update.message.reply_text(
                chunk
            )

        remaining = remaining[cut:].strip()

    if remaining:

        await update.message.reply_text(
            remaining
        )


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "မင်္ဂလာပါ 👋\n\n"

        "🤖 Gemini Movie Recap Bot ဖြစ်ပါတယ်။\n\n"

        "🎬 MP3 / Voice ပို့ရင်\n"
        "• Movie Recap\n"
        "• Myanmar MP3\n"
        "• SRT Subtitle\n"
        "• Thumbnail Prompt\n"
        "ထုတ်ပေးနိုင်ပါတယ်။\n\n"

        "💬 စာပို့ရင် Gemini ကို မေးနိုင်ပါတယ်။\n\n"

        "🖼️ ပုံပို့ပြီးနောက်\n"
        "ဘာပြင်ချင်လဲ စာနဲ့ပြောပါ။\n\n"

        "ဥပမာ:\n"
        "• နောက်ခံကို ဖယ်ပေးပါ\n"
        "• 9:16 ပြောင်းပေးပါ\n"
        "• ပိုကြည်အောင်လုပ်ပါ\n"
        "• လူရဲ့အဝတ်အစားပြောင်းပါ\n"
        "• Movie Thumbnail ပုံစံလုပ်ပါ\n"
        "• နောက်ခံကို ညဘက်အဖြစ်ပြောင်းပါ\n\n"

        "📌 ပုံပို့ပြီး ပြင်ခိုင်းနိုင်ပါတယ်။"
    )

    await update.message.reply_text(
        text
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
# IMAGE EDITING
# =========================================================

async def handle_photo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    photo = update.message.photo[-1]

    status = None

    image_path = None
    output_path = None

    try:

        status = await update.message.reply_text(
            "🖼️ ပုံကို လက်ခံရရှိပါပြီ။\n\n"
            "✏️ ဘာပြင်ချင်လဲ စာနဲ့ရေးပေးပါ။"
        )

        # -------------------------------------------------
        # CHECK CAPTION
        # -------------------------------------------------

        edit_prompt = (
            update.message.caption or ""
        ).strip()

        # -------------------------------------------------
        # IF NO PROMPT
        # -------------------------------------------------

        if not edit_prompt:

            await status.edit_text(
                "🖼️ ပုံရပါပြီ။\n\n"
                "ဥပမာ —\n"
                "• နောက်ခံဖယ်ပေးပါ\n"
                "• 9:16 ပြောင်းပေးပါ\n"
                "• Movie Thumbnail လုပ်ပေးပါ\n"
                "• ပုံကို ပိုကြည်အောင်လုပ်ပါ"
            )

            return

        # -------------------------------------------------
        # DOWNLOAD
        # -------------------------------------------------

        telegram_file = await context.bot.get_file(
            photo.file_id
        )

        image_path = (
            f"input_image_{photo.file_id}.jpg"
        )

        output_path = (
            f"edited_image_{photo.file_id}.png"
        )

        await telegram_file.download_to_drive(
            image_path
        )

        await status.edit_text(
            "🎨 Gemini Image AI က "
            "ပုံကို ပြင်နေပါတယ်...\n\n"
            "⏳ ခဏစောင့်ပါ..."
        )

        # -------------------------------------------------
        # READ IMAGE
        # -------------------------------------------------

        with open(
            image_path,
            "rb"
        ) as image_file:

            image_bytes = image_file.read()

        image_base64 = base64.b64encode(
            image_bytes
        ).decode("utf-8")

        # -------------------------------------------------
        # IMAGE EDIT PROMPT
        # -------------------------------------------------

        full_prompt = f"""
Edit the provided image according to the user's request.

USER REQUEST:
{edit_prompt}

IMPORTANT:

- Preserve the main subject unless the user
  specifically asks to change it.
- Keep the person's face and identity
  unchanged when possible.
- Keep realistic lighting and shadows.
- Make the requested edit naturally.
- Do not add unwanted text.
- Do not add watermarks.
- Do not change unrelated parts of the image.
- If the user asks for a new aspect ratio,
  compose the image naturally for that ratio.

Return the edited image.
"""

        # -------------------------------------------------
        # GEMINI INTERACTIONS API
        # -------------------------------------------------

        interaction = await asyncio.to_thread(
            client.interactions.create,
            model=IMAGE_MODEL,
            input=[
                {
                    "type": "text",
                    "text": full_prompt
                },
                {
                    "type": "image",
                    "data": image_base64,
                    "mime_type": "image/jpeg"
                }
            ],
        )

        # -------------------------------------------------
        # GET GENERATED IMAGE
        # -------------------------------------------------

        generated_image = (
            getattr(
                interaction,
                "output_image",
                None
            )
        )

        if generated_image:

            generated_data = getattr(
                generated_image,
                "data",
                None
            )

            if generated_data:

                image_output = base64.b64decode(
                    generated_data
                )

                with open(
                    output_path,
                    "wb"
                ) as output_file:

                    output_file.write(
                        image_output
                    )

        else:

            # ------------------------------------------------
            # FALLBACK: SEARCH STEPS
            # ------------------------------------------------

            found_image = False

            steps = getattr(
                interaction,
                "steps",
                []
            )

            for step in steps:

                step_type = getattr(
                    step,
                    "type",
                    ""
                )

                if step_type != "model_output":
                    continue

                content_blocks = getattr(
                    step,
                    "content",
                    []
                )

                for block in content_blocks:

                    block_type = getattr(
                        block,
                        "type",
                        ""
                    )

                    if block_type == "image":

                        block_data = getattr(
                            block,
                            "data",
                            None
                        )

                        if block_data:

                            image_output = (
                                base64.b64decode(
                                    block_data
                                )
                            )

                            with open(
                                output_path,
                                "wb"
                            ) as output_file:

                                output_file.write(
                                    image_output
                                )

                            found_image = True
                            break

                if found_image:
                    break

        # -------------------------------------------------
        # CHECK OUTPUT
        # -------------------------------------------------

        if not output_path or not os.path.exists(
            output_path
        ):

            raise RuntimeError(
                "Gemini image model did not "
                "return an image."
            )

        # -------------------------------------------------
        # DELETE STATUS
        # -------------------------------------------------

        try:
            await status.delete()
        except Exception:
            pass

        # -------------------------------------------------
        # SEND IMAGE
        # -------------------------------------------------

        with open(
            output_path,
            "rb"
        ) as output_image:

            await update.message.reply_photo(
                photo=output_image,
                caption="✅ ပုံပြင်ပြီးပါပြီ။"
            )

    except Exception as error:

        logger.exception(
            "Image editing error"
        )

        error_text = str(error)

        try:

            if status:

                await status.edit_text(
                    "❌ ပုံပြင်ရာမှာ Error "
                    "ဖြစ်သွားပါတယ်။\n\n"
                    + error_text
                )

            else:

                await update.message.reply_text(
                    "❌ ပုံပြင်ရာမှာ Error "
                    "ဖြစ်သွားပါတယ်။\n\n"
                    + error_text
                )

        except Exception:
            pass

    finally:

        for path in [
            image_path,
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

    if response.status_code != 200:

        try:

            data = response.json()

            message = (
                data.get("error")
                or data.get("message")
                or str(data)
            )

        except Exception:

            message = response.text

        raise RuntimeError(
            f"TTS Server HTTP "
            f"{response.status_code}: "
            f"{message}"
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
            "TTS response does not contain "
            "audio_base64."
        )

    word_boundaries = data.get(
        "word_boundaries",
        []
    )

    audio_bytes = base64.b64decode(
        audio_base64
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

        current.append(word)

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
                and
                len(current) >= 3
            ):

                should_break = True

        if next_word is None:

            should_break = True

        if should_break:

            groups.append(current)

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

    return "\n".join(lines)


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

        if update.message.audio:

            file_id = (
                update.message.audio.file_id
            )

        elif update.message.voice:

            file_id = (
                update.message.voice.file_id
            )

        else:

            raise RuntimeError(
                "Audio file not found."
            )

        input_path = (
            f"input_{file_id}.mp3"
        )

        srt_path = (
            f"subtitle_{file_id}.srt"
        )

        mp3_path = (
            f"burmese_{file_id}.mp3"
        )

        await status.edit_text(
            "📥 Audio ကို Download "
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

        await status.edit_text(
            "🎙️ Gemini က Audio ကို "
            "နားထောင်နေပါတယ်..."
        )

        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )

        prompt = """
You are a professional Myanmar movie recap writer.

Listen to the uploaded audio carefully.

Understand the entire story.

Create a natural, engaging Myanmar movie recap.

Rules:

1. Include important story events.
2. Keep character names accurate.
3. Translate dialogue naturally.
4. Do not invent events.
5. Do not add information not present
   in the audio.
6. Make it suitable for TikTok and YouTube.
7. Write clear natural Myanmar language.

Return ONLY:

===RECAP_START===

Myanmar movie recap

===RECAP_END===
"""

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
                "Gemini returned empty response."
            )

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
                "Recap text is empty."
            )

        # -------------------------------------------------
        # TTS
        # -------------------------------------------------

        await status.edit_text(
            "🔊 မြန်မာ MP3 အသံဖိုင် "
            "ပြုလုပ်နေပါတယ်..."
        )

        (
            audio_bytes,
            word_boundaries
        ) = await call_tts_server(
            text=recap_text
        )

        with open(
            mp3_path,
            "wb"
        ) as mp3_file:

            mp3_file.write(
                audio_bytes
            )

        # -------------------------------------------------
        # SRT
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
        # SEND RECAP
        # -------------------------------------------------

        try:
            await status.delete()
        except Exception:
            pass

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
                    caption="📄 Myanmar SRT"
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
                caption="🎧 မြန်မာ Recap MP3"
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

            except Exception as error:

                logger.warning(
                    "Gemini file delete error: %s",
                    error
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
            pass

    finally:

        for path in [
            input_path,
            srt_path,
            mp3_path
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

    # START

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # PHOTO / IMAGE EDITING

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            handle_photo
        )
    )

    # AUDIO

    application.add_handler(
        MessageHandler(
            filters.AUDIO
            |
            filters.VOICE,
            handle_audio
        )
    )

    # TEXT CHAT

    application.add_handler(
        MessageHandler(
            filters.TEXT
            &
            ~filters.COMMAND,
            handle_text
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
        "Text Model: %s",
        GEMINI_MODEL
    )

    logger.info(
        "Image Model: %s",
        IMAGE_MODEL
    )

    logger.info(
        "Text Chat: ENABLED"
    )

    logger.info(
        "Audio Recap: ENABLED"
    )

    logger.info(
        "Image Editing: ENABLED"
    )

    logger.info(
        "========================================"
    )

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main()
