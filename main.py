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
async def payment_endpoint(request: Request):
    try:
        data = await request.json()
        
        # Добавляем user_id из Telegram WebApp
        user_id = request.headers.get("X-Telegram-User-ID", "unknown")
        data["user_id"] = user_id
        
        result = await create_payment(request)
        
        if "error" in result:
            print(f"Payment error: {result}")  # Логирование ошибки
            return JSONResponse(result, status_code=500)
            
        return JSONResponse(result)
        
    except Exception as e:
        error_msg = f"Endpoint error: {str(e)}"
        print(error_msg)
        return JSONResponse({"error": error_msg}, status_code=500)
