import logging
import os
import re
import threading
import asyncio
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from supabase import create_client, Client
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

logging.basicConfig(level=logging.ERROR)

# --- 1. سيرفر وهمي للـ Keep-Alive ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- 2. إعدادات قاعدة البيانات الأساسية للمشروع ---
SUPABASE_URL = "https://besvojmipioaeavdwcvj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJlc3Zvam1pcGlvYWVhdmR3Y3ZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUzMzc4NzgsImV4cCI6MjEwMDkxMzg3OH0.yE4u8bCY8vMWPSLeZHKVbQEoC0VUqb41pEHHDBfqX1Q"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 3. إعدادات قاعدة بيانات نتائج الثانوية العامة (المشروع الثاني) ---
RESULTS_SUPABASE_URL = "https://zaycmrniwffsakzbvesb.supabase.co"
RESULTS_SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InpheWNtcm5pd2Zmc2FremJ2ZXNiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUyNjk0NTgsImV4cCI6MjEwMDg0NTQ1OH0.jW37BJ9cRZWk3OSo27GpFco-4urM0gY8t-azJ5uRzDs"
results_supabase: Client = create_client(RESULTS_SUPABASE_URL, RESULTS_SUPABASE_KEY)

# --- 4. إعدادات البوت والـ ID ---
BOT_TOKEN = "8943376248:AAHAdToTCLQAc-3uj9MQ7oAbhTwO5q-rHjs"
ADMIN_CHAT_ID = 1359132699
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/UCL1nCgb41VNqe32kY0tCZ1w/"

REG_NAME, REG_PHONE, SUPPORT_MSG, SUPPORT_REPLY_MSG, RESULT_SEARCH = range(5)
SYSTEM_BUTTONS = ["📝 تسجيل", "📂 الأرشيف", "🎬 الفيديوهات الجديدة", "📺 قناة اليوتيوب", "💬 الدعم", "🎓 نتيجة الثانوية العامة 2026"]

# --- دوال Supabase اللاتزامنية ---
async def ensure_user_registered(user):
    if not user:
        return
    try:
        user_data = {
            "telegram_id": user.id,
            "full_name": user.first_name or "مستخدم",
            "username": user.username or ""
        }
        await asyncio.to_thread(lambda: supabase.table("users").upsert(user_data, on_conflict="telegram_id").execute())
    except Exception as e:
        print(f"Error registering user: {e}")

async def log_chat_message(user_id: int, text: str, sender: str = "user"):
    try:
        if text and text not in SYSTEM_BUTTONS:
            await asyncio.to_thread(lambda: supabase.table("chat_messages").insert({
                "telegram_id": user_id,
                "sender": sender,
                "message_text": text
            }).execute())
    except Exception as e:
        print(f"Error logging chat message: {e}")

