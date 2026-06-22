"""Cleanup DB SheetKaizen — drop configurazioni vecchie"""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def cleanup():
    client = AsyncIOMotorClient(os.getenv("MONGODB_URL"))
    db = client[os.getenv("DB_NAME", "sheetkaizen")]
    
    r1 = await db.configurazioni.delete_many({})
    print(f"✅ Configurazioni eliminate: {r1.deleted_count}")
    
    r2 = await db.reparti.delete_many({})
    print(f"✅ Reparti eliminati: {r2.deleted_count}")
    
    client.close()

if __name__ == "__main__":
    asyncio.run(cleanup())
