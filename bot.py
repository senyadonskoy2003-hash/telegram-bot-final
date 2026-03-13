import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from googletrans import Translator

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")
ADMIN_ID = 123456789  # 👈 замени на свой

if not TOKEN:
    raise Exception("TOKEN не найден!")

translator = Translator()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 Привет! Я бот-переводчик.\n"
        "Просто отправь мне текст — я переведу его на русский."
    )

async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        translated = translator.translate(text, dest='ru')
        await update.message.reply_text(
            f"📝 Оригинал: {text}\n\n"
            f"✅ Перевод: {translated.text}"
        )
    except:
        await update.message.reply_text("❌ Ошибка перевода. Попробуй ещё раз.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate))
    app.run_polling()

if __name__ == "__main__":
    main()