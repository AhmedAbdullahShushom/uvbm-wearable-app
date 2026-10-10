"""SQLite persistence (stdlib only). Timestamps are stored as fixed-width UTC strings."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .alerts import Alert
from .config import DEFAULT_PROFILE

FMT = "%Y-%m-%dT%H:%M:%S.%f"


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime) -> str:
    return to_utc(dt).strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT).replace(tzinfo=timezone.utc)


SCHEMA = """
CREATE TABLE IF NOT EXISTS readings(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, device_id TEXT, volume_ml REAL, smoothed_ml REAL,
  length_cm REAL, width_cm REAL, depth_cm REAL, quality REAL);
CREATE INDEX IF NOT EXISTS ix_readings_ts ON readings(ts);
CREATE TABLE IF NOT EXISTS voids(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, pre_void_ml REAL, interval_min REAL, mean_rate REAL);
CREATE TABLE IF NOT EXISTS intake(id INTEGER PRIMARY KEY, ts TEXT NOT NULL, volume_ml REAL);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, level TEXT, message TEXT, fraction REAL, eta_min REAL);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- helpers
    def _all(self, sql: str, args: tuple = ()) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def _run(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid

    # -- readings
    def add_reading(self, ts, device_id, volume, smoothed, l, w, d, quality) -> None:
        self._run("INSERT INTO readings(ts,device_id,volume_ml,smoothed_ml,length_cm,width_cm,"
                  "depth_cm,quality) VALUES(?,?,?,?,?,?,?,?)",
                  (iso(ts), device_id, volume, smoothed, l, w, d, quality))

    def latest_reading_ts(self) -> Optional[datetime]:
        r = self._all("SELECT MAX(ts) AS ts FROM readings")
        return parse(r[0]["ts"]) if r and r[0]["ts"] else None

    def readings_since(self, since: Optional[datetime]) -> List[Dict[str, Any]]:
        if since is None:
            rows = self._all("SELECT * FROM readings ORDER BY ts")
        else:
            rows = self._all("SELECT * FROM readings WHERE ts > ? ORDER BY ts", (iso(since),))
        for r in rows:
            r["ts"] = parse(r["ts"])
        return rows

    # -- voids
    def add_void(self, ts, pre_void_ml, interval_min, mean_rate) -> None:
        self._run("INSERT INTO voids(ts,pre_void_ml,interval_min,mean_rate) VALUES(?,?,?,?)",
                  (iso(ts), pre_void_ml, interval_min, mean_rate))

    def last_void_ts(self) -> Optional[datetime]:
        r = self._all("SELECT MAX(ts) AS ts FROM voids")
        return parse(r[0]["ts"]) if r and r[0]["ts"] else None

    def voids(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        if since is None:
            return self._all("SELECT * FROM voids ORDER BY ts")
        return self._all("SELECT * FROM voids WHERE ts >= ? ORDER BY ts", (iso(since),))

    def baseline_rate(self, n: int = 10) -> Optional[float]:
        rows = self._all("SELECT mean_rate FROM voids WHERE mean_rate IS NOT NULL "
                         "ORDER BY ts DESC LIMIT ?", (n,))
        vals = sorted(r["mean_rate"] for r in rows)
        return vals[len(vals) // 2] if vals else None

    # -- intake
    def add_intake(self, ts, volume_ml) -> None:
        self._run("INSERT INTO intake(ts,volume_ml) VALUES(?,?)", (iso(ts), volume_ml))

    def intake_between(self, start: datetime, end: datetime) -> float:
        r = self._all("SELECT COALESCE(SUM(volume_ml),0) AS s FROM intake WHERE ts > ? AND ts <= ?",
                      (iso(start), iso(end)))
        return float(r[0]["s"])

    def intakes(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        if since is None:
            return self._all("SELECT * FROM intake ORDER BY ts")
        return self._all("SELECT * FROM intake WHERE ts >= ? ORDER BY ts", (iso(since),))

    # -- alerts
    def add_alert(self, a: Alert) -> int:
        return self._run("INSERT INTO alerts(ts,level,message,fraction,eta_min) VALUES(?,?,?,?,?)",
                         (iso(a.ts), a.level, a.message, a.fraction, a.eta_minutes))

    def alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._all("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))

    def alerts_since(self, since: Optional[datetime]):
        if since is None:
            rows = self._all("SELECT level, ts FROM alerts")
        else:
            rows = self._all("SELECT level, ts FROM alerts WHERE ts > ?", (iso(since),))
        return [(r["level"], parse(r["ts"])) for r in rows]

    # -- profile
    def get_profile(self) -> Dict[str, Any]:
        r = self._all("SELECT value FROM kv WHERE key='profile'")
        prof = dict(DEFAULT_PROFILE)
        if r:
            prof.update(json.loads(r[0]["value"]))
        return prof

    def set_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        prof = {**self.get_profile(), **profile}
        self._run("INSERT OR REPLACE INTO kv(key,value) VALUES('profile',?)", (json.dumps(prof),))
        return prof

    def clear_data(self) -> None:
        with self.lock:
            for t in ("readings", "voids", "intake", "alerts"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()
