"""Simulated ultrasonic patch: posts raw echo telemetry to the backend.

    python simulator/simulate_patch.py --url http://127.0.0.1:8000 --interval 0.5 --step-min 1

Each tick advances SIMULATED time by --step-min minutes (so a 4-hour fill takes ~2 minutes
at the defaults). Includes sensor noise, occasional dropouts, drinking events and voids.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.volume import synthesize_echoes  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--interval", type=float, default=0.5, help="real seconds between frames")
    ap.add_argument("--step-min", type=float, default=1.0, help="simulated minutes per frame")
    ap.add_argument("--fill-rate", type=float, default=1.8, help="baseline ml/min")
    ap.add_argument("--capacity", type=float, default=500.0)
    ap.add_argument("--residual", type=float, default=30.0, help="post-void residual (ml)")
    ap.add_argument("--void-at", type=float, default=0.85, help="void at this fraction")
    ap.add_argument("--dropout", type=float, default=0.03, help="bad-frame probability")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    rng = np.random.default_rng(args.seed)
    client = httpx.Client(base_url=args.url, timeout=5)
    sim_time = datetime.now(timezone.utc)
    volume = args.residual
    boost = 0.0          # extra ml/min after drinking
    boost_left = 0.0
    print(f"Simulating patch -> {args.url}  (Ctrl+C to stop)")

    while True:
        # drinking event (~every 90 simulated minutes)
        if rng.random() < args.step_min / 90.0:
            ml = float(rng.choice([150, 250, 330, 500]))
            client.post("/intake", json={"volume_ml": ml, "timestamp": sim_time.isoformat()})
            boost, boost_left = 0.6 * ml / 120.0, 120.0 + 30.0   # delayed in reality; kept simple
            print(f"[{sim_time:%H:%M}] intake {ml:.0f} ml")

        rate = args.fill_rate * (1 + rng.normal(0, 0.1)) + (boost if boost_left > 0 else 0)
        boost_left = max(boost_left - args.step_min, 0)
        volume += max(rate, 0.1) * args.step_min

        if volume >= args.void_at * args.capacity * (1 + rng.normal(0, 0.03)):
            volume = args.residual
            print(f"[{sim_time:%H:%M}] *** void ***")

        quality = 1.0 if rng.random() > args.dropout else 0.2
        echoes = synthesize_echoes(volume, rng)
        if quality < 0.4:  # garbage frame
            echoes = [(30.0, 30.0 + float(rng.uniform(-20, 400))) for _ in range(3)]
        body = {
            "timestamp": sim_time.isoformat(),
            "ap_echo_us": echoes[0], "tr_echo_us": echoes[1], "si_echo_us": echoes[2],
            "signal_quality": quality, "battery_pct": 87.0,
        }
        try:
            r = client.post("/telemetry", json=body)
            if r.status_code == 200:
                s = r.json()
                eta = s["eta_minutes"]
                print(f"[{sim_time:%H:%M}] {s['volume_ml']:6.1f} ml  {s['percent']:5.1f}%  "
                      f"rate={s['rate_ml_min']}  eta={'-' if eta is None else eta}  {s['state']}")
                if s.get("new_alert"):
                    print(f"      >>> ALERT [{s['new_alert']['level']}] {s['new_alert']['message']}")
            else:
                print(f"[{sim_time:%H:%M}] rejected: {r.text}")
        except httpx.HTTPError as e:
            print("backend unreachable:", e)

        sim_time += timedelta(minutes=args.step_min)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
