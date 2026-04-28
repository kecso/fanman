"""fan_curves.json — Pydantic models and validation."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _no_traversal(path: str, field_name: str) -> str:
    if ".." in path or path.startswith("/"):
        raise ValueError(f"{field_name} must be relative without '..' segments")
    parts = path.replace("\\", "/").split("/")
    if any(p == ".." or p == "" for p in parts):
        raise ValueError(f"{field_name} invalid path segments")
    return path


class SensorType(str, Enum):
    temperature = "temperature"
    rpm = "rpm"
    voltage = "voltage"


class FanMode(str, Enum):
    auto = "auto"
    manual = "manual"
    off = "off"


class Interpolation(str, Enum):
    linear = "linear"
    step = "step"


class CurveStep(BaseModel):
    temp: float
    pwm: int = Field(ge=0, le=255)


class CurveConfig(BaseModel):
    min_temp: float
    max_temp: float
    min_pwm: int = Field(ge=0, le=255)
    max_pwm: int = Field(ge=0, le=255)
    min_start: int = Field(ge=0, le=255)
    min_stop: int = Field(ge=0, le=255)
    hysteresis: float = Field(default=2.0, ge=0)
    interpolation: Interpolation = Interpolation.linear
    steps: list[CurveStep] | None = None

    @model_validator(mode="after")
    def validate_curve(self) -> CurveConfig:
        if self.min_temp >= self.max_temp:
            raise ValueError("curve.min_temp must be less than curve.max_temp")
        if self.min_pwm > self.max_pwm:
            raise ValueError("curve.min_pwm must be <= curve.max_pwm")
        if self.interpolation == Interpolation.step:
            if not self.steps:
                raise ValueError("curve.steps required when interpolation is step")
            temps = [s.temp for s in self.steps]
            if temps != sorted(temps):
                raise ValueError("curve.steps must be sorted ascending by temp")
        return self


class GlobalOverrides(BaseModel):
    poll_interval: int | None = Field(default=None, ge=1)
    failsafe_temp: float | None = None
    log_level: str | None = None


class SensorDef(BaseModel):
    path: str
    label: str
    type: SensorType
    divisor: float | None = None

    @field_validator("path")
    @classmethod
    def path_safe(cls, v: str) -> str:
        return _no_traversal(v, "path")

    @model_validator(mode="after")
    def default_divisor(self) -> SensorDef:
        if self.divisor is None:
            if self.type == SensorType.temperature:
                object.__setattr__(self, "divisor", 1000.0)
            else:
                object.__setattr__(self, "divisor", 1.0)
        return self


class FanDef(BaseModel):
    pwm_path: str
    enable_path: str
    rpm_sensor: str | None = None
    label: str
    temp_source: str
    curve: CurveConfig
    mode: FanMode = FanMode.auto

    @field_validator("pwm_path", "enable_path")
    @classmethod
    def paths_safe(cls, v: str) -> str:
        return _no_traversal(v, "pwm_path")


class SmartDevice(BaseModel):
    device: str
    label: str
    poll_interval: int = Field(default=60, ge=1)

    @field_validator("device")
    @classmethod
    def dev_path(cls, v: str) -> str:
        if not v.startswith("/dev/"):
            raise ValueError("smart_devices[].device must start with /dev/")
        return v


class FanCurvesConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: Literal["1"]
    global_: GlobalOverrides | None = Field(default=None, alias="global")
    sensors: dict[str, SensorDef]
    fans: dict[str, FanDef]
    smart_devices: list[SmartDevice] = Field(default_factory=list)

    @model_validator(mode="after")
    def cross_refs(self) -> FanCurvesConfig:
        for fname, fan in self.fans.items():
            if fan.temp_source not in self.sensors:
                raise ValueError(f"fan '{fname}' references unknown temp_source '{fan.temp_source}'")
            src = self.sensors[fan.temp_source]
            if src.type != SensorType.temperature:
                raise ValueError(f"fan '{fname}' temp_source must be a temperature sensor")
            if fan.rpm_sensor:
                if fan.rpm_sensor not in self.sensors:
                    raise ValueError(f"fan '{fname}' references unknown rpm_sensor '{fan.rpm_sensor}'")
                if self.sensors[fan.rpm_sensor].type != SensorType.rpm:
                    raise ValueError(f"fan '{fname}' rpm_sensor must have type rpm")
        return self


def load_fan_curves(path: Path | str) -> FanCurvesConfig:
    path = Path(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("fan_curves.json is empty")
    raw = json.loads(text)
    return FanCurvesConfig.model_validate(raw)


def dump_fan_curves(config: FanCurvesConfig, path: Path | str) -> None:
    path = Path(path)
    data = config.model_dump(mode="json", by_alias=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_defaults_into_curve(curve: CurveConfig) -> dict[str, Any]:
    """JSON-serializable curve_config for API responses."""
    out = curve.model_dump(mode="json")
    out["interpolation"] = curve.interpolation.value
    if curve.steps:
        out["steps"] = [{"temp": s.temp, "pwm": s.pwm} for s in curve.steps]
    else:
        out["steps"] = None
    return out
