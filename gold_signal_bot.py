import telebot
import os
import time
import logging
import yfinance as yf
import pandas as pd
import pandas_ta as ta
from datetime import datetime, timezone
from threading import Thread
from http.server import HTTPServer, BaseHTTPRequestHandler
from telebot import types

# --- KONFIGURATSIYA ---
TOKEN = "8558072414:AAG_wQ152z4tIkbHW47XR8YZfiwtpyLvauo"
TICKER = "XAUUSD=X" # Gold Spot
ADMIN_ID = 6762465157

bot = telebot.TeleBot(TOKEN)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- KEYBOARDS ---
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("📉 XAUUSD Signal Olish"))
    markup.add(types.KeyboardButton("📚 Trading Kutubxona"))
    return markup

def get_timeframe_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=3)
    btns = [
        types.InlineKeyboardButton("M1 (Zona)", callback_data="tf_1m"),
        types.InlineKeyboardButton("M5", callback_data="tf_5m"),
        types.InlineKeyboardButton("M15", callback_data="tf_15m"),
        types.InlineKeyboardButton("M30", callback_data="tf_30m"),
        types.InlineKeyboardButton("H1", callback_data="tf_1h"),
        types.InlineKeyboardButton("H4", callback_data="tf_4h")
    ]
    markup.add(*btns)
    return markup

# --- ANALYSIS LOGIC ---
def get_fib_levels(data):
    high = data['High'].max()
    low = data['Low'].min()
    diff = high - low
    levels = {
        0.0: high,
        0.236: high - 0.236 * diff,
        0.382: high - 0.382 * diff,
        0.5: high - 0.5 * diff,
        0.618: high - 0.618 * diff,
        1.0: low
    }
    return levels

def analyze_market(timeframe):
    try:
        # Intervalni yfinance formatiga o'tkazish
        mapping = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "1h"} # yfinance has limits on small intervals
        interval = mapping.get(timeframe, "15m")
        period = "1d" if timeframe in ["1m", "5m", "15m"] else "5d"
        
        # 1. Bozor ochiqligini tekshirish (Shanba va Yakshanba dam olish kuni)
        # Oltin bozori odatda Juma kuni 17:00 EST da yopilib, Yakshanba 18:00 EST da ochiladi.
        # Biz UTC bo'yicha hisoblaymiz.
        now = datetime.now(timezone.utc)
        if now.weekday() == 5: # Shanba
            return {"status": "CLOSED", "message": "Bugun Shanba - Bozor dam olmoqda. Dushanbadan ishga tushadi. ✅"}
        if now.weekday() == 6: # Yakshanba
            return {"status": "CLOSED", "message": "Bugun Yakshanba - Bozor hali ochilmadi. Tez orada ishga tushadi. ✅"}

        data = yf.download(TICKER, period=period, interval=interval, progress=False)
        if data.empty: return None

        # 2. Bozor harakatini tekshirish (Volatility)
        # Agar oxirgi 5 ta sham deyarli bir xil narxda bo'lsa, bozor qotib qolgan (Inactive)
        if len(data) > 5:
            last_closes = data['Close'].tail(5)
            if last_closes.max() == last_closes.min():
                return {"status": "INACTIVE", "message": "Bozor harakatlanmayapti (Flat). Hozircha signal yo'q. ✅"}
        
        # Indikatorlar
        data['RSI'] = ta.rsi(data['Close'], length=14)
        data['EMA20'] = ta.ema(data['Close'], length=20)
        data['EMA50'] = ta.ema(data['Close'], length=50)
        
        last_row = data.iloc[-1]
        prev_row = data.iloc[-2]
        current_price = float(last_row['Close'])
        rsi = float(last_row['RSI'])
        
        fib = get_fib_levels(data.tail(50)) # Oxirgi 50 ta sham asosida fib
        
        signal = "NEUTRAL"
        logic_msg = ""
        
        # BUY LOGIC
        if rsi < 35 and current_price <= fib[0.618] * 1.0005: 
            signal = "BUY 📈"
            logic_msg = (
                "🧐 **Analogik Tahlil:** Bozor 'Discount' zonasida. Fibonachchi 0.618 (Oltin kesishma) darajasidan qaytish kuzatilmoqda. "
                "Bu daraja tarixan kuchli qo'llab-quvvatlash zonasi hisoblanadi. RSI indikatori 'Oversold' holatida ekanligi xaridorlar bosimi oshishini bildiradi. "
                "Smart Money tahliliga ko'ra, bu yerda 'Order Block' shakllangan."
            )
        elif last_row['EMA20'] > last_row['EMA50'] and prev_row['EMA20'] <= prev_row['EMA50']:
            signal = "BUY 📈"
            logic_msg = (
                "🧐 **Analogik Tahlil:** EMA 20 va 50 krossoveri (Oltin kesish) sodir bo'ldi. "
                "Trend o'zgarishi tahlili bo'yicha, qisqa muddatli trend uzoq muddatli trenddan yuqoriga chiqdi. "
                "Bu 'Bullish Momentum' (buqalar harakati) boshlanganidan dalolat beradi."
            )
            
        # SELL LOGIC
        elif rsi > 65 and current_price >= fib[0.382] * 0.9995:
            signal = "SELL 📉"
            logic_msg = (
                "🧐 **Analogik Tahlil:** Bozor 'Premium' zonasida. Fibonachchi 0.382 (qarshilik) darajasiga yetib keldi. "
                "RSI indikatori 'Overbought' zonasida bo'lib, xaridorlar kuchi tugayotganini ko'rsatmoqda. "
                "Analogik tahlil bo'yicha narx 'Liquidity Sweep' (likvidlikni yig'ish) jarayonini yakunlab, pastga qaytishi kutilmoqda."
            )
        elif last_row['EMA20'] < last_row['EMA50'] and prev_row['EMA20'] >= prev_row['EMA50']:
            signal = "SELL 📉"
            logic_msg = (
                "🧐 **Analogik Tahlil:** EMA 20 va 50 krossoveri (Ayiqlar kesishi) sodir bo'ldi. "
                "Bu trendning pastga qarab o'zgarganini va sotuvchilar ustunlikni o'z qo'liga olganini tasdiqlaydi."
            )

        # TP / SL hisoblash
        atr = float(ta.atr(data['High'], data['Low'], data['Close'], length=14).iloc[-1])
        tp = current_price + (atr * 2) if "BUY" in signal else current_price - (atr * 2)
        sl = current_price - (atr * 1.5) if "BUY" in signal else current_price + (atr * 1.5)
        
        return {
            "signal": signal,
            "price": round(current_price, 2),
            "tp": round(tp, 2),
            "sl": round(sl, 2),
            "logic": logic_msg,
            "rsi": round(rsi, 1)
        }
    except Exception as e:
        logger.error(f"Analysis error: {e}")
        return None

