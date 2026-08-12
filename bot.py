import os
import asyncio
import logging
import urllib.parse
import base64
import random
import re

from threading import Thread
from datetime import datetime, timezone

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

# ---------------------------------------------------------
# MAIN MODEL
# ---------------------------------------------------------

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash"
)

# ---------------------------------------------------------
# FALLBACK MODEL
# ---------------------------------------------------------

GEMINI_FALLBACK_MODEL = os.getenv(
    "GEMINI_FALLBACK_MODEL",
    "gemini-2.5-flash"
)

# ---------------------------------------------------------
# ADMIN
# ---------------------------------------------------------

ADMIN_USER_ID = int(
    os.getenv(
        "ADMIN_USER_ID",
        "0"
    )
)

# ---------------------------------------------------------
# DAILY FREE LIMIT
# ---------------------------------------------------------

DAILY_FREE_LIMIT = int(
    os.getenv(
        "DAILY_FREE_LIMIT",
        "5"
    )
)

# ---------------------------------------------------------
# PORT
# ---------------------------------------------------------

PORT = int(
    os.getenv(
        "PORT",
        "10000"
    )
)

# ---------------------------------------------------------
# TTS
# ---------------------------------------------------------

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


if ADMIN_USER_ID == 0:

    logger.warning(
        "ADMIN_USER_ID is not configured."
    )


# =========================================================
# GEMINI CLIENT
# =========================================================

client = genai.Client(
    api_key=GEMINI_API_KEY
)


# =========================================================
# USER DAILY USAGE
# =========================================================

user_usage = {}


def get_today():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d"
    )


def is_admin(
    update: Update
):

    if not update.effective_user:

        return False

    return (
        update.effective_user.id
        == ADMIN_USER_ID
    )


def get_user_usage(
    user_id
):

    today = get_today()

    data = user_usage.get(
        user_id
    )

    if not data:

        data = {
            "date": today,
            "count": 0
        }

        user_usage[user_id] = data

        return data

    if data.get("date") != today:

        data = {
            "date": today,
            "count": 0
        }

        user_usage[user_id] = data

    return data


def check_daily_limit(
    update: Update
):

    # -----------------------------------------------------
    # ADMIN UNLIMITED
    # -----------------------------------------------------

    if is_admin(update):

        return True, 0

    # -----------------------------------------------------
    # USER CHECK
    # -----------------------------------------------------

    if not update.effective_user:

        return False, DAILY_FREE_LIMIT

    user_id = (
        update.effective_user.id
    )

    data = get_user_usage(
        user_id
    )

    used = data["count"]

    if used >= DAILY_FREE_LIMIT:

        return False, used

    return True, used


def use_daily_limit(
    update: Update
):

    if is_admin(update):

        return

    if not update.effective_user:

        return

    user_id = (
        update.effective_user.id
    )

    data = get_user_usage(
        user_id
    )

    data["count"] += 1

    user_usage[user_id] = data


def refund_daily_limit(
    update: Update
):

    """
    Gemini/TTS processing မအောင်မြင်ရင်
    အသုံးပြုထားတဲ့ quota 1 ကြိမ်ကို ပြန်ပေးမယ်။
    """

    if is_admin(update):

        return

    if not update.effective_user:

        return

    user_id = (
        update.effective_user.id
    )

    data = get_user_usage(
        user_id
    )

    if data["count"] > 0:

        data["count"] -= 1

    user_usage[user_id] = data


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

    remaining = (
        text.strip()
    )

    while remaining:

        if len(remaining) <= max_length:

            await update.message.reply_text(
                remaining
            )

            break

        chunk = remaining[
            :max_length
        ]

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

        part = (
            remaining[
                :split_position
            ]
            .strip()
        )

        if part:

            await update.message.reply_text(
                part
            )

        remaining = (
            remaining[
                split_position:
            ]
            .strip()
        )


# =========================================================
# GEMINI ERROR DETECTION
# =========================================================

