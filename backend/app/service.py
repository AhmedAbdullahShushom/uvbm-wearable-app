"""Orchestrates one telemetry frame: volume -> smoothing -> void detection -> prediction -> alert."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from .alerts import AlertEngine, Alert
from .config import Settings
from .predictor import INTAKE_LAG_MIN, FillPredictor
from .storage import Store, to_utc
from .volume import volume_from_echoes


@dataclass
class TelemetryIn:
    ap_echo_us: Tuple[float, float]
    tr_echo_us: Tuple[float, float]
    si_echo_us: Tuple[float, float]
    device_id: str = "patch-001"
    timestamp: Optional[datetime] = None
    signal_quality: float = 1.0
    battery_pct: Optional[float] = None


class BladderService:
    def __init__(self, store: Store, settings: Optional[Settings] = None):
        self.store = store
        self.cfg = settings or Settings()
        self.predictor = FillPredictor(self.cfg.fit_window_min, self.cfg.min_fit_points)
        self.alerts = AlertEngine(self.cfg.critical_cooldown_min)
        self.raw_buf: Deque[float] = deque(maxlen=self.cfg.smoothing_window)
        self.episode: List[Tuple[datetime, float]] = []
        self.peak = 0.0
        self.last_void_ts: Optional[datetime] = None
        self.latest: Dict[str, Any] = {"state": "NO_DATA"}
        self._restore()

    # ------------------------------------------------------------------ state
    def _restore(self) -> None:
        self.last_void_ts = self.store.last_void_ts()
        for r in self.store.readings_since(self.last_void_ts):
            self.episode.append((r["ts"], r["smoothed_ml"]))
            self.peak = max(self.peak, r["smoothed_ml"])
        self.alerts.restore(self.store.alerts_since(self.last_void_ts))
        if self.episode:
            self.latest = self._build_status(self.episode[-1][0], self.episode[-1][1],
                                             self.store.get_profile())

    def reset(self) -> None:
        self.store.clear_data()
        self.raw_buf.clear()
        self.episode.clear()
        self.peak = 0.0
        self.last_void_ts = None
        self.alerts.reset()
        self.latest = {"state": "NO_DATA"}

    # ------------------------------------------------------------------ void detection
    def _detect_void(self, ts: datetime, smoothed: float) -> bool:
        drop = self.peak - smoothed
        return (self.peak > 0 and drop >= self.cfg.void_drop_ml
                and drop >= self.cfg.void_drop_ratio * self.peak)

    def _register_void(self, ts: datetime) -> None:
        interval = None
        if self.last_void_ts is not None:
            interval = (ts - self.last_void_ts).total_seconds() / 60.0
        mean_rate = None
        if len(self.episode) >= 2:
            dur = (self.episode[-1][0] - self.episode[0][0]).total_seconds() / 60.0
            if dur >= 10:
                mean_rate = (self.peak - self.episode[0][1]) / dur
        self.store.add_void(ts, self.peak, interval, mean_rate)
        self.last_void_ts = ts
        self.episode.clear()
        self.peak = 0.0
        self.raw_buf.clear()
        self.alerts.reset()

    # ------------------------------------------------------------------ main entry
    def ingest(self, t: TelemetryIn) -> Dict[str, Any]:
        """Raises InvalidReading for implausible frames."""
        ts = to_utc(t.timestamp) if t.timestamp else datetime.now(timezone.utc)
        prof = self.store.get_profile()
        est = volume_from_echoes(t.ap_echo_us, t.tr_echo_us, t.si_echo_us,
                                 t.signal_quality, prof["calibration_factor"])

        self.raw_buf.append(est.volume_ml)
        smoothed = float(np.median(self.raw_buf))
        if self._detect_void(ts, smoothed):
            self._register_void(ts)
            self.raw_buf.append(est.volume_ml)
            smoothed = est.volume_ml

        self.episode.append((ts, smoothed))
        self.peak = max(self.peak, smoothed)
        self.store.add_reading(ts, t.device_id, est.volume_ml, smoothed,
                               est.length_cm, est.width_cm, est.depth_cm, t.signal_quality)

        status = self._build_status(ts, smoothed, prof, raw_ml=est.volume_ml,
                                    battery=t.battery_pct)
        alert = self.alerts.evaluate(ts, status["fraction"], status["eta_minutes"], prof)
        if alert:
            alert.id = self.store.add_alert(alert)
            status["new_alert"] = _alert_dict(alert)
        status["latest_alert"] = self._latest_alert()
        self.latest = status
        return status

    def log_intake(self, volume_ml: float, ts: Optional[datetime] = None) -> None:
        if ts is None:
            ts = self.store.latest_reading_ts() or datetime.now(timezone.utc)
        self.store.add_intake(ts, volume_ml)

    # ------------------------------------------------------------------ status
    def _latest_alert(self) -> Optional[Dict[str, Any]]:
        rows = self.store.alerts(1)
        if not rows:
            return None
        # only show alerts belonging to the current filling episode
        a = rows[0]
        return a if self.last_void_ts is None or a["ts"] > self.last_void_ts.strftime(
            "%Y-%m-%dT%H:%M:%S.%f") else None

    def _build_status(self, ts: datetime, smoothed: float, prof: dict,
                      raw_ml: Optional[float] = None, battery: Optional[float] = None):
        capacity = prof["capacity_ml"]
        target = prof["alert_fraction"] * capacity
        pending = self.store.intake_between(ts - timedelta(minutes=INTAKE_LAG_MIN), ts)
        pred = self.predictor.predict(self.episode, target, ts, pending,
                                      self.store.baseline_rate())
        fraction = float(np.clip(smoothed / capacity, 0.0, 1.5))
        eta = pred.eta_minutes
        if fraction >= prof["critical_fraction"]:
            state = "CRITICAL"
        elif fraction >= prof["alert_fraction"]:
            state = "THRESHOLD"
        elif eta is not None and eta <= prof["lead_minutes"]:
            state = "APPROACHING"
        else:
            state = "NORMAL"
        since_void = ((ts - self.last_void_ts).total_seconds() / 60.0
                      if self.last_void_ts else None)
        return {
            "state": state,
            "timestamp": ts.isoformat(),
            "volume_ml": round(smoothed, 1),
            "raw_volume_ml": None if raw_ml is None else round(raw_ml, 1),
            "capacity_ml": capacity,
            "fraction": round(fraction, 4),
            "percent": round(fraction * 100, 1),
            "rate_ml_min": None if pred.rate_ml_min is None else round(pred.rate_ml_min, 3),
            "rate_source": pred.source,
            "fit_r2": None if pred.r2 is None else round(pred.r2, 3),
            "eta_minutes": None if eta is None else round(eta, 1),
            "eta_time": pred.eta_time.isoformat() if pred.eta_time else None,
            "minutes_since_void": None if since_void is None else round(since_void, 1),
            "pending_intake_ml": pending,
            "battery_pct": battery,
            "new_alert": None,
            "latest_alert": self._latest_alert(),
        }


def _alert_dict(a: Alert) -> Dict[str, Any]:
    d = asdict(a)
    d["ts"] = a.ts.isoformat()
    return d
