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
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# Состояния для диалогов
TEXT, TIME, RECURRING = range(3)

# ========== База данных ==========
def init_db():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    # Одноразовые напоминания
    c.execute('''CREATE TABLE IF NOT EXISTS one_time
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  text TEXT,
                  remind_time TIMESTAMP,
                  done BOOLEAN DEFAULT 0)''')
    
    # Повторяющиеся напоминания
    c.execute('''CREATE TABLE IF NOT EXISTS recurring
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  chat_id INTEGER,
                  text TEXT,
                  pattern TEXT,  -- daily, weekly, monthly
                  time TEXT,      -- время в формате HH:MM
                  day_of_week INTEGER,  -- 0-6 для weekly
                  day_of_month INTEGER, -- 1-31 для monthly
                  active BOOLEAN DEFAULT 1)''')
    
    conn.commit()
    conn.close()

init_db()

# ========== Работа с БД ==========
def add_one_time(chat_id, text, remind_time):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("INSERT INTO one_time (chat_id, text, remind_time) VALUES (?, ?, ?)",
              (chat_id, text, remind_time))
    reminder_id = c.lastrowid
    conn.commit()
    conn.close()
    return reminder_id

def get_due_reminders():
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    now = datetime.now()
    c.execute("SELECT id, chat_id, text FROM one_time WHERE remind_time <= ? AND done = 0", (now,))
    due = c.fetchall()
    conn.close()
    return due

def mark_done(reminder_id):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("UPDATE one_time SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

def add_recurring(chat_id, text, pattern, time_str, day_of_week=None, day_of_month=None):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    c.execute("""INSERT INTO recurring 
                 (chat_id, text, pattern, time, day_of_week, day_of_month) 
                 VALUES (?, ?, ?, ?, ?, ?)""",
              (chat_id, text, pattern, time_str, day_of_week, day_of_month))
    reminder_id = c.lastrowid
    conn.commit()
    conn.close()
    return reminder_id

def get_user_reminders(chat_id):
    conn = sqlite3.connect('reminders.db')
    c = conn.cursor()
    
    # Одноразовые
    c.execute("SELECT id, text, remind_time FROM one_time WHERE chat_id = ? AND done = 0 ORDER BY remind_time", (chat_id,))
    one_time = c.fetchall()
    
    # Повторяющиеся
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
    due = get_due_reminders()
    for reminder_id, chat_id, text in due:
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
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")

# ========== Inline-календарь ==========
def create_calendar(year=None, month=None):
    """Создаёт инлайн-клавиатуру календаря"""
    now = datetime.now()
    year = year or now.year
    month = month or now.month
    
    keyboard = []
    
    # Заголовок с месяцем и годом
    header = [InlineKeyboardButton(f"{year} - {month:02d}", callback_data="ignore")]
    keyboard.append(header)
    
    # Дни недели
    week_days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    keyboard.append([InlineKeyboardButton(day, callback_data="ignore") for day in week_days])
    
    # Пустые ячейки перед первым днём месяца
    first_day = datetime(year, month, 1).weekday()
    empty_cells = first_day
    row = []
    for _ in range(empty_cells):
        row.append(InlineKeyboardButton(" ", callback_data="ignore"))
    
    # Дни месяца
    if month == 12:
        next_month = datetime(year+1, 1, 1)
    else:
        next_month = datetime(year, month+1, 1)
    
    last_day = (next_month - timedelta(days=1)).day
    
    for day in range(1, last_day + 1):
        if len(row) == 7:
            keyboard.append(row)
            row = []
        row.append(InlineKeyboardButton(str(day), callback_data=f"calendar_{year}-{month:02d}-{day:02d}"))
    
    if row:
        keyboard.append(row)
    
    # Навигация
    nav_row = []
    if month > 1:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"prev_{year}_{month-1}"))
    else:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"prev_{year-1}_{12}"))
    
    nav_row.append(InlineKeyboardButton("✅ Выбрать", callback_data="ignore"))
    
    if month < 12:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"next_{year}_{month+1}"))
    else:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"next_{year+1}_{1}"))
    
    keyboard.append(nav_row)
    
    return InlineKeyboardMarkup(keyboard)

# ========== Команда /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📝 Добавить напоминание"],
        ["🔄 Повторяющееся"],
        ["📋 Мои напоминания"],
        ["❌ Удалить напоминание"],
        ["❓ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⏰ *Бот-напоминалка*\n\n"
        "✨ Новые возможности:\n"
        "• 🔁 Повторяющиеся напоминания\n"
        "• ⏰ Кнопка «Отложить»\n"
        "• 💾 База данных (ничего не пропадает)\n"
        "• 📅 Календарь для выбора даты",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

# ========== Добавление напоминания ==========
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Выбрать дату", callback_data="show_calendar")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📝 Напиши *текст напоминания*:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    context.user_data['adding_type'] = 'one_time'
    return TEXT

async def add_recurring_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 Напиши *текст повторяющегося напоминания*:",
        parse_mode="Markdown"
    )
    context.user_data['adding_type'] = 'recurring'
    return TEXT

