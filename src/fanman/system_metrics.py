"""Host metrics from mounted procfs."""

from __future__ import annotations

from pathlib import Path


def parse_loadavg(proc_prefix: Path) -> tuple[float, float, float]:
    path = proc_prefix / "loadavg"
    try:
        parts = path.read_text(encoding="utf-8").split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (OSError, ValueError, IndexError):
        return 0.0, 0.0, 0.0


def parse_mem_used_percent(proc_prefix: Path) -> float:
    info: dict[str, int] = {}
    try:
        for line in (proc_prefix / "meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, rest = line.split(":", 1)
            parts = rest.strip().split()
            if parts:
                info[key.strip()] = int(parts[0])
    except OSError:
        return 0.0
    total = info.get("MemTotal")
    avail = info.get("MemAvailable")
    if not total or total <= 0:
        return 0.0
    if avail is None:
        free = info.get("MemFree", 0)
        buff = info.get("Buffers", 0)
        cached = info.get("Cached", 0)
        avail = free + buff + cached
    used = total - avail
    return round(100.0 * used / total, 1)


def parse_uptime_seconds(proc_prefix: Path) -> int:
    try:
        line = (proc_prefix / "uptime").read_text(encoding="utf-8").strip().split()
        return int(float(line[0]))
    except (OSError, ValueError, IndexError):
        return 0


def parse_hostname(proc_prefix: Path) -> str:
    """Hostname via mounted proc (Linux exposes kernel.hostname here when proc mounted)."""
    try:
        return (proc_prefix / "sys" / "kernel" / "hostname").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def parse_cpu_times_aggregate(proc_prefix: Path) -> tuple[int, int] | None:
    """Returns (idle jiffies, total jiffies) for first aggregate cpu line."""
    try:
        for line in (proc_prefix / "stat").read_text(encoding="utf-8").splitlines():
            if line.startswith("cpu "):
                parts = line.split()
                nums = [int(x) for x in parts[1:]]
                idle = nums[3] + (nums[6] if len(nums) > 6 else 0)
                total = sum(nums)
                return idle, total
    except (OSError, ValueError):
        pass
    return None


def cpu_usage_percent(prev: tuple[int, int] | None, curr: tuple[int, int] | None) -> float:
    if prev is None or curr is None:
        return 0.0
    idle_prev, total_prev = prev
    idle_curr, total_curr = curr
    didle = idle_curr - idle_prev
    dtotal = total_curr - total_prev
    if dtotal <= 0:
        return 0.0
    busy = dtotal - didle
    return round(max(0.0, min(100.0, 100.0 * busy / dtotal)), 1)
