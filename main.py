import os
import json
import base64
import time
import re
import requests
import asyncio
import random
from datetime import datetime, timedelta
from dateutil import parser
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.channels import JoinChannelRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# === НАЛАШТУВАННЯ ===
MY_PERSONAL_GROUP = "1.1"
MAIN_ACCOUNT_USERNAME = "@nemovisio"
CHANNEL_USERNAME = "@strum_dp"
SIREN_CHANNEL_USER = "sirena_dp"

# === ТЕКСТ ПІДТРИМКИ (ОНОВЛЕНИЙ) ===
FOOTER_TEXT = """

___

Підписуйтесь та поділіться з родичами і друзями:
https://t.me/strum_dp

ПІДТРИМКА СЕРВІСУ СТРУМ
🔗 Посилання на банку:
https://send.monobank.ua/jar/9gBQ4LTLUa"""

# Координати Дніпра
DNIPRO_LAT = 48.46
DNIPRO_LON = 35.04

# === ЗМІННІ ===
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
SESSION_STRING = os.environ['TELEGRAM_SESSION']
GEMINI_KEY = os.environ['GEMINI_API_KEY']
GOOGLE_TOKEN = os.environ['GOOGLE_TOKEN_JSON']

# === МЕДІА ===
IMG_SCHEDULE = "https://arcanavisio.com/wp-content/uploads/2026/01/MAIN.jpg"
IMG_UPDATE = "https://arcanavisio.com/wp-content/uploads/2026/01/UPDATE.jpg"
IMG_EMERGENCY = "https://arcanavisio.com/wp-content/uploads/2026/01/EXTRA.jpg"
IMG_ALARM = "https://arcanavisio.com/wp-content/uploads/2026/01/ALARM.jpg"
IMG_ALL_CLEAR = "https://arcanavisio.com/wp-content/uploads/2026/01/REBOUND.jpg"
IMG_MORNING = "https://arcanavisio.com/wp-content/uploads/2026/01/MORN.jpg"
IMG_EVENING = "https://arcanavisio.com/wp-content/uploads/2026/01/EVN.jpg"

processing_lock = asyncio.Lock()
REAL_SIREN_ID = None
IS_ALARM_ACTIVE = False # Пам'ять про стан тривоги

# Мотиваційні фрази
MOTIVATION_QUOTES = [
    "Сьогодні чудовий день, щоб зробити щось важливе!",
    "Навіть найтемніша ніч закінчується світанком.",
    "Тримаймо стрій! Перемога вже близько.",
    "Твоя енергія заряджає цей світ. Світи яскравіше!",
    "Маленькі кроки ведуть до великих змін.",
    "Вір у себе, як ми віримо в ППО!",
    "Не чекай на світло, будь світлом сам.",
    "Сьогоднішній день — це новий шанс.",
    "Кава, віра в ЗСУ та гарний настрій — рецепт твого дня.",
    "Усміхнись, тобі це личить!",
    "Все буде Україна. Головне — не зупинятися.",
    "Зберігай спокій та економ електроенергію.",
    "Ти здатен на більше, ніж думаєш.",
    "Нехай цей день принесе лише добрі новини.",
    "Світло всередині нас ніколи не згасне."
]

# Стан погоди
weather_state = {
    'last_temp': None,
    'last_pressure': None,
    'precip_warned': False,
    'wind_warned': False,
    'temp_warned': False
}

async def get_tasks_service():
    creds_dict = json.loads(GOOGLE_TOKEN)
    creds = Credentials.from_authorized_user_info(creds_dict)
    return build('tasks', 'v1', credentials=creds)

# === РАНКОВИЙ ДАЙДЖЕСТ (08:00) ===
async def morning_digest_loop():
    print("🌅 Morning Digest: Started")
    while True:
        now = datetime.now()
        target_time = now.replace(hour=8, minute=0, second=0, microsecond=0)
        if now >= target_time: target_time += timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        
        await asyncio.sleep(wait_seconds)
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w_res = requests.get(url).json()
            daily = w_res.get('daily', {})
            t_max = daily['temperature_2m_max'][0]
            t_min = daily['temperature_2m_min'][0]
            rain_prob = daily['precipitation_probability_max'][0]
            
            weather_text = f"🌡 **Сьогодні:** {t_min}°C ... {t_max}°C\n"
            if rain_prob > 50: weather_text += f"☔️ **Опади:** Можливий дощ/сніг ({rain_prob}%)."
            else: weather_text += "☀️ **Опади:** Малоймовірні."

            alarm_text = "🔴 **Тривога:** Зараз небезпечно!" if IS_ALARM_ACTIVE else "🟢 **Тривога:** Тихо."
            quote = random.choice(MOTIVATION_QUOTES)

            msg = f"""👋 **Добрий ранок, Дніпро!**

{weather_text}

{alarm_text}

📅 **Графік:** Перевірте канал на наявність змін.

💬 **Думка дня:**
_{quote}_
{FOOTER_TEXT}"""

            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_MORNING)
            print("✅ Morning digest sent.")
        except Exception as e:
            print(f"❌ Morning Error: {e}")
        
        await asyncio.sleep(60)

