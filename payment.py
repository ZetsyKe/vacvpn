from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import httpx
from dotenv import load_dotenv

load_dotenv('backend/key.env')

SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

app = FastAPI()

@app.post("/pay")
async def create_payment(request: Request):
    try:
        # Валидация ключей
        if not SHOP_ID or not API_KEY:
            raise ValueError("Не настроены SHOP_ID или API_KEY в .env файле")
        
        body = await request.json()
        amount = float(body.get("amount", 100))
        
        # Формирование запроса к ЮKassa
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
            "description": "Пополнение баланса VAC VPN",
            "metadata": {
                "payment_id": payment_id,
                "user_id": body.get("user_id", "unknown")
            }
        }

        # Отправка в ЮKassa
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

        # Проверка ответа
        if resp.status_code in (200, 201):
            payment_data = resp.json()
            if not payment_data.get("confirmation", {}).get("confirmation_url"):
                raise ValueError("ЮKassa не вернула confirmation_url")
            return {"payment_url": payment_data["confirmation"]["confirmation_url"]}
        else:
            raise ValueError(f"Ошибка ЮKassa: {resp.status_code} - {resp.text}")

    except Exception as e:
        error_msg = f"Ошибка сервера: {str(e)}"
        print(error_msg)
        return {"error": error_msg}, 500
