# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import backend as B  # noqa: E402

ALPINE_SAMPLE = """---
-
  title: "Mini root filesystem"
  desc: "Minimal root filesystem"
  flavor: alpine-minirootfs
  file: alpine-minirootfs-3.22.1-x86_64.tar.gz
  sha256: abc123
-
  title: "Standard"
  flavor: alpine-standard
  file: alpine-standard-3.22.1-x86_64.iso
  sha256: def456
"""

USBIPD_SAMPLE = """Connected:
BUSID  VID:PID    DEVICE                                                        STATE
1-2    046d:c52b  USB Input Device                                              Not shared
2-3    0bda:5830  Integrated Webcam                                             Shared
2-4    1a86:7523  USB-SERIAL CH340 (COM4)                                       Attached

Persisted:
GUID                                  DEVICE
"""


class Backend(unittest.TestCase):
    def test_alpine_yaml(self):
        self.assertEqual(B.parse_alpine_yaml(ALPINE_SAMPLE),
                         ("alpine-minirootfs-3.22.1-x86_64.tar.gz", "abc123"))
        self.assertEqual(B.parse_alpine_yaml("garbage"), (None, None))

    def test_usbipd_list(self):
        d = B.parse_usbipd_list(USBIPD_SAMPLE)
        self.assertEqual([x["busid"] for x in d], ["1-2", "2-3", "2-4"])
        self.assertEqual(d[1]["state"], "Shared")
        self.assertEqual(d[2]["name"], "USB-SERIAL CH340 (COM4)")

    def test_busid_validation(self):
        for bad in ("1-2; rm -rf", "abc", "", "1-2 3-4"):
            with self.assertRaises(ValueError):
                B._check_busid(bad)
        B._check_busid("2-1.3")

    def test_mount_script(self):
        s = B.mount_script(r"D:\Projects\Share")
        self.assertIn("mount -t drvfs 'D:\\Projects\\Share' /mnt/share", s)
        with self.assertRaises(ValueError):
            B.mount_script("D:\\it's")
        self.assertNotIn("drvfs", B.mount_script(""))

    def test_wsl_conf_isolation(self):
        c = B.wsl_conf(2)
        self.assertIn("[automount]\nenabled=false", c)
        self.assertIn("[interop]\nenabled=false\nappendWindowsPath=false", c)
        self.assertIn("generateResolvConf=true", c)
        self.assertIn("generateResolvConf=false", B.wsl_conf(1))

    def test_network_scripts(self):
        self.assertIn("-P OUTPUT DROP", B.network_script(False, 2))
        self.assertIn("-P OUTPUT ACCEPT", B.network_script(True, 2))
        self.assertIn("offline", B.network_script(False, 1))

    def test_provision_script_balanced(self):
        s = B.provision_script(2)
        self.assertEqual(s.count("PL_EOF"), 2)
        self.assertIn("adduser -D -s /bin/bash dev", s)
        self.assertIn("useradd -m -s /bin/bash dev", s)

    def test_theme_script(self):
        s = B.theme_script("Amber CRT", False, "")
        self.assertIn("internet: OFF", s)
        self.assertIn("[POCKETLINUX]", s)

    def test_decode_utf16(self):
        self.assertEqual(B.decode("Ubuntu\r\n".encode("utf-16-le")), "Ubuntu\n")
        self.assertEqual(B.decode(b"plain"), "plain")


