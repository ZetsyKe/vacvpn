from fastapi import FastAPI, UploadFile, File, HTTPException, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import os
import logging
import json
import asyncio
from datetime import datetime
import traceback

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ZetayKe Bot API",
    description="Complete bot application with file processing and management",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Создаем необходимые папки
os.makedirs("uploads", exist_ok=True)
os.makedirs("static", exist_ok=True)
os.makedirs("temp", exist_ok=True)

# Монтируем статические файлы если папка не пустая
if os.path.exists("static") and os.listdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Глобальные переменные для состояния приложения
bot_status = {
    "is_running": False,
    "last_activity": None,
    "active_tasks": 0,
    "errors": []
}

# =============================================================================
# УЛУЧШЕННАЯ ЗАГРУЗКА МОДУЛЕЙ
# =============================================================================

def load_config():
    """Загрузка конфигурации"""
    try:
        if os.path.exists("config.json"):
            with open("config.json", "r", encoding="utf-8") as f:
                return json.load(f)
        else:
            logger.warning("config.json not found, using default config")
            return {
                "app_name": "ZetayKe Bot",
                "version": "2.0.0",
                "debug": True
            }
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return {}

def safe_import_module(module_name, function_names):
    """Безопасный импорт модуля с обработкой ошибок"""
    try:
        module = __import__(module_name)
        functions = {}
        
        for func_name in function_names:
            if hasattr(module, func_name):
                functions[func_name] = getattr(module, func_name)
            else:
                logger.warning(f"Function {func_name} not found in {module_name}")
                functions[func_name] = None
        
        return {
            "module": module,
            "functions": functions,
            "status": "loaded"
        }
    except ImportError as e:
        logger.warning(f"Module {module_name} import error: {e}")
        return {
            "module": None,
            "functions": {name: None for name in function_names},
            "status": "not_available",
            "error": str(e)
        }
    except Exception as e:
        logger.error(f"Unexpected error importing {module_name}: {e}")
        return {
            "module": None,
            "functions": {name: None for name in function_names},
            "status": "error",
            "error": str(e)
        }

def initialize_modules():
    """Инициализация всех модулей проекта с улучшенной обработкой ошибок"""
    modules_status = {}
    
    # Загружаем bot.py с базовыми функциями
    bot_functions = ["main", "start_bot", "stop_bot", "process_message", "bot_main"]
    bot_result = safe_import_module("bot", bot_functions)
    modules_status["bot"] = bot_result
    
    # Загружаем xray_manager.py с альтернативными именами функций
    xray_functions = ["process_xray", "analyze_image", "generate_report", "process_image", "analyze_xray"]
    xray_result = safe_import_module("xray_manager", xray_functions)
    modules_status["xray_manager"] = xray_result
    
    # Создаем удобный доступ к функциям
    available_functions = {}
    
    # Для бота
    bot_funcs = {}
    for func_name in bot_functions:
        if bot_result["functions"].get(func_name):
            bot_funcs[func_name] = bot_result["functions"][func_name]
    available_functions["bot"] = bot_funcs if bot_funcs else None
    
    # Для xray_manager
    xray_funcs = {}
    for func_name in xray_functions:
        if xray_result["functions"].get(func_name):
            xray_funcs[func_name] = xray_result["functions"][func_name]
    available_functions["xray_manager"] = xray_funcs if xray_funcs else None
    
    return {
        "functions": available_functions,
        "status": modules_status
    }

# Инициализация при старте
config = load_config()
modules = initialize_modules()

# Вспомогательные функции для удобного доступа
def get_bot_function(name):
    func = modules["functions"]["bot"].get(name) if modules["functions"]["bot"] else None
    return func if callable(func) else None

def get_xray_function(name):
    func = modules["functions"]["xray_manager"].get(name) if modules["functions"]["xray_manager"] else None
    return func if callable(func) else None

# =============================================================================
# MIDDLEWARE И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =============================================================================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование всех запросов"""
    start_time = datetime.now()
    
    response = await call_next(request)
    
    process_time = (datetime.now() - start_time).total_seconds() * 1000
    logger.info(f"{request.method} {request.url.path} - Status: {response.status_code} - {process_time:.2f}ms")
    
    return response

def update_bot_status(is_running: bool = None, error: str = None):
    """Обновление статуса бота"""
    global bot_status
    if is_running is not None:
        bot_status["is_running"] = is_running
    if error:
        bot_status["errors"].append({
            "timestamp": datetime.now().isoformat(),
            "error": error
        })
        # Держим только последние 10 ошибок
        bot_status["errors"] = bot_status["errors"][-10:]
    bot_status["last_activity"] = datetime.now().isoformat()

