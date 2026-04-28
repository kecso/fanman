"""Unit tests for curve math."""

from fanman.config_schema import CurveConfig, CurveStep, Interpolation
from fanman.curves import apply_min_start_stop, interpolate_pwm


def test_linear_below_min():
    c = CurveConfig(
        min_temp=40,
        max_temp=75,
        min_pwm=60,
        max_pwm=255,
        min_start=80,
        min_stop=50,
        hysteresis=2,
        interpolation=Interpolation.linear,
    )
    assert interpolate_pwm(30, c) == 60
    assert interpolate_pwm(75, c) == 255


def test_linear_mid():
    c = CurveConfig(
        min_temp=40,
        max_temp=80,
        min_pwm=100,
        max_pwm=200,
        min_start=120,
        min_stop=90,
        hysteresis=2,
        interpolation=Interpolation.linear,
    )
    assert interpolate_pwm(60, c) == 150


def test_step():
    steps = [
        CurveStep(temp=35, pwm=0),
        CurveStep(temp=50, pwm=120),
    ]
    c = CurveConfig(
        min_temp=30,
        max_temp=70,
        min_pwm=0,
        max_pwm=200,
        min_start=70,
        min_stop=40,
        hysteresis=2,
        interpolation=Interpolation.step,
        steps=steps,
    )
    assert interpolate_pwm(40, c) == 0
    assert interpolate_pwm(55, c) == 120


def test_min_start_stop():
    c = CurveConfig(
        min_temp=40,
        max_temp=75,
        min_pwm=60,
        max_pwm=255,
        min_start=90,
        min_stop=50,
        hysteresis=2,
        interpolation=Interpolation.linear,
    )
    assert apply_min_start_stop(30, c, rpm=None) >= c.min_start
