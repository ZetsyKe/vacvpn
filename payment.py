from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv('backend/key.env')
SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

app = FastAPI()

@app.post("/pay")
async def create_payment(request: Request):
    try:
        # Получаем данные из запроса
        body = await request.json()
        amount = float(body.get("amount", 100))  # Сумма по умолчанию 100 руб.
        
        # Генерируем уникальный ID платежа
        payment_id = str(uuid.uuid4())
        
        # Данные для ЮKassa
        data = {
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/vaaaac_bot"  # Куда вернуться после оплаты
            },
            "capture": True,
            "description": "Пополнение баланса VAC VPN",
            "metadata": {
                "payment_id": payment_id
            }
        }
        
        # Отправка запроса в ЮKassa
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=(SHOP_ID, API_KEY),
                headers={"Content-Type": "application/json"},
                json=data
            )
        
        # Проверка ответа
        if response.status_code in (200, 201):
            payment_url = response.json()["confirmation"]["confirmation_url"]
            return {"payment_url": payment_url}
        else:
            return {"error": response.text}, 500
            
    except Exception as e:
        return {"error": str(e)}, 500
