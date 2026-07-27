"""Block device discovery and helpers, built on lsblk and udisks2."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field


class DiskError(RuntimeError):
    """A disk operation failed for a reason worth showing the user."""


@dataclass(frozen=True)
class Disk:
    path: str
    size: int
    model: str
    partitions: tuple[str, ...] = field(default=())

    @property
    def label(self) -> str:
        return f"{self.path}  —  {human_size(self.size)}  —  {self.model or 'Unknown device'}"


def human_size(num_bytes: int) -> str:
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _run(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise DiskError(f"Required tool not found: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise DiskError(f"Timed out running: {' '.join(cmd)}") from exc


def require_tools(*names: str) -> None:
    """Fail early with a readable message instead of a stack trace mid-write."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise DiskError("Missing required tool(s): " + ", ".join(missing))


def _lsblk() -> list[dict]:
    result = _run(["lsblk", "--json", "-b", "-o", "PATH,TRAN,SIZE,MODEL,TYPE,MOUNTPOINT"])
    if result.returncode != 0:
        raise DiskError(f"lsblk failed: {result.stderr.strip()}")
    return json.loads(result.stdout).get("blockdevices", [])


def list_usb_disks() -> list[Disk]:
    """Whole USB disks only — never partitions, never internal drives."""
    disks = []
    for node in _lsblk():
        if node.get("type") != "disk" or node.get("tran") != "usb":
            continue
        partitions = tuple(
            child["path"] for child in node.get("children", []) if child.get("type") == "part"
        )
        disks.append(
            Disk(
                path=node["path"],
                size=int(node.get("size") or 0),
                model=(node.get("model") or "").strip(),
                partitions=partitions,
            )
        )
    return disks


def mountpoint_of(device: str) -> str | None:
    for node in _lsblk():
        for candidate in (node, *node.get("children", [])):
            if candidate.get("path") == device:
                return candidate.get("mountpoint")
    return None


def partition_path(disk: str, index: int = 1) -> str:
    """/dev/sdb -> /dev/sdb1, but /dev/nvme0n1 -> /dev/nvme0n1p1."""
    return f"{disk}p{index}" if disk[-1].isdigit() else f"{disk}{index}"


def unmount_disk(disk: Disk) -> None:
    """Unmount every mounted partition so the device is safe to write."""
    for partition in disk.partitions:
        if mountpoint_of(partition):
            _run(["udisksctl", "unmount", "-b", partition])


def unmount_device(device: str) -> None:
    _run(["udisksctl", "unmount", "-b", device])


def mount_device(device: str, timeout: float = 10.0) -> str:
    """Mount via udisks (no root needed for removable media) and return the mountpoint."""
    result = _run(["udisksctl", "mount", "-b", device])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        mountpoint = mountpoint_of(device)
        if mountpoint:
            return mountpoint
        time.sleep(0.3)
    raise DiskError(f"Could not mount {device}: {result.stderr.strip() or result.stdout.strip()}")


def loop_setup(image: str) -> str:
    result = _run(["udisksctl", "loop-setup", "-r", "-f", image])
    match = re.search(r"(/dev/loop\d+)", result.stdout)
    if not match:
        raise DiskError(f"Could not attach {image} to a loop device: {result.stderr.strip()}")
    return match.group(1)


def loop_delete(loop_device: str) -> None:
    _run(["udisksctl", "loop-delete", "-b", loop_device])


def wait_for_device(device: str, timeout: float = 15.0) -> None:
    """Wait for the kernel to publish a freshly created partition node."""
    _run(["udevadm", "settle"], timeout=int(timeout))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if any(node.get("path") == device for entry in _lsblk()
               for node in (entry, *entry.get("children", []))):
            return
        time.sleep(0.3)
    raise DiskError(f"Partition {device} did not appear after formatting.")
