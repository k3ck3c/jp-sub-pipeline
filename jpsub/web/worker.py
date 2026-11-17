"""Worker en thread dans le serveur : traite les jobs un par un."""

import threading
import time
import traceback

from ..pipeline import Rejected, run_pipeline


class Cancelled(Exception):
    pass


class Worker:
    def __init__(self, db, cfg, on_done=None):
        self.db = db
        self.cfg = cfg
        self.on_done = on_done
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.current_id = None
        self.thread = threading.Thread(target=self._loop, name="jpsub-worker", daemon=True)

    def start(self):
        self.thread.start()

    def notify(self):
        self.wake.set()

    def _loop(self):
        while not self.stop.is_set():
            job = self.db.claim_next()
            if not job:
                self.wake.wait(timeout=5)
                self.wake.clear()
                continue
            self._run(job)

    def _run(self, job):
        job_id = job["id"]
        self.current_id = job_id
        last_write = [0.0]

        def log(msg):
            print(f"[job {job_id}] {msg}", flush=True)
            self.db.append_log(job_id, str(msg))

        def on_event(ev):
            if self.db.status_of(job_id) == "cancelled":
                raise Cancelled()
            now = time.monotonic()
            # Limite les écritures pendant la transcription (une par seconde max)
            if ev["status"] == "running" and ev.get("progress", 0) > 0 and now - last_write[0] < 1:
                return
            last_write[0] = now
            fields = dict(stage=ev["stage"], stage_label=ev["label"], stage_index=ev["index"],
                          total=ev["total"], progress=ev.get("progress", 0))
            for key in ("out_dir", "title", "artist"):
                if ev.get(key):
                    fields[key] = ev[key]
            self.db.update_job(job_id, **fields)

        try:
            result = run_pipeline(job["input"], self.cfg, force_ja=job["force_ja"], on_event=on_event, log=log)
            self.db.update_job(job_id, status="done", progress=1, result=result, title=result["title"],
                               artist=result["artist"], out_dir=result["out_dir"], finished_at=time.time(),
                               message="Terminé")
        except Cancelled:
            log("Annulé")
            self.db.update_job(job_id, status="cancelled", message="Annulé", finished_at=time.time())
        except Rejected as e:
            log(f"[REJET] {e}")
            self.db.update_job(job_id, status="rejected", message=str(e), finished_at=time.time(),
                               title=getattr(e, "title", None), artist=getattr(e, "artist", None),
                               out_dir=getattr(e, "out_dir", None))
        except Exception as e:
            log(traceback.format_exc())
            self.db.update_job(job_id, status="error", message=f"{type(e).__name__}: {e}",
                               finished_at=time.time())
        finally:
            self.current_id = None
            if self.on_done:
                self.on_done()
