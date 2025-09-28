from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="VAC VPN API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Проверяем Firebase
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    
    # Пытаемся инициализировать Firebase
    if not firebase_admin._apps:
        # Используем переменные окружения
        firebase_config = {
            "type": "service_account",
            "project_id": os.getenv("FIREBASE_PROJECT_ID"),
            "private_key_id": os.getenv("FIREBASE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("FIREBASE_PRIVATE_KEY", "").replace('\\n', '\n'),
            "client_email": os.getenv("FIREBASE_CLIENT_EMAIL"),
            "client_id": os.getenv("FIREBASE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        }
        
        cred = credentials.Certificate(firebase_config)
        firebase_admin.initialize_app(cred)
        db = firestore.client()
        logger.info("Firebase initialized successfully")
    else:
        db = firestore.client()
        
except Exception as e:
    logger.error(f"Firebase initialization failed: {e}")
    db = None

@app.get("/")
async def root():
    firebase_status = "connected" if db else "disconnected"
    return {"message": "VAC VPN API is running", "status": "ok", "firebase": firebase_status}

@app.get("/health")
async def health():
    return {"status": "healthy", "firebase": "connected" if db else "disconnected"}

# Тестовый эндпоинт для работы с Firebase
@app.post("/test-user")
async def test_user(user_id: str):
    if not db:
        return {"error": "Firebase not connected"}
    
    try:
        user_ref = db.collection('users').document(user_id)
        user_ref.set({
            'user_id': user_id,
            'created_at': firestore.SERVER_TIMESTAMP,
            'test': True
        })
        return {"success": True, "user_id": user_id}
    except Exception as e:
        return {"error": str(e)}

@app.get("/test-user/{user_id}")
async def get_test_user(user_id: str):
    if not db:
        return {"error": "Firebase not connected"}
    
    try:
        user_ref = db.collection('users').document(user_id)
        user = user_ref.get()
        if user.exists:
            return user.to_dict()
        else:
            return {"error": "User not found"}
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
