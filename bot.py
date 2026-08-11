import os
import asyncio
import logging
import urllib.parse
import requests
import edge_tts

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from google import genai


# =========================
# LOGGING
# =========================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================
# ENVIRONMENT VARIABLES
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


# =========================
# GEMINI
# =========================

client = genai.Client(api_key=GEMINI_API_KEY)


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "မင်္ဂလာပါ 👋\n\n"
        "🎬 ကျွန်တော်က Movie Recap & Translation Bot ပါ။\n\n"
        "📥 MP3 / Voice ဖိုင်ပို့ပေးပါ။\n\n"
        "ကျွန်တော်က —\n"
        "1️⃣ အသံကို စာအဖြစ်ပြောင်းမယ်\n"
        "2️⃣ မြန်မာလို Recap ပြန်ရေးမယ်\n"
        "3️⃣ SRT Subtitle ဖိုင်လုပ်မယ်\n"
        "4️⃣ မြန်မာ MP3 အသံဖိုင်လုပ်မယ်\n"
        "5️⃣ Thumbnail Prompt ထုတ်ပေးမယ်\n\n"
        "📌 MP3 ဖိုင်ကို ပို့လိုက်ပါ။"
    )

    await update.message.reply_text(text)


# =========================
# AUDIO HANDLER
# =========================

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):

    status = await update.message.reply_text(
        "📥 MP3 ဖိုင်ကို လက်ခံရရှိပါပြီ...\n"
        "⏳ Processing လုပ်နေပါတယ်။"
    )

    file_id = None

    try:

        # -------------------------
        # GET FILE ID
        # -------------------------

        if update.message.audio:
            file_id = update.message.audio.file_id

        elif update.message.voice:
            file_id = update.message.voice.file_id

        else:
            await status.edit_text("❌ Audio ဖိုင်မတွေ့ပါ။")
            return


        # -------------------------
        # DOWNLOAD FILE
        # -------------------------

        telegram_file = await context.bot.get_file(file_id)

        input_path = f"input_{file_id}.mp3"
        srt_path = f"subtitle_{file_id}.srt"
        mp3_path = f"burmese_{file_id}.mp3"

        await telegram_file.download_to_drive(input_path)

        await status.edit_text(
            "🎙️ Gemini AI က အသံဖိုင်ကို နားထောင်ပြီး\n"
            "စာသားထုတ်နေပါတယ်..."
        )


        # -------------------------
        # UPLOAD TO GEMINI
        # -------------------------

        audio_file = await asyncio.to_thread(
            client.files.upload,
            file=input_path
        )


        # -------------------------
        # GEMINI PROMPT
        # -------------------------

        prompt = """
You are a professional movie recap translator.

Listen to the uploaded audio carefully.

Your job:

1. Understand the complete audio.
2. Create accurate subtitles in STANDARD SRT format.
3. Translate the dialogue/narration naturally into Myanmar language.
4. Create an engaging Myanmar movie recap.
5. Do NOT invent events that are not in the audio.

IMPORTANT:

Return EXACTLY this format:

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

The SRT timestamps must be realistic and sequential.

The Myanmar translation should sound natural and suitable for narration.
"""


        # -------------------------
        # GEMINI PROCESS
        # -------------------------

        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=[
                audio_file,
                prompt
            ]
        )

        result = response.text or ""


        # -------------------------
        # EXTRACT SRT
        # -------------------------

        srt_content = ""

        if "===SRT_START===" in result and "===SRT_END===" in result:

            srt_content = (
                result
                .split("===SRT_START===")[1]
                .split("===SRT_END===")[0]
                .strip()
            )


        # -------------------------
        # EXTRACT RECAP
        # -------------------------

        recap_text = ""

        if "===RECAP_START===" in result and "===RECAP_END===" in result:

            recap_text = (
                result
                .split("===RECAP_START===")[1]
                .split("===RECAP_END===")[0]
                .strip()
            )

        else:
            recap_text = result.strip()


        # -------------------------
        # SAVE SRT
        # -------------------------

        if srt_content:

            with open(
                srt_path,
                "w",
                encoding="utf-8"
            ) as f:

                f.write(srt_content)


        # -------------------------
        # TTS
        # -------------------------

        await status.edit_text(
            "🔊 မြန်မာအသံဖိုင် ပြုလုပ်နေပါတယ်..."
        )

        # Edge TTS Myanmar voice
        voice = "my-MM-ThihaNeural"

        communicate = edge_tts.Communicate(
            recap_text,
            voice
        )

        await communicate.save(mp3_path)


        # -------------------------
        # THUMBNAIL PROMPT
        # -------------------------

        await status.edit_text(
            "🖼️ Thumbnail Prompt ပြုလုပ်နေပါတယ်..."
        )

        thumbnail_prompt_request = f"""
Create one cinematic English image prompt
for a YouTube movie recap thumbnail.

Based ONLY on this Myanmar recap:

{recap_text}

Requirements:

- cinematic movie poster
- dramatic lighting
- emotional characters
- realistic faces
- high detail
- 16:9 composition
- no text
- no subtitles
- no watermark

Return ONLY the English image prompt.
"""


        prompt_response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=thumbnail_prompt_request
        )

        thumbnail_prompt = (
            prompt_response.text.strip()
            if prompt_response.text
            else "cinematic movie recap thumbnail"
        )


        # -------------------------
        # SEND RECAP
        # -------------------------

        await status.delete()

        await update.message.reply_text(
            "🎬 **မြန်မာ Movie Recap**\n\n"
            + recap_text,
            parse_mode="Markdown"
        )


        # -------------------------
        # SEND SRT
        # -------------------------

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


        # -------------------------
        # SEND MP3
        # -------------------------

        with open(
            mp3_path,
            "rb"
        ) as audio_file_out:

            await update.message.reply_audio(
                audio=audio_file_out,
                filename="burmese_recap.mp3",
                caption="🎧 မြန်မာဘာသာပြန် MP3"
            )


        # -------------------------
        # THUMBNAIL
        # -------------------------

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
                f"Thumbnail failed: {image_error}"
            )

            await update.message.reply_text(
                "⚠️ Thumbnail မထုတ်နိုင်ပါ။\n\n"
                "Prompt:\n"
                + thumbnail_prompt
            )


        # -------------------------
        # DELETE GEMINI FILE
        # -------------------------

        try:

            await asyncio.to_thread(
                client.files.delete,
                name=audio_file.name
            )

        except Exception as delete_error:

            logger.warning(
                f"Gemini file delete error: {delete_error}"
            )


    except Exception as e:

        logger.exception("Processing error")

        try:

            await status.edit_text(
                "❌ Error ဖြစ်သွားပါတယ်။\n\n"
                f"{str(e)}"
            )

        except Exception:
            pass


    finally:

        # -------------------------
        # CLEAN TEMP FILES
        # -------------------------

        for path in [
            f"input_{file_id}.mp3",
            f"subtitle_{file_id}.srt",
            f"burmese_{file_id}.mp3"
        ]:

            try:

                if os.path.exists(path):
                    os.remove(path)

            except Exception:
                pass


# =========================
# MAIN
# =========================

def main():

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN မရှိပါ။")
        return

    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY မရှိပါ။")
        return


    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )


    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    app.add_handler(
        MessageHandler(
            filters.AUDIO | filters.VOICE,
            handle_audio
        )
    )


    print("🤖 Telegram Recap Bot Started...")

    app.run_polling()


if __name__ == "__main__":
    main()
