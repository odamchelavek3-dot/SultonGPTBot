
import os
import logging
import sqlite3
import asyncio

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL")
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

DB_NAME = "sultongpt.db"
user_last_message = {}


def init_db():
    with sqlite3.connect(DB_NAME) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                role TEXT,
                content TEXT
            )
        """)


def save_message(user_id, role, content):
    with sqlite3.connect(DB_NAME) as db:
        db.execute(
            "INSERT INTO history (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        db.execute("""
            DELETE FROM history
            WHERE user_id = ? AND id NOT IN (
                SELECT id FROM history
                WHERE user_id = ?
                ORDER BY id DESC LIMIT 20
            )
        """, (user_id, user_id))


def get_history(user_id):
    with sqlite3.connect(DB_NAME) as db:
        rows = db.execute(
            "SELECT role, content FROM history "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 12",
            (user_id,),
        ).fetchall()
    return list(reversed(rows))


def clear_history(user_id):
    with sqlite3.connect(DB_NAME) as db:
        db.execute("DELETE FROM history WHERE user_id = ?", (user_id,))


def keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🤖 AI bilan suhbat"],
            ["🧠 Xotirani tozalash", "ℹ️ Yordam"],
        ],
        resize_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Assalomu alaykum! Men Sulton 🤖\n\n"
        "Men siz bilan suhbatlashaman, savollaringizga javob beraman "
        "va turli vazifalarda yordam beraman.\n\n"
        "Suhbatni boshlash uchun xabar yozing!",
        reply_markup=keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 SultonGPT yordamchisi\n\n"
        "• Istalgan savolingizni yozing.\n"
        "• Ovozli xabar yuborishingiz mumkin.\n"
        "• Xotirani tozalash tugmasi suhbat tarixini o‘chiradi.\n\n"
        "Eslatma: ovozli xabarni tahlil qilish funksiyasi hali ulanmagan.",
        reply_markup=keyboard(),
    )


async def ask_gemini(user_id, question):
    history = get_history(user_id)

    conversation = [
        f"{role}: {content}" for role, content in history
    ]
    conversation.append(f"user: {question}")

    prompt = (
        "Sen SultonGPT nomli foydali, samimiy va aqlli o‘zbek AI "
        "yordamchisisan. Asosan o‘zbek tilida sodda va tushunarli "
        "javob ber. Foydalanuvchiga hurmat bilan murojaat qil.\n\n"
        + "\n".join(conversation)
        + "\nassistant:"
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=MODEL,
        contents=prompt,
    )

    return response.text or "Kechirasiz, hozir javob tayyorlay olmadim."


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    question = update.message.text.strip()

    if question == "🤖 AI bilan suhbat":
        await update.message.reply_text("Marhamat, savolingizni yozing! 😊")
        return

    if question == "🧠 Xotirani tozalash":
        clear_history(user_id)
        await update.message.reply_text("Suhbat xotirasi tozalandi! 🧹")
        return

    if question == "ℹ️ Yordam":
        await help_command(update, context)
        return

    if not client:
        await update.message.reply_text("AI xizmati sozlanmagan.")
        return

    now = asyncio.get_running_loop().time()
    if now - user_last_message.get(user_id, 0) < 3:
        await update.message.reply_text("Iltimos, biroz kutib turing. 😊")
        return

    user_last_message[user_id] = now
    wait = await update.message.reply_text("⏳ Javob tayyorlayapman...")

    try:
        answer = await ask_gemini(user_id, question)

        save_message(user_id, "user", question)
        save_message(user_id, "assistant", answer)

        if len(answer) <= 4000:
            await wait.edit_text(answer)
        else:
            await wait.edit_text(answer[:4000])
            for i in range(4000, len(answer), 4000):
                await update.message.reply_text(answer[i:i + 4000])

    except Exception:
        logger.exception("Gemini xatosi")
        await wait.edit_text(
            "Kechirasiz, xatolik yuz berdi. Birozdan keyin qayta urinib ko‘ring."
        )


async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎤 Ovozli xabaringizni oldim. Ovoz bilan ishlash funksiyasini "
        "keyingi bosqichda ulaymiz."
    )


def main():
    required = {
        "BOT_TOKEN": BOT_TOKEN,
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "WEBHOOK_PATH": WEBHOOK_PATH,
        "WEBHOOK_SECRET": WEBHOOK_SECRET,
        "RENDER_EXTERNAL_URL": RENDER_URL,
    }

    missing = [key for key, value in required.items() if not value]
    if missing:
        raise ValueError("Sozlanmagan o'zgaruvchilar: " + ", ".join(missing))

    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE, voice_message))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("SULTONGPT WEBHOOK ISHGA TUSHMOQDA")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=WEBHOOK_PATH,
        webhook_url=f"{RENDER_URL}/{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
