"""REST API routes under /api/v1 plus helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, ValidationError

from fanman.config_schema import CurveConfig, FanCurvesConfig, FanMode, dump_fan_curves, load_fan_curves, merge_defaults_into_curve
from fanman.errors import api_error
from fanman.rate_limit import RateLimiter
from fanman.state import EventCategory, FanManState
from fanman.sysfs import read_int, sysfs_abs, write_int


def sensor_unit(dtype: str) -> str:
    if dtype == "temperature":
        return "°C"
    if dtype == "rpm":
        return "RPM"
    return "V"


def serialize_sensor(name: str, state: FanManState, cfg: FanCurvesConfig) -> dict[str, Any]:
    sdef = cfg.sensors[name]
    sr = state.sensors.get(name)
    if sr is None:
        raise api_error("not_found", f"Sensor '{name}' not available", 404)
    return {
        "value": sr.value,
        "unit": sensor_unit(sdef.type.value),
        "raw_value": sr.raw_value,
        "path": sdef.path,
        "label": sdef.label,
        "last_updated_iso": sr.last_updated_iso,
        "stale": sr.stale,
    }


async def serialize_fan(
    request: Request,
    name: str,
    state: FanManState,
    cfg: FanCurvesConfig,
) -> dict[str, Any]:
    if name not in cfg.fans:
        raise api_error("not_found", f"Fan '{name}' not found", 404)
    fdef = cfg.fans[name]
    rt = state.fans.get(name)
    sysfs_prefix = Path(request.app.state.sysfs_prefix)

    pwm_path = sysfs_abs(sysfs_prefix, fdef.pwm_path)
    en_path = sysfs_abs(sysfs_prefix, fdef.enable_path)

    pwm_now = rt.last_pwm_applied if rt else None
    if pwm_now is None:
        pwm_now = await read_int(pwm_path)
    pwm_now = pwm_now or 0

    rpm_val = None
    if fdef.rpm_sensor:
        rr = state.sensors.get(fdef.rpm_sensor)
        if rr and rr.value is not None:
            rpm_val = int(round(rr.value))

    ts_name = fdef.temp_source
    sr_t = state.sensors.get(ts_name)
    temp_c = sr_t.value if sr_t and sr_t.value is not None else None

    enable_val = await read_int(en_path)

    pwm_pct = int(round(pwm_now * 100 / 255)) if pwm_now is not None else 0

    curve_obj = merge_defaults_into_curve(fdef.curve)

    en_out = enable_val if enable_val is not None else None

    return {
        "label": fdef.label,
        "pwm_current": pwm_now,
        "pwm_percent": pwm_pct,
        "rpm": rpm_val,
        "mode": rt.mode.value if rt else fdef.mode.value,
        "temp_source_name": ts_name,
        "temp_current": temp_c,
        "curve_config": curve_obj,
        "enable_value": en_out,
        "error": rt.error if rt else None,
    }


class ModeBody(BaseModel):
    mode: FanMode


class PwmBody(BaseModel):
    value: int = Field(ge=0, le=255)


def build_api_router(
    get_state: Callable[..., FanManState],
    rate_limiter: RateLimiter,
    config_path_getter: Callable[[], str],
    max_hist_minutes_getter: Callable[[], int],
) -> APIRouter:
    router = APIRouter()
    StateDep = Annotated[FanManState, Depends(get_state)]

    @router.get("/sensors")
    async def list_sensors(state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        return {name: serialize_sensor(name, state, cfg) for name in cfg.sensors}

    @router.get("/sensors/{name}")
    async def one_sensor(name: str, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None or name not in cfg.sensors:
            raise api_error("not_found", f"Sensor '{name}' does not exist", 404)
        return serialize_sensor(name, state, cfg)

    @router.get("/fans")
    async def list_fans(request: Request, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        out: dict[str, Any] = {}
        for fname in cfg.fans:
            out[fname] = await serialize_fan(request, fname, state, cfg)
        return out

    @router.get("/fans/{name}")
    async def one_fan(request: Request, name: str, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if name not in cfg.fans:
            raise api_error("not_found", f"Fan '{name}' not found", 404)
        return await serialize_fan(request, name, state, cfg)

    @router.put("/fans/{name}/mode")
    async def put_mode(request: Request, name: str, body: ModeBody, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if name not in cfg.fans:
            raise api_error("not_found", f"Fan '{name}' not found", 404)
        ok, wait = rate_limiter.allow(f"mode:{name}", 1.0)
        if not ok:
            raise api_error(
                "rate_limited",
                f"Maximum 1 mode change per fan per second. Try again in {wait:.1f}s",
                429,
            )
        rt = state.fans[name]
        prev = rt.mode
        rt.mode = body.mode
        sysfs_prefix = Path(request.app.state.sysfs_prefix)
        fdef = cfg.fans[name]
        pwm_path = sysfs_abs(sysfs_prefix, fdef.pwm_path)
        en_path = sysfs_abs(sysfs_prefix, fdef.enable_path)

        if body.mode == FanMode.manual:
            rt.manual_pwm = await read_int(pwm_path) or rt.manual_pwm or 128
            await write_int(en_path, 1)
        elif body.mode == FanMode.auto:
            rt.manual_pwm = None
            rt.thermal_peak = None
            await write_int(en_path, 1)
        elif body.mode == FanMode.off:
            rt.manual_pwm = None
            await write_int(en_path, 0)

        state.add_event(
            "info",
            EventCategory.mode_change,
            f"Fan '{name}' mode {prev.value} → {body.mode.value}",
        )
        return {"fan": name, "mode": body.mode.value, "previous_mode": prev.value}

    @router.put("/fans/{name}/pwm")
    async def put_pwm(name: str, body: PwmBody, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if name not in cfg.fans:
            raise api_error("not_found", f"Fan '{name}' not found", 404)
        rt = state.fans[name]
        if rt.mode != FanMode.manual:
            raise api_error(
                "conflict",
                f"Fan '{name}' is in '{rt.mode.value}' mode. Switch to 'manual' mode first via PUT /api/v1/fans/{name}/mode",
                409,
            )
        ok, wait = rate_limiter.allow(f"pwm:{name}", 1.0)
        if not ok:
            raise api_error(
                "rate_limited",
                f"Maximum 1 PWM write per fan per second. Try again in {wait:.1f}s",
                429,
            )
        rt.manual_pwm = body.value
        pwm_pct = int(round(body.value * 100 / 255))
        state.add_event(
            "info",
            EventCategory.pwm_change,
            f"Fan '{name}' manual PWM → {body.value}",
        )
        return {"fan": name, "pwm_set": body.value, "pwm_percent": pwm_pct}

    @router.get("/fans/{name}/curve")
    async def get_curve(name: str, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if name not in cfg.fans:
            raise api_error("not_found", f"Fan '{name}' not found", 404)
        return merge_defaults_into_curve(cfg.fans[name].curve)

    @router.put("/fans/{name}/curve")
    async def put_curve(name: str, body: CurveConfig, state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if name not in cfg.fans:
            raise api_error("not_found", f"Fan '{name}' not found", 404)
        ok, wait = rate_limiter.allow(f"curve:{name}", 5.0)
        if not ok:
            raise api_error(
                "rate_limited",
                f"Maximum 1 curve write per fan per 5 seconds. Try again in {wait:.1f}s",
                429,
            )
        cfg.fans[name].curve = body
        persisted = True
        path = Path(config_path_getter())

        try:
            dump_fan_curves(cfg, path)
        except OSError:
            persisted = False
        return {"fan": name, "curve_config": merge_defaults_into_curve(body), "persisted": persisted}

    @router.get("/smart")
    async def smart_list(state: StateDep) -> list[dict[str, Any]]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        out: list[dict[str, Any]] = []
        for sd in cfg.smart_devices:
            r = state.smart.get(sd.device)
            if r is None:
                out.append(
                    {
                        "device": sd.device,
                        "label": sd.label,
                        "temperature": None,
                        "power_on_hours": None,
                        "health_status": None,
                        "last_updated_iso": None,
                    }
                )
            else:
                out.append(
                    {
                        "device": r.device,
                        "label": r.label,
                        "temperature": r.temperature,
                        "power_on_hours": r.power_on_hours,
                        "health_status": r.health_status,
                        "last_updated_iso": r.last_updated_iso,
                    }
                )
        return out

    @router.get("/system")
    async def system_metrics(state: StateDep) -> dict[str, Any]:
        if state.boot_started_at is None:
            raise api_error("unavailable", "Still initializing", 503)
        l1, l5, l15 = state.system_load
        return {
            "cpu_load_1m": l1,
            "cpu_load_5m": l5,
            "cpu_load_15m": l15,
            "cpu_usage_percent": state.cpu_usage_percent,
            "memory_used_percent": state.mem_used_percent,
            "uptime_seconds": state.host_uptime_seconds,
        }

    @router.get("/history/{sensor_name}")
    async def history(
        sensor_name: str,
        state: StateDep,
        minutes: int = Query(default=60, ge=1),
    ) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        if sensor_name not in cfg.sensors:
            raise api_error("not_found", f"Sensor '{sensor_name}' not found", 404)
        cap = max_hist_minutes_getter()
        minutes = min(minutes, cap)
        dq = state.history.get(sensor_name)
        readings = []
        if dq:
            span_s = minutes * 60
            cutoff = datetime.now(UTC).timestamp() - span_s
            for ts_iso, val in dq:
                try:
                    from datetime import datetime as dtmod

                    t = dtmod.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if t >= cutoff:
                    readings.append({"timestamp_iso": ts_iso, "value": val})
        return {
            "sensor_name": sensor_name,
            "unit": sensor_unit(cfg.sensors[sensor_name].type.value),
            "readings": readings,
        }

    @router.get("/config")
    async def run_config(state: StateDep) -> dict[str, Any]:
        cfg = state.config
        if cfg is None:
            raise api_error("unavailable", "Configuration not loaded", 503)
        return cfg.model_dump(mode="json", by_alias=True)

    @router.post("/config/reload")
    async def reload_cfg(state: StateDep) -> dict[str, Any]:
        ok, wait = rate_limiter.allow("reload", 10.0)
        if not ok:
            raise api_error(
                "rate_limited",
                f"Maximum one reload per 10 seconds. Try again in {wait:.1f}s",
                429,
            )
        path = Path(config_path_getter())
        try:
            new_cfg = load_fan_curves(path)
        except ValidationError as e:
            raise api_error("validation_error", str(e), 400)
        except json.JSONDecodeError as e:
            raise api_error("validation_error", str(e), 400)
        except ValueError as e:
            raise api_error("validation_error", str(e), 400)
        state.config = new_cfg
        state.reset_runtime_modes_from_config()
        state.add_event(
            "info",
            EventCategory.config_reload,
            "Configuration reloaded from disk",
        )
        return {
            "status": "reloaded",
            "sensors_count": len(new_cfg.sensors),
            "fans_count": len(new_cfg.fans),
            "smart_devices_count": len(new_cfg.smart_devices),
        }

    @router.get("/events")
    async def events(
        state: StateDep,
        limit: int = Query(default=50, ge=1, le=500),
        level: str | None = Query(default=None),
    ) -> dict[str, Any]:
        picked = []
        for ev in state.events:
            if level and ev.level != level:
                continue
            picked.append(ev)
            if len(picked) >= limit:
                break
        return {
            "events": [
                {
                    "timestamp_iso": e.timestamp_iso,
                    "level": e.level,
                    "category": e.category.value,
                    "message": e.message,
                }
                for e in picked
            ]
        }

    return router
