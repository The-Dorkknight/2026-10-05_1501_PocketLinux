# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# WORK IN PROGRESS (0.3.0-wip): written without access to a Windows machine.
# Parsing/script-building logic, a simulated ("demo") mode and the chroot/unshare
# scripts (on a Linux box, tiny root) were exercised. Real WSL / usbipd behaviour
# is NOT verified.
"""PocketLinux backend: WSL import, isolation config, share mount, network, USB.

No GUI code here, so it can be unit-tested on any OS. Every external command
goes through ``run()``, the single chokepoint that demo mode replaces.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

__version__ = "0.3.0-wip"
__build_date__ = "2026-10-05 15:30"
APP = "PocketLinux"
DISTRO = "PocketLinux"
DEFAULT_HOST = "PocketLinux-host"
CHROOT_BASE = "/opt/pocketlinux"   # inside the host distro; chroots are plain folders here
SHARE_MNT = "/mnt/pocketlinux-share"
LINUX_USER = "dev"
NAME_RE = r"^[A-Za-z0-9_-]{1,32}$"

ALPINE_YAML = ("https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/"
               "x86_64/latest-releases.yaml")
ALPINE_BASE = "https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/"
# Not verified from the build sandbox (blocked there). Use "Custom rootfs" if it 404s.
DEBIAN_URL = ("https://github.com/debuerreotype/docker-debian-artifacts/raw/"
              "dist-amd64/trixie/slim/rootfs.tar.xz")

DISTROS = {
    "Alpine Linux (~3 MB, apk)": "alpine",
    "Debian slim (~30 MB, apt)": "debian",
    "Custom rootfs file...": "custom",
}

# name -> (cmd /c "color" code, terminal fg, terminal bg, ANSI colour for prompt tag)
THEMES = {
    "Matrix green": ("0A", "#7CFC98", "#001a0d", "1;32"),
    "Amber CRT": ("06", "#FFB000", "#1a1100", "1;33"),
    "Ice blue": ("0B", "#9FE8FF", "#00121a", "1;36"),
    "Hot magenta": ("0D", "#FF7CE8", "#1a0017", "1;35"),
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
CONFIG_PATH = os.path.join(DATA, "config.json")

DEFAULT_CONFIG = {
    "distro": DISTRO,
    "flavor": "alpine",
    "custom_rootfs": "",
    "wsl_version": 2,
    "layout": "distro",          # "distro" = own WSL distro, "chroot" = folder inside a host
    "host": DEFAULT_HOST,        # chroot layout: which WSL distro hosts the chroot folder
    "chroot_name": "box1",
    "share_dir": "",
    "internet": True,
    "theme": "Matrix green",
    "accepted_disclaimer": False,
}

DEMO = False
_demo_state = {"registered": False, "attached": set(), "shared": {"2-3"}, "chroot": False, "extra": set(), "wsl": "ready", "virt": True}


# --------------------------------------------------------------------------- run
def run(cmd, input_text=None, timeout=600):
    """Run a command; returns (returncode, stdout+stderr as text)."""
    if DEMO:
        return _demo_run(cmd, input_text)
    env = dict(os.environ, WSL_UTF8="1")
    try:
        p = subprocess.run(cmd, input=(input_text.encode() if input_text else None),
                           capture_output=True, timeout=timeout, env=env)
    except FileNotFoundError:
        return 127, "%s not found" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out: %s" % " ".join(cmd[:3])
    out = (p.stdout or b"") + (p.stderr or b"")
    return p.returncode, decode(out)


def run_stream(cmd, stdin_path=None, stdout_path=None, timeout=3600):
    """Like run() but pipes a local file into stdin and/or captures stdout to a
    file (used to move root filesystems in and out of a distro as tar streams)."""
    if DEMO:
        return _demo_run(cmd, None)[0], ""
    env = dict(os.environ, WSL_UTF8="1")
    fin = open(stdin_path, "rb") if stdin_path else None
    fout = open(stdout_path, "wb") if stdout_path else subprocess.PIPE
    try:
        p = subprocess.run(cmd, stdin=fin, stdout=fout, stderr=subprocess.PIPE,
                           timeout=timeout, env=env)
        return p.returncode, decode(p.stderr or b"")
    except FileNotFoundError:
        return 127, "%s not found" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "timed out"
    finally:
        for f in (fin, fout):
            if f not in (None, subprocess.PIPE):
                f.close()


def decode(raw):
    """wsl.exe may emit UTF-16LE (older builds) even with WSL_UTF8=1."""
    if b"\x00" in raw:
        try:
            return raw.decode("utf-16-le").replace("\r", "")
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace").replace("\r", "")


def _demo_run(cmd, input_text):
    name = os.path.basename(cmd[0]).lower()
    if name.startswith("wsl"):
        if "-l" in cmd or "--list" in cmd:
            names = ([DISTRO] if _demo_state["registered"] else []) + sorted(_demo_state["extra"])
            return 0, "".join(n + "\n" for n in names)
        if "--import" in cmd:
            n = cmd[cmd.index("--import") + 1]
            if n == DEFAULT_HOST:
                _demo_state["extra"].add(n)
            else:
                _demo_state["registered"] = True
            return 0, "Import in progress, this may take a few minutes.\n"
        if "--status" in cmd:
            return (0, "Default Version: 2\n") if _demo_state["wsl"] == "ready" else (1, "not installed\n")
        if "--terminate" in cmd or "--unregister" in cmd or "--export" in cmd:
            if "--unregister" in cmd:
                _demo_state["registered"] = False
            return 0, ""
        txt = input_text or ""
        if "test -x" in txt:
            return (0, "") if _demo_state["chroot"] else (1, "")
        if "pl-provision" in txt:
            _demo_state["chroot"] = True
        if "rm -rf" in txt and CHROOT_BASE in txt:
            _demo_state["chroot"] = False
        return 0, "[demo] ran as root: %d lines of script\n" % len(txt.splitlines())
    if name.startswith("usbipd"):
        if cmd[1] == "list":
            a = _demo_state["attached"]
            s = _demo_state["shared"]

            def st(b):
                return "Attached" if b in a else ("Shared" if b in s else "Not shared")
            return 0, ("Connected:\n"
                       "BUSID  VID:PID    DEVICE                                  STATE\n"
                       "1-2    046d:c52b  USB Input Device                        Not shared\n"
                       "2-3    0bda:5830  Integrated Webcam                       %s\n"
                       "2-4    1a86:7523  USB-SERIAL CH340 (COM4)                 %s\n"
                       "\nPersisted:\nGUID  DEVICE\n" % (st("2-3"), st("2-4")))
        if cmd[1] == "attach":
            _demo_state["attached"].add(cmd[-1])
        if cmd[1] == "detach":
            _demo_state["attached"].discard(cmd[-1])
        if cmd[1] == "bind":
            _demo_state["shared"].add(cmd[-1])
        return 0, ""
    return 0, ""


# ------------------------------------------------------------------------ config
def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    os.makedirs(DATA, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# --------------------------------------------------------------------------- WSL
def wsl_exe():
    return shutil.which("wsl.exe") or shutil.which("wsl") or "wsl.exe"


WIN_MIN_BUILD = 19041          # Windows 10 2004 / Windows 11: `wsl --install` and WSL2
OK_CODES = (0, 3010)           # 3010 = success, restart required
CANCELLED = 1223               # user declined the UAC prompt
HELP_URL = "https://learn.microsoft.com/windows/wsl/install"


def windows_build():
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return None


def wsl_state(cfg=None):
    """One of: ready, no_wsl, needs_restart, broken, legacy, unsupported.

    ready          wsl.exe answers `--status`
    no_wsl         WSL is not installed (offer to install it)
    needs_restart  we started an install and Windows has not been restarted yet
    broken         we installed, Windows was restarted, and WSL still does not answer
    legacy         Windows is older than build 19041 (update Windows first)
    unsupported    not Windows
    Detection is by exit code, because wsl.exe's messages are translated."""
    cfg = cfg or {}
    if DEMO:
        return _demo_state["wsl"]
    if not sys.platform.startswith("win"):
        return "unsupported"
    build = windows_build()
    if build and build < WIN_MIN_BUILD:
        return "legacy"
    if shutil.which("wsl.exe") or shutil.which("wsl"):
        rc, _ = run([wsl_exe(), "--status"], timeout=30)
        if rc == 0:
            return "ready"
    if cfg.get("wsl_install_started"):
        before = cfg.get("wsl_install_boot") or ""
        now = boot_time()
        return "broken" if (before and now and now != before) else "needs_restart"
    return "no_wsl"


