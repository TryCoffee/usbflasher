# USB Flasher

A small Qt desktop app for writing disk images to USB drives on Linux.

It only ever lists **removable USB disks** — internal drives never appear in the
device list, so there is no way to pick the wrong one by accident.

![Linux](https://img.shields.io/badge/platform-Linux-blue) ![Python](https://img.shields.io/badge/python-3.10%2B-blue)

## Features

- Detects connected USB drives automatically (internal disks are never listed)
- Real in-app progress bar, parsed live from `dd`
- Two write modes, described below
- Unmounts the target automatically before writing
- Privilege escalation through **polkit** (`pkexec`) — one graphical prompt, no
  terminal emulator, no password typed into the app
- Runs natively on Wayland and X11

## Write modes

**Write image to device** (default) — a byte-for-byte copy of the image onto the
raw device, exactly what `dd` does. This is what you want for practically every
Linux ISO, since those are hybrid images that carry their own partition table
and boot sectors.

**Format device and copy files** — wipes the drive, creates a fresh **GPT** or
**MBR** table with a single FAT32 partition, and copies the image's contents
onto it. Useful for Windows installers and for drives you want to stay readable
and writable afterwards. The resulting stick boots on UEFI systems only, and
FAT32 cannot hold files larger than 4 GB (the app checks and tells you).

> The partition table choice applies **only** to the second mode. In image mode
> the image supplies its own table, so any table written beforehand is
> immediately overwritten — offering the choice there would be meaningless.

## Requirements

- Linux with a graphical session
- Python 3.10+
- PyQt6
- polkit (`pkexec`), `udisks2` (`udisksctl`), `util-linux` (`lsblk`, `wipefs`),
  `parted`, `dosfstools` (`mkfs.vfat`), `coreutils` (`dd`)

All of these ship by default on mainstream desktop distributions. The app checks
for the tools it needs and reports anything missing before touching a device.

## Installation

```bash
git clone https://github.com/TryCoffee/usb-flasher.git
cd usb-flasher
pip install -r requirements.txt
python3 main.py
```

### Desktop menu entry

`usbflasher.desktop` adds the app to your application menu and launcher. It
ships with a placeholder path, so substitute the directory you cloned into as
you install it — run this from inside the repository:

```bash
sed "s|/path/to/usbflasher|$PWD|" usbflasher.desktop \
    > ~/.local/share/applications/usbflasher.desktop
update-desktop-database ~/.local/share/applications
```

"USB Flasher" then appears under **System**. To install it for every user on the
machine, write to `/usr/share/applications/` instead (needs root).

The entry uses the stock `drive-removable-media-usb` icon name, so it picks up
whatever icon theme you already use — nothing extra to install. Remove it again
by deleting the file from `~/.local/share/applications/`.

## Usage

1. Plug in a USB drive and pick it from the list (press **Refresh** if needed).
2. **Browse…** for an `.iso` or `.img` file.
3. Choose a write mode.
4. Press **FLASH** and confirm. Authorise the polkit prompt when it appears.

Wait for "Done. It is safe to remove the device." before unplugging — the write
is only flushed to the drive when the operation reports as finished.

## Notes and limitations

- **There is no cancel button, by design.** Once `dd` is running as root, an
  unprivileged process cannot signal it, so a "Cancel" that silently failed
  would be worse than none. Interrupting a write leaves the drive unusable
  anyway; let it finish and rewrite it if you picked the wrong image.
- Linux only. The device detection, unmounting and privilege escalation are all
  built on Linux-specific tooling.

## Project layout

| File | Purpose |
| --- | --- |
| `main.py` | Application entry point and main window |
| `flasher.py` | Background write workers (`ImageWriter`, `FileCopyWriter`) |
| `disks.py` | Device discovery, mounting and helpers |
| `popups.py` | Message-box wrappers |
| `mainui.ui` | Qt Designer layout |
| `usbflasher.desktop` | Application menu entry |

## License

MIT — see [LICENSE](LICENSE).
