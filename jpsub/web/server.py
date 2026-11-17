"""Serveur FastAPI : API REST + progression SSE + interface statique.

Un seul process : l'API, le worker (thread) et SQLite.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import anki, translate
from ..config import load_config
from ..pipeline import set_language_override
from ..utils import is_url
from .db import DB
from .library import Library
from .worker import Worker

STATIC_DIR = Path(__file__).parent / "static"


class NewJobs(BaseModel):
    urls: list[str]
    force_ja: bool = False


class Retry(BaseModel):
    force_ja: bool | None = None


class WordCard(BaseModel):
    song: str          # « artist_dir/video_id »
    line: int
    word: str
    reading: str = ""
    meaning: str = ""


def create_app(config_path: str = "config.yaml", start_worker: bool = True) -> FastAPI:
    cfg = load_config(config_path)
    db = DB(cfg["paths"]["db"])
    library = Library(cfg["paths"]["output_dir"])
    worker = Worker(db, cfg)

    @asynccontextmanager
    async def lifespan(_app):
        if start_worker:
            worker.start()
        yield
        worker.stop.set()
        worker.notify()

    app = FastAPI(title="jpsub", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
    app.state.cfg, app.state.db, app.state.library, app.state.worker = cfg, db, library, worker

    # --- jobs ----------------------------------------------------------------
    @app.get("/api/jobs")
    def list_jobs():
        return {"jobs": db.list_jobs(), "current": worker.current_id}

    @app.post("/api/jobs")
    def add_jobs(body: NewJobs):
        ids = []
        for raw in body.urls:
            value = raw.strip()
            if not value or value.startswith("#"):
                continue
            if not is_url(value) and not os.path.exists(value):
                raise HTTPException(400, f"Ni URL ni fichier local : {value}")
            ids.append(db.add_job(value, body.force_ja))
        worker.notify()
        return {"ids": ids}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: int):
        job = db.get_job(job_id, with_log=True)
        if not job:
            raise HTTPException(404)
        return job

    @app.post("/api/jobs/{job_id}/retry")
    def retry_job(job_id: int, body: Retry):
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(404)
        if job["status"] in ("queued", "running"):
            raise HTTPException(409, "Job déjà en cours")
        if body.force_ja and job.get("out_dir") and os.path.isdir(job["out_dir"]):
            set_language_override(job["out_dir"], True)
        db.requeue(job_id, force_ja=body.force_ja)
        worker.notify()
        return {"ok": True}

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int):
        job = db.get_job(job_id)
        if not job:
            raise HTTPException(404)
        if job["status"] in ("queued", "running"):
            db.update_job(job_id, status="cancelled", message="Annulé")
        return {"ok": True}

    @app.get("/api/events")
    async def events():
        """Envoie la liste des jobs à chaque changement (SSE)."""
        async def stream():
            last = None
            while True:
                stamp = (db.last_change(), worker.current_id)
                if stamp != last:
                    last = stamp
                    payload = json.dumps({"jobs": db.list_jobs(20), "current": worker.current_id},
                                         ensure_ascii=False)
                    yield f"event: jobs\ndata: {payload}\n\n"
                else:
                    yield ": ping\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- bibliothèque ----------------------------------------------------------
    @app.get("/api/artists")
    def artists():
        return {"artists": library.artists()}

    @app.get("/api/songs")
    def songs(artist: str | None = None, q: str | None = None):
        items = library.songs()
        if artist:
            items = [s for s in items if s["artist_dir"] == artist]
        if q:
            ql = q.lower()
            items = [s for s in items if ql in f"{s['title']} {s['artist']} {s['title_fr']}".lower()]
        return {"songs": items}

    @app.get("/api/songs/{artist_dir}/{video_id}")
    def song(artist_dir: str, video_id: str):
        data = library.song(artist_dir, video_id)
        if not data:
            raise HTTPException(404, "Chanson introuvable")
        return data

    @app.get("/media/{artist_dir}/{video_id}/{filename}")
    def media(artist_dir: str, video_id: str, filename: str):
        path = library.media_path(artist_dir, video_id, filename)
        if not path:
            raise HTTPException(404)
        return FileResponse(path)

    # --- mots & Anki -----------------------------------------------------------
    @app.get("/api/word")
    def word(w: str):
        meaning = db.get_meaning(w)
        key = os.environ.get("DEEPL_API_KEY")
        if meaning is None and key:
            try:
                meaning = translate.translate_text(w, key, cfg["translation"]["target_lang"])
                db.set_meaning(w, meaning)
            except Exception as e:
                meaning = None
                print(f"[word] DeepL : {e}")
        return {"word": w, "meaning": meaning or "", "count": library.word_count(w),
                "translation_available": bool(key)}

    @app.get("/api/anki/status")
    def anki_status():
        try:
            version = anki.anki_request("version")
            return {"ok": True, "version": version, "url": anki.anki_url()}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": anki.anki_url()}

    @app.post("/api/anki/word")
    def anki_word(body: WordCard):
        artist_dir, _, video_id = body.song.partition("/")
        data = library.song(artist_dir, video_id)
        if not data or not (0 <= body.line < len(data["lines"])):
            raise HTTPException(404, "Ligne introuvable")
        line = data["lines"][body.line]
        clip_path = None
        if line["clip"]:
            clip_path = str(library.media_path(artist_dir, video_id, line["clip"]) or "")
        try:
            note_id = anki.push_word_card(
                word=body.word, reading=body.reading, meaning=body.meaning or (db.get_meaning(body.word) or ""),
                sentence=line["text"], sentence_fr=line["fr"], audio_file=line["clip"], audio_path=clip_path,
                source=f"{data['artist']} — {data['title']}", deck=f"JP::{data['artist']}::Mots",
            )
        except Exception as e:
            msg = str(e)
            if "duplicate" in msg.lower():
                raise HTTPException(409, "Carte déjà présente dans Anki")
            raise HTTPException(502, f"Anki injoignable ou erreur : {msg}")
        return {"ok": True, "note_id": note_id}

    # --- interface -------------------------------------------------------------
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def serve(config_path="config.yaml", host="127.0.0.1", port=8000):
    import uvicorn

    uvicorn.run(create_app(config_path), host=host, port=port, log_level="info")
