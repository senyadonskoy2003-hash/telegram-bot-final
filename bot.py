import os
import logging
import asyncio
import re
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# Состояния для диалога
TEXT, TIME = range(2)

# Хранилище напоминаний {chat_id: [(время, текст)]}
reminders = {}

# ========== Команда /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📝 Добавить напоминание"],
        ["📋 Мои напоминания"],
        ["❌ Удалить напоминание"],
        ["❓ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⏰ *Бот-напоминалка*\n\n"
        "Я помогу тебе ничего не забыть!\n\n"
        "👇 Нажимай кнопки и я проведу тебя шаг за шагом.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

# ========== Начало добавления напоминания ==========
async def add_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Напиши мне *текст напоминания*:\n"
        "Например: купить хлеб, позвонить маме, оплатить счёт",
        parse_mode="Markdown"
    )
    return TEXT

# ========== Получаем текст напоминания ==========
async def add_reminder_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['reminder_text'] = update.message.text
    
    await update.message.reply_text(
        "⏰ Теперь напиши *время* в одном из форматов:\n\n"
        "• `18:30` — сегодня в 18:30\n"
        "• `завтра 10:00` — завтра в 10:00\n"
        "• `через 2 часа` — через 2 часа от сейчас\n"
        "• `25.03 15:00` — конкретная дата",
        parse_mode="Markdown"
    )
    return TIME

# ========== Получаем время и сохраняем ==========
async def add_reminder_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    reminder_text = context.user_data.get('reminder_text', 'Напоминание')
    
    now = datetime.now()
    reminder_time = None
    
    # Формат: ЧЧ:ММ
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    
    # Формат: завтра
    if 'завтра' in text and time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        reminder_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0) + timedelta(days=1)
    
    # Формат: через X часов
    elif 'через' in text and 'час' in text:
        hours_match = re.search(r'через\s+(\d+)\s+час', text)
        if hours_match:
            hours = int(hours_match.group(1))
            reminder_time = now + timedelta(hours=hours)
    
    # Формат: только время (сегодня)
    elif time_match and not 'завтра' in text:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        reminder_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if reminder_time < now:
            reminder_time += timedelta(days=1)
    
    # Формат: дата (например 25.03 15:00)
    date_match = re.search(r'(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})', text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        hours = int(date_match.group(3))
        minutes = int(date_match.group(4))
        year = now.year
        reminder_time = datetime(year, month, day, hours, minutes)
        if reminder_time < now:
            reminder_time = reminder_time.replace(year=year + 1)
    
    if reminder_time:
        # Сохраняем
        if chat_id not in reminders:
            reminders[chat_id] = []
        reminders[chat_id].append((reminder_time, reminder_text))
        
        # Запускаем задачу
        asyncio.create_task(send_reminder(chat_id, reminder_time, reminder_text, context.application))
        
        await update.message.reply_text(
            f"✅ *Готово!*\n\n"
            f"📝 Текст: {reminder_text}\n"
            f"⏰ Время: {reminder_time.strftime('%d.%m.%Y в %H:%M')}\n\n"
            f"Я напомню тебе в это время 👌",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "❌ Не понял время. Попробуй ещё раз:\n"
            "• `18:30`\n"
            "• `завтра 10:00`\n"
            "• `через 2 часа`"
        )
        return TIME
    
    return ConversationHandler.END

# ========== Показать список напоминаний ==========
async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in reminders and reminders[chat_id]:
        # Сортируем по времени
        sorted_reminders = sorted(reminders[chat_id], key=lambda x: x[0])
        
        msg = "📋 *Твои напоминания:*\n\n"
        for i, (rem_time, rem_text) in enumerate(sorted_reminders, 1):
            msg += f"{i}. {rem_time.strftime('%d.%m %H:%M')} — {rem_text}\n"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    else:
        await update.message.reply_text("📭 У тебя нет активных напоминаний.")
    
    return ConversationHandler.END

# ========== Начало удаления напоминания ==========
async def delete_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    
    if chat_id in reminders and reminders[chat_id]:
        sorted_reminders = sorted(reminders[chat_id], key=lambda x: x[0])
        context.user_data['sorted_reminders'] = sorted_reminders
        
        msg = "🗑 *Выбери номер напоминания для удаления:*\n\n"
        for i, (rem_time, rem_text) in enumerate(sorted_reminders, 1):
            msg += f"{i}. {rem_time.strftime('%d.%m %H:%M')} — {rem_text}\n"
        msg += "\n❌ Отправь *0* для отмены"
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        return 0  # следующее сообщение обработается в delete_reminder_choose
    else:
        await update.message.reply_text("📭 У тебя нет активных напоминаний.")
        return ConversationHandler.END

# ========== Обработка выбора для удаления ==========
async def delete_reminder_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    
    if text == "0":
        await update.message.reply_text("❌ Удаление отменено.")
        return ConversationHandler.END
    
    try:
        num = int(text) - 1
        sorted_reminders = context.user_data.get('sorted_reminders', [])
        
        if 0 <= num < len(sorted_reminders):
            # Находим оригинальное напоминание в reminders
            rem_to_delete = sorted_reminders[num]
            original_list = reminders.get(chat_id, [])
            
            # Удаляем по содержимому (время + текст)
            reminders[chat_id] = [(t, txt) for t, txt in original_list if t != rem_to_delete[0] or txt != rem_to_delete[1]]
            
            if not reminders[chat_id]:
                del reminders[chat_id]
            
            await update.message.reply_text(f"✅ Напоминание «{rem_to_delete[1]}» удалено.")
        else:
            await update.message.reply_text("❌ Неверный номер.")
    except ValueError:
        await update.message.reply_text("❌ Введи число.")
    
    return ConversationHandler.END

# ========== Помощь ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Как пользоваться ботом:*\n\n"
        "1️⃣ *Добавить напоминание*\n"
        "   Нажми кнопку и следуй шагам\n\n"
        "2️⃣ *Посмотреть список*\n"
        "   Нажми «Мои напоминания»\n\n"
        "3️⃣ *Удалить*\n"
        "   Нажми «Удалить напоминание» и выбери номер\n\n"
        "4️⃣ *Форматы времени*\n"
        "   • 18:30\n"
        "   • завтра 10:00\n"
        "   • через 2 часа\n"
        "   • 25.03 15:00",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# ========== Функция отправки напоминания ==========
async def send_reminder(chat_id: int, reminder_time: datetime, reminder_text: str, app):
    now = datetime.now()
    delay = (reminder_time - now).total_seconds()
    
    if delay > 0:
        await asyncio.sleep(delay)
        
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ *Напоминание!*\n\n{reminder_text}",
                parse_mode="Markdown"
            )
            # Удаляем из списка после отправки
            if chat_id in reminders:
                reminders[chat_id] = [(t, txt) for t, txt in reminders[chat_id] if t != reminder_time]
        except Exception as e:
            logging.error(f"Ошибка отправки напоминания: {e}")

# ========== Отмена диалога ==========
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

# ========== Запуск бота ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Диалог добавления напоминания
    conv_handler_add = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📝 Добавить напоминание$'), add_reminder_start)],
        states={
            TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_text)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_reminder_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Диалог удаления напоминания
    conv_handler_delete = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^❌ Удалить напоминание$'), delete_reminder_start)],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_reminder_choose)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.Regex('^📋 Мои напоминания$'), list_reminders))
    app.add_handler(conv_handler_add)
    app.add_handler(conv_handler_delete)
    
    print("🤖 Бот-напоминалка (с диалогами) запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
