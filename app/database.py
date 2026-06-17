from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client: AsyncIOMotorClient = None
db = None


async def connect_db():
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URI)
    db = client.sheetkaizen
    print("✅ Connesso a MongoDB Atlas - SheetKaizen")


async def close_db():
    global client
    if client:
        client.close()
        print("❌ Disconnesso da MongoDB")
