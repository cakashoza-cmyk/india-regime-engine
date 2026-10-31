"""FastAPI for local use: uvicorn engine.api:app --reload  (manual triggers + JSON dashboard)."""
from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from engine import pipeline

app = FastAPI(title="Macro Regime Intelligence Engine")
DATA = Path(__file__).resolve().parent.parent / "data"


@app.get("/latest")
def latest():
    return json.loads((DATA / "regime_latest.json").read_text())


@app.get("/history")
def history():
    return json.loads((DATA / "regime_history.json").read_text())


@app.post("/run")
def run(force_language: bool = False):
    out = pipeline.run(force_language=force_language)
    return {k: out[k] for k in ("regime_label", "sub_label", "stage", "scores", "sizing_recommendation")}


@app.get("/")
def dashboard():
    return FileResponse(DATA.parent / "engine.html")
