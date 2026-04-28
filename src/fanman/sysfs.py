"""Sysfs and procfs paths."""

from __future__ import annotations

from pathlib import Path


def sysfs_abs(prefix: Path, relative: str) -> Path:
    rel = relative.replace("\\", "/").strip("/")
    return prefix / rel


async def read_int(path: Path) -> int | None:
    try:
        txt = await asyncio_read(path)
        return int(txt.strip())
    except (OSError, ValueError):
        return None


async def write_int(path: Path, value: int) -> None:
    txt = f"{value}\n".encode()
    await asyncio_write(path, txt)


async def asyncio_read(path: Path) -> str:
    import asyncio

    def _read() -> str:
        return path.read_text(encoding="utf-8")

    return await asyncio.to_thread(_read)


async def asyncio_write(path: Path, data: bytes) -> None:
    import asyncio

    def _write() -> None:
        path.write_bytes(data)

    await asyncio.to_thread(_write)
