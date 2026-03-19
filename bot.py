import os
import logging
import requests
import pandas as pd
import matplotlib.pyplot as plt
import mplfinance as mpf
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ.get("TOKEN")
ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY")

if not TOKEN:
    raise Exception("TOKEN не найден!")
if not ALPHA_VANTAGE_KEY:
    raise Exception("ALPHA_VANTAGE_KEY не найден!")

# ========== Функции для работы с Alpha Vantage ==========

def get_quote(ticker):
    """Получить текущую цену и объём"""
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'GLOBAL_QUOTE',
            'symbol': ticker,
            'apikey': ALPHA_VANTAGE_KEY
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'Global Quote' in data and data['Global Quote']:
            quote = data['Global Quote']
            return {
                'price': float(quote.get('05. price', 0)),
                'change': float(quote.get('09. change', 0)),
                'change_percent': float(quote.get('10. change percent', '0%').replace('%', '')),
                'volume': int(quote.get('06. volume', 0))
            }
        return None
    except Exception as e:
        logging.error(f"Alpha Vantage quote error: {e}")
        return None

def get_historical(ticker, outputsize='compact'):
    """Получить исторические данные (до 100 дней)"""
    try:
        url = "https://www.alphavantage.co/query"
        params = {
            'function': 'TIME_SERIES_DAILY',
            'symbol': ticker,
            'outputsize': outputsize,
            'apikey': ALPHA_VANTAGE_KEY
        }
        response = requests.get(url, params=params)
        data = response.json()
        
        if 'Time Series (Daily)' in data:
            df = pd.DataFrame.from_dict(data['Time Series (Daily)'], orient='index')
            df = df.astype(float)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']
            return df
        return None
    except Exception as e:
        logging.error(f"Alpha Vantage historical error: {e}")
        return None

# ========== Команда /start ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["💰 Цена", "📊 График"],
        ["📉 RSI", "📈 Сигналы"],
        ["ℹ️ О боте", "❓ Помощь"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📈 *Биржевой аналитик (Alpha Vantage)*\n\n"
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
        "/chart AAPL - график цены\n"
        "/rsi AAPL - RSI индикатор с графиком\n"
        "/signal AAPL - торговые сигналы\n"
        "/help - это меню\n\n"
        "Примеры тикеров:\n"
        "• Акции: AAPL, TSLA, MSFT\n"
        "• Крипта: BTC, ETH\n"
        "• Валюты: EUR, RUB\n"
        "• Индексы: SPX, DJI\n\n"
        "⚠️ Бесплатный тариф: 5 запросов в минуту",
        parse_mode="Markdown"
    )

# ========== Команда /price ==========
async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /price AAPL")
        return
    
    ticker = context.args[0].upper()
    data = get_quote(ticker)
    
    if data:
        arrow = "🟢" if data['change'] > 0 else "🔴" if data['change'] < 0 else "⚪"
        await update.message.reply_text(
            f"{arrow} *{ticker}*\n\n"
            f"💰 Цена: ${data['price']:.2f}\n"
            f"📊 Изменение: {data['change']:+.2f} ({data['change_percent']:+.2f}%)\n"
            f"📦 Объём: {data['volume']:,}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Тикер {ticker} не найден или превышен лимит запросов.\n"
            f"Попробуй через минуту."
        )

# ========== Команда /chart ==========
async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Укажи тикер, например: /chart AAPL")
        return
    
    ticker = context.args[0].upper()
    df = get_historical(ticker)
    
    if df is None or df.empty:
        await update.message.reply_text(f"❌ Не удалось получить данные для {ticker}")
        return
    
    # Берём последние 30 дней для графика
    df = df.tail(30)
    
    # Создаём свечной график
    mc = mpf.make_marketcolors(up='g', down='r', wick='inherit', volume='in')
    s = mpf.make_mpf_style(marketcolors=mc)
    
    # Добавляем скользящие средние
    apds = [
        mpf.make_addplot(df['Close'].rolling(window=20).mean(), color='blue', width=0.8, label='MA20'),
        mpf.make_addplot(df['Close'].rolling(window=50).mean(), color='orange', width=0.8, label='MA50')
    ]
    
    # Сохраняем график
    fig, axes = mpf.plot(
        df, 
        type='candle',
        style=s,
        volume=True,
        addplot=apds,
        title=f"{ticker} - последние 30 дней",
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
    df = get_historical(ticker, outputsize='full')
    
    if df is None or df.empty:
        await update.message.reply_text(f"❌ Не удалось получить данные для {ticker}")
        return
    
    # Берём последние 60 дней для RSI
    df = df.tail(60)
    
    # Рассчитываем RSI
    rsi_indicator = RSIIndicator(df['Close'], window=14)
    rsi = rsi_indicator.rsi()
    current_rsi = rsi.iloc[-1]
    
    # Создаём график RSI
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [2, 1]})
    
    # Цена
    ax1.plot(df.index, df['Close'], label='Цена', color='black')
    ax1.set_title(f'{ticker} - Цена и RSI')
    ax1.legend()
    ax1.grid(True)
    
    # RSI
    ax2.plot(df.index, rsi, label='RSI', color='purple')
    ax2.axhline(y=70, color='r', linestyle='--', alpha=0.5, label='Перекупленность (70)')
    ax2.axhline(y=30, color='g', linestyle='--', alpha=0.5, label='Перепроданность (30)')
    ax2.fill_between(df.index, 30, 70, alpha=0.1, color='gray')
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
    df = get_historical(ticker, outputsize='full')
    
    if df is None or df.empty:
        await update.message.reply_text(f"❌ Не удалось получить данные для {ticker}")
        return
    
    # Индикаторы
    rsi = RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
    macd = MACD(df['Close']).macd().iloc[-1]
    macd_signal = MACD(df['Close']).macd_signal().iloc[-1]
    ma20 = SMAIndicator(df['Close'], window=20).sma_indicator().iloc[-1]
    ma50 = SMAIndicator(df['Close'], window=50).sma_indicator().iloc[-1]
    current = df['Close'].iloc[-1]
    
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
    avg_volume = df['Volume'].mean()
    last_volume = df['Volume'].iloc[-1]
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
        await update.message.reply_text("📝 Напиши: /chart AAPL")
    elif text == "📉 RSI":
        await update.message.reply_text("📝 Напиши: /rsi AAPL")
    elif text == "📈 Сигналы":
        await update.message.reply_text("📝 Напиши: /signal AAPL")
    elif text == "ℹ️ О боте":
        await update.message.reply_text(
            "🤖 *Биржевой аналитик (Alpha Vantage)*\n\n"
            "Версия: 2.0\n"
            "Данные: Alpha Vantage\n"
            "Технический анализ: RSI, MACD, скользящие средние\n"
            "Лимит: 5 запросов в минуту\n\n"
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
    
    print("🤖 Биржевой бот (Alpha Vantage) запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
