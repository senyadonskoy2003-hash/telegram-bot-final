import os
import logging
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")

if not TOKEN:
    raise Exception("TOKEN не найден!")

# ========== Функция получения данных ==========
def get_stock_data(ticker, period="1mo"):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        return hist, stock.info
    except:
        return None, None

# ========== Команда /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["💰 Цена", "📊 График"],
        ["📉 RSI", "📈 Сигналы"],
        ["ℹ️ О боте", "❓ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📈 *Биржевой аналитик*\n\n"
        "Я помогу анализировать акции, криптовалюты и индексы.\n"
        "Выбери действие на клавиатуре или напиши команду.",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

# ========== Команда /help ==========
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *Доступные команды:*\n\n"
        "/price AAPL - цена, объём, изменение\n"
        "/chart AAPL 1mo - график (1d, 5d, 1mo, 3mo, 1y)\n"
        "/rsi AAPL - RSI индикатор с графиком\n"
        "/signal AAPL - торговые сигналы\n"
        "/help - это меню\n\n"
        "Примеры тикеров:\n"
        "• Акции: AAPL, TSLA, MSFT\n"
        "• Крипта: BTC-USD, ETH-USD\n"
        "• Валюты: EURUSD=X\n"
        "• Индексы: ^GSPC (S&P 500)",
        parse_mode="Markdown"
    )

# ========== Команда /price ==========
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /price AAPL")
        return
    
    ticker = context.args[0].upper()
    hist, info = get_stock_data(ticker, "5d")
    
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Тикер {ticker} не найден")
        return
    
    current = hist['Close'].iloc[-1]
    prev_close = hist['Close'].iloc[-2] if len(hist) > 1 else current
    change = current - prev_close
    change_percent = (change / prev_close) * 100 if prev_close else 0
    
    volume = hist['Volume'].iloc[-1]
    avg_volume = hist['Volume'].mean()
    
    arrow = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
    
    await update.message.reply_text(
        f"{arrow} *{ticker}*\n\n"
        f"💰 Цена: ${current:.2f}\n"
        f"📊 Изменение: {change:+.2f} ({change_percent:+.2f}%)\n"
        f"📦 Объём: {volume:,.0f}\n"
        f"📊 Средний объём: {avg_volume:,.0f}\n\n"
        f"🏢 {info.get('longName', '')[:100]}",
        parse_mode="Markdown"
    )

# ========== Команда /chart ==========
async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /chart AAPL")
        return
    
    ticker = context.args[0].upper()
    period = context.args[1] if len(context.args) > 1 else "1mo"
    
    hist, _ = get_stock_data(ticker, period)
    
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Тикер {ticker} не найден")
        return
    
    # Создаём свечной график
    mc = mpf.make_marketcolors(up='g', down='r', wick='inherit', volume='in')
    s = mpf.make_mpf_style(marketcolors=mc)
    
    # Добавляем скользящие средние
    apds = [
        mpf.make_addplot(hist['Close'].rolling(window=20).mean(), color='blue', width=0.8, label='MA20'),
        mpf.make_addplot(hist['Close'].rolling(window=50).mean(), color='orange', width=0.8, label='MA50')
    ]
    
    # Сохраняем график
    fig, axes = mpf.plot(
        hist, 
        type='candle',
        style=s,
        volume=True,
        addplot=apds,
        title=f"{ticker} - {period}",
        returnfig=True,
        figsize=(12, 8)
    )
    
    plt.savefig('chart.png', bbox_inches='tight')
    plt.close()
    
    with open('chart.png', 'rb') as f:
        await update.message.reply_photo(f)
    
    os.remove('chart.png')

# ========== Команда /rsi ==========
async def rsi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /rsi AAPL")
        return
    
    ticker = context.args[0].upper()
    hist, _ = get_stock_data(ticker, "3mo")
    
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Тикер {ticker} не найден")
        return
    
    # Рассчитываем RSI
    rsi_indicator = RSIIndicator(hist['Close'], window=14)
    rsi = rsi_indicator.rsi()
    current_rsi = rsi.iloc[-1]
    
    # Создаём график RSI
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})
    
    # Цена
    ax1.plot(hist.index, hist['Close'], label='Цена', color='black')
    ax1.set_title(f'{ticker} - Цена и RSI')
    ax1.legend()
    ax1.grid(True)
    
    # RSI
    ax2.plot(hist.index, rsi, label='RSI', color='purple')
    ax2.axhline(y=70, color='r', linestyle='--', alpha=0.5, label='Перекупленность (70)')
    ax2.axhline(y=30, color='g', linestyle='--', alpha=0.5, label='Перепроданность (30)')
    ax2.fill_between(hist.index, 30, 70, alpha=0.1, color='gray')
    ax2.set_ylim(0, 100)
    ax2.legend()
    ax2.grid(True)
    
    plt.tight_layout()
    plt.savefig('rsi.png')
    plt.close()
    
    status = "🟢 Перепродан (возможен рост)" if current_rsi < 30 else "🔴 Перекуплен (возможна коррекция)" if current_rsi > 70 else "⚪ Нейтральная зона"
    
    with open('rsi.png', 'rb') as f:
        await update.message.reply_photo(
            f, 
            caption=f"*{ticker}* - RSI: {current_rsi:.1f}\n{status}",
            parse_mode="Markdown"
        )
    
    os.remove('rsi.png')

