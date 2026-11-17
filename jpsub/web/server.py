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
from starlette.background import BackgroundTask
from pydantic import BaseModel

from .. import anki, study, translate
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


class LineEdit(BaseModel):
    text: str


class Review(BaseModel):
    reviewed: bool = True


class Words(BaseModel):
    words: list[str]


class WordStatus(BaseModel):
    word: str
    status: str | None = None   # known | anki | None


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

    def _song_or_404(artist_dir, video_id):
        data = library.song(artist_dir, video_id)
        if not data:
            raise HTTPException(404, "Chanson introuvable")
        return data

    def _with_study_info(data):
        """Ajoute au vocabulaire le sens connu, le statut (connu / dans Anki) et la fréquence."""
        words = [v["word"] for v in data["vocab"]]
        meanings, statuses = db.meanings(words), db.word_statuses(words)
        across = library.songs_with_word()
        for v in data["vocab"]:
            v["meaning"] = meanings.get(v["word"], "")
            v["status"] = statuses.get(v["word"])
            v["songs"] = across.get(v["word"], 1)
        for line in data["lines"]:
            line.pop("clip_path", None)
        data.pop("dir", None)
        data["translation_available"] = bool(os.environ.get("DEEPL_API_KEY"))
        return data

    @app.get("/api/songs/{artist_dir}/{video_id}")
    def song(artist_dir: str, video_id: str):
        return _with_study_info(_song_or_404(artist_dir, video_id))

    @app.get("/api/songs/{artist_dir}/{video_id}/waveform")
    def song_waveform(artist_dir: str, video_id: str):
        data = _song_or_404(artist_dir, video_id)
        if not data["audio"]:
            raise HTTPException(404, "Pas d'audio")
        d = library.song_dir(artist_dir, video_id)
        return study.waveform(d, d / data["audio"])

    @app.put("/api/songs/{artist_dir}/{video_id}/lines/{index}")
    def edit_line(artist_dir: str, video_id: str, index: int, body: LineEdit):
        d = library.song_dir(artist_dir, video_id)
        if d is None:
            raise HTTPException(404)
        if not body.text.strip():
            raise HTTPException(400, "Ligne vide")
        try:
            study.edit_line(d, index, body.text)
        except IndexError:
            raise HTTPException(404, "Ligne introuvable")
        library.invalidate()
        return _with_study_info(_song_or_404(artist_dir, video_id))

    @app.post("/api/songs/{artist_dir}/{video_id}/lines/{index}/review")
    def review_line(artist_dir: str, video_id: str, index: int, body: Review):
        d = library.song_dir(artist_dir, video_id)
        if d is None:
            raise HTTPException(404)
        study.set_reviewed(d, index, body.reviewed)
        return {"ok": True}

    @app.post("/api/songs/{artist_dir}/{video_id}/retranslate")
    def retranslate(artist_dir: str, video_id: str):
        key = os.environ.get("DEEPL_API_KEY")
        if not key:
            raise HTTPException(400, "DEEPL_API_KEY manquante")
        d = library.song_dir(artist_dir, video_id)
        if d is None:
            raise HTTPException(404)
        try:
            done = study.retranslate(d, key, cfg["translation"]["target_lang"])
        except Exception as e:
            raise HTTPException(502, f"DeepL : {e}")
        return {"retranslated": done, "song": _with_study_info(_song_or_404(artist_dir, video_id))}

    @app.get("/media/{artist_dir}/{video_id}/{filename}")
    def media(artist_dir: str, video_id: str, filename: str):
        path = library.media_path(artist_dir, video_id, filename)
        if not path:
            raise HTTPException(404)
        return FileResponse(path)

    # --- mots & Anki -----------------------------------------------------------
    @app.post("/api/meanings")
    def meanings(body: Words):
        """Sens des mots, traduits par DeepL en un seul lot puis gardés en cache."""
        words = list(dict.fromkeys(w for w in body.words if w))[:200]
        known = db.meanings(words)
        missing = [w for w in words if w not in known]
        key = os.environ.get("DEEPL_API_KEY")
        if missing and key:
            try:
                for start in range(0, len(missing), 50):
                    chunk = missing[start:start + 50]
                    for w, m in zip(chunk, translate.translate_batch(chunk, key, cfg["translation"]["target_lang"])):
                        db.set_meaning(w, m)
                        known[w] = m
            except Exception as e:
                print(f"[meanings] DeepL : {e}")
        return {"meanings": known, "translation_available": bool(key)}

    @app.post("/api/words/status")
    def word_status(body: WordStatus):
        if body.status not in (None, "known", "anki"):
            raise HTTPException(400, "Statut inconnu")
        db.set_word_status(body.word, body.status)
        return {"ok": True}

    def _cards(artist_dir, video_id, words):
        data = _song_or_404(artist_dir, video_id)
        cards = study.word_cards(data, words, db.meanings(words))
        if not cards:
            raise HTTPException(400, "Aucun mot sélectionné")
        return data, cards

    @app.get("/api/anki/status")
    def anki_status():
        try:
            return {"ok": True, "version": anki.anki_request("version"), "url": anki.anki_url()}
        except Exception as e:
            return {"ok": False, "error": str(e), "url": anki.anki_url()}

    @app.post("/api/songs/{artist_dir}/{video_id}/anki")
    def send_to_anki(artist_dir: str, video_id: str, body: Words):
        data, cards = _cards(artist_dir, video_id, body.words)
        try:
            stats = anki.push_word_cards(cards, deck=f"JP::{data['artist']}::Mots")
        except Exception as e:
            raise HTTPException(502, f"Anki injoignable ({anki.anki_url()}) : {e}")
        for c in cards:
            db.set_word_status(c["word"], "anki")
        return stats

    @app.post("/api/songs/{artist_dir}/{video_id}/apkg")
    def export_apkg(artist_dir: str, video_id: str, body: Words):
        data, cards = _cards(artist_dir, video_id, body.words)
        path = study.build_apkg(cards, f"JP::{data['artist']}::Mots")
        for c in cards:
            db.set_word_status(c["word"], "anki")
        name = f"jpsub-{data['artist_dir']}-{video_id}.apkg"
        return FileResponse(path, filename=name, media_type="application/octet-stream",
                            background=BackgroundTask(os.remove, path))

    # --- interface -------------------------------------------------------------
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app


def serve(config_path="config.yaml", host="127.0.0.1", port=8000):
    import uvicorn

    uvicorn.run(create_app(config_path), host=host, port=port, log_level="info")
