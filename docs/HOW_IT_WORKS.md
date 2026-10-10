# How PocketLinux works (plain English)

**WORK IN PROGRESS (0.3.0-wip).** Written from the documented behaviour of `wsl.exe` and `usbipd`, not yet run on a real Windows PC.

## What it does

| Step | Command it runs | What changes |
|---|---|---|
| Check WSL | `wsl --status` | nothing |
| Install WSL (Step 0 button) | `wsl --install --no-distribution` via an admin (UAC) prompt; if this Windows does not support it, `dism /enable-feature` for *Windows Subsystem for Linux* and *Virtual Machine Platform* | installs/switches on WSL (no Linux distro); restart needed |
| Restart (button) | `shutdown /r /t 30` (cancel with `shutdown /a`) | Windows restarts after you confirm; nothing else |
| WSL state | exit code of `wsl --status`; boot time to notice a restart happened | decides which Step 0 box (if any) to show |
| Virtualization | `Win32_ComputerSystem` / `Win32_Processor` via PowerShell | read-only; warns if the BIOS has it off |
| Download | Alpine's `latest-releases.yaml`, then the minirootfs (SHA256 checked) | a `.tar.gz` in `data\downloads` |
| Import | `wsl --import PocketLinux data\rootfs <tar> --version 1\|2` | registers a distro called `PocketLinux`, storage in `data\rootfs` |
| Provision | a shell script sent over stdin as root | writes `/etc/wsl.conf`, installs `bash sudo nano curl usbutils iptables`, creates user `dev` with passwordless `sudo` |
| Open console | `cmd.exe /c "title ... & color .. & wsl.exe -d PocketLinux -u dev -- bash -l"` in a new console window | a themed shell |
| Share | `mount -t drvfs '<folder>' /mnt/share` (as root, on each console open) | one Windows folder visible as `~/share` |
| Internet OFF (WSL2) | `iptables -P OUTPUT DROP` (+ loopback allowed) | outgoing traffic from the distro is dropped until switched back on |
| Internet OFF (WSL1) | blanks `/etc/resolv.conf` | name lookups fail; raw-IP connections still work |
| USB | `usbipd bind` (admin, once per device), `usbipd attach --wsl PocketLinux --busid X`, `usbipd detach` | the device moves from Windows to the Linux VM and back |

## Chroot layout (does not register a new distro)

1. The host is either the small `PocketLinux-host` (created once, `wsl.conf` isolation, `util-linux xz tar iptables usbutils` installed) or a distro you already have. **An existing host is only checked for `unshare chroot tar mount`; its config and packages are never changed.**
2. The root filesystem is streamed in: `wsl -d <host> -u root -- tar -xzf - -C /opt/pocketlinux/<name>` with the downloaded file on stdin (Windows paths are never visible to Linux).
3. Two small scripts are written next to it: `enter-<name>.sh` runs `unshare --mount --uts --ipc --pid --fork --mount-proc=<dir>/proc` (plus `--net` when internet is off), and `inner-<name>.sh` binds `/dev`, mounts `sysfs`, binds the one shared folder (mounted at `/mnt/pocketlinux-share` in the host first) and runs `chroot <dir> su -l dev`.
4. All those mounts exist only inside the private namespace; closing the console removes them. A chroot is **not** a security boundary against root inside it: it shares the host kernel and files outside the folder are one `mount` away for a determined root user. The empty network namespace and the lack of Windows drives are the useful parts.
5. Remove checks `/proc/self/mountinfo` first and refuses if something is still mounted under the folder, because `rm -rf` through a bind mount of your Windows share would delete real files.

## Isolation, honestly

`/etc/wsl.conf` inside the distro sets `automount` off, `interop` off and `appendWindowsPath` off. Result: `C:\`, the Windows `PATH` and Windows programs are not reachable from the Linux shell, and only the chosen folder is mounted. Limits:

- WSL2 distros share one VM and kernel with every other WSL2 distro on the PC (chroot layout: same).
- The internet switch blocks outgoing traffic from the distro; it does not hide the Windows host from the network, and the WSL1 version is DNS-only.
- Windows can always read and write the Linux files at `\\wsl.localhost\PocketLinux`. That is how "Open Linux files" works.
- `dev` has passwordless `sudo` so `apk`/`apt` just work. Anything inside the box can therefore become root *inside the box*.

Treat it as a tidy, separate workspace, not as a place to run untrusted malware.

## What it never does

It never touches other WSL distros, never changes the WSL default version (the version is passed to `--import`), never mounts drives you did not choose, and never deletes anything unless you press **Remove** and confirm. Config lives in `data\config.json`.

## Files

`src/backend.py` holds all logic (no GUI, testable anywhere). `src/main.py` is the tkinter window. `--demo` swaps every external command for a fake so the UI can be explored on any OS.
