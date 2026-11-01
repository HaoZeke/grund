"""HTTP API and the bilingual chat page."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from grund.engine import Engine
from grund_index.catalogue import Catalogue
from grund_index.client import PxWebClient
from grund_rails.vangrail_client import require_checker

ROOT = Path(__file__).resolve().parents[2]
INDEX = Path(os.environ.get("GRUND_INDEX", ROOT / "data" / "index"))
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    require_checker()
    get_engine()
    yield


app = FastAPI(title="Grund", version="0.1.0", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if not (INDEX / "manifest.json").exists():
            raise FileNotFoundError(f"index not built at {INDEX}")
        catalogue = Catalogue.load(INDEX)
        _engine = Engine(catalogue, client=PxWebClient(cache_dir=ROOT / "data" / "cache", rate=4.0))
    return _engine


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    language: str | None = None


EXAMPLES = {
    "en": [
        "What was the consumer price index in June 2024?",
        "What was the annual change in the consumer price index in June 2025?",
        "How many females were there in the population by sex and age in 2024?",
        "How many people moved within Iceland in 2024?",
    ],
    "is": [
        "Hver var vísitala neysluverðs í júní 2024?",
        "Hver var árleg breyting vísitölu neysluverðs í júní 2025?",
        "Hversu margar konur voru í mannfjölda eftir kyni og aldri árið 2024?",
        "Hversu margir fluttu búferlum innanlands árið 2024?",
    ],
}


@app.get("/api/health")
def health() -> dict:
    manifest_path = INDEX / "manifest.json"
    if not manifest_path.exists():
        return {"ok": False, "index": str(INDEX), "detail": "index not built"}
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checker = require_checker()
    return {
        "ok": True,
        "index": manifest,
        "planner": os.environ.get("GRUND_PLANNER", "auto"),
        "checker": {"offline": False, "mode": checker.get("mode"), "via": checker.get("via")},
    }


@app.get("/api/examples")
def examples() -> dict:
    return EXAMPLES


@app.post("/api/ask")
def ask(body: AskRequest) -> dict:
    try:
        engine = get_engine()
    except FileNotFoundError as exc:
        return {"answer": str(exc), "refused": True, "clarify": False, "source": None, "rails": [], "candidates": []}
    return engine.ask(body.question, body.language)


def _mount_ui() -> None:
    if not WEB.exists():
        return
    assets = WEB / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    @app.get("/favicon.svg")
    def favicon() -> FileResponse:
        return FileResponse(WEB / "favicon.svg")

    @app.get("/icons.svg")
    def icons() -> FileResponse:
        return FileResponse(WEB / "icons.svg")


_mount_ui()
