from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from payment import create_payment
from dotenv import load_dotenv
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://vacvpn.vercel.app", "https://web.telegram.org"],
    allow_methods=["POST"],
    allow_headers=["*"],
)

load_dotenv("backend/key.env")

@app.post("/create-payment")
async def payment_endpoint(request: Request):
    try:
        logger.info("Обработка запроса /create-payment")
        
        data = await request.json()
        user_id = request.headers.get("X-Telegram-User-ID", "unknown")
        data["user_id"] = user_id
        
        logger.info(f"Данные запроса: {data}")
        
        result = await create_payment(request)
        
        if "error" in result:
            logger.error(f"Ошибка платежа: {result}")
            return JSONResponse(result, status_code=500)
            
        logger.info("Платеж успешно создан")
        return JSONResponse(result)
        
    except Exception as e:
        error_msg = f"Ошибка обработки: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return JSONResponse({"error": error_msg}, status_code=500)

@app.get("/")
async def health_check():
    return {"status": "ok"}
