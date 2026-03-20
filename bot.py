import os
import logging
import asyncio
import re
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, 
    filters, ContextTypes, ConversationHandler, 
    CallbackQueryHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# ========== НАСТРОЙКА ВРЕМЕНИ ==========
# Московское время (UTC+3)
MSK_OFFSET = timedelta(hours=3)

def now_msk():
    """Возвращает текущее время по Москве"""
    return datetime.now() + MSK_OFFSET

def now_utc():
    """Возвращает текущее время UTC (для БД)"""
    return datetime.now()

def utc_to_msk(utc_time):
    """Конвертирует UTC в МСК"""
    if isinstance(utc_time, str):
        utc_time = datetime.fromisoformat(utc_time)
    return utc_time + MSK_OFFSET

def msk_to_utc(msk_time):
    """Конвертирует МСК в UTC"""
    return msk_time - MSK_OFFSET

# Состояния для диалогов
TEXT, TIME, RECURRING = range(3)

# ========== База данных ==========
def init_db():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS one_time
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  text TEXT,
                  remind_time TIMESTAMP,
                  done BOOLEAN DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS recurring
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  text TEXT,
                  pattern TEXT,
                  time TEXT,
                  day_of_week INTEGER,
                  day_of_month INTEGER,
                  active BOOLEAN DEFAULT 1)''')
    
    conn.commit()
    conn.close()

init_db()

# ========== Работа с БД ==========
def add_one_time(chat_id, text, remind_time_utc):
    """Сохраняет напоминание (время в UTC)"""
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("INSERT INTO one_time (chat_id, text, remind_time) VALUES (?, ?, ?)",
              (chat_id, text, remind_time_utc))
    reminder_id = c.lastrowid
    conn.commit()
    conn.close()
    return reminder_id

def get_due_reminders():
    """Возвращает все просроченные напоминания (сравнивает по UTC)"""
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    now_utc = now_utc()
    c.execute("SELECT id, chat_id, text FROM one_time WHERE remind_time <= ? AND done = 0", (now_utc,))
    due = c.fetchall()
    conn.close()
    return due

def mark_done(reminder_id):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("UPDATE one_time SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

def get_user_reminders(chat_id):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    c.execute("SELECT id, text, remind_time FROM one_time WHERE chat_id = ? AND done = 0 ORDER BY remind_time", (chat_id,))
    one_time = c.fetchall()
    
    c.execute("SELECT id, text, pattern, time FROM recurring WHERE chat_id = ? AND active = 1", (chat_id,))
    recurring = c.fetchall()
    
    conn.close()
    return one_time, recurring

def delete_reminder(reminder_id, is_recurring=False):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    if is_recurring:
        c.execute("DELETE FROM recurring WHERE id = ?", (reminder_id,))
    else:
        c.execute("DELETE FROM one_time WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

# ========== Планировщик ==========
scheduler = AsyncIOScheduler()

async def check_reminders(app):
    """Проверяет и отправляет просроченные напоминания"""
    now_msk_time = now_msk()
    logging.info(f"🔍 Проверка напоминаний (МСК): {now_msk_time.strftime('%H:%M:%S')}")
    
    due = get_due_reminders()
    logging.info(f"📋 Найдено просроченных: {len(due)}")
    
    for reminder_id, chat_id, text in due:
        logging.info(f"📤 Отправляю напоминание {reminder_id} пользователю {chat_id}: {text}")
        try:
            # Создаём клавиатуру для откладывания
            keyboard = [
                [InlineKeyboardButton("⏰ +5 минут", callback_data=f"snooze_{reminder_id}_5")],
                [InlineKeyboardButton("⏰ +30 минут", callback_data=f"snooze_{reminder_id}_30")],
                [InlineKeyboardButton("⏰ +1 час", callback_data=f"snooze_{reminder_id}_60")],
                [InlineKeyboardButton("✅ Выполнено", callback_data=f"done_{reminder_id}")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await app.bot.send_message(
                chat_id=chat_id,
                text=f"⏰ *Напоминание!*\n\n{text}",
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
            logging.info(f"✅ Напоминание {reminder_id} отправлено")
        except Exception as e:
            logging.error(f"❌ Ошибка отправки {reminder_id}: {e}")

# ========== Команда /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📝 Добавить напоминание"],
        ["📋 Мои напоминания"],
        ["❌ Удалить напоминание"],
        ["❓ Помощь"],
        ["🕒 Время сервера"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⏰ *Бот-напоминалка*\n\n"
        "Я помогу тебе ничего не забыть!\n\n"
        "📌 *Все время указывай по МОСКВЕ*\n\n"
        "👇 Нажимай кнопки и я проведу тебя шаг за шагом.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

# ========== Время сервера ==========
async def show_server_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    utc_time = now_utc()
    msk_time = now_msk()
    
    await update.message.reply_text(
        f"🕒 *Время на сервере:*\n"
        f"• UTC: `{utc_time.strftime('%Y-%m-%d %H:%M:%S')}`\n"
        f"• МСК: `{msk_time.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        f"📌 Напоминания приходят по МСК",
        parse_mode="Markdown"
    )

# ========== Проверка БД ==========
async def check_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    c.execute("SELECT id, text, remind_time, done FROM one_time WHERE done = 0")
    one_time = c.fetchall()
    conn.close()
    
    if one_time:
        msg = "📋 *Неотправленные напоминания (в БД в UTC):*\n\n"
        for rid, text, rtime, done in one_time:
            dt_utc = datetime.fromisoformat(rtime)
            dt_msk = utc_to_msk(dt_utc)
            msg += f"• ID:{rid} | {dt_msk.strftime('%d.%m %H:%M')} МСК — {text[:30]}\n"
    else:
        msg = "📭 Нет неотправленных напоминаний"
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# ========== Добавление напоминания ==========
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Напиши *текст напоминания*:",
        parse_mode="Markdown"
    )
    return TEXT

async def add_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['reminder_text'] = update.message.text
    await update.message.reply_text(
        "⏰ Теперь напиши *время* (по МСК) в одном из форматов:\n\n"
        "• `18:30` — сегодня в 18:30 МСК\n"
        "• `завтра 10:00` — завтра в 10:00 МСК\n"
        "• `через 2 часа` — через 2 часа (МСК)\n"
        "• `20.03 15:00` — конкретная дата (МСК)",
        parse_mode="Markdown"
    )
    return TIME

async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    reminder_text = context.user_data.get('reminder_text', 'Напоминание')
    
    # Текущее время по МСК
    now = now_msk()
    remind_time = None
    
    # Формат: ЧЧ:ММ
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    
    if 'завтра' in text and time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        remind_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0) + timedelta(days=1)
    elif 'через' in text and 'час' in text:
        hours_match = re.search(r'через\s+(\d+)\s+час', text)
        if hours_match:
            hours = int(hours_match.group(1))
            remind_time = now + timedelta(hours=hours)
    elif time_match:
        hours = int(time_match.group(1))
        minutes = int(time_match.group(2))
        remind_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if remind_time < now:
            remind_time += timedelta(days=1)
    
    # Формат: дата (например 20.03 15:00)
    date_match = re.search(r'(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})', text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        hours = int(date_match.group(3))
        minutes = int(date_match.group(4))
        year = now.year
        try:
            remind_time = datetime(year, month, day, hours, minutes)
            if remind_time < now:
                remind_time = remind_time.replace(year=year + 1)
        except:
            pass
    
    if remind_time:
        # Конвертируем в UTC для сохранения
        remind_time_utc = msk_to_utc(remind_time)
        reminder_id = add_one_time(chat_id, reminder_text, remind_time_utc)
        
        await update.message.reply_text(
            f"✅ *Готово!*\n\n"
            f"📝 {reminder_text}\n"
            f"⏰ {remind_time.strftime('%d.%m.%Y в %H:%M')} (МСК)\n\n"
            f"💡 Напоминание придет в указанное время",
            parse_mode="Markdown"
        )
        logging.info(f"✅ Сохранено напоминание #{reminder_id}: {reminder_text} на {remind_time} МСК ({remind_time_utc} UTC)")
    else:
        await update.message.reply_text("❌ Не понял время. Попробуй ещё раз.")
        return TIME
    
    return ConversationHandler.END

# ========== Показать список ==========
async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    one_time, recurring = get_user_reminders(chat_id)
    
    msg = "📋 *Твои напоминания (по МСК):*\n\n"
    
    if one_time:
        msg += "*📅 Одноразовые:*\n"
        for rid, text, rtime in one_time:
            dt_utc = datetime.fromisoformat(rtime)
            dt_msk = utc_to_msk(dt_utc)
            msg += f"• {dt_msk.strftime('%d.%m %H:%M')} МСК — {text}\n"
        msg += "\n"
    
    if recurring:
        msg += "*🔄 Повторяющиеся:*\n"
        for rid, text, pattern, rtime in recurring:
            msg += f"• {pattern} в {rtime} — {text}\n"
    
    if not one_time and not recurring:
        msg = "📭 У тебя нет активных напоминаний."
    
    await update.message.reply_text(msg, parse_mode="Markdown")

# ========== Удаление ==========
async def delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    one_time, recurring = get_user_reminders(chat_id)
    
    if not one_time and not recurring:
        await update.message.reply_text("📭 У тебя нет активных напоминаний.")
        return ConversationHandler.END
    
    context.user_data['delete_one_time'] = one_time
    context.user_data['delete_recurring'] = recurring
    
    msg = "🗑 *Выбери номер для удаления:*\n\n"
    
    idx = 1
    for rid, text, rtime in one_time:
        dt_utc = datetime.fromisoformat(rtime)
        dt_msk = utc_to_msk(dt_utc)
        msg += f"{idx}. 📅 {dt_msk.strftime('%d.%m %H:%M')} МСК — {text}\n"
        idx += 1
    
    for rid, text, pattern, rtime in recurring:
        msg += f"{idx}. 🔄 {pattern} в {rtime} — {text}\n"
        idx += 1
    
    msg += "\n❌ Отправь *0* для отмены"
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    return 0

async def delete_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "0":
        await update.message.reply_text("❌ Удаление отменено.")
        return ConversationHandler.END
    
    try:
        num = int(text) - 1
        one_time = context.user_data.get('delete_one_time', [])
        recurring = context.user_data.get('delete_recurring', [])
        
        if num < len(one_time):
            reminder_id = one_time[num][0]
            delete_reminder(reminder_id, is_recurring=False)
            await update.message.reply_text("✅ Напоминание удалено.")
        elif num < len(one_time) + len(recurring):
            rec_idx = num - len(one_time)
            reminder_id = recurring[rec_idx][0]
            delete_reminder(reminder_id, is_recurring=True)
            await update.message.reply_text("✅ Повторяющееся напоминание удалено.")
        else:
            await update.message.reply_text("❌ Неверный номер.")
    except ValueError:
        await update.message.reply_text("❌ Введи число.")
    
    return ConversationHandler.END

# ========== Обработка кнопок ==========
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "📝 Добавить напоминание":
        await add_start(update, context)
        return TEXT
    elif text == "📋 Мои напоминания":
        await list_reminders(update, context)
        return ConversationHandler.END
    elif text == "❌ Удалить напоминание":
        return await delete_start(update, context)
    elif text == "❓ Помощь":
        await help_command(update, context)
        return ConversationHandler.END
    elif text == "🕒 Время сервера":
        await show_server_time(update, context)
        return ConversationHandler.END
    else:
        await update.message.reply_text("❓ Используй кнопки меню 👇")
        return ConversationHandler.END

# ========== Обработка колбэков ==========
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('snooze_'):
        _, reminder_id, minutes = data.split('_')
        minutes = int(minutes)
        
        # Новое время по МСК, потом конвертируем в UTC
        new_time_msk = now_msk() + timedelta(minutes=minutes)
        new_time_utc = msk_to_utc(new_time_msk)
        
        text = query.message.text.replace("⏰ *Напоминание!*\n\n", "")
        
        add_one_time(query.message.chat.id, f"[Отложено] {text}", new_time_utc)
        
        await query.edit_message_text(
            f"⏰ Напоминание отложено на {minutes} минут.\n"
            f"Новое время: {new_time_msk.strftime('%H:%M')} (МСК)"
        )
    
    elif data.startswith('done_'):
        _, reminder_id = data.split('_')
        mark_done(int(reminder_id))
        await query.edit_message_text("✅ Задача выполнена!")

# ========== Помощь ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Как пользоваться ботом:*\n\n"
        "1️⃣ *Добавить напоминание*\n"
        "   Нажми кнопку → введи текст → введи время (по МСК)\n\n"
        "2️⃣ *Форматы времени (МСК)*\n"
        "   • `18:30` — сегодня\n"
        "   • `завтра 10:00`\n"
        "   • `через 2 часа`\n"
        "   • `20.03 15:00`\n\n"
        "3️⃣ *Мои напоминания*\n"
        "   Посмотреть все активные\n\n"
        "4️⃣ *Удалить*\n"
        "   Выбрать по номеру\n\n"
        "5️⃣ *Отложить*\n"
        "   После напоминания нажми кнопку отложить",
        parse_mode="Markdown"
    )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

# ========== Запуск ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Диалог добавления
    conv_add = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📝 Добавить напоминание$'), add_start)],
        states={
            TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_text)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Диалог удаления
    conv_delete = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^❌ Удалить напоминание$'), delete_start)],
        states={
            0: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_choose)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # Обработчики
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("time", show_server_time))
    app.add_handler(CommandHandler("checkdb", check_db))
    app.add_handler(conv_add)
    app.add_handler(conv_delete)
    
    # Обработчик кнопок
    app.add_handler(MessageHandler(
        filters.Regex('^(📝 Добавить напоминание|📋 Мои напоминания|❌ Удалить напоминание|❓ Помощь|🕒 Время сервера)$'), 
        handle_buttons
    ))
    
    # Обработчик колбэков
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    # Планировщик
    scheduler.start()
    
    # Проверка каждые 30 секунд
    scheduler.add_job(
        check_reminders,
        trigger=IntervalTrigger(seconds=30),
        args=[app],
        id='check_reminders'
    )
    
    logging.info("🤖 Бот-напоминалка (МСК) запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
