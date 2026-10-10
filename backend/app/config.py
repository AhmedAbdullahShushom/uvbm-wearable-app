"""Central configuration and physical constants."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

# Speed of sound in soft tissue ~1540 m/s = 0.154 cm per microsecond.
SPEED_OF_SOUND_CM_PER_US = 0.154

# Plausible physical limits used to reject garbage readings (cm).
MIN_DIM_CM = 0.5
MAX_DIM_CM = 20.0
MIN_SIGNAL_QUALITY = 0.4


DEFAULT_PROFILE = {
    "capacity_ml": 500.0,        # individual functional bladder capacity
    "calibration_factor": 1.0,   # per-user correction vs. reference ultrasound
    "alert_fraction": 0.60,      # the ~60 % pre-urgency alert
    "critical_fraction": 0.80,
    "lead_minutes": 15.0,        # warn this many minutes BEFORE the 60 % crossing
}


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("BLADDERSENSE_DB", "bladdersense.db"))
    smoothing_window: int = 5          # median filter length (readings)
    fit_window_min: float = 45.0       # regression window for filling rate
    min_fit_points: int = 6
    void_drop_ml: float = 50.0         # min absolute drop to call it a void
    void_drop_ratio: float = 0.40      # ... and min relative drop vs episode peak
    critical_cooldown_min: float = 10.0
