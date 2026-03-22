import os
import re
import asyncio
import random
import logging
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest

# === 1. НАЛАШТУВАННЯ ===
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"
MONITOR_THREATS_USER = "hyevuy_dnepr"
DTEK_OFFICIAL = "dtek_ua"

API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

# === 2. КОНСТАНТИ ===
TXT_TREVOGA = "<b>⚠️❗️ УВАГА! ОГОЛОШЕНО ПОВІТРЯНУ ТРИВОГУ.</b>\n\n🏃 <b>ВСІМ ПРОЙТИ В УКРИТТЯ.</b>"
TXT_TREVOGA_STOP = "<b>✅ ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ.</b>"

FOOTER = """
____

⭐️ <a href="https://t.me/strum_dp">ПІДПИСАТИСЬ НА КАНАЛ</a>
❤️ <a href="https://send.monobank.ua/jar/9gBQ4LTLUa">ПІДТРИМАТИ СЕРВІС</a>

@strum_dp"""

STRICT_THREATS = ["ракета", "балістика", "пуск", "бпла", "шахед", "дрон", "тривога", "відбій", "загроза"]
MONTHS_UA = {1: "січня", 2: "лютого", 3: "березня", 4: "квітня", 5: "травня", 6: "червня", 7: "липня", 8: "серпня", 9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"}
IS_ALARM_ACTIVE = False 

# === 3. ФОРМАТУВАННЯ ТЕКСТУ ===
def clean_message(text):
    text = re.sub(r"(?i)контент.*@hydneprbot", "", text)
    text = re.sub(r"(?i).*@hydneprbot", "", text)
    for junk in ["надслати новину", "прислать новость", "підписатися", "👉"]:
        text = re.sub(f"(?i){re.escape(junk)}", "", text)
    return "\n".join([l.strip() for l in text.split('\n') if l.strip()])

def format_threat_text(text):
    clean = clean_message(text)
    t_lower = clean.lower()
    emoji = "⚡️"
    if "ракета" in t_lower or "балістика" in t_lower: emoji = "🚀"
    elif "бпла" in t_lower or "шахед" in t_lower: emoji = "🦟"
    elif "тривога" in t_lower: emoji = "⚠️"
    elif "відбій" in t_lower: emoji = "🟢"
    
    final_text = f"<b>{clean.upper()}</b>" if len(clean) < 100 else clean
    return f"{emoji} {final_text}"

# === 4. ОБРОБКА ГРАФІКІВ (КАРТИНКИ) ===
async def process_dtek_image(message_obj):
    now = datetime.now(ZoneInfo("Europe/Kyiv"))
    target_date = now + timedelta(days=1) if now.hour >= 18 else now
    date_str = f"{target_date.day} {MONTHS_UA.get(target_date.month, '')}"
    
    caption = (
        f"⚡️ ‼️Дніпропетровщина: графіки відключень на {date_str}\n"
        "▪️В разі змін, будемо оперативно вас інформувати у нашому телеграм-каналі.\n"
        "Підписуйтесь та поділіться, будь ласка, з родичами та друзями.\n" + FOOTER
    )
    try:
        msg = await client.send_message(CHANNEL_USERNAME, caption, file=message_obj.media, parse_mode='html')
        if msg: await client.pin_message(CHANNEL_USERNAME, msg, notify=True)
        logger.info("✅ Графік опубліковано")
    except Exception as e:
        logger.error(f"Помилка графіку: {e}")

# === 5. ДАЙДЖЕСТИ ТА ПОГОДА ===
def get_weather():
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=48.46&longitude=35.04&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&current=temperature_2m&timezone=Europe%2FKyiv"
        return requests.get(url, timeout=10).json()
    except: return None

def get_ai_quote():
    quotes = [
        "Темрява не може затьмарити наше внутрішнє світло.",
        "Спокій — це найсильніший щит.",
        "Кожен світанок дарує нову надію.",
        "Ми сильніші, ніж думаємо.",
        "Світло завжди перемагає."
    ]
    return random.choice(quotes)

async def send_digest(mode):
    logger.info(f"Preparing {mode} digest...")
    data = await asyncio.to_thread(get_weather)
    w_txt = "🌡 Погода тимчасово недоступна"
    
    if data:
        d = data['daily']
        if mode == "morning":
            w_txt = f"🌡 Температура: {d['temperature_2m_min'][0]}...{d['temperature_2m_max'][0]}°C\n☔️ Опади: {d['precipitation_probability_max'][0]}%"
        else:
            w_txt = f"🌡 Завтра: {d['temperature_2m_min'][1]}...{d['temperature_2m_max'][1]}°C"
    
    q = get_ai_quote()
    if mode == "morning":
        st = "🔴 Тривога активна!" if IS_ALARM_ACTIVE else "🟢 Небо чисте."
        msg = f"<b>☀️ ДОБРОГО РАНКУ, ДНІПРО!</b>\n\n{w_txt}\n📢 Стан: {st}\n\n<blockquote>{q}</blockquote>"
    else:
        msg = f"<b>🌒 НА ДОБРАНІЧ, ДНІПРО!</b>\n\n{w_txt}\n\n<blockquote>{q}</blockquote>\n\n🔋 Не забудьте зарядити гаджети."
    
    try:
        await client.send_message(CHANNEL_USERNAME, msg + FOOTER, parse_mode='html')
        logger.info(f"{mode} digest sent.")
    except Exception as e:
        logger.error(f"Digest error: {e}")

# === 6. ХЕНДЛЕРИ ===

@client.on(events.NewMessage(chats=MONITOR_THREATS_USER))
async def threat_handler(event):
    text = (event.message.message or "")
    text_lower = text.lower()
    
    if "hydneprbot" in text_lower: return 

    if any(k in text_lower for k in STRICT_THREATS):
        logger.info(f"⚠️ THREAT DETECTED: {text[:20]}...")
        clean = format_threat_text(text)
        await client.send_message(CHANNEL_USERNAME, clean + FOOTER, parse_mode='html')

@client.on(events.NewMessage(chats=DTEK_OFFICIAL))
async def dtek_handler(event):
    text = (event.message.message or "").lower()
    if ("дніпро" in text or "дніпропетровщина" in text) and event.message.photo:
        logger.info("⚡️ DTEK Official Graphic Detected")
        await process_dtek_image(event.message)

@client.on(events.NewMessage())
async def main_handler(event):
    try:
        chat = await event.get_chat()
        if chat and chat.username and chat.username.lower() in [MONITOR_THREATS_USER, DTEK_OFFICIAL]: return
    except: pass

    # ТЕСТИ ТА РУЧНЕ КЕРУВАННЯ (Saved Messages)
    if event.out:
        text = event.message.message or ""
        
        # Ручна публікація графіку (треба переслати КАРТИНКУ і додати текст "графік")
        if event.message.photo and any(k in text.lower() for k in ["графік", "дтек"]):
            await process_dtek_image(event.message)
            await event.respond("✅ Графік опубліковано!")
            return

        if "test_morning" in text:
            await event.respond("Test Morning...")
            await send_digest("morning")
        elif "test_evening" in text:
            await event.respond("Test Evening...")
            await send_digest("evening")
        elif "test_threat" in text:
            await event.respond("Test Threat...")
            t = text.replace("test_threat", "").strip() or "Ракетна небезпека"
            await client.send_message(CHANNEL_USERNAME, format_threat_text(t) + FOOTER, parse_mode='html')

    # СИРЕНА
    if chat and chat.username == SIREN_CHANNEL_USER:
        global IS_ALARM_ACTIVE
        text = event.message.message.lower()
        try:
            if "відбій" in text:
                IS_ALARM_ACTIVE = False
                await client.send_message(CHANNEL_USERNAME, TXT_TREVOGA_STOP + FOOTER, parse_mode='html')
            elif "тривог" in text:
                IS_ALARM_ACTIVE = True
                await client.send_message(CHANNEL_USERNAME, TXT_TREVOGA + FOOTER, parse_mode='html')
        except Exception as e:
            logger.error(f"Siren error: {e}")

# === 7. ТАЙМЕРИ ТА ЗАПУСК ===
async def scheduler():
    logger.info("🕒 Scheduler initiated...")
    while True:
        now = datetime.now(ZoneInfo("Europe/Kyiv"))
        
        target_morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target_morning: target_morning += timedelta(days=1)
        
        target_evening = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target_evening: target_evening += timedelta(days=1)
        
        next_event = min(target_morning, target_evening)
        sleep_seconds = (next_event - now).total_seconds()
        
        logger.info(f"💤 Sleeping {int(sleep_seconds)}s until {next_event.strftime('%H:%M')}")
        await asyncio.sleep(sleep_seconds)
        
        if next_event.hour == 8:
            await send_digest("morning")
        else:
            await send_digest("evening")
            
        await asyncio.sleep(60) 

async def startup():
    try:
        await client(JoinChannelRequest(MONITOR_THREATS_USER))
        await client(JoinChannelRequest(DTEK_OFFICIAL))
        logger.info("✅ БОТ ЗАПУЩЕНО. КАРТИНКИ ВИМКНЕНІ (крім графіків).")
    except Exception as e:
        logger.error(f"Startup warning: {e}")

if __name__ == '__main__':
    client.start()
    client.loop.create_task(scheduler())
    client.loop.run_until_complete(startup())
    client.run_until_disconnected()
