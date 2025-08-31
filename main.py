from PyQt6.QtWidgets import QMainWindow,QApplication
from PyQt6.uic import loadUi
import sys, os
import subprocess
from PyQt6.QtWidgets import QFileDialog
import re
import threading
from popups import *


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class MyWindow(QMainWindow):
    def __init__(self):
        super(MyWindow, self).__init__()

        loadUi(resource_path("mainui.ui"), self)

        self.setWindowTitle("Simon's Linux USB flasher")

        self.ptt = "none"
        self.image = "none"

        print(self.list_external_disks())
        self.refresh_disks()
        self.refresh.clicked.connect(self.refresh_disks)

        self.iso.clicked.connect(self.choose_image_file)
        self.flash.clicked.connect(lambda: self.flash_drive(self.ptt, self.image))

        self.mbr.toggled.connect(self.radio_mbr)
        self.gpt.toggled.connect(self.radio_gpt)

    def flash_drive(self, ptt, image):
        print(image)
        print(ptt)

        if self.ptt != "none" and self.image != "none":
            if ask_confirmation("Flasher", "All of data from your drive will be erased, Are you sure?"):
                selected = self.comboBox.currentText()
                if not selected or not image:
                    print("Select disk and image!")
                    return

                device = selected.split(" ")[0]
                print(f"Flashing {image} to {device}...")

                t = threading.Thread(target=self.run_background_flash(self.ptt, device, self.image), daemon=True)
                t.start()
            else:
                pass
        else:
            show_info("Flasher", "Please choose partiton table type and image file")

    def run_background_flash(self, ptt, device, image):
        match self.ptt:
            case "mbr":
                message = "You can close this window now!"
                command = f"sudo wipefs -a {device} && sudo parted {device} mklabel msdos && echo Set MBR to disk! && echo Flashing, wait for the end && sudo dd if={image} of={device} bs=4M status=progress oflag=sync"
                subprocess.run([
                    'konsole',
                    '-e',
                    f'bash -c "{command}; echo \'{message}\'; read -n 1 -s; exit"'
                ])

            case "gpt":
                message = "You can close this window now!"
                command = f"sudo wipefs -a {device} && sudo parted {device} mklabel gpt && echo Set GPT to disk! && echo Flashing, wait for the end && sudo dd if={image} of={device} bs=4M status=progress oflag=sync"
                subprocess.run([
                    'konsole',
                    '-e',
                    f'bash -c "{command}; echo \'{message}\'; read -n 1 -s; exit"'
                ])

            case _:
                show_info("Flasher", "Choose partiton label type!")


        print("Background process finished")

    def radio_mbr(self):
        if self.mbr.isChecked():
            print("MBR is checked")
            self.ptt = "mbr"
            print("Selected partition table type: MBR")

    def radio_gpt(self):
        if self.gpt.isChecked():
            print("GPT is checked")
            self.ptt = "gpt"
            print("Selected partition table type: GPT")


    def refresh_disks(self):
        self.comboBox.clear()
        disks = self.list_external_disks()
        self.comboBox.addItems(disks)

    def choose_image_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ISO/IMG File",
            "",
            "Disk Images (*.iso *.img)"
        )
        if file_path:
            self.choosenfile.setText(file_path)
            self.image = file_path


    def list_external_disks(self):
        result = subprocess.run(
            ["lsblk", "-dn", "-o", "NAME,TRAN,SIZE,MODEL"],
            capture_output=True, text=True
        )
        disks = []
        for line in result.stdout.splitlines():
            parts = line.split(maxsplit=3)
            if len(parts) < 3:
                continue
            name, tran, size = parts[0:3]
            model = parts[3] if len(parts) == 4 else ""

            if tran == "usb":
                display = f"/dev/{name} - {size} - {model}"
                disks.append(display)

        return disks

def window():
    os.environ["QT_QPA_PLATFORM"] = "xcb"
    app = QApplication(sys.argv)
    win = MyWindow()
    win.show()
    sys.exit(app.exec())

window()