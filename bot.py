import logging
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

# --- إعدادات Supabase ---
SUPABASE_URL = "https://besvojmipioaeavdwcvj.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJlc3Zvam1pcGlvYWVhdmR3Y3ZqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODUzMzc4NzgsImV4cCI6MjEwMDkxMzg3OH0.yE4u8bCY8vMWPSLeZHKVbQEoC0VUqb41pEHHDBfqX1Q"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- إعدادات البوت ---
BOT_TOKEN = "8943376248:AAHAdToTCLQAc-3uj9MQ7oAbhTwO5q-rHjs"  # ضع توكن البوت الخاص بك من BotFather
ADMIN_CHAT_ID = 1359132699          # ضع الـ ID الخاص بك هنا لرسائل الدعم

# مراحل الحوار
REG_NAME, REG_PHONE, SUPPORT_MSG = range(3)

# قائمة الأزرار الرئيسية
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📝 تسجيل"), KeyboardButton("📂 الأرشيف")],
        [KeyboardButton("💬 الدعم")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# أمر /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك! اختر من القائمة أدناه:",
        reply_markup=get_main_keyboard()
    )

# --- قسم التسجيل ---
async def start_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("من فضلك أدخل اسمك الكامل:")
    return REG_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    
    phone_button = ReplyKeyboardMarkup(
        [[KeyboardButton("📱 إرسال رقم الهاتف", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await update.message.reply_text("شكراً! الآن أرسل رقم هاتفك بالنقر على الزر أدناه أو اكتبه بنفسك:", reply_markup=phone_button)
    return REG_PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    name = context.user_data.get('name')
    
    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text

    # حفظ البيانات في Supabase
    try:
        data = {
            "telegram_id": user_id,
            "full_name": name,
            "phone_number": phone
        }
        # إجراء عملية الحفظ أو التحديث إذا كان المستخدم مسجلاً من قبل (Upsert)
        supabase.table("users").upsert(data, on_conflict="telegram_id").execute()
        
        await update.message.reply_text(
            f"تم حفظ بياناتك بنجاح في قاعدة البيانات! 🎉\n\nالاسم: {name}\nالرقم: {phone}",
            reply_markup=get_main_keyboard()
        )
    except Exception as e:
        print(f"خطأ أثناء الحفظ في Supabase: {e}")
        await update.message.reply_text(
            "حدث خطأ أثناء حفظ البيانات، يرجى المحاولة لاحقاً.",
            reply_markup=get_main_keyboard()
        )
        
    return ConversationHandler.END

# --- قسم الأرشيف ---
async def open_archive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📄 ملف التعليمات (PDF)", callback_data="pdf_1")],
        [InlineKeyboardButton("📄 الشروط والأحكام (PDF)", callback_data="pdf_2")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر الملف الذي تريد تحميله من الأرشيف:", reply_markup=reply_markup)

async def handle_archive_download(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "pdf_1":
        await query.message.reply_text("رابط تحميل ملف التعليمات: https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf")
    elif query.data == "pdf_2":
        await query.message.reply_text("رابط تحميل الشروط والأحكام: https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf")

# --- قسم الدعم ---
async def start_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("من فضلك اكتب رسالتك وسنقوم بتوصيلها للإدارة:")
    return SUPPORT_MSG

async def send_support_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_msg = update.message.text

    admin_notification = (
        f"📩 **رسالة دعم جديدة**\n\n"
        f"👤 **المستخدِم:** {user.first_name} (@{user.username})\n"
        f"🆔 **ID:** `{user.id}`\n\n"
        f"💬 **الرسالة:**\n{user_msg}"
    )
    
    try:
        await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_notification, parse_mode="Markdown")
        await update.message.reply_text("تم إرسال رسالتك إلى الدعم بنجاح! سنرد عليك في أقرب وقت.", reply_markup=get_main_keyboard())
    except Exception as e:
        await update.message.reply_text("حدث خطأ أثناء الإرسال، يرجى المحاولة لاحقاً.", reply_markup=get_main_keyboard())

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
        states={
            SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_support_to_admin)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(reg_handler)
    app.add_handler(support_handler)
    app.add_handler(MessageHandler(filters.Regex("^📂 الأرشيف$"), open_archive))
    app.add_handler(CallbackQueryHandler(handle_archive_download))

    print("البوت يعمل الآن ومربوط بـ Supabase...")
    app.run_polling()

if __name__ == "__main__":
    main()