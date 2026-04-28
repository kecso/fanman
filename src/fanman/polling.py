"""Periodic sysfs/proc polling and SMART."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from fanman.config_schema import FanCurvesConfig
from fanman.fan_control import control_fans, refresh_pwm_reads
from fanman.smart_monitor import extract_smart_fields, run_smartctl_json
from fanman.state import EventCategory, FanManState, SensorReading, SmartReading
from fanman.sysfs import read_int, sysfs_abs
from fanman.system_metrics import (
    cpu_usage_percent,
    parse_cpu_times_aggregate,
    parse_hostname,
    parse_loadavg,
    parse_mem_used_percent,
    parse_uptime_seconds,
)

logger = logging.getLogger("fanman.poll")


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def poll_sensors_once(
    sysfs_prefix: Path,
    state: FanManState,
    cfg: FanCurvesConfig,
    max_history_samples: int,
) -> None:
    ts = _iso_now()
    for name, sdef in cfg.sensors.items():
        abs_path = sysfs_abs(sysfs_prefix, sdef.path)
        prev = state.sensors.get(name)
        raw = await read_int(abs_path)
        stale = False
        raw_val = prev.raw_value if prev else None
        val = prev.value if prev else None
        last_iso = prev.last_updated_iso if prev else None

        if raw is None:
            stale = True
            if prev is None:
                raw_val = None
                val = None
                last_iso = ts
            else:
                raw_val = prev.raw_value
                val = prev.value
                last_iso = prev.last_updated_iso
        else:
            raw_val = raw
            divisor = float(sdef.divisor or 1.0)
            val = raw_val / divisor
            last_iso = ts

        state.sensors[name] = SensorReading(
            value=val,
            raw_value=raw_val,
            stale=stale,
            last_updated_iso=last_iso,
        )

        if raw is not None and val is not None and not stale:
            state.append_history(name, ts, float(val), max_history_samples)


async def poll_system(proc_prefix: Path, state: FanManState) -> None:
    state.system_load = parse_loadavg(proc_prefix)
    state.mem_used_percent = parse_mem_used_percent(proc_prefix)
    state.host_uptime_seconds = parse_uptime_seconds(proc_prefix)
    state.hostname = parse_hostname(proc_prefix)

    curr = parse_cpu_times_aggregate(proc_prefix)
    if curr is not None:
        prev = state.cpu_curr_jiff
        state.cpu_prev_jiff = prev
        state.cpu_curr_jiff = curr
        state.cpu_usage_percent = cpu_usage_percent(prev, curr)


async def poll_smart(state: FanManState, cfg: FanCurvesConfig, loop_time: float) -> None:
    for sd in cfg.smart_devices:
        key = sd.device
        nxt = state.smart_next_poll_mono.get(key, 0.0)
        if loop_time < nxt:
            continue
        state.smart_next_poll_mono[key] = loop_time + float(sd.poll_interval)
        data = await run_smartctl_json(sd.device)
        ts = _iso_now()
        if not data:
            state.smart[key] = SmartReading(
                device=sd.device,
                label=sd.label,
                temperature=None,
                power_on_hours=None,
                health_status=None,
                last_updated_iso=ts,
            )
            continue
        temp, poh, health = extract_smart_fields(data)
        state.smart[key] = SmartReading(
            device=sd.device,
            label=sd.label,
            temperature=temp,
            power_on_hours=poh,
            health_status=health,
            last_updated_iso=ts,
        )


async def poll_cycle(
    sysfs_prefix: Path,
    proc_prefix: Path,
    state: FanManState,
    cfg: FanCurvesConfig,
    max_history_minutes: int,
) -> None:
    poll_iv = state.effective_poll_interval()
    maxlen = state.max_history_samples(poll_iv, max_history_minutes)
    await poll_sensors_once(sysfs_prefix, state, cfg, maxlen)
    await poll_system(proc_prefix, state)

    loop_time = asyncio.get_running_loop().time()
    await poll_smart(state, cfg, loop_time)

    await control_fans(sysfs_prefix, state, cfg)
    await refresh_pwm_reads(sysfs_prefix, state, cfg)


async def background_worker(
    sysfs_prefix: Path,
    proc_prefix: Path,
    state: FanManState,
    max_history_minutes: int,
    shutdown: asyncio.Event,
) -> None:
    while not shutdown.is_set():
        cfg = state.config
        if cfg is None:
            logger.warning("No configuration loaded — skipping poll cycle")
            await asyncio.sleep(2)
            continue
        try:
            await poll_cycle(sysfs_prefix, proc_prefix, state, cfg, max_history_minutes)
            state.ready = True
        except Exception:
            logger.exception("Poll cycle failed")
            state.add_event(
                "error",
                EventCategory.error,
                "Poll cycle raised an exception — check logs",
            )
        interval = max(1, state.effective_poll_interval())
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=interval)
        except asyncio.TimeoutError:
            continue


async def graceful_fan_restore(sysfs_prefix: Path, cfg: FanCurvesConfig | None, pwm_enable_mode: int) -> None:
    if cfg is None:
        return
    from fanman.sysfs import write_int

    for _fname, fdef in cfg.fans.items():
        try:
            en_path = sysfs_abs(sysfs_prefix, fdef.enable_path)
            await write_int(en_path, pwm_enable_mode)
        except OSError:
            pass
