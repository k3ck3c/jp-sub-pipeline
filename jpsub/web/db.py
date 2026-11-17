"""Base SQLite : la table `jobs` sert aussi de file d'attente (un seul worker)."""

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input TEXT NOT NULL,
    force_ja INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | running | done | error | rejected | cancelled
    stage TEXT, stage_label TEXT, stage_index INTEGER, total INTEGER,
    progress REAL DEFAULT 0,
    message TEXT,
    title TEXT, artist TEXT, out_dir TEXT,
    result TEXT,
    log TEXT DEFAULT '',
    created_at REAL, updated_at REAL, started_at REAL, finished_at REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, id);
CREATE TABLE IF NOT EXISTS word_meanings (
    word TEXT PRIMARY KEY,
    meaning TEXT,
    created_at REAL
);
-- Suivi d'apprentissage : 'known' (je connais déjà) ou 'anki' (carte créée)
CREATE TABLE IF NOT EXISTS word_status (
    word TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    updated_at REAL
);
"""

MAX_LOG_CHARS = 20000


class DB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            # Un job « running » au démarrage = le serveur s'est arrêté pendant le traitement.
            self.conn.execute("UPDATE jobs SET status='queued' WHERE status='running'")

    def _q(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args)

    # --- jobs ----------------------------------------------------------------
    def add_job(self, input_value: str, force_ja=False) -> int:
        now = time.time()
        cur = self._q("INSERT INTO jobs (input, force_ja, created_at, updated_at) VALUES (?, ?, ?, ?)",
                      (input_value, int(force_ja), now, now))
        return cur.lastrowid

    def claim_next(self):
        now = time.time()
        row = self._q(
            "UPDATE jobs SET status='running', started_at=?, updated_at=?, message=NULL "
            "WHERE id = (SELECT id FROM jobs WHERE status='queued' ORDER BY id LIMIT 1) RETURNING *",
            (now, now),
        ).fetchone()
        return dict(row) if row else None

    def update_job(self, job_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        if "result" in fields and not isinstance(fields["result"], str):
            fields["result"] = json.dumps(fields["result"], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def append_log(self, job_id: int, line: str) -> None:
        self._q(
            "UPDATE jobs SET log = substr(coalesce(log, '') || ? || char(10), -?) WHERE id=?",
            (line, MAX_LOG_CHARS, job_id),
        )

    def get_job(self, job_id: int, with_log=False):
        row = self._q("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row, with_log) if row else None

    def list_jobs(self, limit=50) -> list:
        rows = self._q("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [_job(r) for r in rows]

    def status_of(self, job_id: int):
        row = self._q("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["status"] if row else None

    def requeue(self, job_id: int, force_ja=None) -> None:
        fields = {"status": "queued", "message": None, "progress": 0, "finished_at": None}
        if force_ja is not None:
            fields["force_ja"] = int(force_ja)
        self.update_job(job_id, **fields)

    def last_change(self) -> float:
        row = self._q("SELECT max(updated_at) AS t FROM jobs").fetchone()
        return row["t"] or 0

    # --- sens des mots (cache DeepL) ----------------------------------------
    def get_meaning(self, word: str):
        row = self._q("SELECT meaning FROM word_meanings WHERE word=?", (word,)).fetchone()
        return row["meaning"] if row else None

    def set_meaning(self, word: str, meaning: str) -> None:
        self._q("INSERT OR REPLACE INTO word_meanings (word, meaning, created_at) VALUES (?, ?, ?)",
                (word, meaning, time.time()))

    def meanings(self, words) -> dict:
        words = list(words)
        if not words:
            return {}
        marks = ",".join("?" * len(words))
        rows = self._q(f"SELECT word, meaning FROM word_meanings WHERE word IN ({marks})", words).fetchall()
        return {r["word"]: r["meaning"] for r in rows}

    # --- suivi des mots ------------------------------------------------------
    def word_statuses(self, words) -> dict:
        words = list(words)
        if not words:
            return {}
        marks = ",".join("?" * len(words))
        rows = self._q(f"SELECT word, status FROM word_status WHERE word IN ({marks})", words).fetchall()
        return {r["word"]: r["status"] for r in rows}

    def set_word_status(self, word: str, status) -> None:
        if status:
            self._q("INSERT OR REPLACE INTO word_status (word, status, updated_at) VALUES (?, ?, ?)",
                    (word, status, time.time()))
        else:
            self._q("DELETE FROM word_status WHERE word=?", (word,))


def _job(row, with_log=False) -> dict:
    d = dict(row)
    d["force_ja"] = bool(d["force_ja"])
    d["result"] = json.loads(d["result"]) if d.get("result") else None
    if not with_log:
        d.pop("log", None)
    return d