def wsl_available():
    """True when WSL answers (feature installed and Windows restarted if needed)."""
    return wsl_state() == "ready"


def boot_time():
    """Windows last-boot timestamp as text ('' if unknown); lets us tell a restart happened."""
    if DEMO or not sys.platform.startswith("win"):
        return "demo-boot-1" if DEMO else ""
    rc, out = run(["powershell.exe", "-NoProfile", "-Command",
                   "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString('o')"], timeout=30)
    return out.strip() if rc == 0 else ""


def _parse_virt(text):
    """Parse 'HypervisorPresent|VirtualizationFirmwareEnabled' -> True/False/None."""
    parts = [p.strip().lower() for p in (text or "").strip().split("|")]
    if len(parts) != 2:
        return None
    if parts[0] == "true" or parts[1] == "true":
        return True
    return False if parts[1] == "false" else None


def virtualization_enabled():
    """True/False if CPU virtualization is on (needed for WSL2), None if unknown."""
    if DEMO:
        return _demo_state["virt"]
    if not sys.platform.startswith("win"):
        return None
    rc, out = run(["powershell.exe", "-NoProfile", "-Command",
                   "$cs=(Get-CimInstance Win32_ComputerSystem).HypervisorPresent; "
                   "$p=(Get-CimInstance Win32_Processor | Select-Object -First 1)"
                   ".VirtualizationFirmwareEnabled; \"$cs|$p\""], timeout=30)
    return _parse_virt(out) if rc == 0 else None


