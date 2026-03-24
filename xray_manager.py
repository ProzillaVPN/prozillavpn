import os
import uuid
import httpx
import logging
from urllib.parse import quote

class XrayManager:
    def __init__(self):
        self.api_url = os.getenv("XRAY_API_URL", "http://72.56.22.233:8002")
        self.api_key = os.getenv("XRAY_API_KEY", "daf9f2b078551349b17d039c3be16203dd04f0289ef24f08132f46a3826a4f38")

    async def add_user(self, email: str, uuid_str: str = None):
        """Добавляет пользователя через VPS API"""
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

            data = response.json()
            logger.info(f"📥 add-user response: {data}")

            if response.status_code == 200 and data.get("success"):
                logger.info(f"✅ User {email} added successfully")
                return True, data.get("uuid")

            logger.error(f"❌ Failed to add user {email}: {data}")
            return False, data.get("error")

        except Exception as e:
            logger.error(f"❌ Error adding user via VPS API: {e}")
            return False, None

    async def remove_user(self, email: str):
        """Удаляет пользователя через VPS API"""
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

            data = response.json()
            logger.info(f"📥 remove-user response: {data}")

            if response.status_code == 200 and data.get("success"):
                logger.info(f"✅ User {email} removed successfully")
                return True

            logger.error(f"❌ Failed to remove user {email}: {data}")
            return False

        except Exception as e:
            logger.error(f"❌ Error removing user via VPS API: {e}")
            return False

    async def get_user(self, user_uuid: str):
        """Проверяет пользователя через VPS API"""
        try:
            logger.info(f"🔄 Checking user via VPS API: {user_uuid}")

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.api_url}/user/{user_uuid}",
                    headers={
                        "X-API-Key": self.api_key
                    }
                )

            data = response.json()
            logger.info(f"📥 get-user response: {data}")
            return data

        except Exception as e:
            logger.error(f"❌ Error checking user via VPS API: {e}")
            return {"exists": False, "error": str(e)}

def generate_vless_key(uuid_str: str, email: str) -> str:
    server_ip = "72.56.22.233"
    port = 2053
    public_key = "iD8DdcMv8KUDhdM6Khntu36PCfCMGm2XQOI3ma2JFhk"
    short_id = "653913be"
    server_name = "www.google.com"
    remark = quote(email)

    return (
        f"vless://{uuid_str}@{server_ip}:{port}"
        f"?type=tcp"
        f"&security=reality"
        f"&pbk={public_key}"
        f"&fp=chrome"
        f"&sni={server_name}"
        f"&sid={short_id}"
        f"&spx=%2F"
        f"&flow="
        f"&encryption=none"
        f"#{remark}"
    )

@dp.message(Command("testvpn"))
async def test_vpn(message: types.Message):
    user_id = message.from_user.id
    email = f"user_{user_id}"

    xray = XrayManager()
    success, result = await xray.add_user(email=email)

    if not success:
        await message.answer(f"❌ Не удалось создать VPN ключ\nОшибка: {result}")
        return

    user_uuid = result
    vless_key = generate_vless_key(user_uuid, email)

    await message.answer(
        "✅ Тестовый VPN ключ создан:\n\n"
        f"`{vless_key}`",
        parse_mode="Markdown"
    )