from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings


class Database:
    client: AsyncIOMotorClient = None
    db = None


database = Database()


async def connect_db():
    database.client = AsyncIOMotorClient(settings.MONGODB_URI)
    database.db = database.client.sheetkaizen
    print("✅ Connesso a MongoDB Atlas - SheetKaizen")


async def close_db():
    if database.client:
        database.client.close()
        print("❌ Disconnesso da MongoDB")


def get_db():
    return database.db