def _elevated(exe, args):
    """Run `exe args` with a Windows admin (UAC) prompt. Returns (exit code, text).
    Exit code 1223 means the user declined the prompt."""
    quoted = ",".join("'%s'" % a.replace("'", "''") for a in args)
    ps = ("try { $p = Start-Process -FilePath '%s' -ArgumentList %s -Verb RunAs -Wait -PassThru; "
          "exit $p.ExitCode } catch { Write-Output $_.Exception.Message; exit %d }"
          % (exe, quoted, CANCELLED))
    return run(["powershell.exe", "-NoProfile", "-Command", ps], timeout=3600)


DISM_CMD = ("dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart; "
            "dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart; "
            "exit $LASTEXITCODE")


def install_wsl(cfg=None, log=print):
    """Install WSL itself (no Linux distro). Asks Windows for admin rights.
    Tries `wsl --install --no-distribution`; if that is not supported on this
    Windows, falls back to switching on the two Windows features with DISM.
    Returns True if it worked (a restart is normally needed afterwards)."""
    cfg = cfg if cfg is not None else {}
    if DEMO:
        _demo_state["wsl"] = "needs_restart"
        cfg.update(wsl_install_started=True, wsl_install_boot=boot_time())
        log("[demo] WSL install requested; restart needed")
        return True
    log("Windows will ask for permission. Approve it; a console window shows the progress...")
    rc, out = _elevated("wsl.exe", ["--install", "--no-distribution"])
    if rc == CANCELLED:
        log("The permission prompt was declined, nothing was changed.")
        return False
    if rc not in OK_CODES:
        log("'wsl --install' did not work here (code %s). Trying the classic Windows-features method..." % rc)
        return enable_features(cfg, log)
    cfg.update(wsl_install_started=True, wsl_install_boot=boot_time())
    log("WSL is installed. Windows must restart to finish.")
    return True


def enable_features(cfg=None, log=print):
    """Classic method: switch on 'Windows Subsystem for Linux' and 'Virtual Machine
    Platform' with DISM (admin prompt). A restart is needed, then `wsl --update`."""
    cfg = cfg if cfg is not None else {}
    if DEMO:
        _demo_state["wsl"] = "needs_restart"
        cfg.update(wsl_install_started=True, wsl_install_boot=boot_time())
        return True
    rc, out = _elevated("powershell.exe", ["-NoProfile", "-Command", '"%s"' % DISM_CMD])
    if rc == CANCELLED:
        log("The permission prompt was declined, nothing was changed.")
        return False
    if rc not in OK_CODES:
        log("Could not switch on the Windows features (code %s). %s" % (rc, out.strip()[:300]))
        return False
    cfg.update(wsl_install_started=True, wsl_install_boot=boot_time())
    log("Windows features switched on. Restart Windows, then press Re-check (and 'Run wsl --update' if asked).")
    return True


def restart_windows(delay=30):
    """Schedule a Windows restart in `delay` seconds (cancel_restart() aborts it)."""
    if DEMO:
        _demo_state["wsl"] = "ready"
        return 0, ""
    return run(["shutdown", "/r", "/t", str(int(delay)), "/c",
                "PocketLinux: finishing the WSL install"], timeout=30)


def cancel_restart():
    return (0, "") if DEMO else run(["shutdown", "/a"], timeout=30)


def update_wsl():
    """`wsl --update` (fetches Microsoft's current WSL kernel)."""
    return run([wsl_exe(), "--update"], timeout=1800)


def list_distros():
    rc, out = run([wsl_exe(), "-l", "-q"], timeout=30)
    if rc != 0:
        return []
    return [l.strip().lstrip("\ufeff") for l in out.splitlines() if l.strip()]


