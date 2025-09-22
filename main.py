from fastapi import HTTPException
import os
import uuid
import httpx
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta
import sqlite3
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv('backend/key.env')
SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

async def create_payment(data: dict):
    try:
        logger.info("=== Начало создания платежа ===")
        
        if not SHOP_ID or not API_KEY:
            error_msg = "Не настроены SHOP_ID или API_KEY в .env файле"
            logger.error(error_msg)
            return {"error": error_msg}
        
        amount = float(data.get("amount", 100))
        tariff = data.get("tariff", "month")
        user_id = data.get("user_id", "unknown")
        description = data.get("description", "")
        
        # Определяем параметры тарифа
        tariff_config = {
            "month": {"days": 30, "description": "Месячная подписка VAC VPN"},
            "year": {"days": 365, "description": "Годовая подписка VAC VPN"}
        }
        
        tariff_info = tariff_config.get(tariff, tariff_config["month"])
        days = tariff_info["days"]
        tariff_description = description or tariff_info["description"]
        
        payment_id = str(uuid.uuid4())
        
        # Создаем запись о платеже в базе
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO payments 
            (payment_id, user_id, amount, tariff, days, description)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (payment_id, user_id, amount, tariff, days, tariff_description))
        
        conn.commit()
        conn.close()
        
        # Данные для ЮKassa
        yookassa_data = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/vaaaac_bot"
            },
            "capture": True,
            "description": tariff_description,
            "metadata": {
                "payment_id": payment_id,
                "user_id": user_id,
                "tariff": tariff,
                "days": days
            }
        }

        logger.info(f"Отправка запроса в ЮKassa: {yookassa_data}")
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": payment_id
                },
                json=yookassa_data,
                timeout=30.0
            )

        logger.info(f"Ответ ЮKassa: {resp.status_code}")
        
        if resp.status_code in (200, 201):
            payment_data = resp.json()
            logger.info(f"Платеж создан: {payment_data.get('id')}")
            
            # Обновляем запись платежа с ID ЮKassa
            conn = sqlite3.connect('vacvpn.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments SET yookassa_payment_id = ? 
                WHERE payment_id = ?
            ''', (payment_data.get('id'), payment_id))
            conn.commit()
            conn.close()
            
            if not payment_data.get("confirmation", {}).get("confirmation_url"):
                error_msg = "ЮKassa не вернула confirmation_url"
                logger.error(error_msg)
                return {"error": error_msg}
                
            return {
                "payment_id": payment_id,
                "yookassa_payment_id": payment_data.get('id'),
                "payment_url": payment_data["confirmation"]["confirmation_url"],
                "amount": amount,
                "status": "pending",
                "description": tariff_description
            }
        else:
            error_msg = f"Ошибка ЮKassa: {resp.status_code} - {resp.text}"
            logger.error(error_msg)
            
            # Обновляем статус платежа на ошибку
            conn = sqlite3.connect('vacvpn.db')
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE payments SET status = 'failed' 
                WHERE payment_id = ?
            ''', (payment_id,))
            conn.commit()
            conn.close()
            
            return {"error": error_msg}

    except Exception as e:
        error_msg = f"Ошибка создания платежа: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {"error": error_msg}

async def check_payment_status(payment_id: str, user_id: str):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT p.status, p.yookassa_payment_id, p.amount, p.tariff, p.days,
                   p.description, p.created_at, u.has_subscription
            FROM payments p
            LEFT JOIN users u ON p.user_id = u.user_id
            WHERE p.payment_id = ? AND p.user_id = ?
        ''', (payment_id, user_id))
        
        result = cursor.fetchone()
        
        if not result:
            return {"error": "Платеж не найден"}
        
        status, yookassa_id, amount, tariff, days, description, created_at, has_subscription = result
        
        # Если платеж уже подтвержден в базе
        if status == 'success':
            return {
                "payment_id": payment_id,
                "status": "success",
                "amount": amount,
                "tariff": tariff,
                "days": days,
                "has_subscription": bool(has_subscription)
            }
        
        # Проверяем статус в ЮKassa
        if yookassa_id and SHOP_ID and API_KEY:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.yookassa.ru/v3/payments/{yookassa_id}",
                    auth=(SHOP_ID, API_KEY),
                    timeout=10.0
                )
                
                if resp.status_code == 200:
                    yookassa_data = resp.json()
                    new_status = yookassa_data.get('status')
                    
                    # Обновляем статус в базе
                    if new_status in ['succeeded', 'canceled', 'waiting_for_capture']:
                        cursor.execute('''
                            UPDATE payments SET status = ? 
                            WHERE payment_id = ?
                        ''', (new_status, payment_id))
                        
                        # Если платеж успешен - активируем подписку
                        if new_status == 'succeeded':
                            await activate_subscription(user_id, tariff, days)
                            logger.info(f"Подписка активирована для пользователя {user_id}")
                        
                        conn.commit()
                    
                    return {
                        "payment_id": payment_id,
                        "status": new_status,
                        "amount": amount,
                        "tariff": tariff,
                        "days": days,
                        "yookassa_status": yookassa_data.get('status')
                    }
        
        return {
            "payment_id": payment_id,
            "status": status,
            "amount": amount,
            "tariff": tariff,
            "days": days
        }
        
    except Exception as e:
        error_msg = f"Ошибка проверки статуса платежа: {str(e)}"
        logger.error(error_msg)
        return {"error": error_msg}
    
    finally:
        conn.close()

async def activate_subscription(user_id: str, tariff: str, days: int):
    try:
        conn = sqlite3.connect('vacvpn.db')
        cursor = conn.cursor()
        
        # Проверяем существующую подписку
        cursor.execute('''
            SELECT subscription_end FROM users WHERE user_id = ?
        ''', (user_id,))
        
        result = cursor.fetchone()
        current_time = datetime.now()
        
        if result and result[0]:
            # Если подписка уже активна, продлеваем ее
            current_end = datetime.fromisoformat(result[0])
            if current_end > current_time:
                new_end = current_end + timedelta(days=days)
            else:
                new_end = current_time + timedelta(days=days)
        else:
            # Новая подписка
            new_end = current_time + timedelta(days=days)
        
        # Обновляем данные пользователя
        cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, has_subscription, subscription_start, subscription_end, tariff_type, updated_at)
            VALUES (?, TRUE, ?, ?, ?, ?)
        ''', (user_id, current_time.isoformat(), new_end.isoformat(), 
              tariff, current_time.isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Подписка активирована для {user_id} до {new_end}")
        
        # Здесь можно добавить уведомление в Telegram бота
        # await notify_telegram_bot(user_id, f"✅ Подписка активирована на {days} дней")
        
        return True
        
    except Exception as e:
        logger.error(f"Ошибка активации подписки: {e}")
        return False
