# uvbm-wearable-app
backend, mobile app, and web dashboard for a wearable Ultrasonic Bladder Volume Measurement (UBVM) device designed for microgravity. Real-time bladder volume tracking and AI-driven urgency prediction for spaceflight health. Built in Python.
pip install -r requirements.txt
uvicorn backend.app.main:app --reload     # terminal 1
python simulator/simulate_patch.py        # terminal 2
streamlit run web/dashboard.py            # terminal 3
python mobile/app.py                      # terminal 4