async def add_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['reminder_text'] = update.message.text
    
    if context.user_data.get('adding_type') == 'recurring':
        await update.message.reply_text(
            "🔄 *Выбери периодичность:*\n\n"
            "• `каждый день в 09:00`\n"
            "• `каждый понедельник в 10:00`\n"
            "• `каждое 15 число в 18:00`\n\n"
            "Или введи вручную:",
            parse_mode="Markdown"
        )
        return RECURRING
    else:
        await update.message.reply_text(
            "⏰ Выбери *дату и время* через календарь 👇\n"
            "Или напиши в формате: 18:30, завтра 10:00, 25.03 15:00",
            parse_mode="Markdown"
        )
        return TIME

async def add_recurring_parse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    reminder_text = context.user_data.get('reminder_text', 'Напоминание')
    
    # Парсим повторяющееся напоминание
    time_match = re.search(r'(\d{1,2}):(\d{2})', text)
    
    if not time_match:
        await update.message.reply_text("❌ Не могу найти время. Пример: каждый день в 09:00")
        return RECURRING
    
    hours = int(time_match.group(1))
    minutes = int(time_match.group(2))
    time_str = f"{hours:02d}:{minutes:02d}"
    
    if 'каждый день' in text:
        pattern = 'daily'
        add_recurring(chat_id, reminder_text, pattern, time_str)
        await update.message.reply_text(f"✅ Добавлено: каждый день в {time_str} — {reminder_text}")
        
    elif 'понедельник' in text:
        pattern = 'weekly'
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=0)
        await update.message.reply_text(f"✅ Добавлено: каждый понедельник в {time_str} — {reminder_text}")
    elif 'вторник' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=1)
    elif 'среда' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=2)
    elif 'четверг' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=3)
    elif 'пятница' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=4)
    elif 'суббота' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=5)
    elif 'воскресенье' in text:
        add_recurring(chat_id, reminder_text, pattern, time_str, day_of_week=6)
        
    elif 'число' in text:
        day_match = re.search(r'(\d{1,2})\s+число', text)
        if day_match:
            day = int(day_match.group(1))
            pattern = 'monthly'
            add_recurring(chat_id, reminder_text, pattern, time_str, day_of_month=day)
            await update.message.reply_text(f"✅ Добавлено: каждого {day} числа в {time_str} — {reminder_text}")
        else:
            await update.message.reply_text("❌ Не могу найти число. Пример: каждое 15 число в 18:00")
            return RECURRING
    else:
        await update.message.reply_text("❌ Не могу определить периодичность")
        return RECURRING
    
    return ConversationHandler.END

async def add_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.lower()
    reminder_text = context.user_data.get('reminder_text', 'Напоминание')
    
    now = datetime.now()
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
    
    date_match = re.search(r'(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})', text)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        hours = int(date_match.group(3))
        minutes = int(date_match.group(4))
        year = now.year
        remind_time = datetime(year, month, day, hours, minutes)
        if remind_time < now:
            remind_time = remind_time.replace(year=year + 1)
    
    if remind_time:
        reminder_id = add_one_time(chat_id, reminder_text, remind_time)
        
        # Добавляем в планировщик
        scheduler.add_job(
            check_reminders,
            trigger=DateTrigger(run_date=remind_time),
            args=[context.application],
            id=f"reminder_{reminder_id}"
        )
        
        await update.message.reply_text(
            f"✅ *Готово!*\n\n"
            f"📝 {reminder_text}\n"
            f"⏰ {remind_time.strftime('%d.%m.%Y в %H:%M')}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ Не понял время. Попробуй ещё раз.")
        return TIME
    
    return ConversationHandler.END

# ========== Обработка календаря ==========
async def calendar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('calendar_'):
        date_str = data.replace('calendar_', '')
        selected_date = datetime.strptime(date_str, '%Y-%m-%d')
        context.user_data['selected_date'] = selected_date
        
        # Запрашиваем время
        await query.edit_message_text(
            f"📅 Выбрана дата: {selected_date.strftime('%d.%m.%Y')}\n"
            f"⏰ Теперь напиши время (например, 18:30):"
        )
        return TIME
    
    elif data.startswith('prev_'):
        _, year, month = data.split('_')
        calendar = create_calendar(int(year), int(month))
        await query.edit_message_text("📅 Выбери дату:", reply_markup=calendar)
    
    elif data.startswith('next_'):
        _, year, month = data.split('_')
        calendar = create_calendar(int(year), int(month))
        await query.edit_message_text("📅 Выбери дату:", reply_markup=calendar)
    
    elif data == 'show_calendar':
        calendar = create_calendar()
        await query.edit_message_text("📅 Выбери дату:", reply_markup=calendar)

