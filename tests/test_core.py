import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.config import Settings
from backend.app.predictor import FillPredictor
from backend.app.service import BladderService, TelemetryIn
from backend.app.storage import Store
from backend.app.volume import (InvalidReading, ellipsoid_volume_ml, synthesize_echoes,
                                volume_from_echoes)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def frame(volume, ts, rng, quality=1.0):
    e = synthesize_echoes(volume, rng, noise=0.005)
    return TelemetryIn(ap_echo_us=e[0], tr_echo_us=e[1], si_echo_us=e[2],
                       timestamp=ts, signal_quality=quality)


def test_ellipsoid_formula():
    assert ellipsoid_volume_ml(10, 8, 8) == pytest.approx(math.pi / 6 * 640)


@pytest.mark.parametrize("v", [80, 200, 300, 450])
def test_echo_roundtrip(v):
    e = synthesize_echoes(v, np.random.default_rng(1), noise=0.0)
    est = volume_from_echoes(*e)
    assert est.volume_ml == pytest.approx(v, rel=0.01)


def test_rejects_bad_frames():
    with pytest.raises(InvalidReading):
        volume_from_echoes((50, 40), (50, 150), (50, 150))      # back before front
    with pytest.raises(InvalidReading):
        volume_from_echoes((50, 150), (50, 150), (50, 150), signal_quality=0.1)


def test_predictor_rate_and_eta():
    pts = [(T0 + timedelta(minutes=i), 100 + 2.0 * i) for i in range(30)]
    now = pts[-1][0]
    p = FillPredictor().predict(pts, target_ml=300, now=now)
    assert p.rate_ml_min == pytest.approx(2.0, rel=0.02)
    assert p.eta_minutes == pytest.approx((300 - 158) / 2.0, rel=0.03)
    assert p.source == "regression"


def test_predictor_robust_to_outlier():
    pts = [(T0 + timedelta(minutes=i), 100 + 2.0 * i) for i in range(30)]
    pts[15] = (pts[15][0], 400.0)
    p = FillPredictor().predict(pts, 300, pts[-1][0])
    assert p.rate_ml_min == pytest.approx(2.0, rel=0.1)


def test_pending_intake_raises_rate():
    pts = [(T0 + timedelta(minutes=i), 100 + 1.0 * i) for i in range(20)]
    a = FillPredictor().predict(pts, 300, pts[-1][0])
    b = FillPredictor().predict(pts, 300, pts[-1][0], pending_intake_ml=500)
    assert b.rate_ml_min > a.rate_ml_min and b.eta_minutes < a.eta_minutes


def test_full_episode_alerts_and_void(tmp_path):
    svc = BladderService(Store(str(tmp_path / "t.db")), Settings())
    rng = np.random.default_rng(0)
    vol, ts, levels = 40.0, T0, []
    for _ in range(300):                                  # fill at 1.8 ml/min
        vol += 1.8
        s = svc.ingest(frame(vol, ts, rng))
        if s["new_alert"]:
            levels.append((s["new_alert"]["level"], s["percent"]))
        ts += timedelta(minutes=1)
    names = [l for l, _ in levels]
    assert names[0] == "PREDICTIVE" and "THRESHOLD" in names and "CRITICAL" in names
    assert levels[0][1] < 60                              # predictive fires BEFORE 60 %
    assert names.count("THRESHOLD") == 1

    for _ in range(8):                                    # void -> residual
        s = svc.ingest(frame(35, ts, rng))
        ts += timedelta(minutes=1)
    voids = svc.store.voids()
    assert len(voids) == 1 and voids[0]["pre_void_ml"] > 400
    assert s["state"] == "NORMAL"


def test_state_survives_restart(tmp_path):
    path = str(tmp_path / "r.db")
    svc = BladderService(Store(path), Settings())
    rng = np.random.default_rng(2)
    ts, vol = T0, 50.0
    for _ in range(40):
        vol += 2
        svc.ingest(frame(vol, ts, rng)); ts += timedelta(minutes=1)
    svc2 = BladderService(Store(path), Settings())
    assert svc2.latest["volume_ml"] == pytest.approx(svc.latest["volume_ml"], abs=0.1)
    assert len(svc2.episode) == len(svc.episode)
