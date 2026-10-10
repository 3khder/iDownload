import os
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
    raise ValueError("لم يتم العثور على BOT_TOKEN، تأكد من إضافته في إعدادات السيرفر.")

bot = telebot.TeleBot(TOKEN)

# تخزين الرابط مؤقتاً لكل محادثة
user_links = {}

def get_platform_name(url):
    if "tiktok.com" in url:
        return "TikTok"
    elif "instagram.com" in url:
        return "Instagram"
    elif "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    return "الفيديو"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "مرحباً بك! 👋\n"
        "أنا بوت تحميل المقاطع والصوتيات من المنصات التالية:\n"
        "• YouTube (فيديوهات وشورتس)\n"
        "• TikTok (تيك توك)\n"
        "• Instagram (ريلز وبوستات)\n\n"
        "أرسل لي أي رابط وسأعرض لك خيارات الدقة المتاحة أو استخراج الصوت فقط."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(func=lambda msg: True)
def handle_incoming_link(message):
    url = message.text.strip()
    
    # التحقق من أن الرابط يتبع للمنصات المدعومة
    valid_domains = ["tiktok.com", "instagram.com", "youtube.com", "youtu.be"]
    if not any(domain in url for domain in valid_domains):
        bot.reply_to(message, "يرجى إرسال رابط صالح من YouTube أو TikTok أو Instagram فقط.")
        return

    # حفظ الرابط لمحادثة المستخدم
    user_links[message.chat.id] = url
    platform = get_platform_name(url)

    # إنشاء لوحة أزرار تفاعلية
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_best = types.InlineKeyboardButton("🎬 أعلى دقة", callback_data="q_best")
    btn_720 = types.InlineKeyboardButton("📺 دقة 720p", callback_data="q_720")
    btn_360 = types.InlineKeyboardButton("📱 دقة 360p", callback_data="q_360")
    btn_audio = types.InlineKeyboardButton("🎵 مقطع صوت فقط", callback_data="q_audio")
    
    markup.add(btn_best, btn_720)
    markup.add(btn_360, btn_audio)

    bot.reply_to(
        message,
        f"تم التعرف على رابط من {platform} 🎯\nاختر الدقة المطلوبة أو قم بتحميل الصوت فقط:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("q_"))
def process_quality_choice(call):
    chat_id = call.message.chat.id
    url = user_links.get(chat_id)

    if not url:
        bot.answer_callback_query(call.id, "انتهت صلاحية الطلب، يرجى إعادة إرسال الرابط مجدداً.")
        return

    bot.answer_callback_query(call.id)
    choice = call.data

    status_msg = bot.edit_message_text(
        "جاري جلب الملف وتجهيزه، يرجى الانتظار قليلاً... ⏳",
        chat_id=chat_id,
        message_id=call.message.message_id
    )

    is_audio = (choice == "q_audio")

    if choice == "q_best":
        format_str = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
        outtmpl = f"video_{chat_id}_best.%(ext)s"
    elif choice == "q_720":
        format_str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best"
        outtmpl = f"video_{chat_id}_720.%(ext)s"
    elif choice == "q_360":
        format_str = "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]/best"
        outtmpl = f"video_{chat_id}_360.%(ext)s"
    else:
        format_str = "bestaudio[ext=m4a]/bestaudio/best"
        outtmpl = f"audio_{chat_id}.%(ext)s"

    ydl_opts = {
        'format': format_str,
        'outtmpl': outtmpl,
        'max_filesize': 50 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
    }

    downloaded_file = None

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info)

        if downloaded_file and os.path.exists(downloaded_file):
            with open(downloaded_file, 'rb') as media_file:
                if is_audio:
                    bot.send_audio(
                        chat_id,
                        media_file,
                        caption="تم استخراج مقطع الصوت بنجاح 🎵"
                    )
                else:
                    bot.send_video(
                        chat_id,
                        media_file,
                        caption="تم تحميل الفيديو بنجاح 🎬"
                    )
            os.remove(downloaded_file)
            bot.delete_message(chat_id, status_msg.message_id)
        else:
            bot.edit_message_text(
                "تعذر العثور على الملف بعد التنزيل.",
                chat_id=chat_id,
                message_id=status_msg.message_id
            )

    except Exception:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass
        
        bot.edit_message_text(
            "تعذر تحميل المحتوى.\nقد يكون حجم الملف أكبر من 50MB أو أن المحتوى خاص/محمي.",
            chat_id=chat_id,
            message_id=status_msg.message_id
        )

print("Bot is starting...")
bot.infinity_polling()
