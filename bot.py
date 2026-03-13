import os
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from googletrans import Translator

# Состояния для разговора
LANGUAGE_SELECTION, TRANSLATION_MODE = range(2)

logging.basicConfig(level=logging.INFO)

TOKEN = os.environ.get("TOKEN")
ADMIN_ID = 123456789  # 👈 ЗАМЕНИ НА СВОЙ ID

if not TOKEN:
    raise Exception("TOKEN не найден!")

translator = Translator()

# Доступные языки
LANGUAGES = {
    'ru': 'Русский',
    'en': 'Английский',
    'es': 'Испанский',
    'fr': 'Французский',
    'de': 'Немецкий',
    'it': 'Итальянский',
    'zh-cn': 'Китайский',
    'ja': 'Японский',
    'ko': 'Корейский',
    'ar': 'Арабский',
    'tr': 'Турецкий'
}

# Словарь для хранения настроек пользователя
user_settings = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["🌍 Автоматический перевод на русский"],
        ["🔄 Выбрать языки вручную"],
        ["ℹ️ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🌟 Привет! Я бот-переводчик.\n\n"
        "📝 Просто отправь мне текст, и я переведу его.\n"
        "По умолчанию определяю язык и перевожу на русский.\n\n"
        "Выбери режим работы:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Как пользоваться:\n\n"
        "1️⃣ Отправь текст для перевода\n"
        "2️⃣ По умолчанию перевожу на русский\n"
        "3️⃣ Нажми 'Выбрать языки вручную' для настройки\n"
        "4️⃣ /languages - показать все доступные языки\n"
        "5️⃣ /auto - вернуться к автоопределению"
    )

async def languages_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    langs = "\n".join([f"{code} - {name}" for code, name in LANGUAGES.items()])
    await update.message.reply_text(f"🌐 Доступные языки:\n\n{langs}")

async def auto_translate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_settings[user_id] = {'mode': 'auto', 'target': 'ru'}
    await update.message.reply_text("✅ Режим: автоматическое определение языка → русский")

async def manual_mode_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[lang_name] for lang_name in LANGUAGES.values()]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🎯 Выбери язык, с которого будем переводить:",
        reply_markup=reply_markup
    )
    return LANGUAGE_SELECTION

async def select_source_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    selected_lang = update.message.text
    
    # Находим код языка по названию
    source_code = None
    for code, name in LANGUAGES.items():
        if name == selected_lang:
            source_code = code
            break
    
    if source_code:
        context.user_data['source_lang'] = source_code
        
        # Показываем языки для выбора целевого
        keyboard = [[lang_name] for lang_name in LANGUAGES.values()]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"✅ Выбрано: {selected_lang}\n\nТеперь выбери язык, на который переводим:",
            reply_markup=reply_markup
        )
        return TRANSLATION_MODE
    else:
        await update.message.reply_text("❌ Пожалуйста, выбери язык из списка")
        return LANGUAGE_SELECTION

async def select_target_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    selected_lang = update.message.text
    
    # Находим код языка по названию
    target_code = None
    for code, name in LANGUAGES.items():
        if name == selected_lang:
            target_code = code
            break
    
    if target_code:
        source = context.user_data.get('source_lang', 'ru')
        user_settings[user_id] = {
            'mode': 'manual',
            'source': source,
            'target': target_code
        }
        
        # Возвращаем основную клавиатуру
        keyboard = [
            ["🌍 Автоматический перевод на русский"],
            ["🔄 Выбрать языки вручную"],
            ["ℹ️ Помощь"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        source_name = LANGUAGES.get(source, source)
        target_name = LANGUAGES.get(target_code, target_code)
        
        await update.message.reply_text(
            f"✅ Режим: {source_name} → {target_name}\n\n"
            f"Теперь отправляй текст для перевода!",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Пожалуйста, выбери язык из списка")
        return TRANSLATION_MODE

async def translate_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    # Пропускаем команды и кнопки
    if text in ["🌍 Автоматический перевод на русский", "🔄 Выбрать языки вручную", "ℹ️ Помощь"]:
        return
    
    try:
        settings = user_settings.get(user_id, {'mode': 'auto', 'target': 'ru'})
        
        if settings['mode'] == 'auto':
            # Автоматически определяем язык и переводим на русский
            detected = translator.detect(text)
            translated = translator.translate(text, dest='ru')
            
            source_lang = LANGUAGES.get(detected.lang, detected.lang)
            
            await update.message.reply_text(
                f"🔍 Определён язык: {source_lang}\n\n"
                f"📝 Оригинал: {text}\n\n"
                f"✅ Перевод: {translated.text}"
            )
        else:
            # Переводим с выбранного языка на выбранный
            translated = translator.translate(
                text, 
                src=settings['source'], 
                dest=settings['target']
            )
            
            source_name = LANGUAGES.get(settings['source'], settings['source'])
            target_name = LANGUAGES.get(settings['target'], settings['target'])
            
            await update.message.reply_text(
                f"🔄 {source_name} → {target_name}\n\n"
                f"📝 Оригинал: {text}\n\n"
                f"✅ Перевод: {translated.text}"
            )
            
    except Exception as e:
        await update.message.reply_text(
            "❌ Не удалось перевести текст. Проверь язык или попробуй ещё раз."
        )
        logging.error(f"Translation error: {e}")

async def handle_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    if user.id == ADMIN_ID:
        await update.message.reply_text("👋 Привет, админ! Чем могу помочь?")
        
        # Пересылаем сообщение админу от пользователей
        # (можно добавить позже)

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler для ручного выбора языков
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🔄 Выбрать языки вручную$'), manual_mode_start)],
        states={
            LANGUAGE_SELECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_source_language)],
            TRANSLATION_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_target_language)],
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("languages", languages_command))
    app.add_handler(CommandHandler("auto", auto_translate))
    
    app.add_handler(MessageHandler(filters.Regex('^🌍 Автоматический перевод на русский$'), auto_translate))
    app.add_handler(conv_handler)
    
    # Обработчик текстовых сообщений (перевод)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, translate_text))
    
    app.run_polling()

if __name__ == "__main__":
    main()