def is_installed(name=DISTRO):
    return name in list_distros()


def run_root(script, name=DISTRO, timeout=900):
    """Run a shell script as root inside the distro. The script goes over
    stdin so Windows/Linux quoting rules can never mangle it."""
    return run([wsl_exe(), "-d", name, "-u", "root", "--", "sh", "-s"],
               input_text=script.replace("\r\n", "\n"), timeout=timeout)


def terminate(name=DISTRO):
    return run([wsl_exe(), "--terminate", name], timeout=60)


def unregister(name=DISTRO):
    return run([wsl_exe(), "--unregister", name], timeout=300)


def export_distro(dest, name=DISTRO):
    return run([wsl_exe(), "--export", name, dest], timeout=3600)


# ------------------------------------------------------------------- rootfs fetch
def parse_alpine_yaml(text):
    """Return (filename, sha256) of the alpine-minirootfs entry, or (None, None)."""
    blocks, cur = [], {}
    for line in text.splitlines():
        if re.match(r"^-\s*$", line):
            if cur:
                blocks.append(cur)
            cur = {}
            continue
        m = re.match(r"^\s+([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            cur[m.group(1)] = m.group(2).strip().strip('"')
    if cur:
        blocks.append(cur)
    for b in blocks:
        if b.get("flavor") == "alpine-minirootfs" and b.get("file"):
            return b["file"], b.get("sha256")
    return None, None


def download(url, dest, progress=None, sha256=None):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": APP + "/" + __version__})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(65536)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if sha256 and h.hexdigest().lower() != sha256.lower():
        os.remove(dest)
        raise RuntimeError("SHA256 mismatch for %s: download discarded" % url)
    return dest


def fetch_rootfs(flavor, custom_path="", log=print, progress=None):
    dl = os.path.join(DATA, "downloads")
    if DEMO:  # demo mode never touches the network
        os.makedirs(dl, exist_ok=True)
        fake = os.path.join(dl, "demo-rootfs.tar")
        open(fake, "wb").close()
        log("[demo] pretending to download the %s rootfs" % flavor)
        return fake
    if flavor == "custom":
        if not os.path.isfile(custom_path):
            raise RuntimeError("Pick a rootfs .tar / .tar.gz / .tar.xz file first.")
        return custom_path
    if flavor == "alpine":
        log("Looking up the latest Alpine minirootfs...")
        with urllib.request.urlopen(ALPINE_YAML, timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        fname, sha = parse_alpine_yaml(text)
        if not fname:
            raise RuntimeError("Could not find the minirootfs in Alpine's release list.")
        log("Downloading %s (SHA256 checked)..." % fname)
        return download(ALPINE_BASE + fname, os.path.join(dl, fname), progress, sha)
    if flavor == "debian":
        log("Downloading Debian slim rootfs (no checksum available, not verified)...")
        return download(DEBIAN_URL, os.path.join(dl, "debian-trixie-slim.tar.xz"), progress)
    raise RuntimeError("Unknown flavor: %s" % flavor)


# --------------------------------------------------------------- script builders
def wsl_conf(wsl_version, user=LINUX_USER):
    # WSL2 gets a generated resolv.conf (host NAT DNS). WSL1 has no firewall, so
    # we manage resolv.conf ourselves for the (advisory) internet switch.
    gen = "true" if wsl_version == 2 else "false"
    return ("[automount]\nenabled=false\nmountFsTab=false\n\n"
            "[interop]\nenabled=false\nappendWindowsPath=false\n\n"
            "[network]\ngenerateResolvConf=%s\nhostname=pocketlinux\n\n"
            "[user]\ndefault=%s\n" % (gen, user))


def pkg_script(firewall=True):
    """Install tools and create the dev user (works for apk and apt rootfs)."""
    fw_apk = " iptables ip6tables" if firewall else ""
    fw_apt = " iptables" if firewall else ""
    return """if command -v apk >/dev/null 2>&1; then
  apk add --no-cache bash sudo nano curl ca-certificates usbutils shadow%(fa)s
  id %(u)s >/dev/null 2>&1 || adduser -D -s /bin/bash %(u)s
elif command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends bash sudo nano curl ca-certificates usbutils%(fb)s
  id %(u)s >/dev/null 2>&1 || useradd -m -s /bin/bash %(u)s
else
  echo "Unsupported rootfs: neither apk nor apt-get found" >&2; exit 3
fi
mkdir -p /etc/sudoers.d
echo '%(u)s ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/%(u)s
chmod 440 /etc/sudoers.d/%(u)s
mkdir -p /mnt/share
""" % {"fa": fw_apk, "fb": fw_apt, "u": LINUX_USER}


def provision_script(wsl_version):
    return "set -e\ncat > /etc/wsl.conf <<'PL_EOF'\n%s\nPL_EOF\n%s" % (
        wsl_conf(wsl_version).strip(), pkg_script(True))


def _bad_path(p):
    return (not p) or ("'" in p) or ("\n" in p) or ("\r" in p)


def mount_script(share_dir):
    """Mount ONE Windows folder at /mnt/share (automount is off, so nothing else)."""
    if not share_dir:
        return ("mountpoint -q /mnt/share 2>/dev/null && umount /mnt/share\n"
                "rm -f /home/%s/share\n" % LINUX_USER)
    if _bad_path(share_dir):
        raise ValueError("Shared folder path contains a character that is not allowed.")
    return ("mkdir -p /mnt/share\n"
            "mountpoint -q /mnt/share && umount /mnt/share\n"
            "mount -t drvfs '%s' /mnt/share -o metadata,uid=1000,gid=1000\n"
            "ln -sfn /mnt/share /home/%s/share\n" % (share_dir, LINUX_USER))


def network_script(internet, wsl_version):
    if wsl_version == 2:
        if internet:
            return ("for t in iptables ip6tables; do command -v $t >/dev/null 2>&1 && "
                    "{ $t -P OUTPUT ACCEPT; $t -F OUTPUT; }; done; true\n")
        return ("for t in iptables ip6tables; do command -v $t >/dev/null 2>&1 && "
                "{ $t -F OUTPUT; $t -A OUTPUT -o lo -j ACCEPT; $t -P OUTPUT DROP; }; "
                "done; true\n")
    # WSL1: DNS-level only
    if internet:
        return "printf 'nameserver 1.1.1.1\\nnameserver 9.9.9.9\\n' > /etc/resolv.conf\n"
    return "printf '# offline (PocketLinux)\\n' > /etc/resolv.conf\n"


def theme_script(theme, internet, share_dir, path="/etc/profile.d/pocketlinux.sh"):
    _, fg, bg, ansi = THEMES.get(theme, THEMES["Matrix green"])
    return """mkdir -p "$(dirname %(path)s)"
cat > %(path)s <<'PL_EOF'
printf '\\033]11;%(bg)s\\007\\033]10;%(fg)s\\007'
PS1='\\[\\033[%(ansi)sm\\][POCKETLINUX]\\[\\033[0m\\] \\u@\\h:\\w\\$ '
printf '\\033[%(ansi)sm== POCKET LINUX SANDBOX ==\\033[0m  Windows drives: not mounted | share: %(share)s | internet: %(net)s\\n'
PL_EOF
""" % {"bg": bg, "fg": fg, "ansi": ansi, "share": "~/share" if share_dir else "none",
       "net": "on" if internet else "OFF", "path": path}


# ----------------------------------------------------------------- chroot layout
def _check_name(name):
    import re as _re
    if not _re.match(NAME_RE, name or ""):
        raise ValueError("Chroot name: use 1-32 letters, digits, _ or -.")
    return name


def chroot_paths(cfg):
    """(chroot dir, enter script, inner script), all inside the host distro."""
    n = _check_name(cfg["chroot_name"])
    return ("%s/%s" % (CHROOT_BASE, n), "%s/enter-%s.sh" % (CHROOT_BASE, n),
            "%s/inner-%s.sh" % (CHROOT_BASE, n))


def target(cfg):
    """The WSL distro that commands (and USB attach) go to."""
    return cfg["host"] if cfg.get("layout") == "chroot" else cfg["distro"]


def chroot_files_script(cfg, internet, share_dir, boot_cmd=None):
    """Host-side script that (re)writes the enter/inner scripts for one chroot.

    enter-<name>.sh runs `unshare` (own mount, hostname, IPC and PID namespaces,
    plus a NEW EMPTY NETWORK namespace when internet is off) and then the inner
    script binds /dev and the one shared folder and chroots in. Every bind mount
    lives only in that private namespace and vanishes when the console closes."""
    d, enter, inner = chroot_paths(cfg)
    netflag = "" if internet else " --net"
    net_line = ('cp -f /etc/resolv.conf "$D/etc/resolv.conf" 2>/dev/null' if internet
                else "ip link set lo up 2>/dev/null")
    share = ""
    if share_dir:
        share = ('mkdir -p "$D/mnt/share"\n'
                 'mount --bind %s "$D/mnt/share"\n'
                 'mkdir -p "$D/home/%s" && ln -sfn /mnt/share "$D/home/%s/share"\n'
                 % (SHARE_MNT, LINUX_USER, LINUX_USER))
    run = boot_cmd or ('exec chroot "$D" /bin/su -s /bin/bash -l %s' % LINUX_USER)
    return ("mkdir -p %(base)s\n"
            "cat > %(inner)s <<'PL_EOF'\n#!/bin/sh\nD=%(d)s\n"
            'mount --rbind /dev "$D/dev"\n'
            'mount -t sysfs sysfs "$D/sys" 2>/dev/null\n'
            "%(net)s\n%(share)shostname pocketlinux\n%(run)s\nPL_EOF\n"
            "cat > %(enter)s <<'PL_EOF'\n#!/bin/sh\n"
            "exec unshare --mount --uts --ipc --pid --fork --mount-proc=%(d)s/proc%(nf)s sh %(inner)s\n"
            "PL_EOF\nchmod 755 %(enter)s %(inner)s\n"
            % {"base": CHROOT_BASE, "inner": inner, "enter": enter, "d": d, "net": net_line,
               "share": share, "run": run, "nf": netflag})


def share_mount_script(share_dir):
    if not share_dir:
        return "mountpoint -q %s 2>/dev/null && umount %s\ntrue\n" % (SHARE_MNT, SHARE_MNT)
    if _bad_path(share_dir):
        raise ValueError("Shared folder path contains a character that is not allowed.")
    return ("mkdir -p %(m)s\nmountpoint -q %(m)s && umount %(m)s\n"
            "mount -t drvfs '%(p)s' %(m)s -o metadata,uid=1000,gid=1000\n"
            % {"m": SHARE_MNT, "p": share_dir})


def host_conf_script():
    """Only for a host WE create: isolation config + tools needed for chroots."""
    return ("set -e\ncat > /etc/wsl.conf <<'PL_EOF'\n%s\nPL_EOF\n"
            "if command -v apk >/dev/null 2>&1; then\n"
            "  apk add --no-cache util-linux xz tar bash iptables ip6tables usbutils\n"
            "fi\nmkdir -p %s\n" % (wsl_conf(2, user="root").strip(), CHROOT_BASE))


def ensure_host(cfg, log=print, progress=None):
    """Make sure the host distro exists. A host the user already has is NEVER
    modified (no wsl.conf edit, no package install); we only check its tools."""
    host = cfg["host"]
    if host in list_distros():
        rc, out = run_root("for t in unshare chroot tar mount; do command -v $t >/dev/null 2>&1 "
                           "|| { echo \"missing: $t\"; exit 5; }; done\n", host, timeout=60)
        if rc != 0:
            log("Host '%s' lacks needed tools (%s). Install util-linux there, or pick the "
                "default host." % (host, out.strip()))
            return False
        return True
    if host != DEFAULT_HOST:
        log("WSL distro '%s' not found." % host)
        return False
    log("Creating the small shared host '%s' (Alpine, WSL2)..." % host)
    tar = fetch_rootfs("alpine", "", log, progress)
    target_dir = os.path.join(DATA, "host")
    os.makedirs(target_dir, exist_ok=True)
    rc, out = run([wsl_exe(), "--import", host, target_dir, tar, "--version", "2"], timeout=1800)
    if rc != 0:
        log("Host import failed (%d): %s" % (rc, out.strip()[:400]))
        return False
    rc, out = run_root(host_conf_script(), host, timeout=1800)
    log(out.strip()[-300:])
    if rc != 0:
        log("Host setup failed (%d)." % rc)
        return False
    terminate(host)
    return True


def tar_flag(path):
    p = path.lower()
    if p.endswith((".tar.gz", ".tgz")):
        return "-xzf"
    if p.endswith((".tar.xz", ".txz")):
        return "-xJf"
    return "-xf"


def chroot_exists(cfg):
    d = chroot_paths(cfg)[0]
    rc, _ = run_root("test -x %s/bin/sh\n" % d, cfg["host"], timeout=60)
    return rc == 0


def install_chroot(cfg, log=print, progress=None):
    cfg["wsl_version"] = 2  # namespaces (and a real firewall/USB) need WSL2
    if not wsl_available():
        log("WSL is not ready yet. Follow the yellow Step 0 box at the top of the window.")
        return False
    host = cfg["host"]
    d, enter, inner = chroot_paths(cfg)
    if not ensure_host(cfg, log, progress):
        return False
    if chroot_exists(cfg):
        log("Chroot '%s' already exists in %s." % (cfg["chroot_name"], host))
        return True
    tar = fetch_rootfs(cfg["flavor"], cfg.get("custom_rootfs", ""), log, progress)
    log("Unpacking into %s inside %s (a plain folder; nothing else is registered)..." % (d, host))
    rc, out = run_root("mkdir -p %s\n" % d, host, timeout=60)
    if rc != 0:
        log("Could not create folder: %s" % out.strip())
        return False
    rc, err = run_stream([wsl_exe(), "-d", host, "-u", "root", "--", "tar", tar_flag(tar),
                          "-", "-C", d], stdin_path=tar)
    if rc != 0:
        log("Unpack failed (%d): %s" % (rc, err.strip()[:400]))
        return False
    log("Installing tools and the 'dev' user inside the chroot (needs internet)...")
    prov = ("cat > %s/tmp/pl-provision.sh <<'PL_EOF'\nset -e\n%sPL_EOF\n" % (d, pkg_script(False)))
    script = (prov + chroot_files_script(cfg, True, "", 'exec chroot "$D" /bin/sh /tmp/pl-provision.sh')
              + "mkdir -p %s/tmp\n%s </dev/null\n" % (d, enter))
    rc, out = run_root(script, host, timeout=1800)
    log(out.strip()[-500:])
    if rc != 0:
        log("Provisioning failed (%d). The folder exists; fix and re-run." % rc)
        return False
    save_config(cfg)
    log("Done. Pick a shared folder, then press 'Open Linux console'.")
    return True


def remove_chroot(cfg):
    """Delete ONE chroot folder. Refuses if anything is still mounted under it
    (a bind to your Windows share would otherwise be followed by rm -rf)."""
    d, enter, inner = chroot_paths(cfg)
    if not d.startswith(CHROOT_BASE + "/") or len(d) <= len(CHROOT_BASE) + 1:
        raise ValueError("refusing to delete %r" % d)
    script = ('if grep -q " %s/" /proc/self/mountinfo; then echo "still mounted: close the console first"; exit 4; fi\n'
              "rm -rf %s %s %s\n" % (d, d, enter, inner))
    return run_root(script, cfg["host"], timeout=600)


def backup_chroot(cfg, dest):
    d = chroot_paths(cfg)[0]
    return run_stream([wsl_exe(), "-d", cfg["host"], "-u", "root", "--", "tar", "-cf", "-",
                       "-C", d, "."], stdout_path=dest)


# ----------------------------------------------------- layout-aware entry points
def is_ready(cfg):
    """Is the chosen layout fully installed?"""
    if cfg.get("layout") == "chroot":
        return cfg["host"] in list_distros() and chroot_exists(cfg)
    return is_installed(cfg["distro"])


def prepare_session(cfg, log=print):
    """Apply share mount + network + theme. Called before opening the console."""
    if cfg.get("layout") == "chroot":
        d = chroot_paths(cfg)[0]
        script = (share_mount_script(cfg["share_dir"])
                  + theme_script(cfg["theme"], cfg["internet"], cfg["share_dir"],
                                 path=d + "/etc/profile.d/pocketlinux.sh")
                  + chroot_files_script(cfg, cfg["internet"], cfg["share_dir"]))
        rc, out = run_root(script, cfg["host"], timeout=120)
    else:
        name, ver = cfg["distro"], int(cfg["wsl_version"])
        script = (mount_script(cfg["share_dir"]) + network_script(cfg["internet"], ver)
                  + theme_script(cfg["theme"], cfg["internet"], cfg["share_dir"]))
        rc, out = run_root(script, name, timeout=120)
    if rc != 0:
        log("Warning: session setup returned %d: %s" % (rc, out.strip()[:300]))
    return rc == 0


def apply_network(cfg):
    """Apply the internet switch live. In chroot layout it is applied when the
    console is next opened (each console gets its own network namespace)."""
    if cfg.get("layout") == "chroot":
        return 0, "Internet %s: takes effect the next time you open the console." % (
            "ON" if cfg["internet"] else "OFF")
    rc, out = run_root(network_script(cfg["internet"], int(cfg["wsl_version"])),
                       cfg["distro"], timeout=60)
    return rc, out


def remove(cfg):
    if cfg.get("layout") == "chroot":
        return remove_chroot(cfg)
    return unregister(cfg["distro"])


def backup(cfg, dest):
    if cfg.get("layout") == "chroot":
        return backup_chroot(cfg, dest)
    return export_distro(dest, cfg["distro"])


def open_console(cfg):
    """Open a SEPARATE, themed console window (real TTY) running the sandbox shell."""
    color = THEMES.get(cfg["theme"], THEMES["Matrix green"])[0]
    if cfg.get("layout") == "chroot":
        enter = chroot_paths(cfg)[1]
        cmd = '"%s" -d %s -u root --cd / -- %s' % (wsl_exe(), cfg["host"], enter)
    else:
        cmd = '"%s" -d %s -u %s --cd ~ -- bash -l' % (wsl_exe(), cfg["distro"], LINUX_USER)
    line = "title POCKET LINUX SANDBOX & color %s & %s" % (color, cmd)
    if DEMO or not sys.platform.startswith("win"):
        return line
    subprocess.Popen('cmd.exe /c "%s"' % line,
                     creationflags=subprocess.CREATE_NEW_CONSOLE)
    return line


# -------------------------------------------------------------------------- install
def install(cfg, log=print, progress=None):
    """Full one-step setup. Returns True on success."""
    if cfg.get("layout") == "chroot":
        return install_chroot(cfg, log, progress)
    if not wsl_available():
        log("WSL is not ready yet. Follow the yellow Step 0 box at the top of the window.")
        return False
    name, ver = cfg["distro"], int(cfg["wsl_version"])
    if is_installed(name):
        log("%s is already installed." % name)
        return True
    tar = fetch_rootfs(cfg["flavor"], cfg.get("custom_rootfs", ""), log, progress)
    target_dir = os.path.join(DATA, "rootfs")
    os.makedirs(target_dir, exist_ok=True)
    log("Importing into %s (WSL%d)..." % (target_dir, ver))
    rc, out = run([wsl_exe(), "--import", name, target_dir, tar, "--version", str(ver)],
                  timeout=1800)
    if rc != 0:
        log("Import failed (%d): %s" % (rc, out.strip()[:400]))
        return False
    log("Configuring isolation, user and packages (needs internet, ~1 min)...")
    rc, out = run_root(provision_script(ver), name, timeout=1800)
    log(out.strip()[-600:])
    if rc != 0:
        log("Provisioning failed (%d). The distro is imported; fix and re-run." % rc)
        return False
    terminate(name)  # so /etc/wsl.conf is picked up on next start
    save_config(cfg)
    log("Done. Pick a shared folder, then press 'Open Linux console'.")
    return True


# ----------------------------------------------------------------------------- USB
USB_RE = re.compile(r"^(\d+-\d+(?:\.\d+)*)\s+([0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s+"
                    r"(.+?)\s{2,}(Not shared|Shared|Attached.*|Forced.*)\s*$")
BUSID_RE = re.compile(r"^\d+-\d+(\.\d+)*$")


def usbipd_exe():
    p = shutil.which("usbipd") or shutil.which("usbipd.exe")
    if p:
        return p
    guess = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "usbipd-win", "usbipd.exe")
    return guess if (os.path.isfile(guess) or DEMO) else None


def parse_usbipd_list(text):
    """Parse the 'Connected:' table of `usbipd list`."""
    devices, in_connected = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Connected"):
            in_connected = True
            continue
        if s.startswith("Persisted"):
            break
        if not in_connected:
            continue
        m = USB_RE.match(line.rstrip())
        if m:
            devices.append({"busid": m.group(1), "vidpid": m.group(2),
                            "name": m.group(3).strip(), "state": m.group(4)})
    return devices


def list_usb():
    exe = usbipd_exe()
    if not exe:
        return None
    rc, out = run([exe, "list"], timeout=30)
    return parse_usbipd_list(out) if rc == 0 else []


def _check_busid(busid):
    if not BUSID_RE.match(busid):
        raise ValueError("bad bus id: %r" % busid)


def usb_bind(busid):
    """One-time per device; needs admin, so ask Windows for a UAC prompt."""
    _check_busid(busid)
    exe = usbipd_exe()
    if DEMO:
        return run([exe, "bind", "--busid", busid])
    ps = ("Start-Process -FilePath '%s' -ArgumentList 'bind','--busid','%s' "
          "-Verb RunAs -Wait" % (exe, busid))
    return run(["powershell.exe", "-NoProfile", "-Command", ps], timeout=120)


def usb_attach(busid, name=DISTRO):
    _check_busid(busid)
    return run([usbipd_exe(), "attach", "--wsl", name, "--busid", busid], timeout=60)


def usb_detach(busid):
    _check_busid(busid)
    return run([usbipd_exe(), "detach", "--busid", busid], timeout=60)


def install_usbipd():
    return run(["winget", "install", "--exact", "--id", "dorssel.usbipd-win",
                "--accept-package-agreements", "--accept-source-agreements"],
               timeout=900)
