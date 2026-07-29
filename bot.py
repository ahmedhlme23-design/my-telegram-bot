import logging
import os
import re
import threading
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

# --- 1. سيرفر وهمي للاستضافة ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# --- 2. إعدادات Supabase ---
SUPABASE_URL = "https://besvojmipioaeavdwcvj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJlc3Zvam1pcGlvYWVhdmR3Y3ZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUzMzc4NzgsImV4cCI6MjEwMDkxMzg3OH0.yE4u8bCY8vMWPSLeZHKVbQEoC0VUqb41pEHHDBfqX1Q"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 3. إعدادات البوت ---
BOT_TOKEN = "8943376248:AAHAdToTCLQAc-3uj9MQ7oAbhTwO5q-rHjs"  # ضع توكن البوت الخاص بك
ADMIN_CHAT_ID = 1359132699          # ضع الـ ID الخاص بك
YOUTUBE_CHANNEL_URL = "https://www.youtube.com/channel/UCL1nCgb41VNqe32kY0tCZ1w/"

REG_NAME, REG_PHONE, SUPPORT_MSG = range(3)

# --- دوال التحقق من الحظر والـ Mute ---
async def check_user_access(user_id: int):
    """ترجع (يمكنه_الاستخدام, سبب_المنع)"""
    # 1. فحص الإغلاق العام للجميع (Global Mute)
    try:
        global_res = supabase.table("bot_settings").select("value").eq("key", "global_mute").execute()
        if global_res.data and global_res.data[0].get("value") == True:
            return False, "🔒 استقبال الرسائل مغلق حالياً من قبل الإدارة لجميع المستخدمين. يرجى المحاولة لاحقاً."
    except Exception as e:
        print(f"Error checking global mute: {e}")

    # 2. فحص الحظر والكتم للمستخدم
    try:
        user_res = supabase.table("users").select("is_blocked, muted_until").eq("telegram_id", user_id).execute()
        if user_res.data:
            user_data = user_res.data[0]
            
            # حظر نهائي
            if user_data.get("is_blocked"):
                return False, "❌ عذراً، تم حظرك من استخدام هذا البوت."

            # كتم مؤقت
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

# قائمة الأزرار الرئيسية
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 تسجيل"), KeyboardButton("📂 الأرشيف")],
        [KeyboardButton("📺 قناة اليوتيوب"), KeyboardButton("💬 الدعم")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason)
        return

    await update.message.reply_text("أهلاً بك! اختر من القائمة أدناه:", reply_markup=get_main_keyboard())

# --- قسم التسجيل ---
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason)
        return ConversationHandler.END

    await update.message.reply_text("من فضلك أدخل اسمك الكامل (أحرف فقط):")
    return REG_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    name_input = update.message.text.strip()
    if name_input.isdigit() or not re.search(r'[\w\u0600-\u06FF]', name_input):
        await update.message.reply_text("❌ يجب أن يتكون الاسم من أحرف وليس أرقام فقط. أعد إدخال اسمك:")
        return REG_NAME

    context.user_data['name'] = name_input
    phone_button = ReplyKeyboardMarkup([[KeyboardButton("📱 إرسال رقم الهاتف", request_contact=True)]], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("شكراً! الآن أرسل رقم هاتفك بالنقر على الزر أدناه أو اكتبه كأرقام فقط:", reply_markup=phone_button)
    return REG_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    name = context.user_data.get('name')
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        raw_phone = update.message.text.strip()
        cleaned_phone = raw_phone.replace("+", "").replace(" ", "").replace("-", "")
        if not cleaned_phone.isdigit():
            await update.message.reply_text("❌ يجب أن يحتوي رقم الهاتف على أرقام فقط! أعد الإدخال:")
            return REG_PHONE
        phone = raw_phone

    try:
        data = {"telegram_id": user_id, "full_name": name, "phone_number": phone}
        supabase.table("users").upsert(data, on_conflict="telegram_id").execute()
        await update.message.reply_text(f"تم حفظ بياناتك بنجاح! 🎉\n\nالاسم: {name}\nالرقم: {phone}", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء حفظ البيانات، يرجى المحاولة لاحقاً.", reply_markup=get_main_keyboard())
        
    return ConversationHandler.END

# --- قسم الأرشيف ---
async def open_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason)
        return

    try:
        res = supabase.table("archive_files").select("*").order("id", desc=True).execute()
        files = res.data
        if not files:
            await update.message.reply_text("لا توجد ملفات في الأرشيف حالياً.")
            return

        keyboard = [[InlineKeyboardButton(f"📄 {f['title']}", url=f['file_url'])] for f in files]
        await update.message.reply_text("اختر الملف الذي تريد تحميله من الأرشيف:", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء جلب الملفات.")

# --- قسم قناة اليوتيوب ---
async def open_youtube(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason)
        return

    keyboard = [[InlineKeyboardButton("🔗 زيارة قناة اليوتيوب", url=YOUTUBE_CHANNEL_URL)]]
    await update.message.reply_text("اضغط على الزر أدناه للانتقال للقناة:", reply_markup=InlineKeyboardMarkup(keyboard))

# --- قسم الدعم ---
async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    can_access, reason = await check_user_access(user_id)
    if not can_access:
        await update.message.reply_text(reason)
        return ConversationHandler.END

    await update.message.reply_text("من فضلك اكتب رسالتك وسنقوم بتوصيلها للإدارة:")
    return SUPPORT_MSG

async def send_support_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    
    # 🔴 فحص الكتم والحظر فور استلام نص الرسالة قبل حفظها أو إرسالها للأدمن
    can_access, reason = await check_user_access(user.id)
    if not can_access:
        await update.message.reply_text(reason, reply_markup=get_main_keyboard())
        return ConversationHandler.END

    user_msg = update.message.text

    try:
        support_data = {"telegram_id": user.id, "full_name": user.first_name, "username": user.username, "message": user_msg}
        supabase.table("support_messages").insert(support_data).execute()
    except Exception as e:
        print(f"Error saving support: {e}")

    admin_notification = f"📩 **رسالة دعم جديدة**\n\n👤 **المستخدِم:** {user.first_name} (@{user.username})\n🆔 **ID:** `{user.id}`\n\n💬 **الرسالة:**\n{user_msg}"
    
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notification, parse_mode="Markdown")
        await update.message.reply_text("تم إرسال رسالتك إلى الدعم بنجاح!", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء الإرسال.", reply_markup=get_main_keyboard())

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("تم إلغاء العملية.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    reg_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 تسجيل$"), start_registration)],
        states={
            REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            REG_PHONE: [MessageHandler(filters.CONTACT | (filters.TEXT & ~filters.COMMAND), get_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    support_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💬 الدعم$"), start_support)],
        states={SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_support_to_admin)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_handler)
    app.add_handler(support_handler)
    app.add_handler(MessageHandler(filters.Regex("^📂 الأرشيف$"), open_archive))
    app.add_handler(MessageHandler(filters.Regex("^📺 قناة اليوتيوب$"), open_youtube))

    print("البوت يعمل مع التعديل الدقيق لفحص الكتم...")
    app.run_polling()

if __name__ == "__main__":
    main()
