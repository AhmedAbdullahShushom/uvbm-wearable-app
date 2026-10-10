"""Filling-rate estimation and time-to-threshold prediction.

* Robust (Huber) linear regression over a sliding window of smoothed volumes gives the
  current filling velocity (ml/min) and a de-noised current volume.
* If the window is still short, the user's historical median rate is used as a prior.
* Recent fluid intake that has NOT yet reached the bladder (renal lag ~30 min) adds an
  anticipatory rate. This is a tunable heuristic, not a validated physiological model.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence, Tuple

import numpy as np
from sklearn.linear_model import HuberRegressor

# Heuristic: ~60 % of ingested fluid becomes urine, spread over ~2 h after a ~30 min lag.
URINE_FRACTION = 0.60
URINE_SPREAD_MIN = 120.0
INTAKE_LAG_MIN = 30.0
MIN_RATE = 0.02  # ml/min; below this we treat the bladder as not filling


@dataclass
class Prediction:
    rate_ml_min: Optional[float]
    current_ml: float
    eta_minutes: Optional[float]
    eta_time: Optional[datetime]
    r2: Optional[float]
    n_points: int
    source: str  # "regression" | "baseline" | "insufficient_data"


class FillPredictor:
    def __init__(self, window_min: float = 45.0, min_points: int = 6):
        self.window_min = window_min
        self.min_points = min_points

    def predict(self, points: Sequence[Tuple[datetime, float]], target_ml: float,
                now: datetime, pending_intake_ml: float = 0.0,
                baseline_rate: Optional[float] = None) -> Prediction:
        pts = sorted((t, v) for t, v in points
                     if 0 <= (now - t).total_seconds() / 60.0 <= self.window_min)
        n = len(pts)
        current = pts[-1][1] if pts else 0.0
        rate: Optional[float] = None
        r2: Optional[float] = None
        source = "insufficient_data"

        span = (pts[-1][0] - pts[0][0]).total_seconds() / 60.0 if n >= 2 else 0.0
        if n >= self.min_points and span >= 5.0:
            x = np.array([(t - now).total_seconds() / 60.0 for t, _ in pts]).reshape(-1, 1)
            y = np.array([v for _, v in pts])
            model = HuberRegressor(alpha=0.0, max_iter=200).fit(x, y)
            rate = float(model.coef_[0])
            current = float(model.intercept_)  # fitted volume at x = 0 (now)
            r2 = float(model.score(x, y))
            source = "regression"
        elif baseline_rate is not None:
            rate = baseline_rate
            source = "baseline"

        if rate is not None:
            rate = max(rate, 0.0)
            rate += URINE_FRACTION * pending_intake_ml / URINE_SPREAD_MIN
        current = float(max(current, 0.0))

        eta_min: Optional[float] = None
        eta_time: Optional[datetime] = None
        if current >= target_ml:
            eta_min, eta_time = 0.0, now
        elif rate is not None and rate > MIN_RATE:
            eta_min = (target_ml - current) / rate
            eta_time = now + timedelta(minutes=eta_min)
        return Prediction(rate, current, eta_min, eta_time, r2, n, source)
