"""Permanent storage and analysis of uploaded dive logs.

This module is framework-agnostic (no FastAPI/HTTP here) so it can be reused by
the web app, the CLI, or tests.  Uploaded files are stored permanently under a
random per-upload id; each analysis result is recorded in an index.
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone

from .calculator import compute_dssg
from .parser import parse_dive_log
from .report import write_report
from .statistics_report import build_statistics, summarise_dive

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UID_RE = re.compile(r"^[0-9a-f]{32}$")


def sanitise_filename(name: str) -> str:
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    name = name.lstrip(".") or "upload"
    return name[:120]


class DiveStore:
    """Stores raw uploads permanently and keeps the generated reports."""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = os.path.abspath(data_dir)
        self.uploads_dir = os.path.join(self.data_dir, "uploads")
        self.reports_dir = os.path.join(self.data_dir, "reports")
        self.index_path = os.path.join(self.data_dir, "index.json")
        self._lock = threading.Lock()
        os.makedirs(self.uploads_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)

    # -- index ------------------------------------------------------------- #
    def _load_index(self) -> list[dict]:
        if not os.path.exists(self.index_path):
            return []
        try:
            with open(self.index_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, entries: list[dict]) -> None:
        tmp = self.index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2)
        os.replace(tmp, self.index_path)

    def entries(self) -> list[dict]:
        with self._lock:
            return self._load_index()

    def entry(self, uid: str) -> dict | None:
        if not UID_RE.match(uid):
            return None
        for e in self.entries():
            if e.get("id") == uid:
                return e
        return None

    # -- ingest ------------------------------------------------------------ #
    def add(self, filename: str, data: bytes) -> dict:
        """Store ``data`` permanently and analyse it. Always keeps the file."""
        uid = uuid.uuid4().hex
        safe_name = sanitise_filename(filename)
        up_dir = os.path.join(self.uploads_dir, uid)
        os.makedirs(up_dir, exist_ok=True)
        stored = os.path.join(up_dir, safe_name)
        with open(stored, "wb") as fh:
            fh.write(data)

        entry = {
            "id": uid,
            "filename": safe_name,
            "size": len(data),
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "ok",
        }
        try:
            fmt, dives = parse_dive_log(stored)
            if not dives:
                raise ValueError("no dives with a depth/time profile were found")
            results = [compute_dssg(d) for d in dives]
            summaries = [summarise_dive(d, r) for d, r in zip(dives, results)]
            stats = build_statistics(summaries)
            write_report(os.path.join(self.reports_dir, uid),
                         dives, results, summaries, stats)
            entry.update(format=fmt, dive_count=len(dives),
                         mean_dssg=stats["dssg"].get("mean"))
        except Exception as exc:  # noqa: BLE001 - record, keep the raw file
            entry.update(status="error", error=str(exc))

        with self._lock:
            entries = self._load_index()
            entries.insert(0, entry)
            self._save_index(entries)
        return entry

    def statistics(self, uid: str) -> dict | None:
        """Return the saved statistics.json for an analysis, if any."""
        path = self.report_file(uid, "statistics.json")
        if not path:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    # -- safe path resolution --------------------------------------------- #
    def report_file(self, uid: str, filename: str) -> str | None:
        if not UID_RE.match(uid):
            return None
        base = os.path.realpath(os.path.join(self.reports_dir, uid))
        target = os.path.realpath(os.path.join(base, filename or "index.html"))
        if target != base and not target.startswith(base + os.sep):
            return None
        return target if os.path.isfile(target) else None

    def original_file(self, uid: str) -> str | None:
        if not UID_RE.match(uid):
            return None
        up_dir = os.path.join(self.uploads_dir, uid)
        if not os.path.isdir(up_dir):
            return None
        files = os.listdir(up_dir)
        return os.path.join(up_dir, files[0]) if files else None