# =============================================================================
# ОСНОВНЫЕ МАРШРУТЫ (упрощенная версия)
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Главная страница"""
    return """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>ZetayKe Bot</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .status { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; }
            .warning { background: #fff3cd; color: #856404; }
            .error { background: #f8d7da; color: #721c24; }
            .btn { display: inline-block; padding: 10px 20px; margin: 5px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 ZetayKe Bot API</h1>
            <p>Сервер работает успешно!</p>
            
            <div class="status success">
                <strong>✅ API Status:</strong> ONLINE
            </div>
            
            <div class="status warning">
                <strong>⚠️ Bot Module:</strong> {{ bot_status }}
            </div>
            
            <div class="status warning">
                <strong>⚠️ XRay Module:</strong> {{ xray_status }}
            </div>
            
            <div style="margin-top: 20px;">
                <a href="/docs" class="btn">API Documentation</a>
                <a href="/health" class="btn">Health Check</a>
                <a href="/status" class="btn">System Status</a>
            </div>
        </div>
    </body>
    </html>
    """.replace(
        "{{ bot_status }}", 
        modules["status"]["bot"]["status"]
    ).replace(
        "{{ xray_status }}", 
        modules["status"]["xray_manager"]["status"]
    )

@app.get("/health")
async def health_check():
    """Проверка здоровья системы"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "ZetayKe Bot API",
        "modules": {
            "bot": modules["status"]["bot"]["status"],
            "xray_manager": modules["status"]["xray_manager"]["status"]
        }
    }

@app.get("/status")
async def system_status():
    """Полный статус системы"""
    return {
        "status": "operational",
        "timestamp": datetime.now().isoformat(),
        "modules": modules["status"],
        "bot_status": bot_status
    }

# =============================================================================
# ФАЙЛОВЫЕ ОПЕРАЦИИ
# =============================================================================

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """Загрузка файла"""
    try:
        # Сохраняем файл
        file_location = f"uploads/{file.filename}"
        with open(file_location, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        logger.info(f"File {file.filename} uploaded successfully")
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "size": len(content)
        }
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/files")
async def list_files():
    """Список всех загруженных файлов"""
    files = []
    if os.path.exists("uploads"):
        for filename in os.listdir("uploads"):
            file_path = os.path.join("uploads", filename)
            if os.path.isfile(file_path):
                stat = os.stat(file_path)
                files.append({
                    "name": filename,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    return {"files": files}

# =============================================================================
# БОТ МОДУЛЬ (с улучшенной обработкой)
# =============================================================================

@app.post("/bot/start")
async def start_bot():
    """Запуск бота"""
    try:
        if modules["status"]["bot"]["status"] != "loaded":
            raise HTTPException(
                status_code=501, 
                detail=f"Bot module not available: {modules['status']['bot'].get('error', 'Unknown error')}"
            )
        
        # Пробуем разные функции запуска
        start_func = (get_bot_function("start_bot") or 
                     get_bot_function("main") or 
                     get_bot_function("bot_main"))
        
        if not start_func:
            raise HTTPException(status_code=501, detail="No start function found in bot module")
        
        if bot_status["is_running"]:
            return {"message": "Bot is already running", "status": "running"}
        
        # Запускаем бота
        import threading
        
        def run_bot():
            try:
                start_func()
                update_bot_status(True)
            except Exception as e:
                update_bot_status(False, f"Bot error: {str(e)}")
                logger.error(f"Bot execution error: {e}")
        
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
        update_bot_status(True)
        return {"message": "Bot started successfully", "status": "running"}
        
    except Exception as e:
        error_msg = f"Failed to start bot: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@app.post("/bot/stop")
async def stop_bot():
    """Остановка бота"""
    try:
        stop_func = get_bot_function("stop_bot")
        if stop_func:
            stop_func()
        
        update_bot_status(False)
        return {"message": "Bot stopped successfully", "status": "stopped"}
        
    except Exception as e:
        error_msg = f"Failed to stop bot: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

# =============================================================================
# XRAY МОДУЛЬ (с улучшенной обработкой)
# =============================================================================

@app.post("/xray/process")
async def process_xray_image(file: UploadFile = File(...)):
    """Обработка XRay изображения"""
    try:
        if modules["status"]["xray_manager"]["status"] != "loaded":
            raise HTTPException(
                status_code=501, 
                detail=f"XRay manager not available: {modules['status']['xray_manager'].get('error', 'Unknown error')}"
            )
        
        # Пробуем разные функции обработки
        process_func = (get_xray_function("process_xray") or 
                       get_xray_function("process_image") or 
                       get_xray_function("analyze_image") or
                       get_xray_function("analyze_xray"))
        
        if not process_func:
            raise HTTPException(status_code=501, detail="No processing function found in xray_manager")
        
        # Сохраняем временный файл
        temp_path = f"temp/{file.filename}"
        with open(temp_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Обрабатываем изображение
        result = process_func(temp_path)
        
        # Удаляем временный файл
        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return {
            "status": "success",
            "result": result,
            "filename": file.filename
        }
        
    except Exception as e:
        logger.error(f"XRay processing error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"XRay processing failed: {str(e)}")

# =============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# =============================================================================

@app.on_event("startup")
async def startup_event():
    """Действия при запуске приложения"""
    logger.info("🚀 ZetayKe Bot API starting up...")
    logger.info(f"📁 Working directory: {os.getcwd()}")
    logger.info(f"🔧 Loaded modules: {modules['status']}")
    logger.info("✅ Application startup completed")

@app.on_event("shutdown")
async def shutdown_event():
    """Действия при остановке приложения"""
    logger.info("🛑 ZetayKe Bot API shutting down...")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8443))
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=True
    )
