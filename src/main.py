# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# WORK IN PROGRESS (0.3.0-wip): MANY FEATURES MAY BE BROKEN. Not yet tested on a
# real Windows PC (built and checked only in a simulated demo mode).
"""PocketLinux: a tiny, isolated Linux console in a Windows folder (WSL based)."""
import os
import queue
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backend as B  # noqa: E402

# Optional ErrCode hook (see matthew-project-standards):
# import errcode; errcode.install(app="PocketLinux")

BANNER_BG = "#fff3bf"
TITLE = "%s v%s (Built %s)" % (B.APP, B.__version__, B.__build_date__)
STATUS = "v%s • %s • WIP" % (B.__version__, B.__build_date__)


def main(argv):
    if "--version" in argv:
        print("%s %s (built %s) WORK IN PROGRESS" % (B.APP, B.__version__, B.__build_date__))
        return 0
    if "--demo" in argv or "--demo-nowsl" in argv or os.environ.get("POCKETLINUX_DEMO") == "1":
        B.DEMO = True
        if "--demo-nowsl" in argv:  # pretend WSL is not installed yet
            B._demo_state["wsl"] = "no_wsl"
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    App(tk, ttk, filedialog, messagebox).run()
    return 0


class App:
    def __init__(self, tk, ttk, filedialog, messagebox):
        self.tk, self.ttk, self.fd, self.mb = tk, ttk, filedialog, messagebox
        self.cfg = B.load_config()
        self.q = queue.Queue()
        self.busy = False
        self._refreshing = False
        self._again = False
        self.virt = None
        self.restart_pending = False
        self.wsl_state = "ready"
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.minsize(700, 560)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Big.TButton", font=("Segoe UI", 12, "bold"), padding=10)
        style.configure("Warn.TLabel", background="#b3261e", foreground="white",
                        font=("Segoe UI", 9, "bold"), padding=4)
        style.configure("Head.TLabel", font=("Segoe UI", 16, "bold"))
        self._build()
        self._on_layout()
        self._fit()
        self.root.after(100, self._poll)
        self.root.bind("<FocusIn>", self._on_focus)
        threading.Thread(target=self._probe_virt, daemon=True).start()
        self.root.after(300, self._first_run)

    # ---------------------------------------------------------------- layout
    def _build(self):
        tk, ttk = self.tk, self.ttk
        r = self.root
        r.columnconfigure(0, weight=1)
        r.rowconfigure(3, weight=1)
        top = ttk.Frame(r, padding=(12, 10, 12, 0))
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="PocketLinux", style="Head.TLabel").pack(side="left")
        ttk.Label(top, text="  isolated Linux in a folder", foreground="#555").pack(side="left")
        ttk.Label(r, text="WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN",
                  style="Warn.TLabel", anchor="center").grid(row=1, column=0, sticky="ew",
                                                            padx=12, pady=(6, 0))
        self.banner = tk.Frame(r, bg=BANNER_BG, highlightbackground="#d9a400", highlightthickness=1)
        self.banner.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 0))
        self.banner_title = tk.Label(self.banner, bg=BANNER_BG, fg="#3d2f00", anchor="w",
                                     font=("Segoe UI", 10, "bold"), justify="left")
        self.banner_title.pack(fill="x", padx=10, pady=(8, 0))
        self.banner_text = tk.Label(self.banner, bg=BANNER_BG, fg="#3d2f00", anchor="w",
                                    justify="left", wraplength=660)
        self.banner_text.pack(fill="x", padx=10, pady=(2, 4))
        self.banner_btns = tk.Frame(self.banner, bg=BANNER_BG)
        self.banner_btns.pack(fill="x", padx=10, pady=(0, 8))
        self.banner.grid_remove()
        body = ttk.Frame(r, padding=(12, 6, 12, 6))
        body.grid(row=3, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)

        # 1. Install ---------------------------------------------------------
        f = ttk.LabelFrame(body, text=" 1  Install ", padding=8)
        f.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Linux:").grid(row=0, column=0, sticky="w")
        self.distro_var = tk.StringVar(value=self._flavor_label())
        cb = ttk.Combobox(f, textvariable=self.distro_var, state="readonly",
                          values=list(B.DISTROS), width=28)
        cb.grid(row=0, column=1, sticky="w", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_distro())
        self.custom_btn = ttk.Button(f, text="Choose rootfs file...", command=self._pick_rootfs)
        self.custom_btn.grid(row=0, column=2, sticky="w")
        self.mode_var = tk.IntVar(value=int(self.cfg["wsl_version"]))
        mf = ttk.Frame(f)
        mf.grid(row=1, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Radiobutton(mf, text="WSL2: USB + real internet switch (recommended)",
                        variable=self.mode_var, value=2).pack(side="left")
        self.wsl1_rb = ttk.Radiobutton(mf, text="WSL1: no VM, no USB, soft internet switch",
                                       variable=self.mode_var, value=1)
        self.wsl1_rb.pack(side="left", padx=(12, 0))
        lf = ttk.Frame(f)
        lf.grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 4))
        self.layout_var = tk.StringVar(value=self.cfg["layout"])
        ttk.Radiobutton(lf, text="Own WSL distro", variable=self.layout_var, value="distro",
                        command=self._on_layout).pack(side="left")
        ttk.Radiobutton(lf, text="Chroot folder (no new distro)", variable=self.layout_var,
                        value="chroot", command=self._on_layout).pack(side="left", padx=(12, 6))
        ttk.Label(lf, text="host:").pack(side="left")
        self.host_var = tk.StringVar(value=self.cfg["host"])
        self.host_cb = ttk.Combobox(lf, textvariable=self.host_var, width=16,
                                    values=self._host_choices())
        self.host_cb.pack(side="left", padx=(4, 6))
        ttk.Label(lf, text="name:").pack(side="left")
        self.name_var = tk.StringVar(value=self.cfg["chroot_name"])
        self.name_entry = ttk.Entry(lf, textvariable=self.name_var, width=8)
        self.name_entry.pack(side="left", padx=4)
        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4, 0))
        self.install_btn = ttk.Button(bf, text="Install (one step)", command=self._install)
        self.install_btn.pack(side="left")
        self.backup_btn = ttk.Button(bf, text="Backup...", command=self._backup)
        self.backup_btn.pack(side="left")
        self.remove_btn = ttk.Button(bf, text="Remove", command=self._remove)
        self.remove_btn.pack(side="left", padx=6)
        self.bar = ttk.Progressbar(bf, mode="determinate", length=160)
        self.bar.pack(side="right")
        self.install_state = ttk.Label(f, text="")
        self.install_state.grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # 2. Folder ----------------------------------------------------------
        f = ttk.LabelFrame(body, text=" 2  Folder access ", padding=8)
        f.grid(row=1, column=0, sticky="nsew", padx=(0, 4), pady=(0, 4))
        f.columnconfigure(0, weight=1)
        ttk.Label(f, text="Shared with Linux as ~/share (its only Windows folder):").grid(
            row=0, column=0, columnspan=2, sticky="w")
        self.share_var = tk.StringVar(value=self.cfg["share_dir"] or "(none)")
        ttk.Label(f, textvariable=self.share_var, foreground="#245", wraplength=300).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=4)
        f.columnconfigure(1, weight=1)
        ttk.Button(f, text="Choose...", command=self._pick_share).grid(row=2, column=0, sticky="ew")
        ttk.Button(f, text="Clear", command=self._clear_share).grid(row=2, column=1, sticky="ew", padx=(4, 0))
        ttk.Button(f, text="Open shared folder", command=self._open_share).grid(
            row=3, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(f, text="Open Linux files", command=self._open_linux_files).grid(
            row=3, column=1, sticky="ew", pady=(4, 0), padx=(4, 0))

        # 3. Internet --------------------------------------------------------
        f = ttk.LabelFrame(body, text=" 3  Internet ", padding=8)
        f.grid(row=1, column=1, sticky="nsew", padx=(4, 0), pady=(0, 4))
        self.net_var = tk.BooleanVar(value=bool(self.cfg["internet"]))
        ttk.Checkbutton(f, text="Allow internet (apk / apt, downloads)",
                        variable=self.net_var, command=self._on_net).pack(anchor="w")
        self.net_note = ttk.Label(f, text="", foreground="#555", wraplength=300, justify="left")
        self.net_note.pack(anchor="w", pady=(6, 0))
        self._refresh_net_note()
        ttk.Label(f, text="Windows drives and programs are switched off inside the box.",
                  foreground="#555", wraplength=300).pack(anchor="w", pady=(6, 0))

        # 4. USB -------------------------------------------------------------
        f = ttk.LabelFrame(body, text=" 4  USB devices (WSL2 only) ", padding=8)
        f.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 4))
        f.columnconfigure(0, weight=1)
        cols = ("busid", "device", "state")
        self.usb = ttk.Treeview(f, columns=cols, show="headings", height=3, selectmode="browse")
        for c, w in (("busid", 70), ("device", 380), ("state", 120)):
            self.usb.heading(c, text=c.upper())
            self.usb.column(c, width=w, anchor="w")
        self.usb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(f, orient="vertical", command=self.usb.yview)
        self.usb.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")
        ub = ttk.Frame(f)
        ub.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(ub, text="Refresh", command=self._usb_refresh).pack(side="left")
        ttk.Button(ub, text="Attach to Linux", command=self._usb_attach).pack(side="left", padx=6)
        ttk.Button(ub, text="Give back to Windows", command=self._usb_detach).pack(side="left")
        self.usb_install = ttk.Button(ub, text="Install USB support (usbipd-win)",
                                      command=self._install_usbipd)
        self.usb_install.pack(side="left", padx=6)
        ttk.Label(f, text="Attached devices vanish from Windows until given back. Linux drivers depend on the WSL kernel.",
                  foreground="#555", wraplength=640).grid(row=2, column=0, columnspan=2,
                                                         sticky="w", pady=(4, 0))

        # 5. Console ---------------------------------------------------------
        f = ttk.LabelFrame(body, text=" 5  Console ", padding=8)
        f.grid(row=3, column=0, columnspan=2, sticky="nsew")
        f.columnconfigure(2, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Colour:").grid(row=0, column=0, sticky="w")
        self.theme_var = tk.StringVar(value=self.cfg["theme"])
        tc = ttk.Combobox(f, textvariable=self.theme_var, state="readonly",
                          values=list(B.THEMES), width=14)
        tc.grid(row=0, column=1, sticky="w", padx=6)
        tc.bind("<<ComboboxSelected>>", lambda e: self._save())
        ttk.Button(f, text="Open Linux console", style="Big.TButton",
                   command=self._console).grid(row=0, column=2, sticky="e")
        self.log = self.tk.Text(f, height=4, wrap="word", state="disabled",
                                background="#10161c", foreground="#c9d4dc",
                                font=("Consolas", 9), relief="flat")
        self.log.grid(row=1, column=0, columnspan=3, sticky="nsew", pady=(8, 0))

        self.status = ttk.Label(self.root, text=STATUS, anchor="w", relief="sunken", padding=(8, 2))
        self.status.grid(row=4, column=0, sticky="ew")
        # sections 2-5 only matter once WSL works; they are hidden until then
        self.later_secs = [w for w in body.winfo_children()
                           if isinstance(w, ttk.LabelFrame) and w.cget("text").strip()[:1] in "2345"]
        self._refresh_state()
        self._on_distro(save=False)

    # ----------------------------------------------------------- helpers
    def _host_choices(self):
        try:
            others = [d for d in B.list_distros() if d != B.DEFAULT_HOST]
        except Exception:
            others = []
        return [B.DEFAULT_HOST] + others

    def _on_layout(self):
        chroot = self.layout_var.get() == "chroot"
        if chroot:
            self.mode_var.set(2)
        self.wsl1_rb.state(["disabled"] if chroot else ["!disabled"])
        self.host_cb.configure(state="normal" if chroot else "disabled")
        self.name_entry.configure(state="normal" if chroot else "disabled")
        if chroot:
            self.host_cb.configure(values=self._host_choices())
        self._save()
        self._refresh_net_note()
        self._refresh_state()

    def _flavor_label(self):
        for label, fl in B.DISTROS.items():
            if fl == self.cfg["flavor"]:
                return label
        return list(B.DISTROS)[0]

    def _save(self):
        self.cfg["theme"] = self.theme_var.get()
        self.cfg["flavor"] = B.DISTROS[self.distro_var.get()]
        self.cfg["layout"] = self.layout_var.get()
        self.cfg["host"] = self.host_var.get().strip() or B.DEFAULT_HOST
        self.cfg["chroot_name"] = self.name_var.get().strip() or "box1"
        self.cfg["wsl_version"] = 2 if self.cfg["layout"] == "chroot" else self.mode_var.get()
        self.cfg["internet"] = bool(self.net_var.get())
        B.save_config(self.cfg)

    def say(self, text):
        self.q.put(("log", text))

    def _poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert("end", val.rstrip() + "\n")
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "bar":
                    self.bar["value"] = val
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def bg(self, fn, then=None):
        if self.busy:
            self.say("Busy, please wait for the current step to finish.")
            return
        self.busy = True

        def work():
            try:
                fn()
            except Exception as e:  # show the problem instead of dying silently
                self.say("Error: %s" % e)
            finally:
                self.busy = False
                if then:
                    self.q.put(("call", then))
                self.q.put(("call", self._refresh_state))
        threading.Thread(target=work, daemon=True).start()

    def _progress(self, done, total):
        if total:
            self.q.put(("bar", done * 100.0 / total))

    def _installed(self):
        try:
            return B.is_ready(self.cfg)
        except Exception:
            return False

    def _fit(self):
        """Size the window to its content, but never taller than a small screen."""
        self.root.update_idletasks()
        h = min(self.root.winfo_reqheight(), self.root.winfo_screenheight() - 80)
        self.root.geometry("%dx%d" % (max(self.root.winfo_reqwidth(), 700), h))

    def _probe_virt(self):
        self.virt = B.virtualization_enabled()
        self.q.put(("call", self._refresh_state))

    def _on_focus(self, event):
        # coming back from the UAC prompt, a restart or Windows Update: re-check quietly
        if event.widget is self.root and self.wsl_state != "ready" and not self.busy:
            self._refresh_state()

    def _refresh_state(self):
        """Non-blocking: WSL calls run in a thread, the UI is updated via the queue."""
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True

        def work():
            try:
                ws = B.wsl_state(self.cfg)
                inst = (ws == "ready") and self._installed()
            except Exception:
                ws, inst = "no_wsl", False
            self.q.put(("call", lambda: self._apply_state(ws, inst, B.usbipd_exe())))
        threading.Thread(target=work, daemon=True).start()

    def _apply_state(self, ws, inst, usbipd):
        self._refreshing = False
        self.wsl_state = ws
        self._apply_banner(ws)
        warn = False
        if ws != "ready":
            msg = "Waiting for WSL (see the yellow Step 0 box above)."
        elif inst:
            if self.cfg["layout"] == "chroot":
                msg = "Installed: chroot folder %s inside '%s'. Other distros untouched." % (
                    B.chroot_paths(self.cfg)[0], self.cfg["host"])
            else:
                msg = "Installed: %s (WSL%s). Storage folder: %s" % (
                    self.cfg["distro"], self.cfg["wsl_version"], os.path.join(B.DATA, "rootfs"))
        else:
            msg = "WSL is ready. Press Install (needs internet, a few minutes)."
        needs_vm = self.cfg["layout"] == "chroot" or int(self.cfg["wsl_version"]) == 2
        if ws == "ready" and not inst and needs_vm and self.virt is False:
            msg = ("Virtualization looks OFF in your BIOS/UEFI (Intel VT-x / AMD-V / SVM). WSL2 and chroot "
                   "mode need it; choose 'Own WSL distro' + WSL1, or switch it on in the BIOS.")
            warn = True
        self.install_state.configure(text=msg, foreground="#b3261e" if warn else "")
        ready = ws == "ready"
        self.install_btn.configure(text="Install (one step)" if ready else "Install (needs WSL first)",
                                   state="normal" if (ready and not inst) else "disabled")
        for b in (self.backup_btn, self.remove_btn):
            b.configure(state="normal" if inst else "disabled")
        self.usb_install.configure(state="disabled" if usbipd else "normal")
        for w in self.later_secs:
            w.grid() if ready else w.grid_remove()
        self._fit()
        if self._again:
            self._again = False
            self._refresh_state()

    def _apply_banner(self, ws):
        """The yellow 'Step 0' box: tells the user exactly what to do about WSL."""
        for w in self.banner_btns.winfo_children():
            w.destroy()
        info = {
            "no_wsl": ("Step 0: Windows needs WSL first",
                       "WSL (Windows Subsystem for Linux) is Microsoft's built-in feature that PocketLinux "
                       "is built on. It is a small download, not a big VM image. Windows will ask for "
                       "permission, then you restart once.",
                       [("Install WSL now", self._install_wsl, True), ("Help / manual steps", self._show_help, False)]),
            "needs_restart": ("Step 0: restart Windows to finish installing WSL",
                              "WSL is installed, but Windows only switches it on after a restart. Save your "
                              "work first. After restarting, open PocketLinux again (or press Re-check).",
                              [("Cancel restart" if self.restart_pending else "Restart Windows now",
                                self._cancel_restart if self.restart_pending else self._restart_windows, True),
                               ("I already restarted: Re-check", self._refresh_state, False)]),
            "broken": ("WSL is installed but not answering",
                       "Windows was restarted but WSL still does not respond. This is usually fixed by "
                       "'wsl --update', or by switching on virtualization in the BIOS/UEFI.",
                       [("Run wsl --update", self._update_wsl, True), ("Help / fixes", self._show_help, False),
                        ("Re-check", self._refresh_state, False)]),
            "legacy": ("This Windows is too old",
                       "PocketLinux needs Windows 10 version 2004 (build 19041) or newer, or Windows 11.",
                       [("Open Windows Update", lambda: self._open("ms-settings:windowsupdate"), True),
                        ("Help", self._show_help, False)]),
            "unsupported": ("PocketLinux needs Windows",
                            "This computer is not running Windows, so WSL is not available. "
                            "Use --demo to explore the window with fake data.",
                            [("Help", self._show_help, False)]),
        }.get(ws)
        if not info:
            self.banner.grid_remove()
            return
        title, text, buttons = info
        self.banner_title.configure(text=title)
        self.banner_text.configure(text=text)
        for label, cmd, primary in buttons:
            b = self.ttk.Button(self.banner_btns, text=label, command=cmd,
                                style="Big.TButton" if primary else "TButton")
            b.pack(side="left", padx=(0, 8))
        self.banner.grid()

    def _on_distro(self, save=True):
        custom = B.DISTROS[self.distro_var.get()] == "custom"
        self.custom_btn.state(["!disabled"] if custom else ["disabled"])
        if save:
            self._save()

    def _refresh_net_note(self):
        if self.cfg["layout"] == "chroot":
            t = "Chroot: OFF gives the console an empty network (no internet at all); applies next time you open it."
        elif int(self.cfg["wsl_version"]) == 2:
            t = "WSL2: OFF blocks all outgoing traffic from the box with a firewall rule."
        else:
            t = "WSL1: OFF only blanks DNS. Programs using raw IP addresses can still get out."
        self.net_note.configure(text=t)

    def _first_run(self):
        if self.cfg.get("accepted_disclaimer"):
            return
        tk, ttk = self.tk, self.ttk
        d = tk.Toplevel(self.root)
        d.title("Before you start")
        d.transient(self.root)
        d.grab_set()
        d.protocol("WM_DELETE_WINDOW", self.root.destroy)  # closing quits
        txt = ("PocketLinux %s is a work in progress.\n\n"
               "It installs a Linux distro into Windows Subsystem for Linux (WSL) and "
               "can enable WSL, install usbipd-win and attach USB devices. Attached USB "
               "devices are unavailable to Windows until given back.\n\n"
               "Source-available, non-commercial (PolyForm Noncommercial 1.0.0). "
               "Provided as is, with no warranty and no liability. Back up first.\n\n"
               "Copyright Matthew Armstrong." % B.__version__)
        ttk.Label(d, text=txt, wraplength=420, justify="left", padding=14).pack()
        ok = tk.BooleanVar(value=False)
        btn = ttk.Button(d, text="I agree", state="disabled",
                         command=lambda: (self.cfg.update(accepted_disclaimer=True),
                                          B.save_config(self.cfg), d.destroy()))
        ttk.Checkbutton(d, text="I have read this and accept the risks", variable=ok,
                        command=lambda: btn.configure(state="normal" if ok.get() else "disabled")
                        ).pack(anchor="w", padx=14)
        btn.pack(pady=12)

    # ----------------------------------------------------------- actions
    def _pick_rootfs(self):
        p = self.fd.askopenfilename(title="Linux root filesystem",
                                    filetypes=[("Rootfs", "*.tar *.tar.gz *.tgz *.tar.xz *.wsl"),
                                               ("All files", "*.*")])
        if p:
            self.cfg["custom_rootfs"] = p
            self.say("Rootfs: %s" % p)
            self._save()

    def _install(self):
        self._save()
        self.bar["value"] = 0
        self.bg(lambda: B.install(self.cfg, self.say, self._progress),
                then=lambda: (self._refresh_net_note(), self._usb_refresh()))

    def _install_wsl(self):
        def go():
            ok = B.install_wsl(self.cfg, self.say)
            if ok:
                B.save_config(self.cfg)
        self.bg(go)

    def _restart_windows(self):
        if not self.mb.askokcancel("Restart Windows",
                                   "Windows will restart in 30 seconds. Save and close your work now.\n\n"
                                   "You can cancel from this window before then."):
            return

        def go():
            rc, out = B.restart_windows(30)
            if rc == 0:
                self.restart_pending = True
                self.say("Windows restarts in 30 seconds. Press 'Cancel restart' to stop it.")
                self.q.put(("call", lambda: self.root.after(35000, self._restart_done)))
            else:
                self.say("Could not schedule the restart (%s). Restart Windows yourself, then press Re-check." % out.strip())
        self.bg(go)

    def _restart_done(self):
        self.restart_pending = False
        self._refresh_state()

    def _cancel_restart(self):
        def go():
            B.cancel_restart()
            self.restart_pending = False
            self.say("Restart cancelled.")
        self.bg(go)

    def _update_wsl(self):
        def go():
            self.say("Running 'wsl --update' (may take a minute)...")
            rc, out = B.update_wsl()
            self.say(out.strip()[-300:] or "Done.")
        self.bg(go)

    def _show_help(self):
        tk, ttk = self.tk, self.ttk
        d = tk.Toplevel(self.root)
        d.title("WSL: help and manual steps")
        d.transient(self.root)
        text = ("If WSL will not install or start:\n\n"
                "1. Windows must be 10 version 2004 (build 19041) or newer, or Windows 11. "
                "Check Windows Update.\n"
                "2. After installing WSL, restart Windows.\n"
                "3. WSL2 and chroot mode need virtualization (Intel VT-x / AMD-V / SVM Mode) switched on in "
                "the BIOS/UEFI. WSL1 does not.\n"
                "4. Press 'Run wsl --update' to fetch Microsoft's current WSL.\n"
                "5. Manual route: open PowerShell as administrator and run\n"
                "      wsl --install --no-distribution\n"
                "   or tick 'Windows Subsystem for Linux' and 'Virtual Machine Platform' in Windows Features, "
                "then restart.\n\n"
                "Work-and-corporate PCs may block these steps; ask your IT admin in that case.")
        ttk.Label(d, text=text, wraplength=520, justify="left", padding=14).pack()
        bf = ttk.Frame(d, padding=(14, 0, 14, 14))
        bf.pack(fill="x")

        def guide():
            import webbrowser
            webbrowser.open(B.HELP_URL)
        ttk.Button(bf, text="Microsoft's guide", command=guide).pack(side="left")
        ttk.Button(bf, text="Windows Features", command=lambda: self._open("optionalfeatures.exe")).pack(
            side="left", padx=6)
        ttk.Button(bf, text="Use Windows-features method (admin)",
                   command=lambda: self.bg(lambda: B.enable_features(self.cfg, self.say))).pack(side="left")
        ttk.Button(bf, text="Close", command=d.destroy).pack(side="right")

    def _backup(self):
        p = self.fd.asksaveasfilename(defaultextension=".tar", initialfile="pocketlinux-backup.tar",
                                      filetypes=[("Tar archive", "*.tar")])
        if p:
            def go():
                self.say("Exporting to %s ..." % p)
                rc, out = B.backup(self.cfg, p)
                self.say("Backup done." if rc == 0 else "Backup failed: %s" % out.strip())
            self.bg(go)

    def _remove(self):
        what = ("the chroot folder '%s' inside '%s' (the host and other distros stay)" % (
            self.cfg["chroot_name"], self.cfg["host"])) if self.cfg["layout"] == "chroot" else \
            "the whole PocketLinux WSL distro"
        if not self.mb.askyesno("Remove Linux",
                                "This DELETES %s and everything stored inside it "
                                "(not your shared Windows folder). Make a backup first.\n\nContinue?" % what):
            return

        def go():
            rc, out = B.remove(self.cfg)
            self.say("Removed." if rc == 0 else "Failed: %s" % out.strip())
        self.bg(go)

    def _pick_share(self):
        p = self.fd.askdirectory(title="Folder to share with Linux")
        if p:
            p = os.path.normpath(p)
            if "'" in p:
                self.mb.showerror("Folder", "Folders with an apostrophe (') in the path are not supported.")
                return
            self.cfg["share_dir"] = p
            self.share_var.set(p)
            self._save()
            self.say("Shared folder set (mounted when the console opens).")

    def _clear_share(self):
        self.cfg["share_dir"] = ""
        self.share_var.set("(none)")
        self._save()

    def _open(self, path):
        if hasattr(os, "startfile"):
            os.startfile(path)  # noqa: pylint
        else:
            self.say("Would open: %s" % path)

    def _open_share(self):
        if self.cfg["share_dir"]:
            self._open(self.cfg["share_dir"])
        else:
            self.say("No shared folder chosen yet.")

    def _open_linux_files(self):
        name = B.target(self.cfg)
        sub = (B.chroot_paths(self.cfg)[0].replace("/", "\\") if self.cfg["layout"] == "chroot"
               else "\\home\\%s" % B.LINUX_USER)

        def go():
            B.run_root("true", name, timeout=60)  # make sure the distro is running
            self.q.put(("call", lambda: self._open("\\\\wsl.localhost\\%s%s" % (name, sub))))
        self.bg(go)

    def _on_net(self):
        self._save()
        self._refresh_net_note()
        if not self._installed():
            return

        def go():
            rc, out = B.apply_network(self.cfg)
            self.say(out.strip() if self.cfg["layout"] == "chroot" else
                     ("Internet %s." % ("ON" if self.cfg["internet"] else "OFF") if rc == 0
                      else "Could not change internet setting: %s" % out.strip()))
        self.bg(go)

    def _console(self):
        self._save()

        def go():
            if not self._installed():
                self.say("Install Linux first (section 1).")
                return
            self.say("Preparing share, network and theme...")
            B.prepare_session(self.cfg, self.say)
            line = B.open_console(self.cfg)
            self.say("Console opened." if not B.DEMO else "[demo] would run: %s" % line)
        self.bg(go)

    # --- USB
    def _selected_usb(self):
        sel = self.usb.selection()
        return self.usb.item(sel[0], "values")[0] if sel else None

    def _usb_refresh(self):
        devs = B.list_usb()
        for i in self.usb.get_children():
            self.usb.delete(i)
        if devs is None:
            self.usb.insert("", "end", values=("", "usbipd-win is not installed (see button)", ""))
            return
        for d in devs:
            self.usb.insert("", "end", values=(d["busid"], "%s  [%s]" % (d["name"], d["vidpid"]), d["state"]))

    def _usb_attach(self):
        busid = self._selected_usb()
        if not busid:
            self.say("Select a USB device first.")
            return
        if int(self.cfg["wsl_version"]) != 2:
            self.say("USB needs WSL2. Reinstall in WSL2 mode.")
            return

        def go():
            B.run_root("true", B.target(self.cfg), timeout=60)  # VM must be running
            state = [d for d in (B.list_usb() or []) if d["busid"] == busid]
            if state and state[0]["state"] == "Not shared":
                self.say("Sharing %s (approve the admin prompt, one-time)..." % busid)
                B.usb_bind(busid)
            rc, out = B.usb_attach(busid, B.target(self.cfg))
            self.say(("Attached %s." % busid) if rc == 0 else "Attach failed: %s" % out.strip())
        self.bg(go, then=self._usb_refresh)

    def _usb_detach(self):
        busid = self._selected_usb()
        if not busid:
            self.say("Select a USB device first.")
            return

        def go():
            rc, out = B.usb_detach(busid)
            self.say(("Gave %s back to Windows." % busid) if rc == 0 else "Detach failed: %s" % out.strip())
        self.bg(go, then=self._usb_refresh)

    def _install_usbipd(self):
        def go():
            self.say("Installing usbipd-win with winget (approve the admin prompt)...")
            rc, out = B.install_usbipd()
            self.say(out.strip()[-400:] or "Done. Restart this app.")
        self.bg(go, then=self._usb_refresh)

    def run(self):
        self._usb_refresh()
        self.root.mainloop()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
