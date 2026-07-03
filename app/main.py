from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import connect_db, close_db
from app.routes import auth, users, kaizens, action_plans, dashboards, reparti, uploads, documenti, configurazioni, pillars, skill_matrix

app = FastAPI(title="SheetKaizen API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    await connect_db()


@app.on_event("shutdown")
async def shutdown():
    await close_db()


@app.get("/")
async def root():
    return {"status": "ok", "app": "SheetKaizen API", "version": "1.1.0"}


app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(reparti.router, prefix="/api/reparti", tags=["Reparti"])
app.include_router(kaizens.router, prefix="/api/kaizens", tags=["Kaizens"])
app.include_router(action_plans.router, prefix="/api/action-plans", tags=["Action Plans"])
app.include_router(dashboards.router, prefix="/api/dashboards", tags=["Dashboards"])
app.include_router(uploads.router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(documenti.router, prefix="/api/documenti", tags=["Documenti"])
app.include_router(configurazioni.router, prefix="/api/configurazioni", tags=["Configurazioni"])
app.include_router(pillars.router, prefix="/api/pillars", tags=["Pillars"])
app.include_router(skill_matrix.router, prefix="/api", tags=["skill_matrix"])
