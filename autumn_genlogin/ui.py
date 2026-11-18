"""Tkinter desktop UI. The browser and HTTP API run off the GUI thread."""
from __future__ import annotations

import json
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .api import LocalAPI
from .browser import BrowserManager
from .models import Profile, validated_steps
from .secrets import delete_password, set_password
from .storage import Store

BG = "#0e1423"
PANEL = "#192236"
PANEL2 = "#222e45"
FG = "#edf3fc"
MUTED = "#9aaac5"
ACCENT = "#60a5fa"

EXAMPLE_STEPS = [
    {"action": "goto", "url": "https://example.com"},
    {"action": "wait_for", "selector": "h1"},
    {"action": "extract_text", "selector": "h1"},
    {"action": "screenshot"},
]


class ProfileEditor(tk.Toplevel):
    def __init__(self, parent: "App", existing: Profile | None):
        super().__init__(parent.root)
        self.parent = parent
        self.original = existing
        self.profile = replace(existing) if existing else Profile()
        self.title("Edit profile" if existing else "Create profile")
        self.geometry("650x630")
        self.minsize(540, 540)
        self.configure(bg=BG)
        self.transient(parent.root)
        self.grab_set()
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="PROFILE CONFIGURATION", style="Heading.TLabel").pack(anchor="w", pady=(0, 10))
        self.fields: dict[str, tk.StringVar] = {}
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        general, identity, proxy = (ttk.Frame(tabs, padding=18) for _ in range(3))
        tabs.add(general, text="General")
        tabs.add(identity, text="Browser identity")
        tabs.add(proxy, text="Proxy")
        self._field(general, "Name", "name")
        self._field(general, "Group", "group_name")
        self._field(general, "Tags (comma-separated)", "tags")
        self._field(general, "Start URL", "start_url")
        self._field(general, "Browser (installed Chrome / Edge)", "browser", choices=("chrome", "msedge", "chromium"))
        ttk.Label(general, text="Each profile gets its own browser data folder.\nFor bundled Chromium, install it separately with Playwright.", foreground=MUTED).pack(anchor="w", pady=(16, 0))
        self._field(identity, "Locale (e.g. en-US, vi-VN)", "locale")
        self._field(identity, "IANA timezone (e.g. Asia/Ho_Chi_Minh)", "timezone_id")
        self._field(identity, "User agent (optional)", "user_agent")
        self._field(identity, "Viewport width", "viewport_width")
        self._field(identity, "Viewport height", "viewport_height")
        ttk.Label(identity, text="These are standard browser context settings, NOT\na guarantee of anonymity or detection avoidance.", foreground=MUTED).pack(anchor="w", pady=(14, 0))
        self._field(proxy, "Proxy type", "proxy_scheme", choices=("", "http", "socks5"))
        self._field(proxy, "Proxy host / IP", "proxy_host")
        self._field(proxy, "Proxy port", "proxy_port")
        self._field(proxy, "Proxy username", "proxy_username")
        ttk.Label(proxy, text="Proxy password (stored in Windows Credential Manager)").pack(anchor="w", pady=(10, 4))
        self.secret_var = tk.StringVar()
        ttk.Entry(proxy, textvariable=self.secret_var, show="*").pack(fill="x")
        ttk.Label(proxy, text="Leave blank to keep existing password.\nDisabling proxy deletes the saved password.", foreground=MUTED).pack(anchor="w", pady=(8, 0))
        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(20, 0))
        ttk.Button(footer, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(footer, text="Save profile", style="Accent.TButton", command=self.save).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _field(self, parent, title: str, attribute: str, choices: tuple | None = None):
        ttk.Label(parent, text=title).pack(anchor="w", pady=(8, 4))
        val = getattr(self.profile, attribute)
        variable = tk.StringVar(value=str(val))
        self.fields[attribute] = variable
        if choices is not None:
            ttk.Combobox(parent, textvariable=variable, values=choices, state="readonly").pack(fill="x")
        else:
            ttk.Entry(parent, textvariable=variable).pack(fill="x")

    def save(self):
        try:
            pid = self.profile.id
            if self.original and self.parent.manager.active(pid):
                raise ValueError("Stop the browser before editing its profile")
            data = {k: v.get().strip() for k, v in self.fields.items()}
            data["viewport_width"] = int(data["viewport_width"])
            data["viewport_height"] = int(data["viewport_height"])
            data["proxy_port"] = int(data["proxy_port"] or 0)
            p = replace(self.profile, **data)
            p.validate()
            secret = self.secret_var.get()
            if p.proxy_scheme and secret:
                set_password(pid, secret)  # Fail closed if no credential vault exists.
            elif not p.proxy_scheme and self.original and self.original.proxy_scheme:
                delete_password(pid)
            self.parent.store.save(p)
            self.parent.refresh()
            self.parent.notice("Saved: " + p.name)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Profile validation", str(exc), parent=self)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.store = Store()
        self.manager = BrowserManager(self.store)
        self.api = LocalAPI(self.store, self.manager)
        self.root.title("AutumnGenLogin  |  Local Browser Studio")
        self.root.geometry("1230x780")
        self.root.minsize(990, 650)
        self.root.configure(bg=BG)
        self._style()
        self.search = tk.StringVar()
        self.group = tk.StringVar(value="All groups")
        self.status = tk.StringVar(value="Ready · Everything runs locally")
        self._build()
        self.refresh()
        self.root.after(150, self.poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Heading.TLabel", font=("Segoe UI Semibold", 15), foreground=FG)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("TEntry", padding=8, fieldbackground=PANEL, foreground=FG, bordercolor=PANEL2)
        style.configure("TCombobox", padding=6, fieldbackground=PANEL, foreground=FG)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL)], selectbackground=[("readonly", PANEL)])
        style.configure("TButton", padding=(13, 9), background=PANEL2, foreground=FG, borderwidth=0)
        style.map("TButton", background=[("active", "#324461")])
        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff", font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#1d4ed8")])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, borderwidth=0, rowheight=38)
        style.map("Treeview", background=[("selected", "#24457a")], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, font=("Segoe UI Semibold", 10), padding=9)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 10))
        style.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", FG)])

    def _build(self):
        page = ttk.Frame(self.root, padding=(26, 22))
        page.pack(fill="both", expand=True)
        top = ttk.Frame(page)
        top.pack(fill="x", pady=(0, 22))
        title_box = ttk.Frame(top)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="◈  AUTUMN GENLOGIN", font=("Segoe UI Semibold", 22), foreground=ACCENT).pack(anchor="w")
        ttk.Label(title_box, text="Local-first · Separate browser profiles · No subscription required", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Button(top, text="API: OFF", command=self.toggle_api).pack(side="right", padx=(10, 0))
        self.api_button = top.winfo_children()[-1]
        ttk.Button(top, text="Export metadata", command=self.export_profiles).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="Import metadata", command=self.import_profiles).pack(side="right")
        tabs = ttk.Notebook(page)
        tabs.pack(fill="both", expand=True)
        profile_tab, flow_tab, logs_tab = (ttk.Frame(tabs, padding=(0, 16)) for _ in range(3))
        tabs.add(profile_tab, text="  Profiles  ")
        tabs.add(flow_tab, text="  Automation  ")
        tabs.add(logs_tab, text="  Activity log  ")
        controls = ttk.Frame(profile_tab)
        controls.pack(fill="x", pady=(0, 13))
        ttk.Button(controls, text="+ New profile", style="Accent.TButton", command=self.new_profile).pack(side="left")
        for title, callback in (("Edit", self.edit_profile), ("Clone", self.clone_profile), ("Open", self.open_profile), ("Stop", self.stop_profile), ("Delete", self.delete_profile)):
            ttk.Button(controls, text=title, command=callback).pack(side="left", padx=(8, 0))
        ttk.Button(controls, text="Open group", command=self.open_group).pack(side="left", padx=(8, 0))
        ttk.Label(controls, text="Group", style="Muted.TLabel").pack(side="left", padx=(15, 8))
        self.group_combo = ttk.Combobox(controls, width=16, textvariable=self.group, state="readonly")
        self.group_combo.pack(side="left")
        self.group_combo.bind("<<ComboboxSelected>>", lambda *_: self.refresh())
        ttk.Label(controls, text="Search", style="Muted.TLabel").pack(side="left", padx=(20, 8))
        search_input = ttk.Entry(controls, textvariable=self.search)
        search_input.pack(side="left", fill="x", expand=True)
        self.search.trace_add("write", lambda *_: self.refresh())
        tree_frame = ttk.Frame(profile_tab)
        tree_frame.pack(fill="both", expand=True)
        cols = ("name", "group", "tags", "browser", "proxy", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        headers = {"name": ("Profile", 230), "group": ("Group", 130), "tags": ("Tags", 220), "browser": ("Browser", 110), "proxy": ("Proxy", 150), "status": ("Status", 110)}
        for col, (label, width) in headers.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=70, stretch=col in {"name", "tags"})
        bar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda *_: self.open_profile())
        ttk.Label(profile_tab, text="Profiles keep cookies and browsing data in separate local folders. Proxy credentials stay in the OS vault.", style="Muted.TLabel").pack(anchor="w", pady=(12, 0))
        flow_header = ttk.Frame(flow_tab)
        flow_header.pack(fill="x", pady=(0, 10))
        ttk.Label(flow_header, text="JSON automation workflow", style="Heading.TLabel").pack(side="left")
        for title, action in (("Load JSON", self.load_workflow), ("Save JSON", self.save_workflow), ("Run on selected profile", self.run_workflow), ("Cancel", self.cancel_workflow)):
            ttk.Button(flow_header, text=title, command=action).pack(side="right", padx=(8, 0))
        ttk.Label(flow_tab, text="Supported: goto, click, fill, press, check, uncheck, select_option, scroll_into_view, wait, wait_for, screenshot, extract_text.", style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.workflow = tk.Text(flow_tab, font=("Cascadia Code", 11), bg=PANEL, fg=FG, insertbackground=FG, relief="flat", undo=True, padx=17, pady=16, wrap="none")
        self.workflow.pack(fill="both", expand=True)
        self.workflow.insert("1.0", json.dumps(EXAMPLE_STEPS, indent=2, ensure_ascii=False))
        ttk.Label(logs_tab, text="Session activity", style="Heading.TLabel").pack(anchor="w", pady=(0, 14))
        self.log_widget = tk.Text(logs_tab, font=("Cascadia Code", 10), bg=PANEL, fg=FG, insertbackground=FG, relief="flat", state="disabled", padx=15, pady=15)
        self.log_widget.pack(fill="both", expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, textvariable=self.status, foreground=MUTED).pack(side="left")
        ttk.Label(bottom, text="v0.2.0  ·  PRIVATE BY DEFAULT", foreground=ACCENT).pack(side="right")

    def selected_id(self, alert=True):
        selected = self.tree.selection()
        if selected:
            return selected[0]
        if alert:
            messagebox.showinfo("Select profile", "Select a profile in the Profiles tab first.")
        return None

    def notice(self, value):
        self.status.set(value)
        self.log(value)

    def log(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def refresh(self):
        old = self.selected_id(False)
        profiles = self.store.all()
        groups = ["All groups"] + sorted({p.group_name for p in profiles})
        self.group_combo.configure(values=groups)
        if self.group.get() not in groups:
            self.group.set("All groups")
        self.tree.delete(*self.tree.get_children())
        needle = self.search.get().casefold()
        for p in profiles:
            if self.group.get() != "All groups" and p.group_name != self.group.get():
                continue
            if needle and needle not in f"{p.name} {p.tags} {p.group_name}".casefold():
                continue
            self.tree.insert("", "end", iid=p.id, values=(p.name, p.group_name, p.tags, p.browser, (p.proxy_host or "Direct"), "● Running" if self.manager.active(p.id) else "○ Stopped"))
        if old and self.tree.exists(old):
            self.tree.selection_set(old)

    def new_profile(self):
        ProfileEditor(self, None)

    def edit_profile(self):
        pid = self.selected_id()
        if pid:
            ProfileEditor(self, self.store.get(pid))

    def clone_profile(self):
        pid = self.selected_id()
        if pid:
            try:
                p = self.store.clone(pid)
                self.refresh()
                self.notice(f"Cloned {p.name}. Proxy password is not copied.")
            except Exception as exc:
                messagebox.showerror("Clone error", str(exc))

    def open_profile(self):
        pid = self.selected_id()
        if pid:
            try:
                self.manager.start(pid)
                self.refresh()
            except Exception as exc:
                messagebox.showerror("Browser error", str(exc))

    def open_group(self):
        group = self.group.get()
        if group == "All groups":
            messagebox.showinfo("Choose a group", "Select one group from the Group menu first.")
            return
        started, failed = 0, []
        for p in self.store.all():
            if p.group_name != group or self.manager.active(p.id):
                continue
            try:
                self.manager.start(p.id)
                started += 1
            except Exception as exc:
                failed.append(f"{p.name}: {exc}")
        self.refresh()
        self.notice(f"Opened {started} profiles from {group}")
        if failed:
            messagebox.showwarning("Some profiles did not open", "\n".join(failed[:8]))

    def stop_profile(self):
        pid = self.selected_id()
        if pid:
            self.manager.stop(pid)
            self.notice("Stop requested")

    def delete_profile(self):
        pid = self.selected_id()
        if not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Profile running", "Stop the browser before deleting it")
            return
        p = self.store.get(pid)
        if messagebox.askyesno("Delete profile", f"Permanently remove {p.name} and its local browsing data?\nThis cannot be undone."):
            try:
                delete_password(pid)
                self.store.delete(pid)
                self.refresh()
                self.notice("Deleted " + p.name)
            except Exception as exc:
                messagebox.showerror("Delete error", str(exc))

    def export_profiles(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="autumn-profiles.json")
        if path:
            try:
                number = self.store.export_metadata(Path(path))
                self.notice(f"Exported {number} metadata records (no passwords/cookies)")
            except Exception as exc:
                messagebox.showerror("Export error", str(exc))

    def import_profiles(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            try:
                number = self.store.import_metadata(Path(path))
                self.refresh()
                self.notice(f"Imported {number} profiles (fresh IDs and empty sessions)")
            except Exception as exc:
                messagebox.showerror("Import error", str(exc))

    def current_steps(self):
        return validated_steps(json.loads(self.workflow.get("1.0", "end")))

    def run_workflow(self):
        pid = self.selected_id()
        if pid:
            try:
                self.manager.run_steps(pid, self.current_steps())
                self.notice("Workflow queued for selected profile")
            except Exception as exc:
                messagebox.showerror("Automation error", str(exc))

    def cancel_workflow(self):
        pid = self.selected_id()
        if pid:
            self.manager.cancel(pid)
            self.notice("Cancellation requested (after current browser action)")

    def load_workflow(self):
        path = filedialog.askopenfilename(filetypes=[("JSON workflow", "*.json")])
        if path:
            try:
                source = Path(path).read_text(encoding="utf-8")
                validated_steps(json.loads(source))
                self.workflow.delete("1.0", "end")
                self.workflow.insert("1.0", source)
            except Exception as exc:
                messagebox.showerror("Workflow error", str(exc))

    def save_workflow(self):
        try:
            steps = self.current_steps()
            path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON workflow", "*.json")])
            if path:
                Path(path).write_text(json.dumps(steps, indent=2, ensure_ascii=False), encoding="utf-8")
                self.notice(f"Saved workflow: {path}")
        except Exception as exc:
            messagebox.showerror("Workflow error", str(exc))

    def toggle_api(self):
        try:
            if self.api.server:
                self.api.stop()
                self.api_button.configure(text="API: OFF")
                self.notice("Loopback API disabled")
            else:
                self.api.start()
                self.api_button.configure(text="API: ON")
                self.notice("Loopback API enabled at http://127.0.0.1:8765")
                modal = tk.Toplevel(self.root)
                modal.title("Local API access")
                modal.geometry("600x240")
                modal.configure(bg=BG)
                modal.transient(self.root)
                content = ttk.Frame(modal, padding=20)
                content.pack(fill="both", expand=True)
                ttk.Label(content, text="Local API token (valid only until app restart)", style="Heading.TLabel").pack(anchor="w")
                box = ttk.Entry(content, width=74)
                box.insert(0, self.api.token)
                box.configure(state="readonly")
                box.pack(fill="x", pady=15)
                ttk.Label(content, text="Send Authorization: Bearer <token> on every request.\nDo not share this token or expose this API beyond localhost.", style="Muted.TLabel").pack(anchor="w")
                ttk.Button(content, text="Copy token", command=lambda: self._copy(self.api.token)).pack(anchor="e", pady=12)
        except Exception as exc:
            messagebox.showerror("Local API error", str(exc))

    def _copy(self, content):
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.notice("API token copied to clipboard")

    def poll_events(self):
        try:
            changed = False
            for _ in range(100):
                try:
                    pid, kind, message = self.manager.events.get_nowait()
                except __import__("queue").Empty:
                    break
                if kind == "status":
                    changed = True
                self.log(f"[{pid[:8]}] [{kind.upper()}] {message}")
                if kind == "error":
                    self.status.set("Browser error: " + message[:130])
            if changed:
                self.refresh()
        finally:
            self.root.after(150, self.poll_events)

    def on_quit(self):
        self.manager.stop_all()
        # shutdown API on a thread so the UI cannot freeze during shutdown
        if self.api.server:
            import threading
            threading.Thread(target=self.api.stop, daemon=True).start()
        self.root.after(100, self._exit_when_stopped)

    def _exit_when_stopped(self):
        if self.manager.count():
            self.status.set("Closing browser sessions...")
            self.root.after(200, self._exit_when_stopped)
        else:
            self.root.destroy()