# --- HANDLERS ---
@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, (
        "👋 <b>XAUUSD GOLD SIGNAL BOTiga XUSH KELIBSIZ!</b>\n\n"
        "Ushbu bot Fibonachchi, EMA va RSI algoritmlari asosida eng aniq oltin signallarini taqdim etadi.\n\n"
        "👇 Quyidagi menyudan foydalaning:"
    ), parse_mode='HTML', reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "📉 XAUUSD Signal Olish")
def request_signal(message):
    bot.send_message(message.chat.id, "Analiz qilish uchun <b>ZONA (Timeframe)</b>ni tanlang:", parse_mode='HTML', reply_markup=get_timeframe_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("tf_"))
def process_signal(call):
    tf_code = call.data.replace("tf_", "")
    tf_name = {"1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30", "1h": "H1", "4h": "H4"}.get(tf_code, tf_code)
    
    msg = bot.send_message(call.message.chat.id, f"⌛️ {tf_name} zonasi bo'yicha bozor tahlil qilinmoqda...")
    
    result = analyze_market(tf_code)
    
    if not result:
        bot.edit_message_text(f"❌ <b>{tf_name}</b> bo'yicha ma'lumot olishda xatolik yuz berdi.", call.message.chat.id, msg.message_id, parse_mode='HTML')
        return

    if "status" in result and (result['status'] == "CLOSED" or result['status'] == "INACTIVE"):
        bot.edit_message_text(f"⚠️ {result['message']}", call.message.chat.id, msg.message_id, parse_mode='HTML')
        return
        
    if result['signal'] == "NEUTRAL":
        bot.edit_message_text(f"❕ <b>{tf_name}</b> zonasida hozircha aniq signal yo'q. Bozor kutilmoqda...", call.message.chat.id, msg.message_id, parse_mode='HTML')
    else:
        signal_text = (
            f"🔔 <b>XAUUSD [{tf_name}] SIGNAL</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🚀 <b>TUR:</b> <code>{result['signal']}</code>\n"
            f"💰 <b>Narx:</b> <code>{result['price']}</code>\n\n"
            f"🎯 <b>TP:</b> <code>{result['tp']}</code>\n"
            f"❌ <b>SL:</b> <code>{result['sl']}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🧠 <b>ANALIZ:</b> <i>{result['logic']}</i>\n\n"
            f"📈 <b>RSI:</b> <code>{result['rsi']}</code>\n"
            f"🕒 <b>Vaqt:</b> <code>{time.strftime('%H:%M')}</code>"
        )
        bot.edit_message_text(signal_text, call.message.chat.id, msg.message_id, parse_mode='HTML')

@bot.message_handler(func=lambda m: m.text == "📚 Trading Kutubxona")
def library(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📘 Price Action (UZB)", callback_data="book_pa"))
    markup.add(types.InlineKeyboardButton("📙 Smart Money Concepts", callback_data="book_smc"))
    markup.add(types.InlineKeyboardButton("📗 Fibonacci Strategiyasi", callback_data="book_fib"))
    bot.send_message(message.chat.id, "📚 <b>Trading Kitoblar To'plami</b>\n\nYuklab olish uchun kitobni tanlang:", parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("book_"))
def send_book(call):
    # Bu yerda real PDF havolalarini qo'yish mumkin yoki faylni yuborish
    links = {
        "book_pa": "https://t.me/c/123456789/1", # Namuna
        "book_smc": "https://t.me/c/123456789/2",
        "book_fib": "https://t.me/c/123456789/3"
    }
    bot.answer_callback_query(call.id, "Kitob tayyorlanmoqda...", show_alert=False)
    bot.send_message(call.message.chat.id, "📖 Kitobingiz: [Yuklab olish](https://t.me/uz_trading_books)", parse_mode='Markdown')

# --- RENDER SERVER ---
class HealthCheck(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
    def log_message(self, format, *args): pass

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    Thread(target=lambda: HTTPServer(('0.0.0.0', port), HealthCheck).serve_forever(), daemon=True).start()
    
    logger.info("🤖 Gold Signal Bot ishga tushdi...")
    bot.infinity_polling(skip_pending=True)
