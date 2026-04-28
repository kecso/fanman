"""FastAPI entrypoint."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fanman.api_routes import build_api_router
from fanman.config_schema import load_fan_curves
from fanman.polling import background_worker, graceful_fan_restore
from fanman.rate_limit import RateLimiter
from fanman.settings import Settings, get_settings
from fanman.state import EventCategory, FanManState


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    fan_state = FanManState()
    shutdown_event = asyncio.Event()
    rate_limiter = RateLimiter()
    bg_task: asyncio.Task[None] | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal bg_task
        configure_logging(settings.log_level)
        fan_state.boot_started_at = datetime.now(UTC)
        fan_state.settings_snapshot = {
            "poll_interval": settings.poll_interval,
            "failsafe_temp": settings.failsafe_temp,
            "max_history_minutes": settings.max_history_minutes,
        }
        cfg_path = Path(settings.config_path)
        try:
            fan_state.config = load_fan_curves(cfg_path)
            fan_state.reset_runtime_modes_from_config()
            assert fan_state.config is not None
            fan_state.add_event(
                "info",
                EventCategory.startup,
                f"FanMan started — {len(fan_state.config.fans)} fans, {len(fan_state.config.sensors)} sensors",
            )
        except Exception as e:
            logging.getLogger("fanman").exception("Failed to load %s", cfg_path)
            fan_state.add_event(
                "error",
                EventCategory.error,
                f"Startup config load failed: {e}",
            )

        sysfs_prefix = Path(settings.sysfs_prefix)
        proc_prefix = Path(settings.proc_prefix)
        shutdown_event.clear()
        bg_task = asyncio.create_task(
            background_worker(
                sysfs_prefix,
                proc_prefix,
                fan_state,
                settings.max_history_minutes,
                shutdown_event,
            )
        )

        yield

        shutdown_event.set()
        if bg_task:
            bg_task.cancel()
            try:
                await bg_task
            except asyncio.CancelledError:
                pass
        fan_state.add_event("info", EventCategory.shutdown, "FanMan shutting down — restoring pwm_enable modes")
        await graceful_fan_restore(sysfs_prefix, fan_state.config, settings.graceful_shutdown_mode)

    app = FastAPI(title="FanMan", lifespan=lifespan)

    app.state.fan_state = fan_state
    app.state.sysfs_prefix = settings.sysfs_prefix
    app.state.proc_prefix = settings.proc_prefix
    app.state.settings = settings

    templates_dir = Path(__file__).resolve().parent / "templates"
    static_dir = Path(__file__).resolve().parent / "static"

    templates = Jinja2Templates(directory=str(templates_dir))

    def get_state(request: Request) -> FanManState:
        return request.app.state.fan_state

    api_router = build_api_router(
        get_state=get_state,
        rate_limiter=rate_limiter,
        config_path_getter=lambda: str(Path(settings.config_path)),
        max_hist_minutes_getter=lambda: settings.max_history_minutes,
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "detail": str(exc.detail),
                "status_code": exc.status_code,
            },
        )

    @app.get("/api/health")
    async def health(state: FanManState = Depends(get_state)) -> dict[str, object]:
        boot = state.boot_started_at or datetime.now(UTC)
        uptime = int((datetime.now(UTC) - boot).total_seconds())
        return {"status": "ok", "uptime_seconds": uptime}

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request, state: FanManState = Depends(get_state)) -> HTMLResponse:
        import json

        return templates.TemplateResponse(
            "index.html",
            {"request": request, "hostname_json": json.dumps(state.hostname)},
        )

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


_settings_singleton = get_settings()
app = create_app(_settings_singleton)


def main() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run("fanman.main:app", host="0.0.0.0", port=s.web_port)
