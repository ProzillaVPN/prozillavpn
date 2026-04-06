import os
import uuid
import httpx
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


class XrayManager:
    def __init__(self):
        self.api_url = os.getenv("XRAY_API_URL", "http://72.56.22.233:8002")
        self.api_key = os.getenv("XRAY_API_KEY", "daf9f2b078551349b17d039c3be16203dd04f0289ef24f08132f46a3826a4f38")

    async def add_user(self, email: str, uuid_str: str = None):
        try:
            logger.info(f"🔄 Adding user via VPS API: {email}")

            if not uuid_str:
                uuid_str = str(uuid.uuid4())

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.api_url}/add-user",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "email": email,
                        "uuid": uuid_str
                    }
                )

            try:
                data = response.json()
            except Exception:
                logger.error(f"❌ Invalid JSON from VPS API: {response.text}")
                return False, "Invalid JSON response"

            logger.info(f"📥 add-user response: {data}")

            if response.status_code == 200 and data.get("success"):
                logger.info(f"✅ User {email} added successfully")
                return True, data.get("uuid")

            logger.error(f"❌ Failed to add user {email}: {data}")
            return False, data.get("error", "Unknown API error")

        except Exception as e:
            logger.exception(f"❌ Error adding user via VPS API")
            return False, str(e)

    async def remove_user(self, email: str):
        try:
            logger.info(f"🔄 Removing user via VPS API: {email}")

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.api_url}/remove-user",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "email": email
                    }
                )

            try:
                data = response.json()
            except Exception:
                logger.error(f"❌ Invalid JSON from VPS API: {response.text}")
                return False

            logger.info(f"📥 remove-user response: {data}")

            if response.status_code == 200 and data.get("success"):
                logger.info(f"✅ User {email} removed successfully")
                return True

            logger.error(f"❌ Failed to remove user {email}: {data}")
            return False

        except Exception as e:
            logger.exception(f"❌ Error removing user via VPS API")
            return False

    async def get_user(self, user_uuid: str):
        try:
            logger.info(f"🔄 Checking user via VPS API: {user_uuid}")

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.api_url}/user/{user_uuid}",
                    headers={
                        "Authorization": f"Bearer {self.api_key}"
                    }
                )

            try:
                data = response.json()
            except Exception:
                logger.error(f"❌ Invalid JSON from VPS API: {response.text}")
                return {"exists": False, "error": "Invalid JSON response"}

            logger.info(f"📥 get-user response: {data}")
            return data

        except Exception as e:
            logger.exception(f"❌ Error checking user via VPS API")
            return {"exists": False, "error": str(e)}


def generate_vless_key(uuid_str: str, email: str) -> str:
    server_ip = "72.56.22.233"
    port = 2053
    public_key = "iD8DdcMv8KUDhdM6Khntu36PCfCMGm2XQOI3ma2JFhk"
    short_id = "653913be"
    server_name = "www.google.com"
    remark = quote(email)

    query_parts = [
        "type=tcp",
        "security=reality",
        f"pbk={public_key}",
        "fp=chrome",
        f"sni={server_name}",
        f"sid={short_id}",
        "spx=%2F",
        "encryption=none",
    ]

    return f"vless://{uuid_str}@{server_ip}:{port}?{'&'.join(query_parts)}#{remark}"
