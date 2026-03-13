import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from deep_translator import GoogleTranslator

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# Инициализация переводчика
translator = GoogleTranslator(source='auto', target='ru')

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 Привет! Я бот-переводчик.\n"
        "Просто отправь мне текст — я переведу его на русский."
    )

async def translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    try:
        translated = translator.translate(text)
        await update.message.reply_text(
            f"📝 Оригинал: {text}\n\n"
            f"✅ Перевод: {translated}"
        )
    except Exception as e:
        await update.message.reply_text("❌ Ошибка перевода. Попробуй ещё раз.")
        logging.error(f"Translation error: {e}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate))
    app.run_polling()

if __name__ == "__main__":
    main()