async def check_user_access(user_id: int):
    try:
        global_res = await asyncio.to_thread(lambda: supabase.table("bot_settings").select("value").eq("key", "global_mute").execute())
        if global_res.data and global_res.data[0].get("value") == True:
            return False, "🔒 استقبال الرسائل مغلق حالياً من قبل الإدارة لجميع المستخدمين."
    except Exception as e:
        print(f"Error checking global mute: {e}")

    try:
        user_res = await asyncio.to_thread(lambda: supabase.table("users").select("is_blocked, muted_until").eq("telegram_id", user_id).execute())
        if user_res.data:
            user_data = user_res.data[0]
            if user_data.get("is_blocked"):
                return False, "❌ عذراً، تم حظرك من استخدام هذا البوت."

            muted_until_str = user_data.get("muted_until")
            if muted_until_str:
                muted_until = datetime.fromisoformat(muted_until_str.replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                if now < muted_until:
                    diff = muted_until - now
                    hours, remainder = divmod(int(diff.total_seconds()), 3600)
                    minutes, _ = divmod(remainder, 60)
                    time_left = f"{hours} ساعة و {minutes} دقيقة" if hours > 0 else f"{minutes} دقيقة"
                    return False, f"⏳ تم تقييد إرسال الرسائل لك مؤقتاً. يرجى الانتظار: {time_left}."
    except Exception as e:
        print(f"Error checking user access: {e}")

    return True, ""

# قائمة الأزرار الرئيسية متضمنة الزر الجديد
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("🎓 نتيجة الثانوية العامة 2026")],
        [KeyboardButton("📝 تسجيل"), KeyboardButton("📂 الأرشيف")],
        [KeyboardButton("🎬 الفيديوهات الجديدة"), KeyboardButton("📺 قناة اليوتيوب")],
        [KeyboardButton("💬 الدعم")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return

    await update.message.reply_text("أهلاً بك! اختر من القائمة أدناه:", reply_markup=get_main_keyboard())

# --- قسم الاستعلام عن نتيجة الثانوية العامة 2026 ---
async def start_result_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    await update.message.reply_text("🔎 **من فضلك اكتب اسم الطالب أو رقم الجلوس للبحث عن النتيجة:**")
    return RESULT_SEARCH

async def process_result_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    query_text = update.message.text.strip()

    if query_text in SYSTEM_BUTTONS:
        await update.message.reply_text("تم إلغاء البحث عن النتيجة.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    asyncio.create_task(log_chat_message(user.id, f"بحث نتيجة: {query_text}", "user"))

    try:
        # البحث في قاعدة بيانات النتيجة الثانية
        if query_text.isdigit():
            # البحث برقم الجلوس
            seating_num = int(query_text)
            res = await asyncio.to_thread(lambda: results_supabase.table("student_results").select("*").eq("seating_no", seating_num).limit(5).execute())
        else:
            # البحث بالاسم
            res = await asyncio.to_thread(lambda: results_supabase.table("student_results").select("*").ilike("arabic_name", f"%{query_text}%").limit(5).execute())

        students = res.data

        if not students:
            await update.message.reply_text("❌ لم يتم العثور على أي نتيجة تطابق إدخالك. يرجى التأكد من الاسم أو رقم الجلوس والمحاولة مرة أخرى.", reply_markup=get_main_keyboard())
            return ConversationHandler.END

        # عرض النتائج
        for student in students:
            name = student.get("arabic_name", "غير محدد")
            seating = student.get("seating_no", "غير محدد")
            degree = float(student.get("total_degree") or 0)
            case_desc = student.get("student_case_desc", "غير محدد")

            # حساب النسبة المئوية تلقائياً بناءً على مجموع 320
            percentage = (degree / 320.0) * 100.0

            result_msg = (
                f"🎓 **نتيجة الطالب:**\n\n"
                f"👤 **الاسم:** {name}\n"
                f"🔢 **رقم الجلوس:** `{seating}`\n"
                f"📊 **المجموع الكلي:** `{degree}` من 320\n"
                f"📈 **النسبة المئوية:** `{percentage:.2f}%`\n"
                f"📌 **الحالة:** {case_desc}"
            )

            await update.message.reply_text(result_msg, parse_mode="Markdown", reply_markup=get_main_keyboard())

    except Exception as e:
        print(f"Error searching results: {e}")
        await update.message.reply_text("حدث خطأ أثناء جلب النتيجة، يرجى المحاولة لاحقاً.", reply_markup=get_main_keyboard())

    return ConversationHandler.END

# --- قسم الفيديوهات الجديدة ---
async def open_new_videos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return

    try:
        res = await asyncio.to_thread(lambda: supabase.table("new_videos").select("*").order("id", desc=True).limit(5).execute())
        videos = res.data

        if not videos:
            await update.message.reply_text("لا توجد فيديوهات جديدة مضافة حالياً.", reply_markup=get_main_keyboard())
            return

        await update.message.reply_text("🎬 **قائمة الفيديوهات الجديدة:**")

        for vid in videos:
            title = vid.get("title", "فيديو جديد")
            url = vid.get("video_url", "#")
            thumb = vid.get("thumbnail_url")

            keyboard = [[InlineKeyboardButton("▶️ مشاهدة الفيديو الآن", url=url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            caption_text = f"📌 **{title}**"

            sent = False
            if thumb and (thumb.startswith("http://") or thumb.startswith("https://")):
                try:
                    await update.message.reply_photo(photo=thumb, caption=caption_text, parse_mode="Markdown", reply_markup=reply_markup)
                    sent = True
                except Exception:
                    sent = False

            if not sent:
                await update.message.reply_text(caption_text, parse_mode="Markdown", reply_markup=reply_markup)

    except Exception as e:
        print(f"Error fetching videos: {e}")
        await update.message.reply_text("حدث خطأ أثناء جلب الفيديوهات.", reply_markup=get_main_keyboard())

# --- قسم الأرشيف ---
async def open_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return

    try:
        res = await asyncio.to_thread(lambda: supabase.table("archive_files").select("*").order("id", desc=True).execute())
        files = res.data
        if not files:
            await update.message.reply_text("لا توجد ملفات في الأرشيف حالياً.", reply_markup=get_main_keyboard())
            return

        keyboard = [[InlineKeyboardButton(f"📄 {f['title']}", url=f['file_url'])] for f in files]
        await update.message.reply_text("اختر الملف الذي تريد تحميله من الأرشيف:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء جلب الملفات.", reply_markup=get_main_keyboard())

# --- قسم قناة اليوتيوب ---
async def open_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return

    keyboard = [[InlineKeyboardButton("🔗 زيارة قناة اليوتيوب", url=YOUTUBE_CHANNEL_URL)]]
    await update.message.reply_text("اضغط على الزر أدناه للانتقال للقناة:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- قسم التسجيل ---
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    await update.message.reply_text("من فضلك أدخل اسمك الكامل (أحرف فقط):")
    return REG_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    name_input = update.message.text.strip()

    if name_input in SYSTEM_BUTTONS:
        await update.message.reply_text("تم إلغاء عملية التسجيل.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if name_input.isdigit() or not re.search(r'[\w\u0600-\u06FF]', name_input):
        await update.message.reply_text("❌ يجب أن يتكون الاسم من أحرف وليس أرقام فقط. أعد إدخال اسمك:")
        return REG_NAME

    context.user_data['name'] = name_input
    phone_button = ReplyKeyboardMarkup([[KeyboardButton("📱 إرسال رقم الهاتف", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("شكراً! الآن أرسل رقم هاتفك بالنقر على الزر أدناه أو اكتبه كأرقام فقط:", reply_markup=phone_button)
    return REG_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    name = context.user_data.get('name')
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        raw_phone = update.message.text.strip()
        if raw_phone in SYSTEM_BUTTONS:
            await update.message.reply_text("تم إلغاء التسجيل.", reply_markup=get_main_keyboard())
            return ConversationHandler.END

        cleaned_phone = raw_phone.replace("+", "").replace(" ", "").replace("-", "")
        if not cleaned_phone.isdigit():
            await update.message.reply_text("❌ يجب أن يحتوي رقم الهاتف على أرقام فقط! أعد الإدخال:")
            return REG_PHONE
        phone = raw_phone

    try:
        data = {"telegram_id": user.id, "full_name": name, "phone_number": phone}
        await asyncio.to_thread(lambda: supabase.table("users").upsert(data, on_conflict="telegram_id").execute())
        await update.message.reply_text(f"تم حفظ بياناتك بنجاح! 🎉\n\nالاسم: {name}\nالرقم: {phone}", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء حفظ البيانات، يرجى المحاولة لاحقاً.", reply_markup=get_main_keyboard())
        
    return ConversationHandler.END

# --- قسم الدعم ---
async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    asyncio.create_task(ensure_user_registered(user))

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    await update.message.reply_text("من فضلك اكتب رسالتك وسنقوم بتوصيلها للإدارة:")
    return SUPPORT_MSG

async def send_support_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_msg = update.message.text.strip()

    if user_msg in SYSTEM_BUTTONS:
        await update.message.reply_text("تم إلغاء إرسال رسالة الدعم.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    try:
        support_data = {"telegram_id": user.id, "full_name": user.first_name, "username": user.username, "message": user_msg}
        await asyncio.to_thread(lambda: supabase.table("support_messages").insert(support_data).execute())
    except Exception as e:
        print(f"Error saving support: {e}")

    asyncio.create_task(log_chat_message(user.id, user_msg, "user"))

    admin_notification = f"📩 **رسالة دعم جديدة**\n\n👤 **المستخدِم:** {user.first_name} (@{user.username})\n🆔 **ID:** `{user.id}`\n\n💬 **الرسالة:**\n{user_msg}"
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notification, parse_mode="Markdown")
        await update.message.reply_text("تم إرسال رسالتك إلى الدعم بنجاح!", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء الإرسال.", reply_markup=get_main_keyboard())

    return ConversationHandler.END

async def handle_reply_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    ticket_id = query.data.replace("reply_ticket_", "")
    context.user_data['active_ticket_id'] = ticket_id

    await query.message.reply_text("✏️ **من فضلك اكتب ردك الجديد على هذه الرسالة:**")
    return SUPPORT_REPLY_MSG

async def process_user_ticket_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text.strip()
    ticket_id = context.user_data.get('active_ticket_id')

    if text in SYSTEM_BUTTONS:
        await update.message.reply_text("تم إلغاء الإضافة.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if ticket_id:
        try:
            res = await asyncio.to_thread(lambda: supabase.table("support_messages").select("replies").eq("id", ticket_id).single().execute())
            existing_replies = res.data.get("replies") or []
            existing_replies.append({"sender": "user", "text": text, "time": datetime.now().strftime("%Y-%m-%d %H:%M")})

            await asyncio.to_thread(lambda: supabase.table("support_messages").update({
                "replies": existing_replies,
                "is_replied": False
            }).eq("id", ticket_id).execute())

            asyncio.create_task(log_chat_message(user.id, text, "user"))
            await update.message.reply_text("✅ تم إدراج ردك داخل نفس التذكرة وتوصيله للإدارة بنجاح!", reply_markup=get_main_keyboard())
        except Exception as e:
            print(f"Error appending user reply: {e}")
            await update.message.reply_text("حدث خطأ أثناء حفظ الرد.", reply_markup=get_main_keyboard())

    return ConversationHandler.END

async def handle_direct_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        user = update.message.from_user
        text = update.message.text.strip()

        if text in SYSTEM_BUTTONS:
            return

        asyncio.create_task(ensure_user_registered(user))

        can_access, reason = await check_user_access(user.id)
        if not can_access:
            await update.message.reply_text(reason, reply_markup=get_main_keyboard())
            return

        asyncio.create_task(log_chat_message(user.id, text, "user"))

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).concurrent_updates(True).build()

    reg_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 تسجيل$"), start_registration)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            REG_PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), get_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    support_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^💬 الدعم$"), start_support),
            CallbackQueryHandler(handle_reply_button_click, pattern="^reply_ticket_")
        ],
        states={
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_support_to_admin)],
            SUPPORT_REPLY_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_user_ticket_reply)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    result_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎓 نتيجة الثانوية العامة 2026$"), start_result_search)],
        states={
            RESULT_SEARCH: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_result_search)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_handler)
    app.add_handler(support_handler)
    app.add_handler(result_handler)
    app.add_handler(MessageHandler(filters.Regex("^📂 الأرشيف$"), open_archive))
    app.add_handler(MessageHandler(filters.Regex("^📺 قناة اليوتيوب$"), open_youtube))
    app.add_handler(MessageHandler(filters.Regex("^🎬 الفيديوهات الجديدة$"), open_new_videos))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_direct_chat_message))

    print("البوت يعمل مع ميزة نتيجة الثانوية العامة 2026...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
