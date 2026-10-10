# Changelog

## 0.3.0 - 2026-10-10

First published version.

## 0.3.0-wip (2026-10-05)
- Guided WSL setup: yellow "Step 0" box with Install WSL now (admin prompt, `wsl --install --no-distribution`, DISM fallback), Restart Windows now / Cancel restart, Re-check, Run `wsl --update` and a help dialog. States: ready, not installed, restart needed, installed-but-not-answering, Windows too old, not Windows.
- The rest of the window is hidden until WSL works; the Install button is locked until then. State checks run in a background thread (no frozen window) and re-run when the window regains focus.
- Virtualization (BIOS) warning for WSL2 / chroot mode.
- `--demo-nowsl` starts the demo as if WSL were missing.

## 0.2.0-wip (2026-10-05)
- Chroot layout: a root filesystem unpacked into its own folder inside a host WSL distro (tiny `PocketLinux-host`, or an existing distro left untouched), entered through `unshare` namespaces; empty network namespace for "internet off". Layout selector, host picker and chroot name in the GUI; Remove deletes only the chroot folder.
- The unshare/chroot scripts were run for real on Linux against a tiny root (PID 1 = shell, hostname, share visible, offline = only `lo`, no leaked mounts). Still not run on Windows.

## 0.1.0-wip (2026-10-05)
- First proof of concept: one-step WSL import of Alpine/Debian/custom rootfs, isolation config, single shared folder, internet switch, USB picker (usbipd-win), themed separate console.
- Tested only with unit tests and a simulated demo mode; not run on real Windows.
