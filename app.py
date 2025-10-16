from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
import os
import logging
import asyncio
from datetime import datetime
import threading

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VAC VPN API",
    description="VPN Service with Telegram Bot",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальные переменные для состояния приложения
bot_status = {
    "is_running": False,
    "last_activity": None,
    "errors": []
}

# Импорт бота
def initialize_bot():
    """Инициализация бота"""
    try:
        from bot import main as bot_main, dp, bot
        return {
            "main": bot_main,
            "dp": dp,
            "bot": bot,
            "status": "loaded"
        }
    except ImportError as e:
        logger.warning(f"Bot module not available: {e}")
        return {"status": "not_available", "error": str(e)}
    except Exception as e:
        logger.error(f"Error initializing bot: {e}")
        return {"status": "error", "error": str(e)}

# Инициализация при старте
bot_module = initialize_bot()

# Функция для запуска бота в отдельном потоке
def run_bot():
    """Запуск бота в отдельном потоке"""
    try:
        if bot_module["status"] == "loaded":
            logger.info("🤖 Starting Telegram bot...")
            import asyncio
            asyncio.run(bot_module["main"]())
    except Exception as e:
        logger.error(f"❌ Bot execution error: {e}")
        bot_status["is_running"] = False
        bot_status["errors"].append(str(e))

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 VAC VPN API starting up...")
    
    # Автоматически запускаем бота при старте
    if bot_module["status"] == "loaded" and not bot_status["is_running"]:
        logger.info("🔄 Starting Telegram bot automatically...")
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        bot_status["is_running"] = True
        bot_status["last_activity"] = datetime.now().isoformat()
        logger.info("✅ Telegram bot started successfully")

@app.get("/")
async def root():
    """Главная страница"""
    return {
        "message": "VAC VPN API is running",
        "status": "ok",
        "bot_status": bot_status,
        "timestamp": datetime.now().isoformat()
    }

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "bot": {
            "is_running": bot_status["is_running"],
            "module_loaded": bot_module["status"] == "loaded"
        }
    }

@app.get("/status")
async def system_status():
    """Полный статус системы"""
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "bot_status": bot_status,
        "environment": "production"
    }

# Эндпоинты для управления ботом
@app.post("/bot/start")
async def start_bot():
    """Запуск бота"""
    try:
        if bot_module["status"] != "loaded":
            raise HTTPException(status_code=501, detail="Bot module not available")
        
        if bot_status["is_running"]:
            return {"message": "Bot is already running", "status": "running"}
        
        # Запускаем бота в отдельном потоке
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
        bot_status["is_running"] = True
        bot_status["last_activity"] = datetime.now().isoformat()
        
        logger.info("✅ Bot started via API")
        return {"message": "Bot started successfully", "status": "running"}
        
    except Exception as e:
        error_msg = f"Failed to start bot: {str(e)}"
        logger.error(error_msg)
        bot_status["errors"].append(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/bot/stop")
async def stop_bot():
    """Остановка бота"""
    try:
        if not bot_status["is_running"]:
            return {"message": "Bot is not running", "status": "stopped"}
        
        # Останавливаем бота (это остановит только polling, но не завершит процесс)
        if bot_module["status"] == "loaded" and hasattr(bot_module["dp"], 'stop_polling'):
            await bot_module["dp"].stop_polling()
        
        bot_status["is_running"] = False
        
        logger.info("✅ Bot stopped via API")
        return {"message": "Bot stopped", "status": "stopped"}
        
    except Exception as e:
        error_msg = f"Failed to stop bot: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.get("/bot/info")
async def bot_info():
    """Информация о боте"""
    return {
        "bot_status": bot_status,
        "module_loaded": bot_module["status"] == "loaded",
        "timestamp": datetime.now().isoformat()
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False  # На продакшене лучше False
    )
