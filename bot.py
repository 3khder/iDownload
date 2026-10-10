import os
import json
import tempfile
import urllib.parse
import urllib.request
import telebot
from telebot import types
import yt_dlp

# قراءة المتغيرات من ملف .env الخاص بالاستضافة تلقائياً
if os.path.exists(".env"):
    with open(".env", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("لم يتم العثور على BOT_TOKEN، تأكد من ضبطه في إعدادات السيرفر.")

# تشغيل البوت بعدد خيوط معالجة أعلى للتعامل مع الطلبات المتزامنة
bot = telebot.TeleBot(TOKEN, num_threads=8)

# ربط الطلبات بمعرف رسالة الأزرار الخاصة بها منعاً لتداخل الجلسات
active_requests = {}

ALLOWED_DOMAINS = ("tiktok.com", "instagram.com", "youtube.com", "youtu.be")

def is_safe_supported_url(url_text):
    """التحقق الأمني الدقيق من النطاق وتفادي ثغرات التوجيه"""
    try:
        parsed = urllib.parse.urlparse(url_text)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        return any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS)
    except Exception:
        return False

def fetch_tiktok_payload(url):
    """جلب بيانات تيك توك مع ترميز الرابط بالكامل"""
    encoded_url = urllib.parse.quote(url, safe='')
    api_endpoint = f"https://www.tikwm.com/api/?url={encoded_url}"
    req = urllib.request.Request(
        api_endpoint,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        if data.get("code") == 0:
            return data.get("data")
    return None

def download_raw_stream(source_url, destination_path):
    """تنزيل البث المباشر وتخزينه في مسار آمن"""
    req = urllib.request.Request(
        source_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=30) as resp, open(destination_path, 'wb') as out_file:
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            out_file.write(chunk)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "مرحباً بك! 👋\n"
        "أرسل لي أي رابط من YouTube أو TikTok أو Instagram وسأقوم بتوفير خيارات التحميل المناسبة بشكل آمن ومستقل."
    )

@bot.message_handler(func=lambda msg: True)
def handle_link_submission(message):
    url = message.text.strip()
    
    if not is_safe_supported_url(url):
        bot.reply_to(message, "يرجى إرسال رابط صالح ومعتمد من YouTube أو TikTok أو Instagram فقط.")
        return

    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_high = types.InlineKeyboardButton("🎬 دقة عالية (أعلى جودة متوفرة)", callback_data="q_high")
    btn_low = types.InlineKeyboardButton("📱 دقة منخفضة (360p)", callback_data="q_low")
    btn_audio = types.InlineKeyboardButton("🎵 استخراج الصوت (.mp4)", callback_data="q_audio")
    markup.add(btn_high, btn_low, btn_audio)

    prompt = bot.reply_to(message, "اختر ما ترغب بتحميله:", reply_markup=markup)
    
    # حفظ الرابط بالارتباط مع معرّف رسالة الأزرار حصراً
    active_requests[prompt.message_id] = url

@bot.callback_query_handler(func=lambda call: call.data in ["q_high", "q_low", "q_audio"])
def execute_download_flow(call):
    chat_id = call.message.chat.id
    target_msg_id = call.message.message_id
    url = active_requests.get(target_msg_id)

    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية هذا الطلب، أرسل الرابط مرة أخرى.")
        return

    bot.answer_callback_query(call.id)
    choice = call.data
    status = bot.edit_message_text(
        "جاري فحص وتجهيز الملف بأمان، يرجى الانتظار... ⏳",
        chat_id=chat_id,
        message_id=target_msg_id
    )

    # عزل مسار التنزيل داخل مجلد مؤقت فريد يُمحى بالكامل عند الانتهاء
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = os.path.join(temp_dir, "media.mp4")

        try:
            # 1. تيك توك
            if "tiktok.com" in url:
                data = fetch_tiktok_payload(url)
                if data:
                    if choice == "q_audio":
                        src = data.get("music") or data.get("play")
                        download_raw_stream(src, output_file)
                        with open(output_file, 'rb') as f:
                            bot.send_audio(chat_id, f, caption="تم استخراج الصوت بنجاح 🎵")
                    elif choice == "q_low":
                        src = data.get("play")
                        download_raw_stream(src, output_file)
                        with open(output_file, 'rb') as f:
                            bot.send_video(chat_id, f, caption="تم تحميل مقطع TikTok بدقة عادية 📱")
                    else:
                        src = data.get("hdplay") or data.get("play")
                        download_raw_stream(src, output_file)
                        with open(output_file, 'rb') as f:
                            bot.send_video(chat_id, f, caption="تم تحميل مقطع TikTok بأعلى دقة 🎬")

                    bot.delete_message(chat_id, status.message_id)
                    active_requests.pop(target_msg_id, None)
                    return

            # 2. يوتيوب وإنستغرام عبر المحرك الأساسي yt-dlp
            ydl_base_opts = {
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
            }

            # فحص حجم المقطع ومعلوماته مسبقاً قبل الشروع بالتنزيل
            with yt_dlp.YoutubeDL(ydl_base_opts) as ydl_inspect:
                meta = ydl_inspect.extract_info(url, download=False)
                size_est = meta.get('filesize') or meta.get('filesize_approx') or 0
                if size_est > 50 * 1024 * 1024:
                    bot.edit_message_text(
                        "تعذر التحميل: حجم الملف يتجاوز الحد الأقصى المسموح به في تيليجرام (50MB).",
                        chat_id=chat_id,
                        message_id=status.message_id
                    )
                    active_requests.pop(target_msg_id, None)
                    return

            # إعداد مسار وقواعد الجودة
            ydl_download_opts = dict(ydl_base_opts)
            ydl_download_opts['outtmpl'] = os.path.join(temp_dir, 'source.%(ext)s')

            if choice == "q_audio":
                ydl_download_opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
            elif choice == "q_low":
                ydl_download_opts['format'] = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]/best'
            else:
                ydl_download_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best'

            with yt_dlp.YoutubeDL(ydl_download_opts) as ydl_exec:
                info = ydl_exec.extract_info(url, download=True)
                downloaded_file = ydl_exec.prepare_filename(info)

            # ضمان إرسال الامتداد بصيغة mp4 المقروءة
            if downloaded_file and os.path.exists(downloaded_file):
                os.replace(downloaded_file, output_file)

                with open(output_file, 'rb') as f:
                    if choice == "q_audio":
                        bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                    elif choice == "q_low":
                        bot.send_video(chat_id, f, caption="تم التحميل بدقة 360p 📱")
                    else:
                        bot.send_video(chat_id, f, caption="تم التحميل بأعلى جودة متوفرة 🎬")

                bot.delete_message(chat_id, status.message_id)
                active_requests.pop(target_msg_id, None)
            else:
                bot.edit_message_text("تعذر العثور على الملف بعد المعالجة.", chat_id=chat_id, message_id=status.message_id)

        except Exception as err:
            print(f"Operational error: {err}")
            bot.edit_message_text(
                "تعذر استكمال التحميل؛ قد يكون المحتوى مقيداً أو خاصاً أو تجاوز حجمه 50MB.",
                chat_id=chat_id,
                message_id=status.message_id
            )
            active_requests.pop(target_msg_id, None)

print("Bot is starting...")
bot.infinity_polling()
