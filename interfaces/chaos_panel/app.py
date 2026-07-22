"""Chaos control panel: HTTP API + small UI to trigger/stop chaos scenarios, run a real
normal-flow order through the shop's own checkout logic (to test log retrieval before doing
chaos), and reset the environment (flags off, logs archived-and-cleared) between demo takes.
Run: python -m interfaces.chaos_panel.app
"""
from __future__ import annotations

import json
import os
import random
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from chaos.flags import _load as _load_flags
from chaos.flags import reset_all, set_flag
from chaos.scenarios import LOG_PATH, SCENARIOS
from retrieval.log_client import LogClient

_DIR = Path(__file__).parent
_ROOT = _DIR.parent.parent
_RESULTS_DIR = _ROOT / "results"
_DEFAULT_DURATION = {"payment_failure": 180, "payment_outage": 180, "queue_backlog": 180, "overload": 120}

_SHOP_URL = "http://localhost:8080"
# same product IDs and a real fixture "person" the demo's own load-generator uses
_PRODUCTS = ["0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
             "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z", "HQTGWGPNH4"]
_CHECKOUT_PERSON = {
    "email": "larry_sergei@example.com",
    "address": {"streetAddress": "1600 Amphitheatre Parkway", "zipCode": "94043",
                "city": "Mountain View", "state": "CA", "country": "United States"},
    "userCurrency": "USD",
    "creditCard": {"creditCardNumber": "4432-8015-6152-0454", "creditCardExpirationMonth": 1,
                   "creditCardExpirationYear": 2039, "creditCardCvv": 672},
}

app = FastAPI(title="Chaos Control Panel")
app.mount("/static", StaticFiles(directory=_DIR / "static"), name="static")

_lock = threading.Lock()
_current: dict | None = None  # {"name", "started_at", "ends_at", "cancel": threading.Event()}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(scenario: str, duration: int, cancel: threading.Event) -> None:
    global _current
    flag, variant = SCENARIOS[scenario]
    start = _now_iso()
    set_flag(flag, variant)
    cancel.wait(duration)  # returns early if /stop sets it, else after `duration`s
    reset_all()
    end = _now_iso()
    with LOG_PATH.open("a") as f:
        f.write(json.dumps({"scenario": scenario, "flag": flag, "start": start, "end": end}) + "\n")
    with _lock:
        _current = None


@app.get("/")
def index():
    return FileResponse(_DIR / "static" / "index.html")


@app.get("/status")
def status():
    flag_data = _load_flags()["flags"]
    flag_names = {flag for flag, _ in SCENARIOS.values()}
    flags = {flag: flag_data[flag]["defaultVariant"] for flag in flag_names}
    with _lock:
        current = None
        if _current is not None:
            current = {"name": _current["name"], "started_at": _current["started_at"], "ends_at": _current["ends_at"]}
    return {"current": current, "flags": flags, "defaults": _DEFAULT_DURATION}


@app.post("/normal-flow/run")
def run_normal_flow():
    """Place one real order through the shop's actual add-to-cart + checkout logic (no chaos
    involved) with a hand-crafted W3C traceparent header, so we get back a trace_id whose logs
    can immediately be tested via GET /logs/{trace_id} -- useful to confirm the log pipeline
    works before running a failure scenario."""
    trace_id = os.urandom(16).hex()
    traceparent = f"00-{trace_id}-{os.urandom(8).hex()}-01"
    headers = {"traceparent": traceparent}
    user_id = str(uuid.uuid4())
    product_id = random.choice(_PRODUCTS)
    quantity = random.choice([1, 2, 3])

    try:
        cart_resp = requests.post(
            f"{_SHOP_URL}/api/cart",
            json={"item": {"productId": product_id, "quantity": quantity}, "userId": user_id},
            headers=headers, timeout=10,
        )
        cart_resp.raise_for_status()
        checkout_resp = requests.post(
            f"{_SHOP_URL}/api/checkout",
            json={"userId": user_id, **_CHECKOUT_PERSON},
            headers=headers, timeout=10,
        )
        checkout_resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(502, f"shop unreachable/errored: {e}")

    return {
        "trace_id": trace_id,
        "user_id": user_id,
        "product_id": product_id,
        "quantity": quantity,
        "order": checkout_resp.json(),
    }


@app.get("/logs/{trace_id}")
def get_logs(trace_id: str, wait: int = 0):
    """Fetch logs for a trace_id from Loki. `wait` (seconds) polls until logs show up or the
    wait expires -- useful right after /normal-flow/run since ingestion has a few seconds of lag."""
    client = LogClient()
    deadline = time.time() + wait
    entries = client.get_logs_by_trace_id(trace_id)
    while not entries and time.time() < deadline:
        time.sleep(1)
        entries = client.get_logs_by_trace_id(trace_id)
    return {"trace_id": trace_id, "count": len(entries), "logs": [e.model_dump() for e in entries]}


@app.post("/scenarios/{name}/start")
def start_scenario(name: str, duration: int | None = None):
    global _current
    if name not in SCENARIOS:
        raise HTTPException(404, f"unknown scenario: {name}")
    duration = duration or _DEFAULT_DURATION[name]
    with _lock:
        if _current is not None:
            raise HTTPException(409, f"{_current['name']} is already running")
        now = time.time()
        cancel = threading.Event()
        _current = {"name": name, "started_at": now, "ends_at": now + duration, "cancel": cancel}
    threading.Thread(target=_run, args=(name, duration, cancel), daemon=True).start()
    return {"status": "started", "scenario": name, "duration": duration}


@app.post("/scenarios/{name}/stop")
def stop_scenario(name: str):
    with _lock:
        if _current is None or _current["name"] != name:
            raise HTTPException(409, "that scenario isn't running")
        _current["cancel"].set()
    return {"status": "stopping", "scenario": name}


@app.post("/reset")
def clean_reset():
    """Reset flags to off and archive-then-clear the demo logs, so the next case starts clean."""
    with _lock:
        if _current is not None:
            raise HTTPException(409, "a scenario is running -- stop it first")
    reset_all()

    archive_dir = _RESULTS_DIR / "archive" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    moved = []

    history = _RESULTS_DIR / "analysis_history.jsonl"
    if history.exists() and history.stat().st_size > 0:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(history), archive_dir / "analysis_history.jsonl")
        moved.append("results/analysis_history.jsonl")

    convos = _RESULTS_DIR / "conversations"
    if convos.exists() and any(convos.iterdir()):
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(convos), archive_dir / "conversations")
        convos.mkdir(exist_ok=True)
        moved.append("results/conversations/")

    if LOG_PATH.exists() and LOG_PATH.stat().st_size > 0:
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(LOG_PATH), archive_dir / "injected_events.log")
        moved.append("chaos/injected_events.log")

    return {"status": "reset", "archived_to": str(archive_dir) if moved else None, "moved": moved}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8600)
