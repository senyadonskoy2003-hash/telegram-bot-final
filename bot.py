import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from deep_translator import GoogleTranslator

# Состояния для разговора
LANGUAGE_CHOICE = 1

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# Доступные языки
LANGUAGES = {
    'ru': '🇷🇺 Русский',
    'en': '🇬🇧 Английский',
    'es': '🇪🇸 Испанский',
    'fr': '🇫🇷 Французский',
    'de': '🇩🇪 Немецкий',
    'it': '🇮🇹 Итальянский',
    'zh-cn': '🇨🇳 Китайский',
    'ja': '🇯🇵 Японский',
    'ar': '🇸🇦 Арабский',
    'tr': '🇹🇷 Турецкий'
}

# Словарь для хранения выбора языка каждого пользователя
user_target_language = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌟 Привет! Я бот-переводчик.\n\n"
        "📝 Просто отправь мне любой текст — я предложу выбрать язык перевода.\n"
        "После выбора язык запомнится для следующих сообщений."
    )

async def ask_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    original_text = update.message.text
    
    # Сохраняем текст для перевода
    context.user_data['text_to_translate'] = original_text
    
    # Создаём клавиатуру с языками
    keyboard = [[lang_name] for lang_name in LANGUAGES.values()]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "🎯 Выбери язык, на который перевести:",
        reply_markup=reply_markup
    )
    return LANGUAGE_CHOICE

async def translate_to_chosen_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chosen_lang_name = update.message.text
    
    # Находим код языка по названию
    target_code = None
    for code, name in LANGUAGES.items():
        if name == chosen_lang_name:
            target_code = code
            break
    
    if target_code:
        # Сохраняем выбор пользователя
        user_target_language[user_id] = target_code
        
        # Берём сохранённый текст
        original_text = context.user_data.get('text_to_translate', '')
        
        try:
            # Переводим
            translator = GoogleTranslator(source='auto', target=target_code)
            translated = translator.translate(original_text)
            
            # Показываем перевод
            await update.message.reply_text(
                f"📝 Оригинал: {original_text}\n\n"
                f"✅ Перевод ({LANGUAGES[target_code]}):\n{translated}\n\n"
                f"💡 Теперь можешь просто отправлять текст — буду переводить на {LANGUAGES[target_code]}"
            )
        except Exception as e:
            await update.message.reply_text("❌ Ошибка перевода. Попробуй ещё раз.")
            logging.error(f"Translation error: {e}")
    else:
        await update.message.reply_text("❌ Пожалуйста, выбери язык из списка.")
        return LANGUAGE_CHOICE
    
    return ConversationHandler.END

async def auto_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Проверяем, есть ли сохранённый язык для пользователя
    if user_id in user_target_language:
        target = user_target_language[user_id]
        target_name = LANGUAGES.get(target, target)
        
        try:
            translator = GoogleTranslator(source='auto', target=target)
            translated = translator.translate(text)
            
            await update.message.reply_text(
                f"📝 Оригинал: {text}\n\n"
                f"✅ Перевод ({target_name}):\n{translated}"
            )
        except Exception as e:
            await update.message.reply_text("❌ Ошибка перевода. Попробуй ещё раз.")
            logging.error(f"Auto translation error: {e}")
    else:
        # Если язык не выбран — запускаем выбор
        context.user_data['text_to_translate'] = text
        return await ask_language(update, context)

async def reset_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in user_target_language:
        del user_target_language[user_id]
    await update.message.reply_text(
        "🔄 Язык сброшен. При следующем сообщении снова предложу выбрать."
    )

async def list_languages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    langs = "\n".join([f"{code} - {name}" for code, name in LANGUAGES.items()])
    await update.message.reply_text(f"🌐 Доступные языки:\n\n{langs}")

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler для выбора языка
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, auto_translate)],
        states={
            LANGUAGE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, translate_to_chosen_language)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset_language))
    app.add_handler(CommandHandler("languages", list_languages))
    app.add_handler(conv_handler)
    
    app.run_polling()

if __name__ == "__main__":
    main()
