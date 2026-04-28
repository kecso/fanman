"""smartctl JSON parsing."""

from __future__ import annotations

import asyncio
import json
from asyncio.subprocess import PIPE
from typing import Any


async def run_smartctl_json(device: str) -> dict[str, Any] | None:
    proc = await asyncio.create_subprocess_exec(
        "smartctl",
        "-j",
        "-a",
        device,
        stdout=PIPE,
        stderr=PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode not in (0, 4):  # 4 = warnings but often readable
        return None
    try:
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def extract_smart_fields(data: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    """temperature °C, power_on_hours, PASSED|FAILED|None."""
    temp: int | None = None
    poh: int | None = None
    health: str | None = None

    # NVMe
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict):
        if "temperature" in nvme:
            try:
                temp = int(nvme["temperature"])
            except (TypeError, ValueError):
                pass

    # ATA SMART attributes table
    ata = data.get("ata_smart_attributes")
    if isinstance(ata, dict):
        table = ata.get("table")
        if isinstance(table, list):
            for row in table:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name", "")).lower()
                val = row.get("value")
                raw = row.get("raw")
                if name in ("temperature_celsius", "airflow_temperature_cel"):
                    try:
                        if isinstance(raw, dict) and "value" in raw:
                            temp = int(str(raw["value"]).split()[0])
                        elif val is not None:
                            temp = int(val)
                    except (TypeError, ValueError):
                        pass
                if "power" in name and "hour" in name:
                    try:
                        poh = int(raw.get("value") if isinstance(raw, dict) else raw or val)
                    except (TypeError, ValueError, AttributeError):
                        pass

    # Generic temperature field (some outputs)
    if temp is None and "temperature" in data:
        try:
            temp = int(data["temperature"])
        except (TypeError, ValueError):
            pass

    poh_section = data.get("power_on_time")
    if isinstance(poh_section, dict) and poh is None:
        hrs = poh_section.get("hours")
        if hrs is not None:
            try:
                poh = int(hrs)
            except (TypeError, ValueError):
                pass

    if poh is None:
        poh = data.get("power_on_hours")
        try:
            poh = int(poh) if poh is not None else None
        except (TypeError, ValueError):
            poh = None

    smart_status = data.get("smartctl")
    if isinstance(smart_status, dict):
        passed = smart_status.get("passed")
        if passed is True:
            health = "PASSED"
        elif passed is False:
            health = "FAILED"

    return temp, poh, health
