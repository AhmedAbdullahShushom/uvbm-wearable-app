"""Clinician / user web dashboard (Streamlit).

    streamlit run web/dashboard.py
"""
from __future__ import annotations

import os

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="BladderSense", page_icon="🩺", layout="wide")

api = st.sidebar.text_input("Backend URL", os.getenv("BLADDERSENSE_API", "http://127.0.0.1:8000"))
hours = st.sidebar.slider("History window (h)", 1, 72, 24)
days = st.sidebar.slider("Trend window (days)", 1, 30, 7)
live_every = st.sidebar.selectbox("Auto-refresh", ["2s", "5s", "10s"], index=1)


def get(path: str, **params):
    try:
        r = httpx.get(f"{api}{path}", params=params, timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Backend error on {path}: {e}")
        return None


STATE_COLOR = {"NORMAL": "#2ecc71", "APPROACHING": "#f1c40f", "THRESHOLD": "#e67e22",
               "CRITICAL": "#e74c3c", "NO_DATA": "#95a5a6"}


def gauge(s: dict) -> go.Figure:
    return go.Figure(go.Indicator(
        mode="gauge+number", value=s.get("percent", 0),
        number={"suffix": "%"}, title={"text": f"Bladder fill - {s['state']}"},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": STATE_COLOR[s["state"]]},
               "steps": [{"range": [0, 60], "color": "rgba(46,204,113,.15)"},
                         {"range": [60, 80], "color": "rgba(230,126,34,.2)"},
                         {"range": [80, 100], "color": "rgba(231,76,60,.25)"}],
               "threshold": {"line": {"color": "orange", "width": 4}, "value": 60}})
    ).update_layout(height=280, margin=dict(t=60, b=10, l=20, r=20))


@st.fragment(run_every=live_every)
def live_panel():
    s = get("/status")
    if not s:
        return
    if s["state"] == "NO_DATA":
        st.info("Waiting for patch data. Start the simulator: `python simulator/simulate_patch.py`")
        return
    c1, c2 = st.columns([1, 1])
    c1.plotly_chart(gauge(s), use_container_width=True)
    with c2:
        m1, m2 = st.columns(2)
        m1.metric("Volume", f"{s['volume_ml']:.0f} ml", f"of {s['capacity_ml']:.0f} ml",
                  delta_color="off")
        m2.metric("Filling rate", "-" if s["rate_ml_min"] is None
                  else f"{s['rate_ml_min']:.2f} ml/min", s["rate_source"], delta_color="off")
        m3, m4 = st.columns(2)
        eta = s["eta_minutes"]
        m3.metric("Time to alert level", "-" if eta is None else
                  ("reached" if eta <= 0 else f"{eta:.0f} min"))
        sv = s["minutes_since_void"]
        m4.metric("Since last void", "-" if sv is None else f"{sv/60:.1f} h")
        if s.get("latest_alert"):
            a = s["latest_alert"]
            (st.error if a["level"] == "CRITICAL" else st.warning)(f"{a['level']}: {a['message']}")
    hist = get("/history", hours=hours)
    voids = get("/voids", days=days) or []
    if hist:
        df = pd.DataFrame(hist)
        df["ts"] = pd.to_datetime(df["ts"])
        fig = go.Figure()
        fig.add_scatter(x=df.ts, y=df.volume_ml, mode="markers", name="raw",
                        marker=dict(size=4, opacity=.35))
        fig.add_scatter(x=df.ts, y=df.smoothed_ml, mode="lines", name="smoothed",
                        line=dict(width=3))
        fig.add_hline(y=0.6 * s["capacity_ml"], line_dash="dash", line_color="orange",
                      annotation_text="60% alert")
        fig.add_hline(y=s["capacity_ml"], line_dash="dot", line_color="red",
                      annotation_text="capacity")
        for v in voids:
            t = pd.to_datetime(v["ts"])
            if t >= df.ts.min():
                fig.add_vline(x=t, line_color="rgba(52,152,219,.6)")
        fig.update_layout(title="Filling curve (blue lines = voids)", height=380,
                          yaxis_title="ml", margin=dict(t=50, b=10))
        st.plotly_chart(fig, use_container_width=True)


st.title("🩺 BladderSense - microgravity bladder monitor")
live_panel()

st.subheader("Voiding patterns & trends")
voids = get("/voids", days=days) or []
if voids:
    vd = pd.DataFrame(voids)
    vd["ts"] = pd.to_datetime(vd["ts"])
    vd["date"] = vd.ts.dt.date
    a, b = st.columns(2)
    iv = vd.dropna(subset=["interval_min"])
    fig = go.Figure(go.Bar(x=iv.ts, y=iv.interval_min / 60, name="interval"))
    fig.update_layout(title="Voiding interval (h)", height=320, yaxis_title="hours")
    a.plotly_chart(fig, use_container_width=True)
    fig = go.Figure(go.Bar(x=vd.ts, y=vd.pre_void_ml, name="pre-void volume"))
    fig.add_hline(y=500, line_dash="dot", line_color="red")
    fig.update_layout(title="Pre-void volume (ml)", height=320, yaxis_title="ml")
    b.plotly_chart(fig, use_container_width=True)

    daily = vd.groupby("date").agg(voids=("ts", "count"), mean_interval_h=("interval_min", lambda x: x.mean() / 60),
                                   mean_pre_void_ml=("pre_void_ml", "mean"),
                                   max_pre_void_ml=("pre_void_ml", "max"),
                                   mean_fill_rate=("mean_rate", "mean")).round(2)
    st.dataframe(daily, use_container_width=True)
    st.download_button("Download voids CSV", vd.to_csv(index=False), "voids.csv", "text/csv")
else:
    st.caption("No voids recorded yet.")

left, right = st.columns(2)
with left:
    st.subheader("Alerts")
    al = get("/alerts", limit=25)
    if al:
        st.dataframe(pd.DataFrame(al)[["ts", "level", "message", "fraction"]],
                     use_container_width=True, hide_index=True)
    else:
        st.caption("No alerts yet.")
with right:
    st.subheader("Log fluid intake")
    ml = st.number_input("Volume (ml)", 50, 1500, 250, 50)
    if st.button("Log intake"):
        httpx.post(f"{api}/intake", json={"volume_ml": ml}, timeout=5)
        st.success(f"Logged {ml} ml")
    st.subheader("Profile / calibration")
    prof = get("/profile") or {}
    cap = st.number_input("Functional capacity (ml)", 100, 1500, int(prof.get("capacity_ml", 500)))
    cal = st.number_input("Calibration factor", 0.5, 2.0, float(prof.get("calibration_factor", 1.0)), 0.01,
                          help="Scale to match a reference ultrasound/catheter volume.")
    frac = st.slider("Alert fraction", 0.3, 0.9, float(prof.get("alert_fraction", 0.6)), 0.05)
    lead = st.number_input("Predictive lead (min)", 0, 120, int(prof.get("lead_minutes", 15)))
    if st.button("Save profile"):
        r = httpx.put(f"{api}/profile", json={"capacity_ml": cap, "calibration_factor": cal,
                                              "alert_fraction": frac, "lead_minutes": lead}, timeout=5)
        st.success("Saved") if r.status_code == 200 else st.error(r.text)
