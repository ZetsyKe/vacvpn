from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import uuid
import logging
from datetime import datetime, timedelta
from pydantic import BaseModel
from typing import Optional
import secrets

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Модели данных
class UserInitRequest(BaseModel):
    user_id: str
    username: str
    first_name: str
    last_name: str = ""
    start_param: str = ""

class PaymentRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int

class BalancePaymentRequest(BaseModel):
    user_id: str
    tariff_id: str
    tariff_price: float
    tariff_days: int

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('vacvpn.db')
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            balance REAL DEFAULT 0,
            subscription_days INTEGER DEFAULT 0,
            has_subscription BOOLEAN DEFAULT FALSE,
            vless_uuid TEXT,
            referrer_id TEXT,
            registration_date TEXT,
            last_payment_date TEXT,
            last_payment_amount REAL DEFAULT 0
        )
    ''')
    
    # Таблица платежей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            payment_id TEXT PRIMARY KEY,
            user_id TEXT,
            amount REAL,
            tariff_id TEXT,
            status TEXT,
            created_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    ''')
    
    # Таблица рефералов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id TEXT,
            referred_id TEXT,
            bonus_credited BOOLEAN DEFAULT FALSE,
            created_at TEXT,
            FOREIGN KEY (referrer_id) REFERENCES users (user_id),
            FOREIGN KEY (referred_id) REFERENCES users (user_id)
        )
    ''')
    
    # Таблица серверов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            address TEXT,
            port INTEGER,
            location TEXT,
            is_active BOOLEAN DEFAULT TRUE
        )
    ''')
    
    # Добавляем тестовые серверы если их нет
    cursor.execute("SELECT COUNT(*) FROM servers")
    if cursor.fetchone()[0] == 0:
        test_servers = [
            ("🇷🇺 Москва #1", "moscow1.vacvpn.ru", 443, "Moscow"),
            ("🇷🇺 Москва #2", "moscow2.vacvpn.ru", 443, "Moscow"),
            ("🇩🇪 Германия #1", "frankfurt1.vacvpn.eu", 443, "Germany"),
            ("🇺🇸 США #1", "newyork1.vacvpn.com", 443, "USA")
        ]
        cursor.executemany(
            "INSERT INTO servers (name, address, port, location) VALUES (?, ?, ?, ?)",
            test_servers
        )
    
    conn.commit()
    conn.close()

init_db()

