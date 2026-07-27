#!/usr/bin/env python3
"""USB Flasher — write disk images to USB drives on Linux."""

from __future__ import annotations

import os
import sys

from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow
from PyQt6.uic import loadUi

import disks
from disks import Disk, DiskError
from flasher import FileCopyWriter, ImageWriter
from popups import ask_confirmation, show_error, show_info

APP_NAME = "USB Flasher"


def resource_path(relative_path: str) -> str:
    """Resolve bundled data files, whether run from source or a PyInstaller build."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        loadUi(resource_path("mainui.ui"), self)
        self.setWindowTitle(APP_NAME)

        self.image_path: str | None = None
        self.worker: ImageWriter | FileCopyWriter | None = None

        self.refreshButton.clicked.connect(self.refresh_devices)
        self.browseButton.clicked.connect(self.choose_image)
        self.flashButton.clicked.connect(self.start_flash)
        self.modeFilesRadio.toggled.connect(self._update_mode)

        self._update_mode()
        self.refresh_devices()

    # --- device list -----------------------------------------------------

    def refresh_devices(self) -> None:
        self.deviceCombo.clear()
        try:
            devices = disks.list_usb_disks()
        except DiskError as exc:
            show_error(self, APP_NAME, str(exc))
            return

        for disk in devices:
            self.deviceCombo.addItem(disk.label, disk)

        if devices:
            self.set_status(f"Found {len(devices)} USB device(s).")
        else:
            self.set_status("No USB devices found. Plug one in and press Refresh.")
        self._update_flash_button()

    def selected_disk(self) -> Disk | None:
        return self.deviceCombo.currentData()

    # --- image selection -------------------------------------------------

    def choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image file", "", "Disk images (*.iso *.img);;All files (*)"
        )
        if not path:
            return
        self.image_path = path
        self.imagePathEdit.setText(path)
        self.imagePathEdit.setToolTip(path)
        self.set_status(f"Selected image: {disks.human_size(os.path.getsize(path))}")
        self._update_flash_button()

    # --- ui state --------------------------------------------------------

    def _update_mode(self) -> None:
        copying_files = self.modeFilesRadio.isChecked()
        for widget in (self.tableLabel, self.tableGptRadio, self.tableMbrRadio):
            widget.setEnabled(copying_files)

    def _update_flash_button(self) -> None:
        self.flashButton.setEnabled(
            self.worker is None and self.selected_disk() is not None and self.image_path is not None
        )

    def _set_busy(self, busy: bool) -> None:
        for widget in (self.deviceCombo, self.refreshButton, self.browseButton,
                       self.modeBox, self.flashButton):
            widget.setEnabled(not busy)
        if not busy:
            self._update_mode()
            self._update_flash_button()

    def set_status(self, message: str) -> None:
        self.statusLabel.setText(message)

    # --- flashing --------------------------------------------------------

    def start_flash(self) -> None:
        disk = self.selected_disk()
        if disk is None or self.image_path is None:
            show_info(self, APP_NAME, "Select a USB device and an image file first.")
            return

        if os.path.getsize(self.image_path) > disk.size:
            show_error(
                self, APP_NAME,
                f"The image ({disks.human_size(os.path.getsize(self.image_path))}) is larger "
                f"than {disk.path} ({disks.human_size(disk.size)}).",
            )
            return

        if not ask_confirmation(
            self, APP_NAME,
            f"Erase {disk.path} and write {os.path.basename(self.image_path)}?",
            f"Everything on {disk.label} will be destroyed. This cannot be undone.",
        ):
            return

        try:
            if self.modeFilesRadio.isChecked():
                table = "gpt" if self.tableGptRadio.isChecked() else "mbr"
                self.worker = FileCopyWriter(disk, self.image_path, table, self)
            else:
                self.worker = ImageWriter(disk, self.image_path, self)
        except (DiskError, OSError) as exc:
            show_error(self, APP_NAME, str(exc))
            return

        self.worker.progress.connect(self.progressBar.setValue)
        self.worker.status.connect(self.set_status)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.finished.connect(self._on_finished)

        self.progressBar.setValue(0)
        self._set_busy(True)
        self.worker.start()

    def _on_success(self) -> None:
        self.set_status("Done. It is safe to remove the device.")
        show_info(self, APP_NAME, "Finished writing. It is safe to remove the device.")

    def _on_failure(self, message: str) -> None:
        self.progressBar.setValue(0)
        self.set_status(f"Failed: {message}")
        show_error(self, APP_NAME, message)

    def _on_finished(self) -> None:
        self.worker = None
        self._set_busy(False)
        self.refresh_devices()

    def closeEvent(self, event) -> None:
        if self.worker is not None and self.worker.isRunning():
            if not ask_confirmation(
                self, APP_NAME, "A write is still in progress.",
                "Quitting now will leave the device in an unusable state. Quit anyway?",
            ):
                event.ignore()
                return
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
