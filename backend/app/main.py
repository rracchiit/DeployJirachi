import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import apps, health

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="CloudForge API", version="0.2.0")

# DEV ONLY: allows the static dashboard (file:// or another port) to call the API.
# Restrict allow_origins to your real frontend origin before any real deployment.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(health.router)
app.include_router(apps.router)