# ========== Обработка кнопок откладывания ==========
async def snooze_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith('snooze_'):
        _, reminder_id, minutes = data.split('_')
        minutes = int(minutes)
        
        # Создаём новое напоминание через X минут
        new_time = datetime.now() + timedelta(minutes=minutes)
        add_one_time(query.message.chat.id, f"[Отложено] {query.message.text}", new_time)
        
        await query.edit_message_text(
            f"⏰ Напоминание отложено на {minutes} минут.\n"
            f"Новое время: {new_time.strftime('%H:%M')}"
        )
    
    elif data.startswith('done_'):
        _, reminder_id = data.split('_')
        mark_done(int(reminder_id))
        await query.edit_message_text("✅ Задача выполнена!")

# ========== Показать список ==========
async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    one_time, recurring = get_user_reminders(chat_id)
    
    msg = "📋 *Твои напоминания:*\n\n"
    
    if one_time:
        msg += "*📅 Одноразовые:*\n"
        for rid, text, rtime in one_time:
            msg += f"• {rtime[:16]} — {text}\n"
        msg += "\n"
    
    if recurring:
        msg += "*🔄 Повторяющиеся:*\n"
        for rid, text, pattern, rtime in recurring:
            if pattern == 'daily':
                msg += f"• Каждый день в {rtime} — {text}\n"
            elif pattern == 'weekly':
                msg += f"• Каждую неделю в {rtime} — {text}\n"
            elif pattern == 'monthly':
                msg += f"• Каждый месяц в {rtime} — {text}\n"
        msg += "\n"
    
    if not one_time and not recurring:
        msg = "📭 У тебя нет активных напоминаний."
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    return ConversationHandler.END

# ========== Удаление напоминания ==========
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
        msg += f"{idx}. 📅 {rtime[:16]} — {text}\n"
        idx += 1
    
    for rid, text, pattern, rtime in recurring:
        if pattern == 'daily':
            msg += f"{idx}. 🔄 Каждый день в {rtime} — {text}\n"
        elif pattern == 'weekly':
            msg += f"{idx}. 🔄 Каждую неделю в {rtime} — {text}\n"
        elif pattern == 'monthly':
            msg += f"{idx}. 🔄 Каждый месяц в {rtime} — {text}\n"
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
            # Удаляем одноразовое
            reminder_id = one_time[num][0]
            delete_reminder(reminder_id, is_recurring=False)
            await update.message.reply_text("✅ Напоминание удалено.")
        elif num < len(one_time) + len(recurring):
            # Удаляем повторяющееся
            rec_idx = num - len(one_time)
            reminder_id = recurring[rec_idx][0]
            delete_reminder(reminder_id, is_recurring=True)
            await update.message.reply_text("✅ Повторяющееся напоминание удалено.")
        else:
            await update.message.reply_text("❌ Неверный номер.")
    except ValueError:
        await update.message.reply_text("❌ Введи число.")
    
    return ConversationHandler.END

# ========== Помощь ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Как пользоваться:*\n\n"
        "1️⃣ *Обычное напоминание*\n"
        "   Нажми «Добавить напоминание» → введи текст → выбери время\n\n"
        "2️⃣ *Повторяющееся*\n"
        "   Нажми «Повторяющееся» → напиши текст → укажи периодичность\n\n"
        "3️⃣ *После напоминания*\n"
        "   Можно отложить на 5/30/60 минут или отметить выполненным\n\n"
        "4️⃣ *Календарь*\n"
        "   При выборе даты можно нажать кнопку и выбрать день",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Действие отменено.")
    return ConversationHandler.END

# ========== Запуск ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Диалоги
    conv_add = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^📝 Добавить напоминание$'), add_start)],
        states={
            TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_text)],
            TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_time)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    conv_recurring = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🔄 Повторяющееся$'), add_recurring_start)],
        states={
            TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_text)],
            RECURRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_recurring_parse)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
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
    app.add_handler(MessageHandler(filters.Regex('^📋 Мои напоминания$'), list_reminders))
    app.add_handler(conv_add)
    app.add_handler(conv_recurring)
    app.add_handler(conv_delete)
    
    # Callback-запросы
    app.add_handler(CallbackQueryHandler(calendar_callback, pattern='^(calendar_|prev_|next_|show_calendar)'))
    app.add_handler(CallbackQueryHandler(snooze_callback, pattern='^(snooze_|done_)'))
    
    # Планировщик
    scheduler.start()
    
    # Проверяем просроченные напоминания каждые 30 секунд
    scheduler.add_job(
        check_reminders,
        trigger=IntervalTrigger(seconds=30),
        args=[app],
        id='check_reminders'
    )
    
    print("🤖 Бот с БД и календарём запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