class ChrootLayout(unittest.TestCase):
    CFG = dict(B.DEFAULT_CONFIG, layout="chroot", host="PocketLinux-host", chroot_name="box1")

    def test_offline_gets_empty_network_namespace(self):
        off = B.chroot_files_script(self.CFG, False, "")
        on = B.chroot_files_script(self.CFG, True, "")
        self.assertIn("--mount-proc=/opt/pocketlinux/box1/proc --net sh", off)
        self.assertNotIn(" --net sh", on)
        self.assertIn("--pid --fork", on)

    def test_share_bound_only_when_chosen(self):
        self.assertIn("mount --bind /mnt/pocketlinux-share", B.chroot_files_script(self.CFG, True, "D:\\X"))
        self.assertNotIn("pocketlinux-share", B.chroot_files_script(self.CFG, True, ""))

    def test_scripts_are_valid_sh(self):
        import subprocess
        for s in (B.chroot_files_script(self.CFG, False, "D:\\X"), B.share_mount_script("D:\\X"),
                  B.host_conf_script(), B.pkg_script(False), B.pkg_script(True)):
            r = subprocess.run(["sh", "-n"], input=s.encode(), capture_output=True)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_name_and_path_validation(self):
        for bad in ("", "../x", "a b", "x;rm", "a" * 40):
            with self.assertRaises(ValueError):
                B.chroot_paths(dict(self.CFG, chroot_name=bad))
        self.assertEqual(B.chroot_paths(self.CFG)[0], "/opt/pocketlinux/box1")

    def test_remove_refuses_if_mounted(self):
        # the generated script must check mountinfo BEFORE rm -rf
        B.DEMO = True
        try:
            captured = {}
            orig = B.run_root
            B.run_root = lambda script, name=None, timeout=0: captured.update(s=script) or (0, "")
            B.remove_chroot(self.CFG)
        finally:
            B.run_root = orig
            B.DEMO = False
        s = captured["s"]
        self.assertLess(s.index("mountinfo"), s.index("rm -rf"))
        self.assertIn("rm -rf /opt/pocketlinux/box1 ", s)

    def test_tar_flags(self):
        self.assertEqual(B.tar_flag("a.tar.gz"), "-xzf")
        self.assertEqual(B.tar_flag("a.tar.xz"), "-xJf")
        self.assertEqual(B.tar_flag("a.tar"), "-xf")

    def test_target_follows_layout(self):
        self.assertEqual(B.target(self.CFG), "PocketLinux-host")
        self.assertEqual(B.target(dict(B.DEFAULT_CONFIG)), "PocketLinux")

    def test_existing_host_conf_not_touched(self):
        # host_conf_script (writes /etc/wsl.conf) must only be used for our own host
        import inspect
        src = inspect.getsource(B.ensure_host)
        self.assertLess(src.index("host in list_distros()"), src.index("host_conf_script"))


_orig_list = B.list_distros


class WslInstall(unittest.TestCase):
    def setUp(self):
        self._saved = (B._elevated, B.boot_time, B.run, B.DEMO)
        self.calls = []

    def tearDown(self):
        B._elevated, B.boot_time, B.run, B.DEMO = self._saved

    def fake_elevated(self, results):
        it = iter(results)

        def f(exe, args):
            self.calls.append((exe, args))
            return next(it), "msg"
        B._elevated = f
        B.boot_time = lambda: "boot-A"

    def test_install_ok_records_boot_for_restart_detection(self):
        self.fake_elevated([0])
        cfg = {}
        self.assertTrue(B.install_wsl(cfg, lambda m: None))
        self.assertEqual(self.calls[0], ("wsl.exe", ["--install", "--no-distribution"]))
        self.assertTrue(cfg["wsl_install_started"])
        self.assertEqual(cfg["wsl_install_boot"], "boot-A")

    def test_restart_required_code_counts_as_success(self):
        self.fake_elevated([3010])
        self.assertTrue(B.install_wsl({}, lambda m: None))

    def test_declined_uac_changes_nothing(self):
        self.fake_elevated([1223])
        cfg, logs = {}, []
        self.assertFalse(B.install_wsl(cfg, logs.append))
        self.assertNotIn("wsl_install_started", cfg)
        self.assertEqual(len(self.calls), 1)  # no fallback after a decline
        self.assertTrue(any("declined" in l for l in logs))

    def test_falls_back_to_dism_when_wsl_install_unsupported(self):
        self.fake_elevated([1, 3010])
        cfg = {}
        self.assertTrue(B.install_wsl(cfg, lambda m: None))
        self.assertEqual(self.calls[1][0], "powershell.exe")
        self.assertIn("Microsoft-Windows-Subsystem-Linux", self.calls[1][1][2])
        self.assertIn("VirtualMachinePlatform", self.calls[1][1][2])
        self.assertTrue(cfg["wsl_install_started"])

    def test_both_methods_failing_reports_false(self):
        self.fake_elevated([1, 5])
        cfg = {}
        self.assertFalse(B.install_wsl(cfg, lambda m: None))
        self.assertNotIn("wsl_install_started", cfg)

    def test_elevated_quotes_arguments(self):
        B.run = lambda cmd, input_text=None, timeout=0: (0, "") if self.calls.append(cmd) is None else None
        self._saved_el = None
        B._elevated = self._saved[0]
        B._elevated("wsl.exe", ["--install", "it's"])
        ps = self.calls[0][-1]
        self.assertIn("'--install','it''s'", ps)
        self.assertIn("-Verb RunAs", ps)
        self.assertIn("exit 1223", ps)

    def test_state_machine(self):
        B.DEMO = False
        sys_platform = B.sys.platform
        B.sys.platform = "win32"
        orig_build, orig_which = B.windows_build, B.shutil.which
        try:
            B.windows_build = lambda: 22631
            B.shutil.which = lambda n: "wsl.exe"
            B.run = lambda cmd, input_text=None, timeout=0: (1, "")
            B.boot_time = lambda: "boot-A"
            self.assertEqual(B.wsl_state({}), "no_wsl")
            self.assertEqual(B.wsl_state({"wsl_install_started": True, "wsl_install_boot": "boot-A"}), "needs_restart")
            self.assertEqual(B.wsl_state({"wsl_install_started": True, "wsl_install_boot": "boot-OLD"}), "broken")
            B.run = lambda cmd, input_text=None, timeout=0: (0, "ok")
            self.assertEqual(B.wsl_state({"wsl_install_started": True}), "ready")
            B.windows_build = lambda: 18362
            self.assertEqual(B.wsl_state({}), "legacy")
        finally:
            B.sys.platform = sys_platform
            B.windows_build, B.shutil.which = orig_build, orig_which

    def test_parse_virt(self):
        self.assertTrue(B._parse_virt("True|False"))     # hypervisor already running
        self.assertTrue(B._parse_virt("False|True"))
        self.assertFalse(B._parse_virt("False|False"))
        self.assertIsNone(B._parse_virt("garbage"))
        self.assertIsNone(B._parse_virt("False|"))

    def test_demo_walkthrough(self):
        B.DEMO = True
        B._demo_state["wsl"] = "no_wsl"
        cfg = {}
        self.assertEqual(B.wsl_state(cfg), "no_wsl")
        self.assertTrue(B.install_wsl(cfg, lambda m: None))
        self.assertEqual(B.wsl_state(cfg), "needs_restart")
        B.restart_windows(1)
        self.assertEqual(B.wsl_state(cfg), "ready")
        B._demo_state["wsl"] = "ready"