# Вспомогательные функции
def get_db_connection():
    conn = sqlite3.connect('vacvpn.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_vless_uuid():
    return str(uuid.uuid4())

async def get_user_data(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM users WHERE user_id = ?
    ''', (user_id,))
    
    user = cursor.fetchone()
    conn.close()
    
    return dict(user) if user else None

async def update_user_data(user_id: str, update_data: dict):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        set_clause = ", ".join([f"{key} = ?" for key in update_data.keys()])
        values = list(update_data.values())
        values.append(user_id)
        
        cursor.execute(f'''
            UPDATE users SET {set_clause} WHERE user_id = ?
        ''', values)
        
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"Error updating user data: {e}")
        return False

async def credit_referral_bonus(referred_user_id: str, purchase_amount: float):
    """Начисление бонусов рефереру"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Находим реферера
        cursor.execute('''
            SELECT referrer_id FROM users WHERE user_id = ?
        ''', (referred_user_id,))
        
        result = cursor.fetchone()
        if not result or not result['referrer_id']:
            return
        
        referrer_id = result['referrer_id']
        
        # Проверяем, не начислялся ли уже бонус
        cursor.execute('''
            SELECT bonus_credited FROM referrals 
            WHERE referrer_id = ? AND referred_id = ?
        ''', (referrer_id, referred_user_id))
        
        existing = cursor.fetchone()
        if existing and existing['bonus_credited']:
            return
        
        # Начисляем бонусы
        referrer_bonus = 50  # 50₽ рефереру
        referred_bonus = 100  # 100₽ приглашенному
        
        # Обновляем баланс реферера
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (referrer_bonus, referrer_id))
        
        # Обновляем баланс приглашенного
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (referred_bonus, referred_user_id))
        
        # Отмечаем бонус как начисленный
        if existing:
            cursor.execute('''
                UPDATE referrals SET bonus_credited = TRUE 
                WHERE referrer_id = ? AND referred_id = ?
            ''', (referrer_id, referred_user_id))
        else:
            cursor.execute('''
                INSERT INTO referrals (referrer_id, referred_id, bonus_credited, created_at)
                VALUES (?, ?, ?, ?)
            ''', (referrer_id, referred_user_id, True, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"🎁 Referral bonus credited: referrer={referrer_id}, referred={referred_user_id}")
        
    except Exception as e:
        logger.error(f"Error crediting referral bonus: {e}")

# API Endpoints
@app.post("/init-user")
async def init_user(request: UserInitRequest):
    try:
        logger.info(f"🔍 INIT-USER START: user_id={request.user_id}, start_param='{request.start_param}'")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем существующего пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (request.user_id,))
        existing_user = cursor.fetchone()
        
        is_referral = False
        referrer_id = None
        
        # Обработка реферальной ссылки
        if request.start_param and request.start_param.startswith('ref_'):
            referrer_id = request.start_param.replace('ref_', '')
            is_referral = True
            logger.info(f"🎯 Referral detected: referrer_id={referrer_id}")
        
        if existing_user:
            # Обновляем существующего пользователя
            cursor.execute('''
                UPDATE users SET 
                username = ?, first_name = ?, last_name = ?
                WHERE user_id = ?
            ''', (request.username, request.first_name, request.last_name, request.user_id))
            
            # Если это реферал и реферер еще не установлен
            if is_referral and not existing_user['referrer_id']:
                cursor.execute('''
                    UPDATE users SET referrer_id = ? WHERE user_id = ?
                ''', (referrer_id, request.user_id))
                
                # Добавляем запись в рефералы
                cursor.execute('''
                    INSERT OR IGNORE INTO referrals (referrer_id, referred_id, created_at)
                    VALUES (?, ?, ?)
                ''', (referrer_id, request.user_id, datetime.now().isoformat()))
                
        else:
            # Создаем нового пользователя
            vless_uuid = generate_vless_uuid()
            
            cursor.execute('''
                INSERT INTO users (
                    user_id, username, first_name, last_name, 
                    vless_uuid, referrer_id, registration_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                request.user_id, request.username, request.first_name, 
                request.last_name, vless_uuid, referrer_id, 
                datetime.now().isoformat()
            ))
            
            # Добавляем запись в рефералы если это реферал
            if is_referral:
                cursor.execute('''
                    INSERT INTO referrals (referrer_id, referred_id, created_at)
                    VALUES (?, ?, ?)
                ''', (referrer_id, request.user_id, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ INIT-USER SUCCESS: user_id={request.user_id}, is_referral={is_referral}")
        
        return {
            "success": True,
            "is_referral": is_referral,
            "referrer_id": referrer_id
        }
        
    except Exception as e:
        logger.error(f"❌ INIT-USER ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user-data")
async def get_user_data_endpoint(user_id: str):
    try:
        logger.info(f"📊 USER-DATA REQUEST: user_id={user_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем данные пользователя
        cursor.execute('''
            SELECT * FROM users WHERE user_id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_dict = dict(user)
        
        # Получаем реферальную статистику
        cursor.execute('''
            SELECT COUNT(*) as total_referrals, 
                   SUM(CASE WHEN bonus_credited THEN 50 ELSE 0 END) as total_bonus_money
            FROM referrals 
            WHERE referrer_id = ?
        ''', (user_id,))
        
        ref_stats = cursor.fetchone()
        
        conn.close()
        
        response_data = {
            "user_id": user_dict['user_id'],
            "username": user_dict['username'],
            "first_name": user_dict['first_name'],
            "balance": user_dict['balance'],
            "subscription_days": user_dict['subscription_days'],
            "has_subscription": bool(user_dict['has_subscription']),
            "vless_uuid": user_dict['vless_uuid'],
            "referral_stats": {
                "total_referrals": ref_stats['total_referrals'],
                "total_bonus_money": ref_stats['total_bonus_money'] or 0
            }
        }
        
        logger.info(f"✅ USER-DATA SUCCESS: user_id={user_id}, days={user_dict['subscription_days']}")
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ USER-DATA ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/buy-with-balance")
async def buy_with_balance(request: BalancePaymentRequest):
    try:
        logger.info(f"💰 BUY-WITH-BALANCE START: user_id={request.user_id}, tariff={request.tariff_id}, price={request.tariff_price}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем данные пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (request.user_id,))
        user = cursor.fetchone()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_balance = user['balance']
        
        # Проверяем достаточность баланса
        if user_balance < request.tariff_price:
            return {
                "success": False,
                "error": f"Недостаточно средств на балансе. На вашем балансе {user_balance}₽, а требуется {request.tariff_price}₽"
            }
        
        # Вычисляем новые значения
        new_balance = user_balance - request.tariff_price
        current_days = user['subscription_days'] or 0
        new_subscription_days = current_days + request.tariff_days
        
        # Обновляем данные пользователя
        cursor.execute('''
            UPDATE users SET 
            balance = ?,
            subscription_days = ?,
            has_subscription = TRUE,
            last_payment_date = ?,
            last_payment_amount = ?
            WHERE user_id = ?
        ''', (
            new_balance,
            new_subscription_days,
            datetime.now().isoformat(),
            request.tariff_price,
            request.user_id
        ))
        
        # Начисляем реферальные бонусы
        await credit_referral_bonus(request.user_id, request.tariff_price)
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ BUY-WITH-BALANCE SUCCESS: user_id={request.user_id}, new_balance={new_balance}, new_days={new_subscription_days}")
        
        return {
            "success": True,
            "message": f"Подписка успешно активирована! Списписано {request.tariff_price}₽ с баланса",
            "new_balance": new_balance,
            "new_subscription_days": new_subscription_days
        }
        
    except Exception as e:
        logger.error(f"❌ BUY-WITH-BALANCE ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/create-payment")
async def create_payment(request: PaymentRequest):
    try:
        logger.info(f"💳 CREATE-PAYMENT: user_id={request.user_id}, tariff={request.tariff_id}")
        
        # Генерируем ID платежа
        payment_id = f"pay_{secrets.token_hex(8)}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Сохраняем платеж в базу
        cursor.execute('''
            INSERT INTO payments (payment_id, user_id, amount, tariff_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            payment_id,
            request.user_id,
            request.tariff_price,
            request.tariff_id,
            'pending',
            datetime.now().isoformat()
        ))
        
        conn.commit()
        conn.close()
        
        # В реальном проекте здесь должна быть интеграция с ЮKassa
        # Для тестов возвращаем фиктивную платежную ссылку
        payment_link = f"https://yookassa.ru/test/payment/{payment_id}"
        
        return {
            "success": True,
            "payment_id": payment_id,
            "payment_link": payment_link
        }
        
    except Exception as e:
        logger.error(f"❌ CREATE-PAYMENT ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/check-payment")
async def check_payment(payment_id: str):
    try:
        logger.info(f"🔍 CHECK-PAYMENT: payment_id={payment_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM payments WHERE payment_id = ?
        ''', (payment_id,))
        
        payment = cursor.fetchone()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")
        
        # В реальном проекте здесь проверка статуса в ЮKassa
        # Для тестов имитируем успешный платеж
        if payment['status'] == 'pending':
            # Обновляем статус на успешный
            cursor.execute('''
                UPDATE payments SET status = 'succeeded', completed_at = ?
                WHERE payment_id = ?
            ''', (datetime.now().isoformat(), payment_id))
            
            # Обновляем данные пользователя
            cursor.execute('''
                SELECT tariff_id, amount FROM payments WHERE payment_id = ?
            ''', (payment_id,))
            
            payment_data = cursor.fetchone()
            tariff_id = payment_data['tariff_id']
            amount = payment_data['amount']
            
            # Определяем количество дней по tariff_id
            tariff_days = 30 if tariff_id == '1month' else 365
            
            cursor.execute('''
                UPDATE users SET 
                subscription_days = subscription_days + ?,
                has_subscription = TRUE,
                last_payment_date = ?,
                last_payment_amount = ?
                WHERE user_id = ?
            ''', (
                tariff_days,
                datetime.now().isoformat(),
                amount,
                payment['user_id']
            ))
            
            # Начисляем реферальные бонусы
            await credit_referral_bonus(payment['user_id'], amount)
            
            conn.commit()
        
        conn.close()
        
        return {
            "success": True,
            "payment_status": "succeeded",
            "payment_id": payment_id
        }
        
    except Exception as e:
        logger.error(f"❌ CHECK-PAYMENT ERROR: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/get-vless-config")
async def get_vless_config(user_id: str):
    try:
        logger.info(f"🔧 GET-VLESS-CONFIG: user_id={user_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем активную подписку
        cursor.execute('''
            SELECT subscription_days, vless_uuid FROM users WHERE user_id = ?
        ''', (user_id,))
        
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        if not user['subscription_days'] or user['subscription_days'] <= 0:
            raise HTTPException(status_code=403, detail="No active subscription")
        
        # Получаем список серверов
        cursor.execute('''
            SELECT * FROM servers WHERE is_active = TRUE
        ''')
        
        servers = cursor.fetchall()
        conn.close()
        
        server_configs = []
        for server in servers:
            vless_url = f"vless://{user['vless_uuid']}@{server['address']}:{server['port']}?security=tls&type=ws&path=/vless#VACVPN-{server['name']}"
            
            server_configs.append({
                "name": server['name'],
                "address": server['address'],
                "port": server['port'],
                "location": server['location'],
                "vless_url": vless_url
            })
        
        return {
            "success": True,
            "vless_uuid": user['vless_uuid'],
            "servers": server_configs
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ GET-VLESS-CONFIG ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 🔧 АДМИНИСТРАТИВНЫЕ ФУНКЦИИ ДЛЯ ТЕСТИРОВАНИЯ

@app.post("/admin/reset-test-data")
async def reset_test_data(user_id: str):
    """Сброс тестовых данных для пользователя"""
    try:
        logger.info(f"🔄 RESET-TEST-DATA: user_id={user_id}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Сбрасываем данные пользователя
        cursor.execute('''
            UPDATE users SET 
            balance = 0,
            subscription_days = 0,
            has_subscription = FALSE,
            last_payment_amount = 0
            WHERE user_id = ?
        ''', (user_id,))
        
        # Удаляем платежи пользователя
        cursor.execute('''
            DELETE FROM payments WHERE user_id = ?
        ''', (user_id,))
        
        # Удаляем реферальные связи где пользователь является реферером или приглашенным
        cursor.execute('''
            DELETE FROM referrals WHERE referrer_id = ? OR referred_id = ?
        ''', (user_id, user_id))
        
        # Сбрасываем реферера у пользователя
        cursor.execute('''
            UPDATE users SET referrer_id = NULL WHERE user_id = ?
        ''', (user_id,))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": "Тестовые данные сброшены"
        }
        
    except Exception as e:
        logger.error(f"❌ RESET-TEST-DATA ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/admin/add-balance")
async def add_balance(user_id: str, amount: float):
    """Добавить баланс для тестирования"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (amount, user_id))
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"Баланс пополнен на {amount}₽"
        }
        
    except Exception as e:
        logger.error(f"❌ ADD-BALANCE ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/user-stats")
async def get_user_stats(user_id: str):
    """Получить полную статистику пользователя"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Данные пользователя
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        user = cursor.fetchone()
        
        # Рефералы
        cursor.execute('''
            SELECT referred_id, bonus_credited, created_at 
            FROM referrals WHERE referrer_id = ?
        ''', (user_id,))
        referrals = cursor.fetchall()
        
        # Платежи
        cursor.execute('SELECT * FROM payments WHERE user_id = ?', (user_id,))
        payments = cursor.fetchall()
        
        conn.close()
        
        return {
            "user": dict(user) if user else None,
            "referrals": [dict(ref) for ref in referrals],
            "payments": [dict(pay) for pay in payments]
        }
        
    except Exception as e:
        logger.error(f"❌ USER-STATS ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
