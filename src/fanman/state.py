"""Shared runtime state (sensor readings, fans, history, events)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fanman.config_schema import FanCurvesConfig, FanMode


class EventCategory(str, Enum):
    startup = "startup"
    shutdown = "shutdown"
    mode_change = "mode_change"
    failsafe = "failsafe"
    config_reload = "config_reload"
    error = "error"
    pwm_change = "pwm_change"


@dataclass
class SensorReading:
    value: float | None
    raw_value: int | None
    stale: bool
    last_updated_iso: str | None


@dataclass
class FanRuntime:
    mode: FanMode
    manual_pwm: int | None = None
    last_pwm_applied: int | None = None
    thermal_peak: float | None = None
    error: str | None = None


@dataclass
class SmartReading:
    device: str
    label: str
    temperature: int | None
    power_on_hours: int | None
    health_status: str | None
    last_updated_iso: str | None


@dataclass
class LogEvent:
    timestamp_iso: str
    level: str
    category: EventCategory
    message: str


@dataclass
class FanManState:
    config: FanCurvesConfig | None = None
    settings_snapshot: dict[str, Any] = field(default_factory=dict)

    sensors: dict[str, SensorReading] = field(default_factory=dict)
    fans: dict[str, FanRuntime] = field(default_factory=dict)
    smart: dict[str, SmartReading] = field(default_factory=dict)

    failsafe_active: bool = False
    ready: bool = False
    boot_started_at: datetime | None = None
    startup_time_iso: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    process_uptime_anchor: datetime = field(default_factory=lambda: datetime.now(UTC))

    cpu_prev_jiff: tuple[int, int] | None = None
    cpu_curr_jiff: tuple[int, int] | None = None
    cpu_usage_percent: float = 0.0

    system_load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mem_used_percent: float = 0.0
    host_uptime_seconds: int = 0
    hostname: str = "unknown"

    history: dict[str, deque[tuple[str, float]]] = field(default_factory=dict)
    events: deque[LogEvent] = field(default_factory=lambda: deque(maxlen=500))

    smart_next_poll_mono: dict[str, float] = field(default_factory=dict)

    def effective_failsafe_temp(self) -> float:
        env = float(self.settings_snapshot.get("failsafe_temp", 85))
        if self.config is None:
            return env
        g = self.config.global_
        if g and g.failsafe_temp is not None:
            return float(g.failsafe_temp)
        return env

    def effective_poll_interval(self) -> int:
        env = int(self.settings_snapshot.get("poll_interval", 5))
        if self.config is None:
            return env
        g = self.config.global_
        if g and g.poll_interval is not None:
            return int(g.poll_interval)
        return env

    def append_history(self, name: str, timestamp_iso: str, val: float, maxlen: int) -> None:
        if name not in self.history:
            self.history[name] = deque(maxlen=maxlen)
        self.history[name].append((timestamp_iso, val))

    def max_history_samples(self, poll_interval_s: int, max_minutes: int) -> int:
        if poll_interval_s <= 0:
            poll_interval_s = 5
        return max(120, int(max_minutes * 60 / poll_interval_s) + 10)

    def add_event(self, level: str, category: EventCategory, message: str) -> None:
        ts = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        self.events.appendleft(LogEvent(timestamp_iso=ts, level=level, category=category, message=message))

    def reset_runtime_modes_from_config(self) -> None:
        assert self.config is not None
        self.fans = {
            name: FanRuntime(mode=f.mode, manual_pwm=None, thermal_peak=None)
            for name, f in self.config.fans.items()
        }
