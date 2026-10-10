"""BladderSense mobile app (Flet).

Run on desktop:   python mobile/app.py
Run in browser:   flet run --web mobile/app.py
Build Android:    flet build apk        (see Flet docs; BLE on-device needs Android permissions)
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime

import flet as ft
import httpx

from notifier import notify

DEFAULT_API = os.getenv("BLADDERSENSE_API", "http://127.0.0.1:8000")
COLORS = {"NO_DATA": ft.Colors.GREY, "NORMAL": ft.Colors.GREEN, "APPROACHING": ft.Colors.AMBER,
          "THRESHOLD": ft.Colors.ORANGE, "CRITICAL": ft.Colors.RED}


async def main(page: ft.Page):
    page.title = "BladderSense"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO

    api = ft.TextField(value=DEFAULT_API, label="Backend URL", dense=True)
    ring = ft.ProgressRing(value=0, width=190, height=190, stroke_width=16, color=ft.Colors.GREEN)
    pct = ft.Text("--%", size=42, weight=ft.FontWeight.BOLD)
    vol = ft.Text("", size=14, color=ft.Colors.GREY)
    gauge = ft.Stack(
        [ring, ft.Container(ft.Column([pct, vol], alignment=ft.MainAxisAlignment.CENTER,
                                      horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            alignment=ft.alignment.center, width=190, height=190)],
        width=190, height=190)
    state_txt = ft.Text("Waiting for data...", size=18, weight=ft.FontWeight.W_600)
    eta_txt = ft.Text("", size=15)
    rate_txt = ft.Text("", size=13, color=ft.Colors.GREY)
    alert_txt = ft.Text("", size=14, color=ft.Colors.ORANGE)
    conn_txt = ft.Text("", size=12, color=ft.Colors.GREY)

    vol_series = ft.LineChartData(data_points=[], stroke_width=3, color=ft.Colors.CYAN,
                                  curved=True, stroke_cap_round=True)
    thr_series = ft.LineChartData(data_points=[], stroke_width=2, color=ft.Colors.ORANGE)
    chart = ft.LineChart(data_series=[vol_series, thr_series], min_x=-360, max_x=0, min_y=0,
                         max_y=500, height=220, expand=False,
                         left_axis=ft.ChartAxis(labels_size=40),
                         bottom_axis=ft.ChartAxis(labels_size=24, title=ft.Text("min ago", size=11)))

    async def log_water(ml: int):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                await c.post(f"{api.value}/intake", json={"volume_ml": ml})
            page.open(ft.SnackBar(ft.Text(f"Logged {ml} ml")))
        except Exception as e:
            page.open(ft.SnackBar(ft.Text(f"Failed: {e}")))

    ble_task = {"task": None, "stop": None}

    async def toggle_ble(e):
        if e.control.value:
            try:
                from ble_connector import stream_to_backend
            except Exception as ex:
                e.control.value = False
                page.open(ft.SnackBar(ft.Text(f"BLE unavailable: {ex}")))
                page.update()
                return
            ble_task["stop"] = asyncio.Event()
            ble_task["task"] = asyncio.create_task(stream_to_backend(
                api.value, on_status=lambda m: setattr(conn_txt, "value", m) or page.update(),
                stop=ble_task["stop"]))
        elif ble_task["stop"]:
            ble_task["stop"].set()

    page.add(
        ft.Row([ft.Text("BladderSense", size=26, weight=ft.FontWeight.BOLD)]),
        ft.Row([gauge], alignment=ft.MainAxisAlignment.CENTER),
        ft.Column([state_txt, eta_txt, rate_txt, alert_txt],
                  horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        ft.Divider(),
        ft.Text("Last 6 hours (ml)  -  orange = alert threshold", size=12),
        chart,
        ft.Row([ft.ElevatedButton("+150 ml", on_click=lambda e: page.run_task(log_water, 150)),
                ft.ElevatedButton("+250 ml", on_click=lambda e: page.run_task(log_water, 250)),
                ft.ElevatedButton("+500 ml", on_click=lambda e: page.run_task(log_water, 500))],
               alignment=ft.MainAxisAlignment.CENTER),
        ft.Divider(),
        api,
        ft.Switch(label="Use BLE patch on this phone", on_change=toggle_ble),
        conn_txt,
    )

    seen = {"alert_id": None, "first": True}

    def render(s: dict, hist: list):
        st = s.get("state", "NO_DATA")
        color = COLORS.get(st, ft.Colors.GREY)
        ring.color = color
        if st == "NO_DATA":
            state_txt.value = "Waiting for patch data..."
            return
        ring.value = min(s["fraction"], 1.0)
        pct.value = f"{s['percent']:.0f}%"
        vol.value = f"{s['volume_ml']:.0f} / {s['capacity_ml']:.0f} ml"
        state_txt.value = {"NORMAL": "Normal", "APPROACHING": "Approaching threshold",
                           "THRESHOLD": "Threshold reached - plan to void",
                           "CRITICAL": "Critical - void now"}[st]
        state_txt.color = color
        eta = s.get("eta_minutes")
        eta_txt.value = ("" if eta is None else
                         ("Threshold reached" if eta <= 0 else f"~{eta:.0f} min to alert level"))
        rate_txt.value = (f"Filling rate {s['rate_ml_min']:.2f} ml/min ({s['rate_source']})"
                          if s.get("rate_ml_min") is not None else "")
        a = s.get("latest_alert")
        alert_txt.value = a["message"] if a else ""
        if a:
            if not seen["first"] and a["id"] != seen["alert_id"]:
                notify(f"BladderSense - {a['level']}", a["message"])
                page.open(ft.SnackBar(ft.Text(a["message"]), bgcolor=color))
            seen["alert_id"] = a["id"]
        seen["first"] = False

        if hist:
            end = datetime.fromisoformat(hist[-1]["ts"])
            vol_series.data_points = [
                ft.LineChartDataPoint((datetime.fromisoformat(h["ts"]) - end).total_seconds() / 60,
                                      h["smoothed_ml"]) for h in hist]
            thr = s["capacity_ml"] * 0.6
            thr_series.data_points = [ft.LineChartDataPoint(-360, thr), ft.LineChartDataPoint(0, thr)]
            chart.max_y = s["capacity_ml"]

    async def poll():
        async with httpx.AsyncClient(timeout=5) as c:
            while True:
                try:
                    s = (await c.get(f"{api.value}/status")).json()
                    hist = (await c.get(f"{api.value}/history", params={"hours": 6})).json()
                    render(s, hist)
                    conn_txt.value = conn_txt.value if ble_task["stop"] and not ble_task["stop"].is_set() \
                        else f"Connected to backend - {datetime.now():%H:%M:%S}"
                except Exception as e:
                    conn_txt.value = f"Backend unreachable: {e.__class__.__name__}"
                page.update()
                await asyncio.sleep(2)

    page.run_task(poll)


if __name__ == "__main__":
    ft.app(target=main)
