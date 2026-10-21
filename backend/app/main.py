
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import apps

app = FastAPI(title="CloudForge API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500", "http://localhost:5500"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(apps.router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