# ========== Команда /signal ==========
async def signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /signal AAPL")
        return
    
    ticker = context.args[0].upper()
    hist, _ = get_stock_data(ticker, "3mo")
    
    if hist is None or hist.empty:
        await update.message.reply_text(f"❌ Тикер {ticker} не найден")
        return
    
    # Индикаторы
    rsi = RSIIndicator(hist['Close'], window=14).rsi().iloc[-1]
    macd = MACD(hist['Close']).macd().iloc[-1]
    macd_signal = MACD(hist['Close']).macd_signal().iloc[-1]
    ma20 = SMAIndicator(hist['Close'], window=20).sma_indicator().iloc[-1]
    ma50 = SMAIndicator(hist['Close'], window=50).sma_indicator().iloc[-1]
    current = hist['Close'].iloc[-1]
    
    signals = []
    
    # RSI сигналы
    if rsi < 30:
        signals.append("🟢 RSI: перепроданность (сигнал к покупке)")
    elif rsi > 70:
        signals.append("🔴 RSI: перекупленность (сигнал к продаже)")
    else:
        signals.append("⚪ RSI: нейтрально")
    
    # MACD сигналы
    if macd > macd_signal:
        signals.append("🟢 MACD: бычий сигнал (выше сигнальной)")
    else:
        signals.append("🔴 MACD: медвежий сигнал (ниже сигнальной)")
    
    # Скользящие средние
    if current > ma20 and current > ma50:
        signals.append("🟢 Цена выше MA20 и MA50 (восходящий тренд)")
    elif current < ma20 and current < ma50:
        signals.append("🔴 Цена ниже MA20 и MA50 (нисходящий тренд)")
    else:
        signals.append("⚪ Смешанные сигналы по MA")
    
    # Объёмы
    avg_volume = hist['Volume'].mean()
    last_volume = hist['Volume'].iloc[-1]
    if last_volume > avg_volume * 1.5:
        signals.append(f"📊 Аномальный объём: {last_volume/avg_volume:.1f}x от среднего")
    
    signal_text = f"*{ticker} - Сигналы*\n\n"
    signal_text += "\n".join(signals)
    signal_text += f"\n\n💰 Текущая цена: ${current:.2f}"
    
    await update.message.reply_text(signal_text, parse_mode="Markdown")

# ========== Обработчик кнопок ==========
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "💰 Цена":
        await update.message.reply_text("📝 Напиши: /price AAPL (или любой другой тикер)")
    elif text == "📊 График":
        await update.message.reply_text("📝 Напиши: /chart AAPL (или /chart BTC-USD 3mo)")
    elif text == "📉 RSI":
        await update.message.reply_text("📝 Напиши: /rsi AAPL")
    elif text == "📈 Сигналы":
        await update.message.reply_text("📝 Напиши: /signal AAPL")
    elif text == "ℹ️ О боте":
        await update.message.reply_text(
            "🤖 *Биржевой аналитик*\n\n"
            "Версия: 1.0\n"
            "Данные: Yahoo Finance\n"
            "Технический анализ: RSI, MACD, скользящие средние\n\n"
            "⚠️ Данные не являются инвестиционной рекомендацией.",
            parse_mode="Markdown"
        )
    elif text == "❓ Помощь":
        await help_command(update, context)

# ========== Обработчик обычного текста ==========
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❓ Я понимаю только команды:\n"
        "/price AAPL\n"
        "/chart AAPL\n"
        "/rsi AAPL\n"
        "/signal AAPL\n\n"
        "Или используй кнопки внизу экрана 👇"
    )

# ========== Запуск бота ==========
def main():
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("chart", chart))
    app.add_handler(CommandHandler("rsi", rsi))
    app.add_handler(CommandHandler("signal", signal))
    
    # Обработчики кнопок
    app.add_handler(MessageHandler(filters.Regex('^(💰 Цена|📊 График|📉 RSI|📈 Сигналы|ℹ️ О боте|❓ Помощь)$'), handle_buttons))
    
    # Обработчик обычного текста
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 Биржевой бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
