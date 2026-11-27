"""Hugging Face Spaces uyumlu FastAPI mikro servisi ve günlük otonom zamanlayıcı."""

from __future__ import annotations

import asyncio
import html
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from engine.bulletin import (
    build_bulletin_payload,
    get_cached_bulletin,
    load_bulletin_from_disk,
    update_bulletin_cache,
)
from engine.config import LeagueId
from engine.runner import CycleResult, get_runner_status, run_full_cycle

logger = logging.getLogger(__name__)

START_MONOTONIC = time.monotonic()
sync_lock = asyncio.Lock()


def _parse_float_env(name: str, default: float, *, allow_zero: bool = False) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        if val < 0 or (not allow_zero and val == 0):
            raise ValueError
        return val
    except ValueError:
        return default


def _is_scheduler_enabled() -> bool:
    return os.getenv("SCHEDULER_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


async def _daily_scheduler_loop(startup_delay: float, interval_seconds: float) -> None:
    """Uygulama açılışından kısa süre sonra ve ardından günde 1 kez tam döngüyü çalıştırır."""
    try:
        if startup_delay > 0:
            await asyncio.sleep(startup_delay)
        while True:
            if not sync_lock.locked():
                async with sync_lock:
                    try:
                        logger.info("Zamanlayıcı günlük senkronizasyonu başlatıyor...")
                        cycle_res = await asyncio.to_thread(run_full_cycle)
                        if isinstance(cycle_res, CycleResult) and cycle_res.predictions_count > 0:
                            await asyncio.to_thread(update_bulletin_cache, cycle_res)
                    except Exception:
                        logger.exception("Zamanlayıcı döngüsünde beklenmeyen hata oluştu.")
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Arka plan zamanlayıcısı durduruldu.")
        raise


@asynccontextmanager
async def lifespan(application: FastAPI):
    await asyncio.to_thread(load_bulletin_from_disk)
    task: asyncio.Task[None] | None = None
    if _is_scheduler_enabled():
        startup_delay = _parse_float_env("STARTUP_SYNC_DELAY_SECONDS", 5.0, allow_zero=True)
        interval_hours = _parse_float_env("SYNC_INTERVAL_HOURS", 24.0)
        task = asyncio.create_task(
            _daily_scheduler_loop(
                startup_delay=startup_delay,
                interval_seconds=interval_hours * 3600.0,
            )
        )
    application.state.scheduler_task = task
    try:
        yield
    finally:
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Futbol Skor ve Analiz Motoru",
    version="1.0.0",
    description="4 büyük lig için otonom fikstür, sakatlık, skor tahmini ve analiz servisi.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _uptime_seconds() -> float:
    return round(time.monotonic() - START_MONOTONIC, 2)


def _is_scheduler_running(request: Request) -> bool:
    task: asyncio.Task[None] | None = getattr(request.app.state, "scheduler_task", None)
    return task is not None and not task.done()


def require_sync_api_key(request: Request) -> None:
    expected = os.getenv("SYNC_API_KEY", "").strip()
    candidate = request.headers.get("x-api-key", "").strip()
    if not candidate:
        auth = request.headers.get("authorization", "").strip()
        scheme, _, token = auth.partition(" ")
        if scheme.lower() == "bearer":
            candidate = token.strip()
    if (
        not expected
        or not candidate
        or not secrets.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise HTTPException(
            status_code=401,
            detail="Geçersiz veya eksik API anahtarı.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _bulletin_age_seconds() -> float | None:
    cached = get_cached_bulletin()
    if not isinstance(cached, dict):
        return None
    raw_ts = cached.get("generated_at")
    if not isinstance(raw_ts, str) or not raw_ts.strip():
        return None
    try:
        parsed_dt = datetime.fromisoformat(raw_ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed_dt.tzinfo is None:
        parsed_dt = parsed_dt.replace(tzinfo=UTC)
    return max(0.0, round((datetime.now(UTC) - parsed_dt).total_seconds(), 1))


def _build_overview_payload(request: Request) -> dict[str, Any]:
    state = get_runner_status().to_dict()
    return {
        "service": "Futbol Skor ve Analiz Motoru",
        "status": state["last_status"],
        "is_running": state["is_running"],
        "scheduler_active": _is_scheduler_running(request),
        "uptime": _uptime_seconds(),
        "last_updated_at": state["last_run_finished_at"],
        "leagues": state["leagues"],
    }


def _render_dashboard_html(payload: dict[str, Any]) -> str:
    status_text = html.escape(str(payload["status"]))
    updated = html.escape(str(payload["last_updated_at"] or "Henüz çalıştırılmadı"))
    uptime = html.escape(f"{payload['uptime']} sn")

    rows: list[str] = []
    for lg in payload["leagues"].values():
        rows.append(
            "<tr>"
            f"<td><strong>{html.escape(str(lg['name']))}</strong></td>"
            f"<td>{html.escape(str(lg['status']))}</td>"
            f"<td>{int(lg['matches_count'])}</td>"
            f"<td>{int(lg['injuries_count'])}</td>"
            f"<td>{int(lg['predictions_count'])}</td>"
            f"<td>{html.escape(str(lg['last_sync_at'] or '-'))}</td>"
            "</tr>"
        )

    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="tr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Futbol Skor ve Analiz Motoru</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, -apple-system, sans-serif; }}
    body {{ max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }}
    .meta {{ display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 1rem 0 1.5rem; }}
    .card {{ border: 1px solid rgba(128,128,128,0.3); border-radius: 8px; padding: 0.75rem 1rem; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ text-align: left; padding: 0.65rem; border-bottom: 1px solid rgba(128,128,128,0.25); }}
  </style>
</head>
<body>
  <h1>⚽ Futbol Skor ve Analiz Motoru</h1>
  <div class="meta">
    <div class="card"><strong>Durum:</strong> {status_text}</div>
    <div class="card"><strong>Son Güncelleme:</strong> {updated}</div>
    <div class="card"><strong>Çalışma Süresi:</strong> {uptime}</div>
  </div>
  <table>
    <thead>
      <tr>
        <th>Lig</th><th>Durum</th><th>Maç</th><th>Sakatlık</th><th>Tahmin</th><th>Son Senkronizasyon</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</body>
</html>"""


@app.get("/", response_model=None)
async def root(
    request: Request,
    format: str | None = Query(default=None, pattern="^(json|html)$"),
) -> HTMLResponse | JSONResponse:
    payload = _build_overview_payload(request)
    accept = request.headers.get("accept", "").lower()
    wants_html = format == "html" or (
        format != "json" and "text/html" in accept and "application/json" not in accept
    )
    if wants_html:
        return HTMLResponse(content=_render_dashboard_html(payload))
    return JSONResponse(content=payload)


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "status": "ok",
        "uptime": _uptime_seconds(),
        "scheduler_active": _is_scheduler_running(request),
        "bulletin_age_seconds": await asyncio.to_thread(_bulletin_age_seconds),
    }


@app.get("/status")
async def status(request: Request) -> dict[str, Any]:
    data = get_runner_status().to_dict()
    data["uptime"] = _uptime_seconds()
    data["scheduler_active"] = _is_scheduler_running(request)
    return data


async def _execute_sync(
    *,
    league: LeagueId | None,
    dry_run: bool,
) -> dict[str, Any]:
    if sync_lock.locked() or get_runner_status().is_running:
        raise HTTPException(status_code=409, detail="Senkronizasyon zaten devam ediyor.")

    async with sync_lock:
        result = await asyncio.to_thread(
            run_full_cycle,
            leagues=league,
            persist=not dry_run,
        )
        if not dry_run:
            bulletin = await asyncio.to_thread(update_bulletin_cache, result)
        else:
            bulletin = build_bulletin_payload(
                result,
                existing_bulletin=get_cached_bulletin(),
            )

    payload = result.to_dict()
    payload["data_source"] = bulletin["data_source"]
    payload["generated_at"] = bulletin["generated_at"]
    payload["total_matches"] = bulletin["total_matches"]
    payload["total_injuries"] = bulletin["total_injuries"]
    payload["total_played_matches"] = bulletin["total_played_matches"]
    return payload


@app.get("/api/v1/bulletin")
async def get_bulletin(
    request: Request,
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    if not refresh:
        cached = get_cached_bulletin()
        if cached is not None:
            return cached
        raise HTTPException(
            status_code=503,
            detail="Bülten önbelleği henüz hazırlanmadı; zamanlayıcı veya yetkili senkronizasyon bekleniyor.",
        )

    require_sync_api_key(request)
    prev_cached = get_cached_bulletin()
    prev_generated_at = prev_cached.get("generated_at") if prev_cached else None

    async with sync_lock:
        current_cached = get_cached_bulletin()
        if (
            current_cached is not None
            and current_cached.get("generated_at") != prev_generated_at
        ):
            return current_cached

        cycle = await asyncio.to_thread(
            run_full_cycle,
            leagues=None,
            persist=True,
            only_next_round=True,
        )
        if cycle.predictions_count == 0 and cycle.status == "error":
            raise HTTPException(
                status_code=503,
                detail="Bülten verisi üretilemedi; hiçbir ligden maç alınamadı.",
            )
        bulletin = await asyncio.to_thread(update_bulletin_cache, cycle)

    if not bulletin or int(bulletin.get("total_matches", 0)) <= 0:
        raise HTTPException(
            status_code=503,
            detail="Bülten verisi üretilemedi; hiçbir ligden maç alınamadı.",
        )
    return bulletin


@app.post("/sync", dependencies=[Depends(require_sync_api_key)])
async def sync(
    league: LeagueId | None = Query(default=None),
    dry_run: bool = Query(default=False),
) -> dict[str, Any]:
    return await _execute_sync(league=league, dry_run=dry_run)


@app.post("/api/v1/sync", dependencies=[Depends(require_sync_api_key)])
async def sync_v1(
    league: LeagueId | None = Query(default=None),
    dry_run: bool = Query(default=False),
) -> dict[str, Any]:
    return await _execute_sync(league=league, dry_run=dry_run)


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=7860)
