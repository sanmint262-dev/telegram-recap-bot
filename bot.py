import os
import asyncio
import logging
import urllib.parse
import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import edge_tts

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# API Keys (Render Environment မှ ယူသည်)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Gemini Setup
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "မင်္ဂလာပါ! ကျွန်တော်က Gemini AI သုံးထားတဲ့ Recap & Translation Bot ဖြစ်ပါတယ်။\n\n"
        "✨ **လုပ်ဆောင်နိုင်သော Feature များ:**\n"
        "၁။ MP3 ဖိုင် ပို့ပေးပါက -> မြန်မာလို Recap၊ SRT စာတမ်းထိုး၊ ဘာသာပြန် MP3 အသံဖိုင် နှင့် Thumbnail ပုံ ထုတ်ပေးပါမည်။"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("📥 MP3 ဖိုင်ကို လက်ခံရရှိပါပြီ။ Gemini မှ Process လုပ်နေပါတယ်...")
    
    file_id = update.message.audio.file_id or update.message.voice.file_id
    file_info = await context.bot.get_file(file_id)
    
    input_path = f"temp_{file_id}.mp3"
    srt_path = f"subtitle_{file_id}.srt"
    translated_mp3_path = f"translated_{file_id}.mp3"

    try:
        # 1. Download MP3
        await file_info.download_to_drive(input_path)
        await msg.edit_text("🎙️ Gemini AI ဖြင့် အသံဖိုင်ကို စာပြောင်းနေပါသည်...")

        # 2. Upload Audio File to Gemini
        audio_file = genai.upload_file(path=input_path)

        # 3. Request Recap & SRT via Gemini
        prompt = (
            "Listen to this audio file carefully.\n"
            "1. Generate standard SRT format subtitles for this audio.\n"
            "2. Provide a brief, engaging summary/recap of the content in Myanmar language.\n\n"
            "Format your output strictly like this:\n"
            "===SRT_START===\n"
            "[Put SRT content here]\n"
            "===SRT_END===\n"
            "===RECAP_START===\n"
            "[Put Myanmar recap text here]\n"
            "===RECAP_END==="
        )

        response = model.generate_content([audio_file, prompt])
        result_text = response.text

        srt_content = ""
        recap_text = ""

        if "===SRT_START===" in result_text and "===SRT_END===" in result_text:
            srt_content = result_text.split("===SRT_START===")[1].split("===SRT_END===")[0].strip()

        if "===RECAP_START===" in result_text and "===RECAP_END===" in result_text:
            recap_text = result_text.split("===RECAP_START===")[1].split("===RECAP_END===")[0].strip()
        else:
            recap_text = result_text

        # Save SRT file
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        # 4. Generate Audio using Edge-TTS (Free)
        await msg.edit_text("🔊 ဘာသာပြန်ထားသော စာသားကို MP3 အသံဖိုင် ပြန်ပြောင်းနေပါသည်...")
        voice = "my-MM-ThihaNeural"
        communicate = edge_tts.Communicate(recap_text, voice)
        await communicate.save(translated_mp3_path)

        # 5. Generate Free Thumbnail Image (Pollinations.ai)
        await msg.edit_text("🖼️ YouTube Thumbnail ပုံ ဆွဲပေးနေပါသည်...")
        img_prompt_req = f"Create a vivid, 1-sentence English prompt for a YouTube video thumbnail based on this recap: {recap_text}"
        prompt_resp = model.generate_content(img_prompt_req)
        clean_prompt = prompt_resp.text.strip()

        encoded_prompt = urllib.parse.quote(clean_prompt)
        thumbnail_url = f"https://pollinations.ai/p/{encoded_prompt}?width=1280&height=720&seed=42&model=flux"

        # Delete status message
        await msg.delete()

        # Send Results
        await update.message.reply_text(f"📌 **Recap (မြန်မာလို):**\n\n{recap_text}")

        if srt_content:
            with open(srt_path, "rb") as srt_file:
                await update.message.reply_document(document=srt_file, filename="subtitle.srt", caption="📄 SRT Subtitle File")

        with open(translated_mp3_path, "rb") as audio_out:
            await update.message.reply_audio(audio=audio_out, filename="burmese_recap.mp3", caption="🎧 ဘာသာပြန်ထားသော MP3 အသံဖိုင်")

        # Send Free Thumbnail
        await update.message.reply_photo(photo=thumbnail_url, caption=f"🎨 **Generated Thumbnail**\n\nPrompt: {clean_prompt}")

        # Clean up uploaded Gemini file
        genai.delete_file(audio_file.name)

    except Exception as e:
        await msg.edit_text(f"❌ Error တက်သွားပါသည်: {str(e)}")

    finally:
        for p in [input_path, srt_path, translated_mp3_path]:
            if os.path.exists(p):
                os.remove(p)

def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        print("Error: API Tokens မထည့်ရသေးပါ။ Render Environment မှာ ထည့်ပေးပါ။")
        return

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, handle_audio))

    print("Bot starting with Gemini API...")
    app.run_polling()

if __name__ == '__main__':
    main()
