from fastapi import FastAPI

from app.api import router as api_router

app = FastAPI(title="Telegram Parser Scheduler", version="0.1.0")
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "scheduler", "status": "ok"}


