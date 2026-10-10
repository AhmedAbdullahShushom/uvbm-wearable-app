"""FastAPI ingestion + analytics API.   Run:  uvicorn backend.app.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import Settings
from .service import BladderService, TelemetryIn
from .storage import Store, parse, to_utc
from .volume import InvalidReading


# ----------------------------------------------------------------------- schemas
class TelemetryModel(BaseModel):
    device_id: str = "patch-001"
    timestamp: Optional[datetime] = None
    ap_echo_us: Tuple[float, float] = Field(..., description="[front, back] echo time, us")
    tr_echo_us: Tuple[float, float]
    si_echo_us: Tuple[float, float]
    signal_quality: float = Field(1.0, ge=0, le=1)
    battery_pct: Optional[float] = Field(None, ge=0, le=100)


class IntakeModel(BaseModel):
    volume_ml: float = Field(..., gt=0, le=3000)
    timestamp: Optional[datetime] = None


class ProfileModel(BaseModel):
    capacity_ml: Optional[float] = Field(None, gt=50, le=1500)
    calibration_factor: Optional[float] = Field(None, gt=0.3, le=3.0)
    alert_fraction: Optional[float] = Field(None, gt=0.1, lt=1.0)
    critical_fraction: Optional[float] = Field(None, gt=0.2, le=1.2)
    lead_minutes: Optional[float] = Field(None, ge=0, le=180)


class WSManager:
    def __init__(self):
        self.clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def disconnect(self, ws: WebSocket):
        self.clients.discard(ws)

    async def broadcast(self, payload: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(ws)


settings = Settings()
state: Dict[str, object] = {}
ws_manager = WSManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(settings.db_path)
    state["store"] = store
    state["svc"] = BladderService(store, settings)
    yield


app = FastAPI(title="BladderSense API", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def svc() -> BladderService:
    return state["svc"]  # type: ignore[return-value]


def store() -> Store:
    return state["store"]  # type: ignore[return-value]


# ----------------------------------------------------------------------- routes
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/telemetry")
async def telemetry(t: TelemetryModel):
    try:
        status = svc().ingest(TelemetryIn(**t.model_dump()))
    except InvalidReading as e:
        raise HTTPException(422, f"rejected reading: {e}")
    await ws_manager.broadcast({"type": "status", "data": status})
    if status.get("new_alert"):
        await ws_manager.broadcast({"type": "alert", "data": status["new_alert"]})
    return status


@app.get("/status")
def get_status():
    return svc().latest


@app.get("/history")
def history(hours: float = Query(24, gt=0, le=24 * 30)):
    """Readings for the last `hours`, relative to the newest reading (works with simulated time)."""
    end = store().latest_reading_ts()
    if end is None:
        return []
    rows = store().readings_since(end - timedelta(hours=hours))
    return [{"ts": r["ts"].isoformat(), "volume_ml": r["volume_ml"],
             "smoothed_ml": r["smoothed_ml"]} for r in rows]


@app.get("/voids")
def voids(days: float = Query(7, gt=0, le=365)):
    end = store().latest_reading_ts() or datetime.now(timezone.utc)
    rows = store().voids(end - timedelta(days=days))
    return [{**r, "ts": parse(r["ts"]).isoformat()} for r in rows]


@app.post("/intake")
def add_intake(i: IntakeModel):
    svc().log_intake(i.volume_ml, to_utc(i.timestamp) if i.timestamp else None)
    return {"ok": True}


@app.get("/intake")
def get_intake(hours: float = Query(24, gt=0)):
    end = store().latest_reading_ts() or datetime.now(timezone.utc)
    rows = store().intakes(end - timedelta(hours=hours))
    return [{**r, "ts": parse(r["ts"]).isoformat()} for r in rows]


@app.get("/alerts")
def alerts(limit: int = Query(50, ge=1, le=500)):
    return [{**r, "ts": parse(r["ts"]).isoformat()} for r in store().alerts(limit)]


@app.get("/profile")
def get_profile():
    return store().get_profile()


@app.put("/profile")
def put_profile(p: ProfileModel):
    merged = {**store().get_profile(), **p.model_dump(exclude_none=True)}
    if merged["critical_fraction"] <= merged["alert_fraction"]:
        raise HTTPException(422, "critical_fraction must exceed alert_fraction")
    return store().set_profile(p.model_dump(exclude_none=True))


@app.post("/reset")
def reset():
    """Wipe readings/voids/intake/alerts (demo/testing). Profile is kept."""
    svc().reset()
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_json({"type": "status", "data": svc().latest})
        while True:
            await ws.receive_text()  # keep-alive; clients may send pings
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
