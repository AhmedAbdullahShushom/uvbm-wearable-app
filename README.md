# BladderSense - microgravity bladder monitoring (Python stack)

```
 patch (BLE/Wi-Fi) -> FastAPI backend -> volume math -> filling-rate ML -> alerts
                          |                                   |
                  Flet mobile app  <---- REST / WebSocket ----> Streamlit dashboard
```

## Layout
| Path | What it does |
|---|---|
| `backend/app/volume.py` | echo time -> wall distance -> ellipsoid volume `V = (pi/6)*L*W*H*cal` |
| `backend/app/predictor.py` | Huber regression filling rate (ml/min), ETA to 60 %, intake heuristic |
| `backend/app/alerts.py` | PREDICTIVE (before 60 %), THRESHOLD (60 %), CRITICAL (80 %) |
| `backend/app/service.py` | pipeline: median smoothing, void detection, prediction, alerting |
| `backend/app/storage.py` | SQLite persistence (state survives restarts) |
| `backend/app/main.py` | REST + WebSocket API |
| `simulator/simulate_patch.py` | fake patch with noise, dropouts, drinking, voids |
| `mobile/` | Flet app, `bleak` BLE gateway, local notifications |
| `web/dashboard.py` | Streamlit dashboard |
| `tests/test_core.py` | unit + end-to-end tests |

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

uvicorn backend.app.main:app --reload            # 1. API  (docs at /docs)
python simulator/simulate_patch.py               # 2. simulated patch (1 sim-min per 0.5 s)
streamlit run web/dashboard.py                   # 3. web dashboard
python mobile/app.py                             # 4. mobile app (desktop preview)
pytest -q                                        # tests
```

## Telemetry format (`POST /telemetry`)
```json
{"timestamp":"2026-01-01T10:00:00Z",
 "ap_echo_us":[49.0,151.0], "tr_echo_us":[49.0,170.0], "si_echo_us":[49.0,190.0],
 "signal_quality":0.95, "battery_pct":87}
```
`[front_wall_echo, back_wall_echo]` per axis (AP depth, TR width, SI length), round-trip microseconds.

## Things you MUST do before relying on it
* **Calibrate** `calibration_factor` per user against a reference (catheter or clinical bladder scan).
  Real bladders are not ellipsoids; error of 10-20 % is typical for L x W x H formulas.
* The **intake -> urine heuristic** (`predictor.py`) and the ETA lead time are tunable assumptions,
  not validated physiology. Fit them to your beta-test data.
* Median smoothing delays void detection by ~2-3 frames; voids are timestamped at detection.
* Mobile: Flet has no built-in push API. `plyer` gives local notifications; on Android these mirror to
  a paired watch automatically. Real remote push (FCM) or a dedicated watch UI needs extra work.
* BLE UUIDs / packet layout in `mobile/ble_connector.py` are placeholders for your firmware.
* Research prototype - not a medical device.