# === ВЕЧІРНІЙ ДАЙДЖЕСТ (22:00) ===
async def evening_digest_loop():
    print("🌙 Evening Digest: Started")
    while True:
        now = datetime.now()
        target_time = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now >= target_time: target_time += timedelta(days=1)
        wait_seconds = (target_time - now).total_seconds()
        
        await asyncio.sleep(wait_seconds)
        
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=Europe%2FKyiv"
            w_res = requests.get(url).json()
            daily = w_res.get('daily', {})
            
            t_max = daily['temperature_2m_max'][1]
            t_min = daily['temperature_2m_min'][1]
            rain_prob = daily['precipitation_probability_max'][1]
            
            weather_text = f"🌡 **Завтра:** {t_min}°C ... {t_max}°C\n"
            if rain_prob > 50: weather_text += f"☔️ **Опади:** Очікується дощ/сніг."
            else: weather_text += "✨ **Опади:** Без істотних опадів."

            alarm_text = "🔴 **Тривога:** Зараз лунає сирена." if IS_ALARM_ACTIVE else "🟢 **Тривога:** Наразі спокійно."

            msg = f"""🌙 **На добраніч, Дніпро!**

{weather_text}

{alarm_text}

🔋 **Нагадування:** Не забудьте поставити гаджети та павербанки на зарядку, якщо це потрібно.

Тихої ночі всім нам. ✨
{FOOTER_TEXT}"""

            await client.send_message(CHANNEL_USERNAME, msg, file=IMG_EVENING)
            print("✅ Evening digest sent.")
        except Exception as e:
            print(f"❌ Evening Error: {e}")
        
        await asyncio.sleep(60)

# === ПОГОДНІ АЛЕРТИ ===
async def check_weather_alerts():
    print("🌤 Weather Monitor: Started")
    while True:
        try:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={DNIPRO_LAT}&longitude={DNIPRO_LON}&current=temperature_2m,precipitation,rain,showers,snowfall,surface_pressure,wind_speed_10m&timezone=Europe%2FKyiv"
            response = await asyncio.to_thread(requests.get, url)
            data = response.json().get('current', {})

            if not data:
                await asyncio.sleep(1800)
                continue

            temp = data.get('temperature_2m', 0)
            pressure = data.get('surface_pressure', 0)
            wind = data.get('wind_speed_10m', 0)
            rain = data.get('rain', 0) + data.get('showers', 0)
            snow = data.get('snowfall', 0)
            
            alerts = []

            if temp < -10:
                if not weather_state['temp_warned']:
                    alerts.append(f"🥶 **СИЛЬНИЙ МОРОЗ:** {temp}°C! Одягайтесь тепліше.")
                    weather_state['temp_warned'] = True
            elif temp > 30:
                if not weather_state['temp_warned']:
                    alerts.append(f"🥵 **ПЕКЕЛЬНА СПЕКА:** {temp}°C! Беріть воду та панамку.")
                    weather_state['temp_warned'] = True
            else:
                if -9 < temp < 29: weather_state['temp_warned'] = False

            if wind > 15:
                if not weather_state['wind_warned']:
                    alerts.append(f"💨 **ШТОРМОВИЙ ВІТЕР:** {wind} м/с. Обережно під деревами.")
                    weather_state['wind_warned'] = True
            else:
                if wind < 10: weather_state['wind_warned'] = False

            if snow > 0:
                if not weather_state['precip_warned']:
                    alerts.append(f"❄️ **УВАГА: СНІГОПАД!** Можлива ожеледиця.")
                    weather_state['precip_warned'] = 'snow'
            elif rain > 0:
                if not weather_state['precip_warned']:
                    alerts.append(f"☔️ **ПОЧАВСЯ ДОЩ.** Не забудьте парасольку.")
                    weather_state['precip_warned'] = 'rain'
            else:
                weather
