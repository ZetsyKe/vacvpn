from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from dotenv import load_dotenv
import uuid
import os
import httpx

# Загрузка переменных из .env
load_dotenv('key.env')

# Константы ЮKassa
SHOP_ID = os.getenv("SHOP_ID")
API_KEY = os.getenv("API_KEY")

# Настройка FastAPI
app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent

# Статические файлы (index.html)
app.mount("/static", StaticFiles(directory=BASE_DIR), name="static")

@app.get("/", response_class=FileResponse)
async def read_index():
    return FileResponse(BASE_DIR / "index.html")

@app.post("/create-payment")
async def create_payment(request: Request):
    try:
        body = await request.json()
        amount = body.get("amount", 100)  # Сумма в рублях (можно изменить)

        # Уникальный идентификатор платежа
        payment_id = str(uuid.uuid4())

        # Запрос в ЮKassa
        headers = {
            "Content-Type": "application/json"
        }
        auth = (SHOP_ID, API_KEY)
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
            "description": "Пополнение баланса VPN",
            "metadata": {
                "payment_id": payment_id
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                auth=auth,
                headers=headers,
                json=data
            )

        if response.status_code == 200 or response.status_code == 201:
            payment = response.json()
            return JSONResponse({"payment_url": payment["confirmation"]["confirmation_url"]})
        else:
            return JSONResponse({"error": "Ошибка при создании платежа", "details": response.text}, status_code=500)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
