import os
import re
import ssl
import json
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

bot = telebot.TeleBot(TOKEN)
user_links = {}

# إعداد اتصال آمن لتخطي أي مشاكل في شهادات SSL للروابط الوسيطة
ssl_unverified = ssl.create_default_context()
ssl_unverified.check_hostname = False
ssl_unverified.verify_mode = ssl.CERT_NONE

def download_file_stream(source_url, output_path):
    """تنزيل محتوى الرابط مباشرة وحفظه كملف mp4"""
    req = urllib.request.Request(
        source_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=30, context=ssl_unverified) as resp, open(output_path, 'wb') as f:
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            f.write(chunk)

def get_tiktok_info(url):
    """جلب بيانات تيك توك وتخطي الحظر"""
    api_url = f"https://www.tikwm.com/api/?url={url}"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        if data.get("code") == 0:
            return data["data"]
    return None

def get_instagram_stream(url):
    """استخراج رابط فيديو إنستغرام عبر بوابات فك التقييد"""
    match = re.search(r'instagram\.com/(?:[a-zA-Z0-9_\.]+/)?(reel|p|tv)/([A-Za-z0-9_-]+)', url)
    if not match:
        return None
    
    media_type = match.group(1)
    shortcode = match.group(2)
    path = f"/{media_type}/{shortcode}/"
    
    gateways = [
        f"https://ddinstagram.com{path}",
        f"https://kkinstagram.com{path}",
        f"https://instafix.app{path}"
    ]

    for target_url in gateways:
        try:
            req = urllib.request.Request(
                target_url,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)'}
            )
            with urllib.request.urlopen(req, timeout=12, context=ssl_unverified) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                
                video_match = re.search(r'<meta\s+property=["\']og:video(?::secure_url)?["\']\s+content=["\']([^"\']+)["\']', html)
                if not video_match:
                    video_match = re.search(r'<meta\s+(?:name|property)=["\']twitter:player:stream["\']\s+content=["\']([^"\']+)["\']', html)
                if not video_match:
                    video_match = re.search(r'<video[^>]+src=["\']([^"\']+)["\']', html)
                
                if video_match:
                    direct_url = video_match.group(1).replace("&amp;", "&")
                    if direct_url.startswith("http"):
                        return direct_url
        except Exception:
            continue

    try:
        ydl_opts_ig = {'quiet': True, 'no_warnings': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts_ig) as ydl:
            info = ydl.extract_info(url, download=False)
            if 'url' in info:
                return info['url']
    except Exception:
        pass

    return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "مرحباً بك! 👋\n"
        "أرسل لي أي رابط من YouTube أو TikTok أو Instagram وسأقوم بعرض خيارات التحميل المناسبة فوراً."
    )

@bot.message_handler(func=lambda msg: True)
def handle_incoming_link(message):
    url = message.text.strip()
    valid_domains = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be"]
    
    if not any(domain in url for domain in valid_domains):
        bot.reply_to(message, "يرجى إرسال رابط صالح من YouTube أو TikTok أو Instagram.")
        return

    chat_id = message.chat.id
    user_links[chat_id] = url

    # إنشاء الأزرار عمودياً فوق بعضها (row_width=1)
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn_high = types.InlineKeyboardButton("🎬 دقة عالية (أعلى جودة متوفرة)", callback_data="q_high")
    btn_low = types.InlineKeyboardButton("📱 دقة منخفضة (360p)", callback_data="q_low")
    btn_audio = types.InlineKeyboardButton("🎵 صوت فقط (.mp4)", callback_data="q_audio")
    
    markup.add(btn_high, btn_low, btn_audio)

    bot.reply_to(message, "اختر ما ترغب بتحميله:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["q_high", "q_low", "q_audio"])
def handle_download_choice(call):
    chat_id = call.message.chat.id
    url = user_links.get(chat_id)

    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية الطلب، يرجى إعادة إرسال الرابط.")
        return

    bot.answer_callback_query(call.id)
    choice = call.data
    status = bot.edit_message_text("جاري جلب المحتوى وتجهيزه، انتظر لحظات... ⏳", chat_id=chat_id, message_id=call.message.message_id)
    output_file = f"media_{chat_id}.mp4"

    try:
        # 1. منصة تيك توك
        if "tiktok.com" in url:
            data = get_tiktok_info(url)
            if data:
                if choice == "q_high":
                    src = data.get("hdplay") or data.get("play")
                    download_file_stream(src, output_file)
                    with open(output_file, 'rb') as f:
                        bot.send_video(chat_id, f, caption="تم تحميل مقطع TikTok بأعلى دقة 🎬")
                elif choice == "q_low":
                    src = data.get("play")
                    download_file_stream(src, output_file)
                    with open(output_file, 'rb') as f:
                        bot.send_video(chat_id, f, caption="تم تحميل مقطع TikTok بدقة عادية 📱")
                else:
                    src = data.get("music") or data.get("play")
                    download_file_stream(src, output_file)
                    with open(output_file, 'rb') as f:
                        bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                
                if os.path.exists(output_file):
                    os.remove(output_file)
                bot.delete_message(chat_id, status.message_id)
                return

        # 2. منصة إنستغرام
        if "instagram.com" in url:
            video_url = get_instagram_stream(url)
            if video_url:
                download_file_stream(video_url, output_file)
                with open(output_file, 'rb') as f:
                    if choice == "q_audio":
                        bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                    elif choice == "q_low":
                        bot.send_video(chat_id, f, caption="تم تحميل مقطع Instagram بدقة منخفضة 📱")
                    else:
                        bot.send_video(chat_id, f, caption="تم تحميل مقطع Instagram بأعلى جودة 🎬")
                
                if os.path.exists(output_file):
                    os.remove(output_file)
                bot.delete_message(chat_id, status.message_id)
                return

        # 3. منصة يوتيوب
        temp_file = f"temp_{chat_id}.%(ext)s"

        if choice == "q_audio":
            format_rule = "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio/best"
        elif choice == "q_low":
            format_rule = "best[height<=360][ext=mp4]/best[height<=360]/best"
        else:
            format_rule = "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best"

        ydl_opts = {
            'format': format_rule,
            'outtmpl': temp_file,
            'max_filesize': 50 * 1024 * 1024,
            'quiet': True,
            'no_warnings': True
        }

        temp_downloaded = None
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            temp_downloaded = ydl.prepare_filename(info)

        if temp_downloaded and os.path.exists(temp_downloaded):
            if os.path.exists(output_file):
                os.remove(output_file)
            os.replace(temp_downloaded, output_file)

            with open(output_file, 'rb') as f:
                if choice == "q_audio":
                    bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                elif choice == "q_low":
                    bot.send_video(chat_id, f, caption="تم تحميل الفيديو بدقة 360p 📱")
                else:
                    bot.send_video(chat_id, f, caption="تم تحميل الفيديو بأعلى جودة متوفرة 🎬")

            if os.path.exists(output_file):
                os.remove(output_file)
            bot.delete_message(chat_id, status.message_id)
        else:
            bot.edit_message_text("تعذر العثور على الملف بعد المعالجة.", chat_id=chat_id, message_id=status.message_id)

    except Exception as e:
        if os.path.exists(output_file):
            os.remove(output_file)
        print(f"Download error: {e}")
        bot.edit_message_text("تعذر تحميل المحتوى؛ قد يتجاوز حجم المقطع حد 50MB المسموح به أو يكون مقيداً.", chat_id=chat_id, message_id=status.message_id)

print("Bot is starting...")
bot.infinity_polling()
