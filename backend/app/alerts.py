"""Alert trigger logic: predictive (before 60 %), threshold (60 %), critical (80 %)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Alert:
    ts: datetime
    level: str            # PREDICTIVE | THRESHOLD | CRITICAL
    message: str
    fraction: float
    eta_minutes: Optional[float] = None
    id: Optional[int] = None


class AlertEngine:
    def __init__(self, critical_cooldown_min: float = 10.0):
        self.critical_cooldown = timedelta(minutes=critical_cooldown_min)
        self.reset()

    def reset(self) -> None:
        """Call after every void: a new filling episode starts."""
        self.sent_predictive = False
        self.sent_threshold = False
        self.last_critical: Optional[datetime] = None

    def restore(self, levels_and_times) -> None:
        for level, ts in levels_and_times:
            if level == "PREDICTIVE":
                self.sent_predictive = True
            elif level == "THRESHOLD":
                self.sent_threshold = True
            elif level == "CRITICAL":
                self.last_critical = ts

    def evaluate(self, now: datetime, fraction: float, eta_minutes: Optional[float],
                 profile: dict) -> Optional[Alert]:
        thr, crit, lead = (profile["alert_fraction"], profile["critical_fraction"],
                           profile["lead_minutes"])
        pct = round(fraction * 100)
        if fraction >= crit:
            if self.last_critical is None or now - self.last_critical >= self.critical_cooldown:
                self.last_critical = now
                self.sent_threshold = self.sent_predictive = True
                return Alert(now, "CRITICAL",
                             f"Bladder {pct}% full - please void as soon as possible.", fraction)
        elif fraction >= thr:
            if not self.sent_threshold:
                self.sent_threshold = self.sent_predictive = True
                return Alert(now, "THRESHOLD",
                             f"Bladder reached {pct}% (threshold {round(thr*100)}%). "
                             "Plan to void soon.", fraction, 0.0)
        elif eta_minutes is not None and eta_minutes <= lead and not self.sent_predictive:
            self.sent_predictive = True
            return Alert(now, "PREDICTIVE",
                         f"Bladder {pct}% full; expected to reach {round(thr*100)}% in "
                         f"~{round(eta_minutes)} min.", fraction, eta_minutes)
        return None
