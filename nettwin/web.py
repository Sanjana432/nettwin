"""Serve the topology workshop and its bounded comparison API."""
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .engine import compare
from .examples import scenario

STATIC = Path(__file__).with_name("static")
app = FastAPI(title="NetTwin")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/scenarios/{name}")
def get_scenario(name: str):
    try:
        return scenario(name)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


def analyze(config):
    if not isinstance(config, dict):
        raise ValueError("Provide an object containing baseline, candidate and policies.")
    drill = config.get("drill", False)
    if not isinstance(drill, bool):
        raise ValueError("The drill flag must be true or false.")
    return compare(config.get("baseline"), config.get("candidate"), config.get("policies"), drill)


@app.post("/api/compare")
async def compare_snapshots(request: Request):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 65_536:
            raise HTTPException(413, "Topology exceeds 64 KiB.")
        raw.extend(chunk)
    try:
        config = json.loads(raw)
        return await run_in_threadpool(analyze, config)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(422, str(exc)) from exc
