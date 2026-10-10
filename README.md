# uvbm-wearable-app
backend, mobile app, and web dashboard for a wearable Ultrasonic Bladder Volume Measurement (UBVM) device designed for microgravity. Real-time bladder volume tracking and AI-driven urgency prediction for spaceflight health. Built in Python.
pip install -r requirements.txt
uvicorn backend.app.main:app --reload     # terminal 1
python simulator/simulate_patch.py        # terminal 2
streamlit run web/dashboard.py            # terminal 3
python mobile/app.py                      # terminal 4

Calibration: each user’s calibration_factor must be checked against a reference measurement such as a clinical bladder scan. Ellipsoid formulas are typically off by 10–20%.
Intake heuristic: the fluid-intake adjustment in predictor.py is an assumption I made, not validated physiology. Tune it with your beta-test data.
BLE: the UUIDs and packet layout are placeholders until they match your firmware.
Mobile alerts: plyer gives local notifications only, and on Android these mirror to a paired watch automatically. Remote push (FCM) or a dedicated watch app needs more work.
Flet version: the code is written for Flet 0.25–0.27 (pinned in requirements.txt), since its API changes between versions.