def get_error_code(
    error
):

    text = str(
        error
    ).lower()

    if (
        "503" in text
        or
        "unavailable" in text
        or
        "service unavailable" in text
    ):

        return "503"

    if (
        "429" in text
        or
        "quota" in text
        or
        "resource_exhausted" in text
        or
        "too many requests" in text
    ):

        return "429"

    if "404" in text:

        return "404"

    if "403" in text:

        return "403"

    return "OTHER"


# =========================================================
# GEMINI SAFE REQUEST
# =========================================================

async def gemini_generate(
    contents,
    preferred_model=None,
    max_attempts=3,
):

    models = []

    first_model = (
        preferred_model
        or GEMINI_MODEL
    )

    if first_model:

        models.append(
            first_model
        )

    if (
        GEMINI_FALLBACK_MODEL
        and
        GEMINI_FALLBACK_MODEL
        not in models
    ):

        models.append(
            GEMINI_FALLBACK_MODEL
        )

    last_error = None

    for model_index, model in enumerate(
        models
    ):

        for attempt in range(
            max_attempts
        ):

            try:

                logger.info(
                    "Gemini request: model=%s attempt=%s",
                    model,
                    attempt + 1
                )

                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=contents,
                )

                if not response:

                    raise RuntimeError(
                        "Gemini returned no response."
                    )

                return response

            except Exception as error:

                last_error = error

                error_code = (
                    get_error_code(
                        error
                    )
                )

                logger.warning(
                    "Gemini error: model=%s code=%s attempt=%s error=%s",
                    model,
                    error_code,
                    attempt + 1,
                    error,
                )

                # -------------------------------------------------
                # DO NOT RETRY permanent errors
                # -------------------------------------------------

                if error_code in (
                    "403",
                    "404",
                ):

                    break

                # -------------------------------------------------
                # RETRY 429 / 503 / temporary errors
                # -------------------------------------------------

                if attempt < (
                    max_attempts - 1
                ):

                    delay = min(
                        30,
                        (
                            2 ** attempt
                        ) + random.uniform(
                            0.5,
                            1.5
                        )
                    )

                    logger.info(
                        "Retrying Gemini in %.1f seconds...",
                        delay
                    )

                    await asyncio.sleep(
                        delay
                    )

        # -----------------------------------------------------
        # Try fallback model
        # -----------------------------------------------------

        if model_index < (
            len(models) - 1
        ):

            logger.warning(
                "Switching Gemini model: %s -> %s",
                model,
                models[
                    model_index + 1
                ]
            )

            await asyncio.sleep(
                1
            )

    raise RuntimeError(
        "Gemini request failed after retries.\n\n"
        f"Last error: {last_error}"
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if is_admin(update):

        quota_text = (
            "👑 Admin Account\n"
            "♾️ Daily Recap Limit: Unlimited"
        )

    else:

        _, used = (
            check_daily_limit(
                update
            )
        )

        quota_text = (
            "👤 Free User\n"
            f"📊 Today: {used}/{DAILY_FREE_LIMIT}"
        )

    welcome = (
        "မင်္ဂလာပါ 👋\n\n"

        "🤖 Gemini Movie Recap Bot ဖြစ်ပါတယ်။\n\n"

        f"{quota_text}\n\n"

        "🎬 MP3 / Voice ပို့ရင် —\n\n"

        "1️⃣ Audio ကို Gemini နားထောင်မယ်\n"
        "2️⃣ မြန်မာ Movie Recap ပြန်ရေးမယ်\n"
        "3️⃣ မြန်မာ MP3 ပြုလုပ်မယ်\n"
        "4️⃣ SRT Subtitle ပြုလုပ်မယ်\n"
        "5️⃣ Thumbnail Prompt ထုတ်မယ်\n"
        "6️⃣ Thumbnail ပုံထုတ်မယ်\n\n"

        "💬 စာပို့ရင် Gemini Chat အသုံးပြုနိုင်ပါတယ်။\n\n"

        "📌 /quota → ဒီနေ့ quota စစ်ရန်\n\n"

        "🎧 MP3 / Voice ဖိုင် ပို့ပြီး စတင်ပါ။"
    )

    await update.message.reply_text(
        welcome
    )


# =========================================================
# QUOTA
# =========================================================

async def quota(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if is_admin(update):

        await update.message.reply_text(
            "👑 Admin Account\n\n"
            "♾️ Daily Recap Limit: Unlimited"
        )

        return

    if not update.effective_user:

        return

    data = get_user_usage(
        update.effective_user.id
    )

    used = data["count"]

    remaining = max(
        0,
        DAILY_FREE_LIMIT - used
    )

    await update.message.reply_text(
        "📊 Daily Free Quota\n\n"
        f"အသုံးပြုပြီး: {used}\n"
        f"ကျန်ရှိ: {remaining}\n"
        f"Limit: {DAILY_FREE_LIMIT}/day\n\n"
        "🔄 နောက်နေ့မှာ quota ပြန်ရပါမယ်။"
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
        update.message.text
        or ""
    ).strip()

    if not user_text:

        return

    status = None

    try:

        status = await update.message.reply_text(
            "🤖 Gemini စဉ်းစားနေပါတယ်..."
        )

        response = await gemini_generate(
            contents=user_text,
            max_attempts=3
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

        error_code = (
            get_error_code(
                error
            )
        )

        if error_code == "503":

            error_text = (
                "⚠️ Gemini Server ခဏအလုပ်များနေပါတယ်။\n\n"
                "🔄 Bot က Retry လုပ်ပြီးပါပြီ။\n"
                "ခဏအကြာ ပြန်စမ်းကြည့်ပါ။"
            )

        elif error_code == "429":

            error_text = (
                "⚠️ Gemini API quota/rate limit ပြည့်နေပါတယ်။\n\n"
                "Google API quota ပြန်ရတဲ့အထိ စောင့်ရပါမယ်။"
            )

        else:

            error_text = (
                "❌ Gemini Error\n\n"
                + str(error)
            )

        try:

            if status:

                await status.edit_text(
                    error_text
                )

            else:

                await update.message.reply_text(
                    error_text
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

    if response.status_code != 200:

        try:

            error_data = (
                response.json()
            )

            error_message = (
                error_data.get("error")
                or
                error_data.get("message")
                or
                str(error_data)
            )

        except Exception:

            error_message = (
                response.text
            )

        raise RuntimeError(
            f"TTS Server HTTP "
            f"{response.status_code}: "
            f"{error_message}"
        )

    try:

        data = (
            response.json()
        )

    except Exception as error:

        raise RuntimeError(
            "TTS server returned invalid JSON: "
            + str(error)
        )

    audio_base64 = (
        data.get(
            "audio_base64"
        )
    )

    if not audio_base64:

        raise RuntimeError(
            "TTS server response does not "
            "contain audio_base64."
        )

    word_boundaries = (
        data.get(
            "word_boundaries",
            []
        )
    )

    try:

        audio_bytes = (
            base64.b64decode(
                audio_base64
            )
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
            offset
            +
            duration
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
                and
                len(current) >= 3
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
            str(
                subtitle_number
            )
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
# CREATE THUMBNAIL URL
# =========================================================

def create_thumbnail_url(
    thumbnail_prompt
):

    encoded_prompt = (
        urllib.parse.quote(
            thumbnail_prompt
        )
    )

    return (
        "https://image.pollinations.ai/prompt/"
        + encoded_prompt
        + "?width=1280"
        + "&height=720"
        + "&nologo=true"
    )


# =========================================================
# CLEAN PROMPT
# =========================================================

def clean_thumbnail_prompt(
    text
):

    if not text:

        return (
            "cinematic movie recap poster, "
            "dramatic lighting, "
            "realistic characters, "
            "emotional scene, "
            "high detail, "
            "16:9, no text"
        )

    text = (
        text.strip()
    )

    text = re.sub(
        r"```.*?```",
        "",
        text,
        flags=re.DOTALL
    )

    return text.strip()


# =========================================================
# AUDIO HANDLER
# =========================================================

async def handle_audio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    # =====================================================
    # CHECK LIMIT
    # =====================================================

    allowed, used = (
        check_daily_limit(
            update
        )
    )

    if not allowed:

        await update.message.reply_text(
            "⚠️ ဒီနေ့အတွက် Free quota ပြည့်သွားပါပြီ။\n\n"
            f"📊 အသုံးပြုပြီး: "
            f"{used}/{DAILY_FREE_LIMIT}\n\n"
            "🔄 မနက်ဖြန် ပြန်သုံးနိုင်ပါတယ်။"
        )

        return

    # =====================================================
    # STATUS
    # =====================================================

    status = await update.message.reply_text(
        "📥 Audio ဖိုင်ကို လက်ခံရရှိပါပြီ...\n\n"
        "⏳ Processing စတင်နေပါတယ်..."
    )

    file_id = None

    input_path = None
    srt_path = None
    mp3_path = None

    audio_file = None

    quota_consumed = False

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

            raise RuntimeError(
                "Audio ဖိုင် မတွေ့ပါ။"
            )

        # =================================================
        # FILE PATHS
        # =================================================

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

        # =================================================
        # DOWNLOAD
        # =================================================

        await status.edit_text(
            "📥 Audio ဖိုင်ကို Download လုပ်နေပါတယ်..."
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
            "🎙️ Gemini က Audio ကို နားထောင်နေပါတယ်...\n\n"
            f"Model: {GEMINI_MODEL}"
        )

        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )

        # =================================================
        # RECAP PROMPT
        # =================================================

        prompt = """
You are a professional Myanmar movie recap writer.

Listen to the uploaded audio carefully.

Understand the complete story.

TASK:

1. Understand all important events.
2. Identify dialogue and narration.
3. Translate the story naturally into Myanmar.
4. Create an engaging Myanmar movie recap.
5. Do not invent events.
6. Keep character names and story details accurate.
7. Make the narration easy to understand.
8. Use natural Myanmar language.
9. Write for TikTok / YouTube movie recap viewers.
10. Do not add information that is not contained
    in the uploaded audio.

IMPORTANT:

- Do NOT summarize too aggressively.
- Keep important story details.
- Explain events in chronological order.
- Use natural paragraphs.
- Avoid unnecessary headings.
- Do not include English explanations.

Return ONLY:

===RECAP_START===

Myanmar movie recap here.

===RECAP_END===
"""

        # =================================================
        # GEMINI AUDIO
        # =================================================

        response = await gemini_generate(
            contents=[
                audio_file,
                prompt,
            ],
            max_attempts=3
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
            "===RECAP_START==="
            in result
            and
            "===RECAP_END==="
            in result
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
Create ONE cinematic English prompt
for a movie recap thumbnail.

Use ONLY information from this Myanmar recap:

{recap_text}

Requirements:

- cinematic movie poster
- dramatic lighting
- emotional characters
- realistic faces
- realistic environment
- strong composition
- high detail
- dramatic atmosphere
- YouTube movie recap thumbnail
- 16:9
- no text
- no subtitles
- no watermark

Return ONLY the English image prompt.
"""

        thumbnail_response = (
            await gemini_generate(
                contents=thumbnail_request,
                max_attempts=3
            )
        )

        thumbnail_prompt = clean_thumbnail_prompt(
            thumbnail_response.text
            if thumbnail_response.text
            else ""
        )

        # =================================================
        # QUOTA CONSUMED
        # =================================================

        # IMPORTANT:
        # အားလုံးအောင်မြင်ပြီးမှ quota စားမယ်။

        use_daily_limit(
            update
        )

        quota_consumed = True

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
        # THUMBNAIL
        # =================================================

        thumbnail_url = (
            create_thumbnail_url(
                thumbnail_prompt
            )
        )

        try:

            await status.delete()

        except Exception:

            pass

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
                "Thumbnail image failed: %s",
                image_error
            )

            await send_long_message(
                update,
                "⚠️ Thumbnail ပုံ တိုက်ရိုက်မပေါ်နိုင်ပါ။\n\n"
                "🖼️ Thumbnail Prompt:\n\n"
                + thumbnail_prompt
            )

        # =================================================
        # SUCCESS MESSAGE
        # =================================================

        if is_admin(update):

            final_quota = (
                "👑 Admin — Unlimited"
            )

        else:

            final_used = get_user_usage(
                update.effective_user.id
            )["count"]

            final_quota = (
                f"📊 Today: "
                f"{final_used}/{DAILY_FREE_LIMIT}"
            )

        await update.message.reply_text(
            "✅ Processing ပြီးပါပြီ။\n\n"
            f"{final_quota}"
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

        # -------------------------------------------------
        # REFUND QUOTA IF IT WAS ALREADY CONSUMED
        # -------------------------------------------------

        if quota_consumed:

            refund_daily_limit(
                update
            )

        error_code = (
            get_error_code(
                error
            )
        )

        if error_code == "503":

            error_message = (
                "⚠️ Gemini Server ခဏအလုပ်များနေပါတယ်။\n\n"
                "🔄 Bot က Main Model နဲ့ Fallback Model "
                "နှစ်ခုလုံးကို Retry လုပ်ပြီးပါပြီ။\n\n"
                "ခဏအကြာ MP3 ကို ပြန်ပို့ကြည့်ပါ။"
            )

        elif error_code == "429":

            error_message = (
                "⚠️ Gemini API quota/rate limit "
                "ပြည့်နေပါတယ်။\n\n"
                "Google API quota ပြန်ရတဲ့အထိ "
                "စောင့်ရပါမယ်။"
            )

        elif error_code == "403":

            error_message = (
                "❌ Gemini API permission error ဖြစ်ပါတယ်။\n\n"
                "GEMINI_API_KEY နဲ့ API access ကို စစ်ပါ။"
            )

        elif error_code == "404":

            error_message = (
                "❌ Gemini model/file မတွေ့ပါ။\n\n"
                "GEMINI_MODEL ကို စစ်ပါ။"
            )

        else:

            error_message = (
                "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                + str(error)
            )

        try:

            await status.edit_text(
                error_message
            )

        except Exception:

            try:

                await update.message.reply_text(
                    error_message
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

                    os.remove(
                        path
                    )

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
    # QUOTA
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "quota",
            quota
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

    # -----------------------------------------------------
    # FLASK
    # -----------------------------------------------------

    start_web_server()

    # -----------------------------------------------------
    # TELEGRAM
    # -----------------------------------------------------

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
        "Main Gemini Model: %s",
        GEMINI_MODEL
    )

    logger.info(
        "Fallback Gemini Model: %s",
        GEMINI_FALLBACK_MODEL
    )

    logger.info(
        "TTS Server: %s",
        TTS_URL
    )

    logger.info(
        "Admin User ID: %s",
        ADMIN_USER_ID
    )

    logger.info(
        "Daily Free Limit: %s",
        DAILY_FREE_LIMIT
    )

    logger.info(
        "Text Chat: ENABLED"
    )

    logger.info(
        "Audio Recap: ENABLED"
    )

    logger.info(
        "Thumbnail: Pollinations"
    )

    logger.info(
        "========================================"
    )

    # -----------------------------------------------------
    # IMPORTANT
    # -----------------------------------------------------
    #
    # stop_signals=None
    # prevents:
    #
    # RuntimeError:
    # set_wakeup_fd only works in main thread
    #
    # IMPORTANT:
    # Render မှာ ဒီ Bot service တစ်ခုတည်းကိုသာ run ပါ။
    # Bot instance ၂ ခု run မထားပါနဲ့။
    #
    # -----------------------------------------------------

    application.run_polling(
        drop_pending_updates=True,
        stop_signals=None
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
