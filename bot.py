import os
import re
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
user_sessions = {}

def download_file_stream(source_url, output_path):
    """تنزيل محتوى الرابط مباشرة وحفظه كملف mp4"""
    req = urllib.request.Request(
        source_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    with urllib.request.urlopen(req, timeout=30) as resp, open(output_path, 'wb') as f:
        while True:
            chunk = resp.read(1024 * 64)
            if not chunk:
                break
            f.write(chunk)

def get_tiktok_info(url):
    """فحص روابط تيك توك وجلب الجودات المتوفرة"""
    api_url = f"https://www.tikwm.com/api/?url={url}"
    req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        if data.get("code") == 0:
            return data["data"]
    return None

def get_instagram_stream(url):
    """استخراج رابط الفيديو المتاح من إنستغرام عبر بوابات فك الحظر"""
    clean_url = url.split("?")[0]
    gateways = ["ddinstagram.com", "instafix.app"]
    
    for gw in gateways:
        try:
            parts = clean_url.split("instagram.com")
            proxy_url = parts[0] + gw + parts[1]
            req = urllib.request.Request(
                proxy_url,
                headers={'User-Agent': 'TelegramBot (like TwitterBot)'}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
                match = re.search(r'<meta\s+property=["\']og:video["\']\s+content=["\']([^"\']+)["\']', html)
                if not match:
                    match = re.search(r'<meta\s+name=["\']twitter:player:stream["\']\s+content=["\']([^"\']+)["\']', html)
                if match:
                    return match.group(1).replace("&amp;", "&")
        except Exception:
            continue
    return None

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "مرحباً بك! 👋\n"
        "أرسل لي أي رابط من YouTube أو TikTok أو Instagram.\n"
        "سأقوم بفحص الفيديو وعرض خيارات الدقة المتوفرة فعلياً في المصدر لتحميلها، أو استخراج الصوت بصيغة .mp4."
    )

@bot.message_handler(func=lambda msg: True)
def analyze_and_prompt(message):
    url = message.text.strip()
    valid_domains = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be"]
    
    if not any(domain in url for domain in valid_domains):
        bot.reply_to(message, "يرجى إرسال رابط صالح من YouTube أو TikTok أو Instagram.")
        return

    checking_msg = bot.reply_to(message, "جاري فحص الجودات المتاحة للمقطع... 🔍")
    chat_id = message.chat.id
    markup = types.InlineKeyboardMarkup(row_width=2)

    # 1. فحص مقاطع تيك توك
    if "tiktok.com" in url:
        try:
            data = get_tiktok_info(url)
            if data:
                user_sessions[chat_id] = {'type': 'tiktok', 'data': data}
                buttons = []
                if data.get("hdplay"):
                    buttons.append(types.InlineKeyboardButton("🎬 دقة عالية (HD)", callback_data="tt_hd"))
                    buttons.append(types.InlineKeyboardButton("📱 دقة عادية (SD)", callback_data="tt_sd"))
                else:
                    buttons.append(types.InlineKeyboardButton("🎬 تحميل الفيديو", callback_data="tt_sd"))
                buttons.append(types.InlineKeyboardButton("🎵 صوت فقط (.mp4)", callback_data="tt_audio"))
                markup.add(*buttons)
                bot.edit_message_text("الجودات المتوفرة لمقطع TikTok:", chat_id=chat_id, message_id=checking_msg.message_id, reply_markup=markup)
                return
        except Exception as e:
            print(f"TikTok inspect error: {e}")

    # 2. فحص مقاطع إنستغرام
    elif "instagram.com" in url:
        try:
            video_url = get_instagram_stream(url)
            if video_url:
                user_sessions[chat_id] = {'type': 'instagram', 'url': video_url}
                btn_vid = types.InlineKeyboardButton("🎬 تحميل الفيديو (الجودة الأصلية)", callback_data="ig_video")
                btn_aud = types.InlineKeyboardButton("🎵 صوت فقط (.mp4)", callback_data="ig_audio")
                markup.add(btn_vid, btn_aud)
                bot.edit_message_text("الخيارات المتاحة لمقطع Instagram:", chat_id=chat_id, message_id=checking_msg.message_id, reply_markup=markup)
                return
        except Exception as e:
            print(f"Instagram inspect error: {e}")

    # 3. فحص مقاطع يوتيوب
    else:
        try:
            ydl_opts_info = {'quiet': True, 'no_warnings': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts_info) as ydl:
                info = ydl.extract_info(url, download=False)

            available_heights = set()
            for f in info.get('formats', []):
                h = f.get('height')
                if h and f.get('vcodec') != 'none' and h <= 1080:
                    available_heights.add(h)

            standard_tiers = [1080, 720, 480, 360, 240]
            matched_tiers = [tier for tier in standard_tiers if any(abs(tier - h) <= 25 for h in available_heights)]

            if not matched_tiers:
                matched_tiers = sorted(list(available_heights), reverse=True)[:3]

            user_sessions[chat_id] = {'type': 'youtube', 'url': url}
            buttons = [types.InlineKeyboardButton(f"📺 دقة {tier}p", callback_data=f"yt_{tier}") for tier in matched_tiers]
            buttons.append(types.InlineKeyboardButton("🎵 صوت فقط (.mp4)", callback_data="yt_audio"))
            markup.add(*buttons)
            bot.edit_message_text(f"الجودات المتوفرة لفيديو YouTube:\n({info.get('title', 'فيديو')[:50]})", chat_id=chat_id, message_id=checking_msg.message_id, reply_markup=markup)
            return
        except Exception as e:
            print(f"YouTube inspect error: {e}")

    bot.edit_message_text("تعذر قراءة الجودات المتوفرة للمقطع؛ قد يكون خاصاً أو مقيداً.", chat_id=chat_id, message_id=checking_msg.message_id)

@bot.callback_query_handler(func=lambda call: True)
def process_download(call):
    chat_id = call.message.chat.id
    session = user_sessions.get(chat_id)

    if not session:
        bot.answer_callback_query(call.id, "انتهت صلاحية الطلب، أرسل الرابط مرة أخرى.")
        return

    bot.answer_callback_query(call.id)
    choice = call.data
    status = bot.edit_message_text("جاري تنزيل المحتوى ومعالجته... ⏳", chat_id=chat_id, message_id=call.message.message_id)
    output_file = f"media_{chat_id}.mp4"

    try:
        # معالجة TikTok
        if session['type'] == 'tiktok':
            data = session['data']
            if choice == "tt_hd":
                src = data.get("hdplay") or data.get("play")
            elif choice == "tt_sd":
                src = data.get("play")
            else:
                src = data.get("music") or data.get("play")

            download_file_stream(src, output_file)
            with open(output_file, 'rb') as f:
                if choice == "tt_audio":
                    bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                else:
                    bot.send_video(chat_id, f, caption="تم التحميل بنجاح 🎬")

        # معالجة Instagram
        elif session['type'] == 'instagram':
            download_file_stream(session['url'], output_file)
            with open(output_file, 'rb') as f:
                if choice == "ig_audio":
                    bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                else:
                    bot.send_video(chat_id, f, caption="تم التحميل بنجاح 🎬")

        # معالجة YouTube
        elif session['type'] == 'youtube':
            url = session['url']
            temp_file = f"temp_{chat_id}.%(ext)s"
            
            if choice == "yt_audio":
                format_rule = "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio/best"
            else:
                target_h = choice.split("_")[1]
                format_rule = f"bestvideo[height<={target_h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_h}][ext=mp4]/best[height<={target_h}]/best"

            ydl_opts = {
                'format': format_rule,
                'outtmpl': temp_file,
                'max_filesize': 50 * 1024 * 1024,
                'quiet': True,
                'no_warnings': True
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_name = ydl.prepare_filename(info)

            if os.path.exists(downloaded_name):
                if os.path.exists(output_file):
                    os.remove(output_file)
                os.replace(downloaded_name, output_file)
                with open(output_file, 'rb') as f:
                    if choice == "yt_audio":
                        bot.send_audio(chat_id, f, caption="تم استخراج الصوت بصيغة .mp4 بنجاح 🎵")
                    else:
                        bot.send_video(chat_id, f, caption="تم التحميل بنجاح 🎬")

        if os.path.exists(output_file):
            os.remove(output_file)
        bot.delete_message(chat_id, status.message_id)

    except Exception as e:
        if os.path.exists(output_file):
            os.remove(output_file)
        print(f"Error during send: {e}")
        bot.edit_message_text("تعذر استكمال التحميل؛ قد يتجاوز حجم الملف حد 50MB المسموح به في تيليجرام.", chat_id=chat_id, message_id=status.message_id)

print("Bot is starting...")
bot.infinity_polling()
