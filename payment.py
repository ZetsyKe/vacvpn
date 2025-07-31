from fastapi import Request
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import sqlite3

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')
SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Функция инициализации БД
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            subscription_end TEXT
        )
    ''')
    conn.commit()
    conn.close()

# Инициализируем БД при запуске
init_db()

async def create_payment(request: Request):
    try:
        logger.info("=== Начало обработки платежа ===")
        
        if not SHOP_ID or not API_KEY:
            error_msg = "Не настроены SHOP_ID или API_KEY в .env файле"
            logger.error(error_msg)
            return {"error": error_msg}, 500
        
        body = await request.json()
        logger.info(f"Получены данные: {body}")
        
        amount = float(body.get("amount", 100))
        tariff = body.get("tariff", "month")
        user_id = body.get("user_id", "unknown")
        
        payment_id = str(uuid.uuid4())
        data = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": f"Подписка VAC VPN ({'месячная' if tariff == 'month' else 'годовая'})",
            "metadata": {
                "payment_id": payment_id,
                "user_id": user_id,
                "tariff": tariff
            }
        }

        logger.info(f"Отправка запроса в ЮKassa: {data}")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=data,
                timeout=10
            )

        logger.info(f"Ответ ЮKassa: {resp.status_code}, {resp.text}")
        
        if resp.status_code in (200, 201):
            payment_data = resp.json()
            logger.info(f"Данные платежа: {payment_data}")
            
            if not payment_data.get("confirmation", {}).get("confirmation_url"):
                error_msg = "ЮKassa не вернула confirmation_url"
                logger.error(error_msg)
                return {"error": error_msg}, 500
            
            # Активируем подписку в БД
            days = 30 if tariff == "month" else 365
            conn = sqlite3.connect('vacvpn.db')
            cursor = conn.cursor()
            
            # Создаем пользователя с балансом 0, если не существует
            cursor.execute('''
                INSERT OR IGNORE INTO users (user_id, balance)
                VALUES (?, 0)
            ''', (user_id,))
            
            # Обновляем подписку
            cursor.execute('''
                UPDATE users 
                SET has_subscription = TRUE, 
                    subscription_end = ?
                WHERE user_id = ?
            ''', ((datetime.now() + timedelta(days=days)).isoformat(), user_id))
            
            # Обновляем баланс (добавляем сумму платежа)
            cursor.execute('''
                UPDATE users 
                SET balance = balance + ?
                WHERE user_id = ?
            ''', (amount, user_id))
            
            conn.commit()
            conn.close()
            
            return {"payment_url": payment_data["confirmation"]["confirmation_url"]}
        else:
            error_msg = f"Ошибка ЮKassa: {resp.status_code} - {resp.text}"
            logger.error(error_msg)
            return {"error": error_msg}, 500

    except Exception as e:
        error_msg = f"Ошибка сервера: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}, 500
