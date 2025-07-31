from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from payment import create_payment
import os
from dotenv import load_dotenv

app = FastAPI()

# Настройка CORS (разрешаем запросы из фронтенда и Telegram)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vacvpn.vercel.app",  # Ваш фронтенд на Vercel
        "https://web.telegram.org"     # Telegram WebApp
    ],
    allow_methods=["POST"],
    allow_headers=["*"],
)

# Загрузка переменных окружения
load_dotenv("backend/key.env")

@app.post("/create-payment")
async def handle_payment(request: Request):
    try:
        data = await request.json()
        amount = data.get("amount", 100)
        
        # Создаем платеж через функцию из payment.py
        result = await create_payment(request)
        
        if "error" in result:
            return JSONResponse(result, status_code=500)
        return JSONResponse(result)
        
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