class DemoFlow(unittest.TestCase):
    def setUp(self):
        B.DEMO = True
        B._demo_state.update(registered=False, attached=set(), shared={"2-3"}, chroot=False, extra=set(), wsl="ready", virt=True)
        B.DATA = os.path.join(os.path.dirname(__file__), "_tmpdata")
        B.CONFIG_PATH = os.path.join(B.DATA, "config.json")

    def tearDown(self):
        B.DEMO = False
        import shutil
        shutil.rmtree(B.DATA, ignore_errors=True)

    def test_usb_cycle(self):
        B.usb_attach("2-3")
        self.assertEqual([d for d in B.list_usb() if d["busid"] == "2-3"][0]["state"], "Attached")
        B.usb_detach("2-3")
        self.assertEqual([d for d in B.list_usb() if d["busid"] == "2-3"][0]["state"], "Shared")

    def test_chroot_install_demo(self):
        cfg = dict(B.DEFAULT_CONFIG, layout="chroot", flavor="custom", custom_rootfs=__file__)
        logs = []
        self.assertFalse(B.is_ready(cfg))
        B._demo_state["registered"] = True  # pretend the host exists
        B.list_distros = lambda: ["PocketLinux-host"]
        try:
            self.assertTrue(B.install(cfg, logs.append))
            self.assertTrue(B.is_ready(cfg))
            self.assertTrue(B.prepare_session(cfg, logs.append))
            self.assertIn("enter-box1.sh", B.open_console(cfg))
            B.remove(cfg)
            self.assertFalse(B.is_ready(cfg))
        finally:
            B.list_distros = _orig_list

    def test_install_demo(self):
        cfg = dict(B.DEFAULT_CONFIG, flavor="custom")
        cfg["custom_rootfs"] = __file__  # any existing file stands in for a rootfs
        logs = []
        self.assertTrue(B.install(cfg, logs.append))
        self.assertTrue(B.is_installed())
        self.assertTrue(B.prepare_session(cfg, logs.append))
        self.assertIn("wsl.exe", B.open_console(cfg).lower())


if __name__ == "__main__":
    unittest.main()
