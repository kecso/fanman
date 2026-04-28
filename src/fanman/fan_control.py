"""PWM writes from temperatures and curves."""

from __future__ import annotations

from pathlib import Path

from fanman.config_schema import FanCurvesConfig, FanMode
from fanman.curves import apply_min_start_stop, interpolate_pwm
from fanman.state import EventCategory, FanManState
from fanman.sysfs import read_int, sysfs_abs, write_int


async def control_fans(sysfs_prefix: Path, state: FanManState, cfg: FanCurvesConfig) -> None:
    fs_temp = state.effective_failsafe_temp()
    temps_c: list[float] = []
    for name, sdef in cfg.sensors.items():
        if sdef.type.value != "temperature":
            continue
        sr = state.sensors.get(name)
        if sr and sr.value is not None:
            temps_c.append(sr.value)

    trip = bool(temps_c) and max(temps_c) >= fs_temp

    if trip and not state.failsafe_active:
        state.add_event(
            "warning",
            EventCategory.failsafe,
            f"Failsafe activated: max temp ≥ {fs_temp:.0f}°C — all fans set to 100%",
        )

    if not trip and state.failsafe_active:
        state.add_event(
            "info",
            EventCategory.failsafe,
            "Failsafe deactivated: all temperatures below threshold",
        )

    state.failsafe_active = trip

    if trip:
        for fan_name in cfg.fans:
            rt = state.fans.get(fan_name)
            if rt is None:
                continue
            fdef = cfg.fans[fan_name]
            pwm_path = sysfs_abs(sysfs_prefix, fdef.pwm_path)
            en_path = sysfs_abs(sysfs_prefix, fdef.enable_path)
            rt.error = None
            try:
                await write_int(en_path, 1)
                await write_int(pwm_path, 255)
                rt.last_pwm_applied = 255
            except OSError as e:
                rt.error = str(e)
                state.add_event("error", EventCategory.error, str(e))
        return

    for fan_name, fdef in cfg.fans.items():
        rt = state.fans.get(fan_name)
        if rt is None:
            continue
        rt.error = None
        pwm_path = sysfs_abs(sysfs_prefix, fdef.pwm_path)
        en_path = sysfs_abs(sysfs_prefix, fdef.enable_path)

        try:
            if rt.mode == FanMode.off:
                await write_int(en_path, 0)
                rt.last_pwm_applied = await read_int(pwm_path)
                continue

            await write_int(en_path, 1)

            if rt.mode == FanMode.manual:
                pwm_val = rt.manual_pwm
                if pwm_val is None:
                    pwm_val = await read_int(pwm_path) or 128
                    rt.manual_pwm = pwm_val
                pwm_val = max(0, min(255, int(pwm_val)))
                await write_int(pwm_path, pwm_val)
                rt.last_pwm_applied = pwm_val
                continue

            ts_name = fdef.temp_source
            sr = state.sensors.get(ts_name)
            temp_c = sr.value if sr and sr.value is not None else fdef.curve.min_temp

            rpm_val: float | None = None
            if fdef.rpm_sensor:
                rr = state.sensors.get(fdef.rpm_sensor)
                if rr and rr.value is not None:
                    rpm_val = float(rr.value)

            curve = fdef.curve
            ideal = interpolate_pwm(temp_c, curve)
            ideal = apply_min_start_stop(ideal, curve, rpm_val)

            last = rt.last_pwm_applied
            if last is None:
                last = await read_int(pwm_path)
            if last is None:
                last = ideal

            peak = rt.thermal_peak
            if peak is None:
                peak = temp_c

            if ideal >= last:
                out = ideal
                peak = max(peak, temp_c)
            else:
                if temp_c <= peak - curve.hysteresis:
                    out = ideal
                    peak = temp_c
                else:
                    out = last

            rt.thermal_peak = peak
            await write_int(pwm_path, out)
            rt.last_pwm_applied = out
        except OSError as e:
            rt.error = str(e)
            state.add_event(
                "error",
                EventCategory.error,
                f"Fan '{fan_name}': {e}",
            )


async def refresh_pwm_reads(sysfs_prefix: Path, state: FanManState, cfg: FanCurvesConfig) -> None:
    """Best-effort sysfs pwm readback for dashboard/API."""
    for fan_name, fdef in cfg.fans.items():
        rt = state.fans.get(fan_name)
        if rt is None:
            continue
        pwm_path = sysfs_abs(sysfs_prefix, fdef.pwm_path)
        v = await read_int(pwm_path)
        if v is not None:
            rt.last_pwm_applied = v
