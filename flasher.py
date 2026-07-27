"""Background workers that do the actual writing.

Two strategies, because they are genuinely different operations:

* ``ImageWriter`` byte-copies the image onto the raw device with ``dd``. The
  image supplies its own partition table, so asking the user to pick GPT or MBR
  here would be theatre — whatever we wrote would be overwritten by sector 0 of
  the image.
* ``FileCopyWriter`` builds a fresh GPT or MBR disk with a single FAT32
  partition and copies the image contents onto it. This is where the partition
  table choice actually decides anything.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

import disks
from disks import Disk, DiskError

FAT32_MAX_FILE_SIZE = 4 * 1024**3 - 1

# dd's progress output is translated, and some locales put the number after the
# word ("skopiowane 1031897088 bajtow"), so the command below forces LC_ALL=C
# and this pattern matches the C-locale form only.
_DD_PROGRESS = re.compile(rb"^(\d+)\s+bytes\b")


def _pkexec(script: str) -> list[str]:
    """Run one privileged shell script, so the user authenticates only once."""
    disks.require_tools("pkexec")
    return ["pkexec", "/bin/sh", "-c", script]


def _describe_exit(code: int, stderr: str) -> str:
    if code in (126, 127):
        return "Authentication was cancelled or failed."
    return stderr.strip() or f"Command exited with status {code}."


class _Writer(QThread):
    """Common plumbing: progress reporting and a single terminal result."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, disk: Disk, image: str, parent=None):
        super().__init__(parent)
        self.disk = disk
        self.image = image
        self.image_size = os.path.getsize(image)

    def run(self) -> None:
        try:
            self._write()
        except DiskError as exc:
            self.failed.emit(str(exc))
        except OSError as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.progress.emit(100)
            self.succeeded.emit()

    def _write(self) -> None:
        raise NotImplementedError


class ImageWriter(_Writer):
    """dd the image straight onto the device, streaming dd's own progress."""

    def _write(self) -> None:
        disks.require_tools("dd", "udisksctl")
        self.status.emit("Unmounting target device…")
        disks.unmount_disk(self.disk)

        command = (
            f"LC_ALL=C dd if={shlex.quote(self.image)} of={shlex.quote(self.disk.path)} "
            "bs=4M status=progress conv=fsync"
        )
        self.status.emit("Waiting for authorisation…")
        process = subprocess.Popen(
            _pkexec(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        tail = []
        assert process.stderr is not None
        for chunk in _iter_progress_lines(process.stderr):
            tail.append(chunk.decode(errors="replace").strip())
            del tail[:-5]
            match = _DD_PROGRESS.match(chunk)
            if match and self.image_size:
                written = int(match.group(1))
                self.progress.emit(min(99, written * 100 // self.image_size))
                self.status.emit(
                    f"Writing… {disks.human_size(written)} of {disks.human_size(self.image_size)}"
                )

        if process.wait() != 0:
            raise DiskError(_describe_exit(process.returncode, "\n".join(tail)))

        self.status.emit("Flushing write cache…")


class FileCopyWriter(_Writer):
    """Partition + format the device, then copy the image's files onto it."""

    def __init__(self, disk: Disk, image: str, table: str, parent=None):
        super().__init__(disk, image, parent)
        if table not in ("gpt", "mbr"):
            raise ValueError(f"Unknown partition table: {table}")
        self.table = table

    def _write(self) -> None:
        disks.require_tools("parted", "wipefs", "mkfs.vfat", "udisksctl", "udevadm")
        self.status.emit("Unmounting target device…")
        disks.unmount_disk(self.disk)

        partition = disks.partition_path(self.disk.path)
        self.status.emit("Waiting for authorisation…")
        self._partition_and_format(partition)

        self.status.emit("Waiting for the new partition…")
        disks.wait_for_device(partition)

        loop_device = disks.loop_setup(self.image)
        try:
            self.status.emit("Mounting image and target…")
            source = Path(disks.mount_device(loop_device))
            target = Path(disks.mount_device(partition))
            try:
                self._copy_tree(source, target)
            finally:
                self.status.emit("Unmounting…")
                disks.unmount_device(partition)
                disks.unmount_device(loop_device)
        finally:
            disks.loop_delete(loop_device)

    def _partition_and_format(self, partition: str) -> None:
        device = shlex.quote(self.disk.path)
        label = _fat_label(self.image)
        steps = [
            f"wipefs -a {device}",
            f"parted -s {device} mklabel {'gpt' if self.table == 'gpt' else 'msdos'}",
            f"parted -s {device} mkpart primary fat32 1MiB 100%",
        ]
        steps.append(
            f"parted -s {device} set 1 esp on"
            if self.table == "gpt"
            else f"parted -s {device} set 1 boot on"
        )
        steps += [
            f"partprobe {device} || true",
            "udevadm settle",
            f"mkfs.vfat -F 32 -n {shlex.quote(label)} {shlex.quote(partition)}",
        ]

        result = subprocess.run(
            _pkexec(" && ".join(steps)), capture_output=True, text=True
        )
        if result.returncode != 0:
            raise DiskError(_describe_exit(result.returncode, result.stderr))

    def _copy_tree(self, source: Path, target: Path) -> None:
        files = [path for path in source.rglob("*") if path.is_file() and not path.is_symlink()]
        oversized = [path for path in files if path.stat().st_size > FAT32_MAX_FILE_SIZE]
        if oversized:
            names = ", ".join(path.name for path in oversized[:3])
            raise DiskError(
                "This image contains files larger than 4 GB, which FAT32 cannot store "
                f"({names}). Use the ISO image write mode instead."
            )

        total = sum(path.stat().st_size for path in files) or 1
        free = shutil.disk_usage(target).free
        if total > free:
            raise DiskError(
                f"Not enough space on the device: need {disks.human_size(total)}, "
                f"{disks.human_size(free)} free."
            )

        copied = 0
        last_percent = -1
        for path in files:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.status.emit(f"Copying {path.name}…")
            with path.open("rb") as src, destination.open("wb") as dst:
                while chunk := src.read(4 * 1024 * 1024):
                    dst.write(chunk)
                    copied += len(chunk)
                    percent = min(99, copied * 100 // total)
                    if percent != last_percent:
                        self.progress.emit(percent)
                        last_percent = percent

        self.status.emit("Flushing write cache…")
        os.sync()


def _iter_progress_lines(stream):
    """dd separates progress updates with \\r, so readline() would block for ages."""
    buffer = b""
    while True:
        block = stream.read(256)
        if not block:
            break
        buffer += block
        buffer = buffer.replace(b"\r", b"\n")
        *complete, buffer = buffer.split(b"\n")
        for line in complete:
            if line.strip():
                yield line
    if buffer.strip():
        yield buffer


def _fat_label(image: str) -> str:
    """FAT32 labels: up to 11 characters, upper case, conservative charset."""
    stem = Path(image).stem.upper()
    cleaned = "".join(char for char in stem if char.isalnum() or char in "-_")
    return cleaned[:11] or "USB"
