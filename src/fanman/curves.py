"""Curve interpolation and hysteresis helpers."""

from __future__ import annotations

from fanman.config_schema import CurveConfig, Interpolation


def interpolate_pwm(temp_c: float, curve: CurveConfig) -> int:
    """Pure PWM target from temperature (no hysteresis)."""
    if curve.interpolation == Interpolation.linear:
        if temp_c <= curve.min_temp:
            return curve.min_pwm
        if temp_c >= curve.max_temp:
            return curve.max_pwm
        span = curve.max_temp - curve.min_temp
        if span <= 0:
            return curve.min_pwm
        t = (temp_c - curve.min_temp) / span
        return int(round(curve.min_pwm + (curve.max_pwm - curve.min_pwm) * t))

    assert curve.steps
    pwm = curve.min_pwm
    for step in curve.steps:
        if temp_c >= step.temp:
            pwm = step.pwm
        else:
            break
    return max(curve.min_pwm, min(curve.max_pwm, pwm))


def apply_min_start_stop(pwm: int, curve: CurveConfig, rpm: float | None) -> int:
    """Avoid fan stall: boost toward min_start when duty is below min_stop but RPM is absent/low."""
    if pwm <= 0:
        return 0
    stopped = rpm is None or rpm < 120
    if pwm > 0 and pwm < curve.min_stop:
        if stopped:
            return max(curve.min_start, curve.min_pwm)
        return max(curve.min_stop, pwm)
    return min(255, pwm)
