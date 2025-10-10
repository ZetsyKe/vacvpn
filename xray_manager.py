import httpx
import json
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

class XrayManager:
    def __init__(self, api_url: str = "http://127.0.0.1:8080"):
        self.api_url = api_url
        
    async def add_user(self, email: str, uuid: str) -> bool:
        """Добавить пользователя в Xray"""
        try:
            async with httpx.AsyncClient() as client:
                # Добавляем пользователя
                response = await client.post(
                    f"{self.api_url}/add",
                    json={
                        "email": email,
                        "level": 0,
                        "inboundTag": "proxy",
                        "settings": {
                            "clients": [
                                {
                                    "id": uuid,
                                    "flow": "xtls-rprx-vision",
                                    "email": email
                                }
                            ]
                        }
                    }
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ User {email} added to Xray")
                    return True
                else:
                    logger.error(f"❌ Failed to add user {email}: {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error adding user to Xray: {e}")
            return False
    
    async def remove_user(self, email: str) -> bool:
        """Удалить пользователя из Xray"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/remove",
                    json={
                        "email": email,
                        "inboundTag": "proxy"
                    }
                )
                
                if response.status_code == 200:
                    logger.info(f"✅ User {email} removed from Xray")
                    return True
                else:
                    logger.error(f"❌ Failed to remove user {email}: {response.text}")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Error removing user from Xray: {e}")
            return False
    
    async def get_user_stats(self, email: str) -> Dict:
        """Получить статистику пользователя"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.api_url}/getUserStats?email={email}&inboundTag=proxy")
                if response.status_code == 200:
                    return response.json()
                return {}
        except Exception as e:
            logger.error(f"❌ Error getting user stats: {e}")
            return {}
