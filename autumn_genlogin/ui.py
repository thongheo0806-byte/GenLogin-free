"""Tkinter desktop UI. The browser and HTTP API run off the GUI thread."""
from __future__ import annotations

from .schedule_tab import ScheduleTabMixin
from .batch_tab import BatchTabMixin

import json
import threading
from datetime import datetime, timedelta
import queue
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from uuid import uuid4
from tkinter import filedialog, messagebox, simpledialog, ttk

from .api import LocalAPI
from .batch import BatchRunner
from .qa_sync import LocalQASynchronizer
from .miniapps import MiniAppLibrary
from .miniapp_signatures import publisher_fingerprint
from .cloud_sessions import CloudSessionHandoff
from .profile_backup import export_encrypted_profile, restore_encrypted_profile
from .browser_shared import SharedBrowserManager
from .graph_ui import GraphEditor
from .scheduler import ScheduleStore, Scheduler
from .team_sync import CloudClient, safe_profile_metadata, HubError
from .diagnostics import audit_store
from .visual_workflow import WorkflowBuilder
from .models import Profile, validated_steps
from .secrets import delete_password, set_password
from .services import save_profile_with_credentials
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
        self._field(general, "Browser (installed Chrome / Edge)", "browser", choices=("chrome", "msedge", "chromium", "firefox", "webkit"))
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
        ttk.Label(proxy, text="Leave blank to keep password only if username is unchanged.\nChanging/disabling proxy clears the previous password.", foreground=MUTED).pack(anchor="w", pady=(8, 0))
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
            save_profile_with_credentials(self.parent.store, p, self.original, secret,
                                          set_secret=set_password, delete_secret=delete_password)
            self.parent.refresh()
            self.parent.notice("Saved: " + p.name)
            self.destroy()
        except Exception as exc:
            messagebox.showerror("Profile validation", str(exc), parent=self)


class App(BatchTabMixin, ScheduleTabMixin):
    def __init__(self, root: tk.Tk):
        self.root = root
        self.store = Store(reuse_connections=True)
        self.manager = SharedBrowserManager(self.store)
        self.schedule_store = ScheduleStore(self.store)
        self.scheduler = Scheduler(self.schedule_store, self.manager.start_workflow,
                                   dispatch_job=self._dispatch_scheduled_job)
        self.scheduler.start()
        self.batches = BatchRunner(self.store, self.manager)
        self.qa_sync = LocalQASynchronizer(self.manager)
        # Background tasks send only completed results to this queue.
        # No Tk widget or StringVar is touched outside the main UI thread.
        self._ui_task_results = queue.Queue()
        self._recorder_starting = set()
        self._recorder_stop_requested = set()
        self._qa_starting = False
        self._qa_stop_requested = False
        self.miniapps = MiniAppLibrary(self.store)
        self.cloud = None
        self.cloud_revision = {"profiles": 0, "workflows": 0}
        # In-memory known remote snapshots scoped by server/team/document.
        # Unknown remote revisions are never overwritten without a pull.
        self.cloud_bases = {}
        self.extensions = self.manager.extensions
        self.api = LocalAPI(self.store, self.manager, self.schedule_store, self.batches)
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
        self._ui_destroyed = False
        self._quitting = False
        self._driver_shutdown_started = False
        self._driver_shutdown_failed = False
        self._shutdown_after = None
        self._poll_after = self.root.after(150, self.poll_events)
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)
        self.root.bind("<Destroy>", self._root_destroyed, add="+")

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
        ttk.Button(top, text="Diagnostics", command=self.show_diagnostics).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="Export metadata", command=self.export_profiles).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="Import metadata", command=self.import_profiles).pack(side="right")
        ttk.Button(top, text="Encrypted backup", command=self.backup_profile).pack(side="right", padx=(10, 0))
        ttk.Button(top, text="Restore backup", command=self.restore_profile).pack(side="right", padx=(10, 0))
        tabs = ttk.Notebook(page)
        tabs.pack(fill="both", expand=True)
        profile_tab, flow_tab, batch_tab, qa_tab, miniapps_tab, extensions_tab, schedule_tab, cloud_tab, logs_tab = (ttk.Frame(tabs, padding=(0, 16)) for _ in range(9))
        tabs.add(profile_tab, text="  Profiles  ")
        tabs.add(flow_tab, text="  Automation  ")
        tabs.add(batch_tab, text="  Batch tasks  ")
        tabs.add(qa_tab, text="  Local QA sync  ")
        tabs.add(miniapps_tab, text="  Miniapps  ")
        tabs.add(extensions_tab, text="  Extensions  ")
        tabs.add(schedule_tab, text="  Scheduler  ")
        tabs.add(cloud_tab, text="  Team sync  ")
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
        self.group_combo.bind("<<ComboboxSelected>>", lambda *_: self.render_cached_profiles())
        ttk.Label(controls, text="Search", style="Muted.TLabel").pack(side="left", padx=(20, 8))
        search_input = ttk.Entry(controls, textvariable=self.search)
        search_input.pack(side="left", fill="x", expand=True)
        self._search_after = None
        self._cached_profiles = []
        self.search.trace_add("write", lambda *_: self.schedule_search())
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
        ttk.Label(flow_header, text="Workflow automation", style="Heading.TLabel").pack(side="left")
        for title, action in (("Load", self.load_workflow), ("Save", self.save_workflow),
                              ("Import image", self.import_image_template),
                              ("Record", self.start_recorder), ("Stop recording", self.stop_recorder),
                              ("Use recording", self.import_recording),
                              ("Run", self.run_workflow), ("Cancel", self.cancel_workflow)):
            ttk.Button(flow_header, text=title, command=action).pack(side="right", padx=(8, 0))
        self.flow_tabs = ttk.Notebook(flow_tab)
        self.flow_tabs.pack(fill="both", expand=True)
        visual_panel = ttk.Frame(self.flow_tabs, padding=12)
        json_panel = ttk.Frame(self.flow_tabs, padding=12)
        graph_panel = ttk.Frame(self.flow_tabs, padding=12)
        self.flow_tabs.add(visual_panel, text="  Visual step builder  ")
        self.flow_tabs.add(json_panel, text="  JSON source  ")
        self.flow_tabs.add(graph_panel, text="  Node graph  ")
        self.builder = WorkflowBuilder(visual_panel, EXAMPLE_STEPS)
        self.builder.pack(fill="both", expand=True)
        self.workflow = tk.Text(json_panel, font=("Cascadia Code", 11), bg=PANEL, fg=FG,
                                insertbackground=FG, relief="flat", undo=True, padx=17, pady=16, wrap="none")
        self.workflow.pack(fill="both", expand=True)
        self.workflow.insert("1.0", json.dumps(EXAMPLE_STEPS, indent=2, ensure_ascii=False))
        self.graph_builder = GraphEditor(graph_panel)
        self.graph_builder.pack(fill="both", expand=True)
        self.flow_tabs.bind("<<NotebookTabChanged>>", self._sync_workflow_tabs)
        # Extensions are never downloaded automatically and never executed on install.
        extension_header = ttk.Frame(extensions_tab)
        extension_header.pack(fill="x", pady=(0, 12))
        ttk.Label(extension_header, text="Locally installed Manifest V3 extensions", style="Heading.TLabel").pack(side="left")
        for title, cmd in (("Add folder", self.install_extension_folder), ("Add ZIP", self.install_extension_zip),
                           ("Update ZIP", self.update_extension_zip), ("Rollback update", self.rollback_extension_update),
                           ("Attach to selected profile", self.attach_extension), ("Detach", self.detach_extension),
                           ("Remove", self.remove_extension)):
            ttk.Button(extension_header, text=title, command=cmd).pack(side="right", padx=(7, 0))
        ttk.Label(extensions_tab, text="Only Playwright Chromium supports sideloaded extensions. Select a profile in Profiles first. Review permissions before enabling.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.extension_tree = ttk.Treeview(extensions_tab, columns=("name", "version", "permissions", "attached"), show="headings")
        for column, width in (("name", 280), ("version", 110), ("permissions", 470), ("attached", 120)):
            self.extension_tree.heading(column, text=column.title())
            self.extension_tree.column(column, width=width, stretch=column in ("name", "permissions"))
        self.extension_tree.pack(fill="both", expand=True)
        self.extension_tree.bind("<Double-1>", lambda *_: self.extension_details())
        ttk.Button(extensions_tab, text="View permissions", command=self.extension_details).pack(anchor="e", pady=(10, 0))
        self.refresh_extensions()
        self._build_schedule_tab(schedule_tab)
        self._build_batch_tab(batch_tab)
        self._build_qa_sync_tab(qa_tab)
        self._build_miniapp_tab(miniapps_tab)
        self._build_cloud_tab(cloud_tab)
        ttk.Label(logs_tab, text="Session activity", style="Heading.TLabel").pack(anchor="w", pady=(0, 14))
        self.log_widget = tk.Text(logs_tab, font=("Cascadia Code", 10), bg=PANEL, fg=FG, insertbackground=FG, relief="flat", state="disabled", padx=15, pady=15)
        self.log_widget.pack(fill="both", expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Label(bottom, textvariable=self.status, foreground=MUTED).pack(side="left")
        ttk.Label(bottom, text="DEVELOPMENT  ·  NO EXE RELEASE", foreground=ACCENT).pack(side="right")

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

    def schedule_search(self):
        if self._search_after is not None:
            self.root.after_cancel(self._search_after)
        self._search_after = self.root.after(200, self.render_cached_profiles)

    def refresh(self):
        self._cached_profiles = self.store.all()
        groups = ["All groups"] + sorted({p.group_name for p in self._cached_profiles})
        self.group_combo.configure(values=groups)
        if self.group.get() not in groups:
            self.group.set("All groups")
        self.render_cached_profiles()
        self.refresh_extensions()

    def render_cached_profiles(self):
        self._search_after = None
        old = self.selected_id(False)
        self.tree.delete(*self.tree.get_children())
        needle = self.search.get().casefold()
        for p in self._cached_profiles:
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
            self.notice("Opening selected profile...")
            self._run_ui_task(lambda: self.manager.start(pid),
                              lambda _result: self.refresh(), title="Browser error")

    def open_group(self):
        group = self.group.get()
        if group == "All groups":
            messagebox.showinfo("Choose a group", "Select one group from the Group menu first.")
            return
        def task():
            started, failed = 0, []
            for p in self.store.all():
                if p.group_name != group or self.manager.active(p.id):
                    continue
                try:
                    self.manager.start(p.id)
                    started += 1
                except Exception as exc:
                    failed.append(f"{p.name}: {type(exc).__name__}")
            return started, failed
        def finished(result):
            started, failed = result
            self.refresh()
            self.notice(f"Opened {started} profiles from {group}")
            if failed:
                messagebox.showwarning("Some profiles did not open", "\n".join(failed[:8]),
                                       parent=self.root)
        self.notice("Opening selected profile group...")
        self._run_ui_task(task, finished, title="Browser group")

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
                from .services import delete_profile_with_credentials
                leftovers, credential_warning = delete_profile_with_credentials(
                    self.store, pid, delete_secret=delete_password, clear_run=self.manager.clear_run)
                if credential_warning:
                    messagebox.showwarning("Credential cleanup", credential_warning, parent=self.root)
                self.refresh()
                self.notice("Deleted " + p.name)
                if leftovers:
                    messagebox.showwarning("Data cleanup pending", "Some deleted files could not be removed. See Diagnostics for pending cleanup.", parent=self.root)
            except Exception as exc:
                messagebox.showerror("Delete error", str(exc))

    def show_diagnostics(self):
        report = audit_store(self.store)
        lines = [f"{item['status'].upper():4}  {item['name']}: {item['detail']}"
                 for item in report["checks"]]
        summary = report["summary"]
        messagebox.showinfo("AutumnGenLogin diagnostics",
                            "\n".join(lines) + "\n\n" + str(summary), parent=self.root)
        self.notice(f"Diagnostics: {summary['failed']} failures, {summary['warnings']} warnings")

    def backup_profile(self):
        pid = self.selected_id()
        if not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Encrypted profile backup",
                                   "Close this browser profile before backing up its session.",
                                   parent=self.root)
            return
        if not messagebox.askyesno("Sensitive browser-data backup",
                                   "The encrypted backup contains browser cookies, sessions and local storage.\n"
                                   "It intentionally excludes OS vault passwords and installed extension packages.\n\n"
                                   "Keep the passphrase private. Lost passphrases cannot be recovered. Continue?",
                                   parent=self.root):
            return
        target = filedialog.asksaveasfilename(title="Save encrypted profile backup",
                        defaultextension=".aglb", filetypes=[("Autumn encrypted backup","*.aglb")])
        if not target:
            return
        secret = simpledialog.askstring("Encrypt profile",
                        "Enter a strong passphrase (12+ characters):", show="*",parent=self.root)
        if secret is None:
            return
        check = simpledialog.askstring("Confirm passphrase",
                        "Re-enter the backup passphrase:", show="*",parent=self.root)
        if secret != check:
            messagebox.showerror("Encrypted backup","Passphrases do not match.",parent=self.root)
            return
        self._run_ui_task(
            lambda:export_encrypted_profile(self.store,pid,Path(target),secret),
            lambda count:self.notice(f"Encrypted profile backup saved ({count} files)"),
            title="Encrypted backup",
        )

    def restore_profile(self):
        source = filedialog.askopenfilename(title="Restore encrypted profile backup",
                        filetypes=[("Autumn encrypted backup","*.aglb")])
        if not source:
            return
        if not messagebox.askyesno("Restore sensitive profile data",
                                   "Restore browser data as a NEW local profile?\n"
                                   "Existing profiles will not be overwritten.\n"
                                   "Proxy passwords and extension packages are NOT restored.",
                                   parent=self.root):
            return
        secret = simpledialog.askstring("Decrypt profile",
                        "Enter the backup passphrase:", show="*",parent=self.root)
        if secret is None:
            return
        def done(profile):
            self.refresh()
            self.notice("Restored encrypted profile: "+profile.name)
            messagebox.showinfo("Profile restored",
                "Restored a NEW profile. Reconfigure proxy passwords and "
                "review browser compatibility before launching it.",
                parent=self.root)
        self._run_ui_task(
            lambda:restore_encrypted_profile(self.store,Path(source),secret),
            done,title="Restore backup",
        )

    def export_profiles(self):
        path=filedialog.asksaveasfilename(
            defaultextension=".json",filetypes=[("JSON","*.json")],
            initialfile="autumn-profiles.json")
        if path:
            self._run_ui_task(
                lambda:self.store.export_metadata(Path(path)),
                lambda count:self.notice(
                    f"Exported {count} metadata records (no passwords/cookies)"),
                title="Export metadata",
            )

    def import_profiles(self):
        path=filedialog.askopenfilename(filetypes=[("JSON","*.json")])
        if path:
            def done(count):
                self.refresh()
                self.notice(
                    f"Imported {count} profiles (fresh IDs and empty sessions)")
            self._run_ui_task(
                lambda:self.store.import_metadata(Path(path)),
                done,title="Import metadata",
            )

    def _sync_workflow_tabs(self, _event=None):
        # Switching back after invalid JSON emits a second Tk event: guard it
        # so the invalid work-in-progress is never overwritten by stale steps.
        if getattr(self, "_ignore_next_workflow_tab_event", False):
            # Tk dispatches the programmatic select event asynchronously.
            self._ignore_next_workflow_tab_event = False
            return
        if getattr(self, "_syncing_workflow", False) or self.flow_tabs.index("current") == 2:
            return
        self._syncing_workflow = True
        try:
            if self.flow_tabs.index("current") == 0:
                try:
                    self.builder.set_steps(validated_steps(json.loads(self.workflow.get("1.0", "end"))))
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    messagebox.showerror("Invalid JSON workflow", str(exc), parent=self.root)
                    self._ignore_next_workflow_tab_event = True
                    self.flow_tabs.select(1)
            else:
                steps = self.builder.get_steps() if self.builder._steps else []
                self.workflow.delete("1.0", "end")
                self.workflow.insert("1.0", json.dumps(steps, indent=2, ensure_ascii=False))
        finally:
            self._syncing_workflow = False

    def current_steps(self):
        if self.flow_tabs.index("current") == 0:
            return self.builder.get_steps()
        if self.flow_tabs.index("current") == 2:
            return self.graph_builder.get_graph()
        return validated_steps(json.loads(self.workflow.get("1.0", "end")))

    def import_image_template(self):
        path = filedialog.askopenfilename(title="Import distinctive image-click template",
                filetypes=[("PNG image", "*.png")])
        if not path:
            return
        if not messagebox.askyesno("Local image template",
                "Import this PNG for local viewport matching?\n"
                "Screenshots and the template remain on this computer.\n"
                "Avoid pictures containing passwords or personal information.\n"
                "Only a unique, high-confidence match may be clicked.",
                parent=self.root):
            return
        try:
            ident = self.manager.image_templates.import_png(Path(path))
            self.root.clipboard_clear()
            self.root.clipboard_append(ident)
            self.notice("Image template imported; SHA-256 ID copied to clipboard.")
            messagebox.showinfo("Image click template",
                "Template ID copied to clipboard.\n"
                "Add the 'click_image' action and paste it as template_id.\n"
                "Set confidence to 0.94. The target must be visible in the viewport.",
                parent=self.root)
        except Exception as exc:
            messagebox.showerror("Image template", str(exc), parent=self.root)

    def run_workflow(self):
        pid = self.selected_id()
        if pid:
            try:
                workflow = self.current_steps()
                if isinstance(workflow, dict): self.manager.run_graph(pid, workflow)
                else: self.manager.run_steps(pid, workflow)
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
                data = json.loads(source)
                if isinstance(data, dict):
                    self.graph_builder.set_graph(data)
                    self.flow_tabs.select(2)
                    self.notice("Loaded graph workflow")
                    return
                validated_steps(data)
                self.workflow.delete("1.0", "end")
                self.workflow.insert("1.0", source)
                self.builder.set_steps(validated_steps(data))
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

    def start_recorder(self):
        pid = self.selected_id()
        if not pid or pid in self._recorder_starting:
            return
        self._recorder_starting.add(pid)
        self.notice("Installing recorder for selected profile...")

        def done(_result):
            self._recorder_starting.discard(pid)
            if pid in self._recorder_stop_requested:
                self._recorder_stop_requested.discard(pid)
                self.manager.stop_recording(pid)
                self.notice("Recorder stopped (stop requested during startup)")
            else:
                self.notice("Recorder active for selected browser only; input values and page URLs are never captured.")

        def failed(message):
            self._recorder_starting.discard(pid)
            self._recorder_stop_requested.discard(pid)
            messagebox.showerror("Recorder", message, parent=self.root)
        self._run_ui_task(lambda: self.manager.start_recording(pid), done,
                          title="Recorder", failed=failed)

    def stop_recorder(self):
        pid = self.selected_id()
        if pid:
            if pid in self._recorder_starting:
                self._recorder_stop_requested.add(pid)
                self.notice("Recorder stop queued until startup completes")
                return
            self.manager.stop_recording(pid)
            self.notice("Recorder stopped; import the captured actions before closing the profile")

    def import_recording(self):
        pid = self.selected_id()
        if not pid: return
        report = self.manager.recording_review(pid)
        if report and report.get("still_recording"):
            messagebox.showwarning("Recorder",
                "Stop the selected-tab recording before reviewing or importing its steps.",
                parent=self.root)
            return
        steps = self.manager.recorded_steps(pid)
        if not steps:
            messagebox.showinfo("Recorder", "No actions recorded. Open a profile and click Record first.", parent=self.root)
            return
        try:
            report = self.manager.recording_review(pid)
            if not report:
                raise ValueError("No browser recording available")
            warnings = "\n".join("• " + line for line in report["warnings"])
            details = (f"Actions: {report['step_count']}\n"
                       f"Redacted form fields: {report['redacted_fields']}\n"
                       f"Observed page loads (no URLs retained): {report['navigation_boundaries']}\n"
                       f"Other tabs ignored: {report['ignored_tabs']}\n\n"
                       + warnings + "\n\nImport as an EDITABLE draft?")
            if not messagebox.askyesno("Review recorded actions before replay",
                                       details, parent=self.root):
                return
            self.builder.set_steps(steps)
            self.flow_tabs.select(0)
            self.notice(f"Imported {len(steps)} reviewed structural steps; verify placeholders before replay")
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Recorder", str(exc), parent=self.root)

    def _build_miniapp_tab(self, frame):
        ttk.Label(frame,text="Reviewed local Miniapps (JSON workflows, never executable packages)",
                  style="Heading.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Label(frame,text="Import local JSON templates, including signed packages with separately "
                  "trusted Ed25519 keys. Preview permissions, then load a reviewed EDITABLE draft.\n"
                  "A signature proves key continuity, NOT publisher identity. No marketplace or auto-run.",
                  style="Muted.TLabel").pack(anchor="w",pady=(0,14))
        actions=ttk.Frame(frame)
        actions.pack(fill="x",pady=(0,10))
        for title,command in (("Import JSON",self.import_miniapp),
                              ("Preview",self.preview_miniapp),
                              ("Load draft",self.load_miniapp),
                              ("Remove",self.remove_miniapp)):
            ttk.Button(actions,text=title,command=command).pack(side="left",padx=(0,8))
        publisher_row=ttk.Frame(frame)
        publisher_row.pack(fill="x",pady=(0,9))
        for title,handler in (("Trust publisher key",self.trust_miniapp_publisher),
                              ("List trusted keys",self.list_miniapp_publishers),
                              ("Untrust publisher key",self.untrust_miniapp_publisher)):
            ttk.Button(publisher_row,text=title,command=handler).pack(side="left",padx=(0,8))
        self.miniapp_tree=ttk.Treeview(frame,
                columns=("name","version","category","steps","trust","origins"),
                show="headings",selectmode="browse")
        for key,title,width in (("name","Miniapp",190),("version","Version",85),
                                ("category","Category",115),("steps","Steps",65),
                                ("trust","Signature",115),
                                ("origins","Navigation origins",340)):
            self.miniapp_tree.heading(key,text=title)
            self.miniapp_tree.column(key,width=width,stretch=key in {"name","origins"})
        self.miniapp_tree.pack(fill="both",expand=True)
        self.miniapp_tree.bind("<Double-1>",lambda *_:self.preview_miniapp())
        self.refresh_miniapps()

    def trust_miniapp_publisher(self):
        label=simpledialog.askstring("Trust Miniapp signing key",
            "Enter a local label for this publisher key:",parent=self.root)
        if not label:
            return
        pub=simpledialog.askstring("Publisher Ed25519 public key",
            "Paste the 32-byte Ed25519 public key as canonical base64.\n"
            "Never paste a private key or secret.",parent=self.root)
        if not pub:
            return
        try:
            fingerprint=publisher_fingerprint(pub.strip())
            if not messagebox.askyesno("Verify publisher fingerprint OUT OF BAND",
                "This key will be TRUSTED to sign Miniapps on this machine.\n"
                "Signing only proves the holder of the private key; it does "
                "NOT prove a real organization or guarantee a safe workflow.\n\n"
                f"SHA-256 fingerprint:\n{fingerprint}\n\n"
                "Compare this fingerprint with a separately verified "
                "publisher source before trusting. Confirm?",
                parent=self.root):
                return
            self.miniapps.trust_publisher(label,pub.strip())
            self.notice("Trusted Miniapp signing key: "+fingerprint[:16])
        except Exception as exc:
            messagebox.showerror("Miniapp key",str(exc),parent=self.root)

    def list_miniapp_publishers(self):
        rows=self.miniapps.list_publishers()
        messagebox.showinfo("Locally trusted Miniapp public keys",
            "\n".join(f"{x['label']}: {x['fingerprint']}" for x in rows)
            if rows else "No publisher keys trusted.",
            parent=self.root)

    def untrust_miniapp_publisher(self):
        fingerprint=simpledialog.askstring("Untrust publisher",
            "Paste the full 64-character SHA-256 fingerprint of the key:",
            parent=self.root)
        if not fingerprint:
            return
        if not messagebox.askyesno("Revoke LOCAL Miniapp key trust",
            "Remove this key from the local trust list?\n"
            "Installed packages will remain visible but their signature "
            "status becomes 'untrusted' and they cannot load as drafts.\n"
            "This does not revoke signed files already shared elsewhere.",
            parent=self.root):
            return
        try:
            self.miniapps.untrust_publisher(fingerprint.strip())
            self.refresh_miniapps()
            self.notice("Local Miniapp signing-key trust removed")
        except Exception as exc:
            messagebox.showerror("Untrust publisher",str(exc),parent=self.root)

    def refresh_miniapps(self):
        if not hasattr(self,"miniapp_tree"):
            return
        self.miniapp_tree.delete(*self.miniapp_tree.get_children())
        for record in self.miniapps.list():
            self.miniapp_tree.insert("","end",iid=record.id,
                values=(record.name,record.version,record.category,
                        record.steps,record.signature_status,
                        ", ".join(record.origins) or "(current page)"))

    def selected_miniapp(self):
        selection=self.miniapp_tree.selection()
        if not selection:
            messagebox.showinfo("Miniapps","Select an installed miniapp first.",parent=self.root)
            return None
        return selection[0]

    def import_miniapp(self):
        path=filedialog.askopenfilename(title="Import local reviewed miniapp",
                       filetypes=[("Miniapp JSON","*.json")])
        if not path:
            return
        if not messagebox.askyesno("Untrusted workflow warning",
                "Only import JSON miniapps from trusted sources. Imported steps "
                "may navigate or click webpages after you explicitly load and run them.\n"
                "No code or script will be executed on import. Continue?",
                parent=self.root):
            return
        try:
            record=self.miniapps.install_json(Path(path))
            self.refresh_miniapps()
            self.notice(f"Imported local miniapp: {record.name} v{record.version} "
                        f"[{record.signature_status}]")
        except Exception as exc:
            messagebox.showerror("Miniapp import",str(exc),parent=self.root)

    def preview_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            doc=self.miniapps.get(ident)
            origins=sorted({s["url"].split("/",3)[0]+"//"+s["url"].split("/",3)[2]
                            for s in doc["workflow"] if s["action"]=="goto"})
            actions=", ".join(x["action"] for x in doc["workflow"])
            messagebox.showinfo("Miniapp preview",
                f"{doc['name']} v{doc['version']} ({doc['category']})\n"
                f"{doc['description']}\n\n"
                f"Signature: {record.signature_status}\n"
                f"Publisher key fingerprint: {record.publisher_fingerprint or '(none)'}\n"
                f"Navigation origins: {', '.join(origins) or '(current page)'}\n"
                f"Steps: {len(doc['workflow'])}\nActions: {actions[:750]}\n\n"
                "The miniapp will never run automatically.",
                parent=self.root)
        except Exception as exc:
            messagebox.showerror("Miniapp preview",str(exc),parent=self.root)

    def load_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            if record.signature_status=="untrusted":
                raise ValueError("Previously trusted signing key was removed. "
                                 "Re-establish trust out of band before loading.")
            preview=", ".join(record.origins) or "(currently open webpage)"
            if not messagebox.askyesno("Load miniapp draft",
                 f"Load '{record.name}' v{record.version} as a new editable workflow draft?\n\n"
                 f"Navigation origins: {preview}\nSteps: {record.steps}\n"
                 f"Signature: {record.signature_status}\n"
                 f"Publisher fingerprint: {record.publisher_fingerprint or '(none)'}\n\n"
                 "Unsigned packages do NOT verify publisher identity. "
                 "Review clicks, input placeholders and page permissions before running. "
                 "Your current workflow editor contents will be replaced.",
                 parent=self.root):
                return
            doc=self.miniapps.get(ident)
            self.builder.set_steps(doc["workflow"])
            self.flow_tabs.select(0)
            self.notice(f"Loaded miniapp draft: {record.name}; not executed")
        except Exception as exc:
            messagebox.showerror("Miniapp load",str(exc),parent=self.root)

    def remove_miniapp(self):
        ident=self.selected_miniapp()
        if not ident:
            return
        try:
            record=self.miniapps._record(ident)
            if messagebox.askyesno("Remove miniapp",
                    f"Remove local template '{record.name}' v{record.version}? "
                    "Existing exported workflow files are unaffected.",parent=self.root):
                self.miniapps.remove(ident)
                self.refresh_miniapps()
                self.notice("Local miniapp template removed")
        except Exception as exc:
            messagebox.showerror("Remove miniapp",str(exc),parent=self.root)

    def _build_qa_sync_tab(self, frame):
        ttk.Label(frame,text="Local test-only click synchronizer",
                  style="Heading.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Label(frame,text="Experimental local QA: clicks on specially marked "
                  "buttons are mirrored across matching tabs and local QA iframes "
                  "from one open master to up to five followers.\n"
                  "Only the SAME http://127.0.0.1:port test origin is allowed. "
                  "No logins, real websites, field values, cookies or keyboard copying.",
                  style="Muted.TLabel").pack(anchor="w",pady=(0,14))
        row=ttk.Frame(frame)
        row.pack(fill="x",pady=(0,10))
        ttk.Button(row,text="Start local QA click sync",style="Accent.TButton",
                   command=self.start_qa_sync).pack(side="left",padx=(0,10))
        ttk.Button(row,text="Stop QA sync",command=self.stop_qa_sync).pack(side="left",padx=(0,10))
        ttk.Button(row,text="Refresh sync status",command=self.refresh_qa_sync).pack(side="left")
        self.qa_sync_label=tk.StringVar(value="QA sync is OFF")
        ttk.Label(frame,textvariable=self.qa_sync_label).pack(anchor="w",pady=12)

    def start_qa_sync(self):
        pid=self.selected_id()
        if not pid or self._qa_starting:
            return
        try:
            if not self.manager.active(pid):
                raise ValueError("Open the master QA profile first")
            master=self.store.get(pid)
            followers=[p.id for p in self.store.all()
                       if p.group_name==master.group_name and p.id!=pid
                       and self.manager.active(p.id)]
            if not 1 <= len(followers) <= 5:
                raise ValueError("Open 1-5 other QA profiles in the same group first")
            if not messagebox.askyesno("Enable LOCAL QA mirror",
                    f"Mirror marked-button clicks from {master.name} to "
                    f"{len(followers)} other open QA profiles?\n\n"
                    "All pages must be on the SAME local test origin "
                    "(http://127.0.0.1:port).\n"
                    "No website logins, personal accounts or passwords. Continue?",
                    parent=self.root):
                return
            self._qa_starting=True
            self.qa_sync_label.set("Starting QA sync (checking profile readiness)...")
            def done(state):
                self._qa_starting=False
                if self._qa_stop_requested:
                    self._qa_stop_requested=False
                    self.stop_qa_sync()
                    return
                self.qa_sync_label.set(f"QA sync on: {len(followers)} followers at {state['origin']}")
                self.notice("Experimental local QA click sync started")
            def failed(message):
                self._qa_starting=False
                self._qa_stop_requested=False
                self.qa_sync_label.set("QA sync is OFF")
                messagebox.showerror("QA synchronizer",message,parent=self.root)
            self._run_ui_task(lambda:self.qa_sync.start(pid,followers),
                              done,title="QA synchronizer",failed=failed)
        except Exception as exc:
            messagebox.showerror("QA synchronizer",str(exc),parent=self.root)

    def stop_qa_sync(self):
        if self._qa_starting:
            self._qa_stop_requested=True
            self.qa_sync_label.set("QA sync stop queued until startup completes")
            return
        self.qa_sync_label.set("Stopping QA sync...")
        self._run_ui_task(
            self.qa_sync.stop,
            lambda _state:(self.qa_sync_label.set("QA sync is OFF"),
                           self.notice("QA click sync stopped")),
            title="QA synchronizer",
        )

    def refresh_qa_sync(self):
        def done(state):
            if not state["active"]:
                self.qa_sync_label.set("QA sync is OFF")
            else:
                self.qa_sync_label.set(
                    f"QA sync: {state['mirrored_clicks']} master clicks, "
                    f"{state['delivered_clicks']} follower deliveries, "
                    f"{state['failed_clicks']} failures; local {state['origin']}")
        self._run_ui_task(self.qa_sync.status,done,title="QA synchronizer")

    def _build_cloud_tab(self,frame):
        ttk.Label(frame, text="Opt-in encrypted team sync and manual archive handoff",style="Heading.TLabel").pack(anchor="w", pady=8)
        ttk.Label(frame, text="Requires self-hosted server (python main.py --hub), HTTPS for remote access.\n"
                  "Metadata/workflows exclude sessions; sensitive encrypted .aglb session backup upload "
                  "is OPTIONAL and must be explicitly confirmed. Never sync open browser state.",
                  style="Muted.TLabel").pack(anchor="w",pady=8)
        self.cloud_fields={}
        for title,name,default,secret in (("Server URL","url","http://127.0.0.1:8899",False),
                    ("User","username","",False),("Password","password","",True),
                    ("Team ID","team_id","",False),("Shared encryption passphrase","passphrase","",True)):
            box=ttk.Frame(frame);box.pack(fill="x",pady=4)
            ttk.Label(box,text=title,width=28).pack(side="left")
            var=tk.StringVar(value=default)
            ttk.Entry(box,textvariable=var,show="*" if secret else "",width=60).pack(side="left",fill="x",expand=True)
            self.cloud_fields[name]=var
        row=ttk.Frame(frame);row.pack(fill="x",pady=12)
        for title,action in (("Register",self.cloud_register),("Login",self.cloud_login),
                             ("Create team",self.cloud_create_team),("Invite member",self.cloud_invite),
                             ("Push metadata",lambda:self.cloud_sync("profiles","push")),
                             ("Pull metadata",lambda:self.cloud_sync("profiles","pull")),
                             ("Push workflow",lambda:self.cloud_sync("workflows","push")),
                             ("Pull workflow",lambda:self.cloud_sync("workflows","pull"))):
            ttk.Button(row,text=title,command=action).pack(side="left",padx=3)
        archive_row=ttk.Frame(frame)
        archive_row.pack(fill="x",pady=(5,8))
        ttk.Button(archive_row,text="Upload encrypted session backup",
                   command=self.cloud_upload_session).pack(side="left",padx=(0,9))
        ttk.Button(archive_row,text="Download encrypted session backup",
                   command=self.cloud_download_session).pack(side="left",padx=(0,9))
        ttk.Button(archive_row,text="Revoke team archive",
                   command=self.cloud_revoke_session).pack(side="left")
        archive_tools=ttk.Frame(frame)
        archive_tools.pack(fill="x",pady=(1,8))
        ttk.Button(archive_tools,text="Resume interrupted encrypted backup upload",
                   command=self.cloud_resume_upload_session).pack(side="left",padx=(0,12))
        ttk.Button(archive_tools,text="List team archives (admin)",
                   command=self.cloud_list_sessions).pack(side="left")
        self.cloud_status=tk.StringVar(value="Not signed in")
        ttk.Label(frame,textvariable=self.cloud_status).pack(anchor="w")
        ttk.Label(frame,text="Remote team roles: owner, admin, editor, viewer. Push uses revision checks to reject conflicts.",style="Muted.TLabel").pack(anchor="w",pady=8)

    def _cloud_action(self,fn,finished=None):
        # Tk widgets and after() must never be touched from a network worker.
        # Reuse the queue drained exclusively on the GUI main thread.
        self._run_ui_task(
            fn,
            finished or (lambda _:self.cloud_status.set("Success")),
            title="Team sync",
            failed=lambda message:messagebox.showerror(
                "Team sync",message,parent=self.root),
        )

    def cloud_upload_session(self):
        # Preassign an ID so a failed upload can be resumed after restart.
        self._cloud_upload_session(str(uuid4()),resuming=False)

    def cloud_resume_upload_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Resume encrypted backup upload",
            "Enter the original 36-character handoff ID.\n"
            "You must select EXACTLY the same encrypted .aglb file and "
            "use the same TEAM passphrase.\n"
            "A mismatch will be rejected, never overwritten.",parent=self.root)
        if ident:
            self._cloud_upload_session(ident.strip(),resuming=True)

    def _cloud_upload_session(self,ident,resuming=False):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        source=filedialog.askopenfilename(title="Select the already encrypted .aglb backup",
                   filetypes=[("Autumn encrypted backup","*.aglb")])
        if not source:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Session backup",
                "Enter a strong shared TEAM encryption passphrase.",parent=self.root)
        warning=("RESUME a previously interrupted transfer" if resuming
                 else "UPLOAD a sensitive encrypted browser session")
        if not messagebox.askyesno(warning,
                "You are sharing an encrypted archive containing cookies, "
                "saved sessions and local storage.\n\n"
                "The backup is already encrypted with its own archive password "
                "and will be encrypted again with the TEAM password.\n"
                "Members with both passwords and access can restore it.\n\n"
                f"Transfer ID: {ident}\n"
                "Copy this ID before starting so you can resume if interrupted.\n"
                "Use only a backup from a STOPPED profile. Continue?",
                parent=self.root):
            return
        # The ID must be available BEFORE the background worker sends data.
        # Clipboard contains only random UUID, never credentials or a password.
        self.root.clipboard_clear()
        self.root.clipboard_append(ident)
        self.cloud_status.set("Encrypted transfer ID copied (keep for retries): "+ident)

        def task():
            return CloudSessionHandoff(self.cloud).upload(
                team_id,Path(source),passphrase,session_id=ident)
        def finished(actual_id):
            self.cloud_status.set("Encrypted archive published: "+actual_id)
            messagebox.showinfo("Encrypted backup uploaded",
                "The encrypted backup was published to the team.\n"
                "Transfer UUID: "+actual_id+"\n\n"
                "This was a manual file handoff, not live session sync.\n"
                "You may retry a completed transfer with the same file: "
                "the server's contents will be verified but NOT overwritten.",
                parent=self.root)
        self._cloud_action(task,finished)

    def cloud_download_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Encrypted session handoff",
                 "Paste the 36-character archive transfer UUID:",parent=self.root)
        if not ident:
            return
        dest=filedialog.asksaveasfilename(title="Save encrypted backup only",
                defaultextension=".aglb",filetypes=[("Autumn encrypted backup","*.aglb")])
        if not dest:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Session backup","Enter the TEAM encryption passphrase.",
                                        parent=self.root)
        if not messagebox.askyesno("Download sensitive encrypted backup",
                "Download this encrypted session backup to a NEW local file?\n"
                "It will NOT be decrypted or automatically installed.\n"
                "Restore manually through 'Restore backup' using the original "
                "archive passphrase only after reviewing the file.",
                parent=self.root):
            return
        def task():
            return CloudSessionHandoff(self.cloud).download(
                team_id,ident,Path(dest),passphrase)
        def finished(size):
            self.cloud_status.set(f"Encrypted backup downloaded ({size} bytes); not restored")
            messagebox.showinfo("Encrypted archive downloaded",
                "Only encrypted .aglb bytes were saved.\n"
                "Use Restore backup separately with the original archive passphrase "
                "to create a NEW local profile. No existing profile is overwritten.",
                parent=self.root)
        self._cloud_action(task,finished)

    def cloud_list_sessions(self):
        """Let owners/admins discover orphan handoffs and copy revocation IDs."""
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        team_id=self.cloud_fields["team_id"].get().strip()

        def show(items):
            popup=tk.Toplevel(self.root)
            popup.title("Encrypted team archives (owner/admin)")
            popup.geometry("880x410")
            popup.transient(self.root)
            columns=("uuid","state","documents","bytes","uploaders")
            table=ttk.Treeview(popup,columns=columns,show="headings",selectmode="browse")
            for field,heading,width in (
                ("uuid","Archive UUID",315),("state","State",90),
                ("documents","Documents",90),("bytes","Stored bytes",110),
                ("uploaders","Uploaders",220)
            ):
                table.heading(field,text=heading)
                table.column(field,width=width,stretch=(field=="uploaders"))
            table.pack(fill="both",expand=True,padx=8,pady=8)
            for item in items:
                table.insert("", "end",values=(
                    item["session_id"],
                    "Complete" if item["has_manifest"] else "Partial",
                    item["documents"],item["stored_bytes"],
                    ", ".join(item["uploaders"]) or "Legacy / unknown"
                ))
            def copy_uuid():
                selected=table.selection()
                if not selected:
                    return
                ident=table.item(selected[0],"values")[0]
                self.root.clipboard_clear()
                self.root.clipboard_append(ident)
                self.cloud_status.set("Archive UUID copied for download or revocation")
            ttk.Button(popup,text="Copy selected archive UUID",
                       command=copy_uuid).pack(anchor="w",padx=8,pady=(0,8))
            self.cloud_status.set(f"Admin archive listing: {len(items)} handoff IDs")

        self._cloud_action(lambda:self.cloud.list_sessions(team_id),show)

    def cloud_revoke_session(self):
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        ident=simpledialog.askstring("Revoke published encrypted session",
                 "Paste the archived handoff UUID to revoke:",parent=self.root)
        if not ident:
            return
        team_id=self.cloud_fields["team_id"].get().strip()
        if not messagebox.askyesno("PERMANENT encrypted archive revocation",
                "Only a team OWNER or ADMIN can revoke this encrypted archive.\n\n"
                "The Hub will permanently remove its encrypted parts and "
                "manifest and refuse publishing under this UUID again.\n"
                "This action cannot be undone.\n\n"
                "IMPORTANT: copies previously downloaded by other members "
                "CANNOT be recovered or deleted remotely. Continue?",
                parent=self.root):
            return
        def done(result):
            deleted=result["deleted_documents"]
            self.cloud_status.set(
                f"Archive revoked on hub; {deleted} encrypted documents removed")
            messagebox.showinfo("Hub archive revoked",
                f"The Hub deleted {deleted} encrypted documents and blocked "
                "this handoff ID from being reused.\n\n"
                "Previously downloaded files are NOT revoked.",
                parent=self.root)
        self._cloud_action(lambda:self.cloud.revoke_session(team_id,ident),done)

    def cloud_register(self):
        values={k:v.get() for k,v in self.cloud_fields.items()}
        def task():
            return CloudClient(values["url"]).register(values["username"],values["password"])
        self._cloud_action(task,lambda _:self.cloud_status.set("User registered; log in next"))

    def cloud_login(self):
        values={k:v.get() for k,v in self.cloud_fields.items()}
        def task():
            client=CloudClient(values["url"])
            client.login(values["username"],values["password"])
            return client
        def done(client):
            self.cloud=client
            self.cloud_revision={"profiles":0,"workflows":0}
            # A new sign-in is not proof the same principal owns old baselines.
            # Require a newly approved pull before any subsequent merge.
            self.cloud_bases.clear()
            self.cloud_fields["password"].set("")
            self.cloud_status.set("Authenticated · token kept in memory")
        self._cloud_action(task,done)

    def cloud_create_team(self):
        if not self.cloud:return messagebox.showinfo("Team sync","Log in first")
        self._cloud_action(lambda:self.cloud.create_team("Autumn team"),
            lambda ident:(self.cloud_fields["team_id"].set(ident),self.cloud_status.set("Team created: "+ident)))

    def cloud_invite(self):
        if not self.cloud:return messagebox.showinfo("Team sync","Log in first")
        username=simpledialog.askstring("Add team member","Existing username",parent=self.root)
        if not username:return
        role=simpledialog.askstring("Team role","viewer, editor or admin",parent=self.root)
        if role not in {"viewer","editor","admin"}:return
        team_id=self.cloud_fields["team_id"].get()
        self._cloud_action(lambda:self.cloud.set_member(team_id,username,role),
                           lambda _:self.cloud_status.set(f"Added {username} as {role}"))

    def cloud_sync(self,name,direction):
        from copy import deepcopy
        from .cloud_merge import merge_cloud_documents
        if not self.cloud:
            return messagebox.showinfo("Team sync","Log in first",parent=self.root)
        client=self.cloud
        team_id=self.cloud_fields["team_id"].get().strip()
        passphrase=self.cloud_fields["passphrase"].get()
        if len(passphrase)<12:
            return messagebox.showerror("Sync","Use a passphrase of at least 12 characters",parent=self.root)
        scope=(client.url,team_id,name)
        if direction=="push":
            try:
                # Profile catalog snapshots can wait on SQLite; take them
                # on the sync worker rather than freezing the Tk thread.
                doc=(None if name=="profiles"
                     else {"format":"AutumnGenLogin/workflow-1",
                           "workflow":self.current_steps()})
            except Exception as exc:
                return messagebox.showerror("Sync",type(exc).__name__,parent=self.root)
            if not messagebox.askyesno(
                "Encrypted sync","Review the local document before upload. "
                "Server changes will be checked and never silently overwritten. Continue?",
                parent=self.root
            ):
                return
            baseline=self.cloud_bases.get(scope)
            expected_rev,base_doc=(baseline if baseline else (None,None))
            def inspect():
                local_doc=safe_profile_metadata(self.store) if name=="profiles" else doc
                remote_rev,remote_doc=client.pull(team_id,name,passphrase)
                if expected_rev is not None and (
                    remote_rev < expected_rev or
                    (remote_rev==expected_rev and remote_doc!=base_doc)
                ):
                    return {"conflicts":("remote-revision-regressed",)}
                merged,conflicts=merge_cloud_documents(
                    name,base_doc,local_doc,remote_doc)
                if conflicts:
                    return {"conflicts":conflicts}
                return {"revision":remote_rev,"remote":remote_doc,
                        "merged":merged,"local":local_doc,
                        "needs_review":remote_doc is not None and
                                        remote_doc!=base_doc}
            def inspected(state):
                if state.get("conflicts"):
                    self.cloud_status.set("Conflict: no upload; review remote document first")
                    messagebox.showwarning(
                        "Cloud revision conflict",
                        f"Upload blocked: {len(state['conflicts'])} conflicting location(s). "
                        "Pull and inspect the remote revision before resolving; "
                        "no data was overwritten.",
                        parent=self.root)
                    return
                merged=state["merged"]
                if state["remote"]==merged:
                    self.cloud_status.set(
                        "Remote revision already contains the proposed document. "
                        "Pull to update local data.")
                    return
                if state["needs_review"] and not messagebox.askyesno(
                    "Review three-way merge",
                    "The server changed since your last approved pull. "
                    "A structural three-way merge found no overlapping conflicts. "
                    "Upload the merged metadata now? "
                    "Afterward, pull the merged result to update your local copy.",
                    parent=self.root
                ):
                    self.cloud_status.set("Merge cancelled: nothing uploaded")
                    return
                def submit():
                    # A concurrent local edit after the preview also must not
                    # publish an obsolete profile snapshot under user consent.
                    if name=="profiles" and safe_profile_metadata(self.store)!=state["local"]:
                        raise ValueError("Local profiles changed since upload preview; review again")
                    # Server-side optimistic CAS protects against another
                    # writer racing between preview and this upload.
                    return client.push(team_id,name,state["revision"],merged,passphrase)
                def submitted(revision):
                    if state["needs_review"]:
                        self.cloud_bases.pop(scope,None)
                        self.cloud_status.set(
                            f"Merge uploaded at revision {revision}. Pull before next push.")
                    else:
                        self.cloud_bases[scope]=(revision,deepcopy(merged))
                        self.cloud_status.set(f"Uploaded {name} revision {revision}")
                self._cloud_action(submit,submitted)
            self._cloud_action(inspect,inspected)
        else:
            # Capture the baseline on the Tk owner thread, then perform ALL
            # network, SQLite and merge computation in the background.
            prior=deepcopy(self.cloud_bases.get(scope))
            def task():
                revision,doc=client.pull(team_id,name,passphrase)
                state={"revision":revision,"doc":doc}
                if not doc or name!="profiles":
                    return state
                from .cloud_merge import prepare_cloud_profile_pull
                if prior is not None and (revision<prior[0] or
                        (revision==prior[0] and doc!=prior[1])):
                    return {**state,"conflicts":("remote-revision-regressed",)}
                local_doc=safe_profile_metadata(self.store)
                merged,conflicts=prepare_cloud_profile_pull(
                    local_doc,doc,prior[1] if prior else None)
                state["conflicts"]=conflicts
                if conflicts:
                    return state
                before={item["id"]:item for item in local_doc["profiles"]}
                changes=[item for item in merged["profiles"]
                         if before.get(item["id"])!=item]
                state["expected_local"]=local_doc
                state["pending"]={"format":merged["format"],"profiles":changes}
                return state

            def done(state):
                # Discard replies from a login or team no longer displayed.
                if (self.cloud is not client or
                        self.cloud_fields["team_id"].get().strip()!=team_id or
                        self.cloud_bases.get(scope)!=prior):
                    self.cloud_status.set("Cloud context changed; repeat the Pull review")
                    return
                revision,doc=state["revision"],state["doc"]
                if not doc:
                    return self.cloud_status.set("No remote document")
                if state.get("conflicts"):
                    self.cloud_status.set(
                        f"Pull blocked: {len(state['conflicts'])} local/remote metadata conflict(s)")
                    return messagebox.showwarning(
                        "Cloud pull needs conflict resolution",
                        f"Found {len(state['conflicts'])} overlapping or unverified field(s). "
                        "No local profiles were modified. Review and reconcile "
                        "the same profile ID on both sides before retrying.",
                        parent=self.root)
                if name=="profiles":
                    pending=state["pending"]
                    summary=(f"Apply {len(pending['profiles'])} new/updated safe "
                             "profile metadata record(s)? Local-only records "
                             "and proxy/vault credentials will be preserved. "
                             "Conflicting local edits were not overwritten.")
                else:
                    summary=(f"Import encrypted {name} revision {revision} into local data? "
                             "This establishes a baseline for future conflict detection.")
                if not messagebox.askyesno("Cloud preview",summary,parent=self.root):
                    return

                def accepted():
                    if self.cloud is not client or self.cloud_bases.get(scope)!=prior:
                        self.cloud_status.set("Cloud context changed; repeat Pull")
                        return
                    self.cloud_bases[scope]=(revision,deepcopy(doc))
                    self.cloud_revision[name]=revision

                if name=="profiles":
                    from .team_sync import merge_safe_profiles
                    def apply():
                        return merge_safe_profiles(
                            self.store,state["pending"],
                            active=self.manager.active,
                            expected_local=state["expected_local"])
                    def applied(count):
                        self.refresh()
                        self.cloud_status.set(
                            f"Reconciled {count} changed profile metadata rows; "
                            "local-only profiles preserved")
                        accepted()
                    # SQLite BEGIN IMMEDIATE and save now execute on a
                    # thread-affine worker, never inside a Tk callback.
                    self._cloud_action(apply,applied)
                else:
                    try:
                        if doc.get("format")!="AutumnGenLogin/workflow-1":
                            raise ValueError("Wrong workflow format")
                        flow=doc["workflow"]
                        if isinstance(flow,dict):
                            self.graph_builder.set_graph(flow)
                            self.flow_tabs.select(2)
                        else:
                            self.builder.set_steps(validated_steps(flow))
                            self.flow_tabs.select(0)
                        self.cloud_status.set("Downloaded workflow")
                        accepted()
                    except Exception as exc:
                        self.cloud_status.set("Pull failed: no baseline was updated")
                        messagebox.showerror("Team sync",type(exc).__name__,parent=self.root)
            self._cloud_action(task,done)

    def refresh_extensions(self):
        if not hasattr(self, "extension_tree"):
            return
        self.extension_tree.delete(*self.extension_tree.get_children())
        profile_id = self.selected_id(False) if hasattr(self, "tree") else None
        attached = set(self.extensions.attached_ids(profile_id)) if profile_id else set()
        for item in self.extensions.list():
            permissions = ", ".join([*item.permissions, *item.host_permissions])
            self.extension_tree.insert("", "end", iid=item.id,
                                       values=(item.name, item.version, permissions[:150], "Yes" if item.id in attached else "No"))

    def selected_extension(self):
        selection = self.extension_tree.selection()
        if not selection:
            messagebox.showinfo("Extensions", "Select an extension first", parent=self.root)
            return None
        return next((e for e in self.extensions.list() if e.id == selection[0]), None)

    def install_extension_folder(self):
        source = filedialog.askdirectory(title="Choose an unpacked Manifest V3 extension")
        if source:
            self._install_extension(Path(source), archive=False)

    def install_extension_zip(self):
        source = filedialog.askopenfilename(title="Choose a Manifest V3 extension archive", filetypes=[("ZIP", "*.zip")])
        if source:
            self._install_extension(Path(source), archive=True)

    def _install_extension(self, path: Path, archive: bool):
        if not messagebox.askyesno("Untrusted extension warning",
                                   "Browser extensions can read and modify web pages, including private data.\n"
                                   "Only install extensions that you trust and have reviewed. Continue?", parent=self.root):
            return
        try:
            record = self.extensions.install_zip(path) if archive else self.extensions.install_folder(path)
            self.refresh_extensions()
            self.notice(f"Imported {record.name}, not enabled on any profile")
            messagebox.showinfo("Extension imported (not enabled)",
                                f"Name: {record.name}\nVersion: {record.version}\n"
                                f"Permissions: {', '.join(record.permissions) or '(none)'}\n"
                                f"Hosts: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                "Use Attach to allow this extension in a selected Chromium profile.", parent=self.root)
        except Exception as exc:
            messagebox.showerror("Install extension", str(exc), parent=self.root)

    def update_extension_zip(self):
        old = self.selected_extension()
        if not old:
            return
        path = filedialog.askopenfilename(title="Choose a reviewed newer MV3 extension package",
                            filetypes=[("ZIP archive","*.zip")])
        if not path:
            return
        candidate = None
        try:
            candidate = self.extensions.prepare_update(old.id,Path(path),archive=True)
            additional_api = sorted(set(candidate.permissions) - set(old.permissions))
            additional_host = sorted(set(candidate.host_permissions) - set(old.host_permissions))
            if not messagebox.askyesno("Review extension update permissions",
                                       f"Update {old.name} from {old.version} to {candidate.version}?\n"
                                       "Review source trust: same extension name is NOT a developer signature.\n\n"
                                       f"NEW API permissions: {', '.join(additional_api) or '(none)'}\n"
                                       f"NEW host access: {', '.join(additional_host) or '(none)'}\n\n"
                                       "Affected profiles must all be stopped. "
                                       "The old package is retained for rollback.",
                                       parent=self.root):
                self.extensions.remove(candidate.id)
                return
            update = self.extensions.apply_update(old.id,candidate.id)
            self.refresh_extensions()
            self.notice(f"Updated {old.name} on {len(update.profile_ids)} stopped profiles")
            messagebox.showinfo("Extension updated",
                                f"New version imported: {candidate.version}\n"
                                "Restart affected profiles to load the new package.\n"
                                "Keep the old package if rollback may be necessary.",
                                parent=self.root)
        except Exception as exc:
            if candidate:
                try:
                    self.extensions.remove(candidate.id)
                except (ValueError, KeyError, OSError):
                    pass
            messagebox.showerror("Update extension",str(exc),parent=self.root)

    def rollback_extension_update(self):
        record = self.selected_extension()
        if not record:
            return
        updates = [u for u in self.extensions.list_upgrades()
                   if u.new_id == record.id and u.status == "applied"]
        if not updates:
            return messagebox.showinfo("Rollback",
                        "Select a newer extension package with an active update record.",
                        parent=self.root)
        latest = updates[0]
        previous = next((p for p in self.extensions.list() if p.id == latest.old_id), None)
        if previous is None:
            return messagebox.showerror("Rollback","Previous extension version is missing.",parent=self.root)
        if not messagebox.askyesno("Rollback extension",
                                   f"Restore {record.name} from {record.version} to {previous.version} "
                                   f"on {len(latest.profile_ids)} affected profiles?\n\n"
                                   "All affected browsers must be stopped. Current website actions "
                                   "cannot be undone. Restart profiles after rollback.",
                                   parent=self.root):
            return
        try:
            self.extensions.rollback_update(latest.id)
            self.refresh_extensions()
            self.notice(f"Rolled back {record.name} to {previous.version}")
        except Exception as exc:
            messagebox.showerror("Rollback extension",str(exc),parent=self.root)

    def extension_details(self):
        record = self.selected_extension()
        if record:
            messagebox.showinfo("Extension permissions",
                                f"{record.name} (v{record.version})\n\n"
                                f"API permissions: {', '.join(record.permissions) or '(none)'}\n"
                                f"Host permissions: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                "Imported extension source is not audited or automatically updated.", parent=self.root)

    def attach_extension(self):
        record, pid = self.selected_extension(), self.selected_id()
        if not record or not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Profile running", "Stop this profile before modifying extensions")
            return
        if not messagebox.askyesno("Grant extension access",
                                   f"Enable {record.name} for this browser profile?\n\n"
                                   f"API permissions: {', '.join(record.permissions) or '(none)'}\n"
                                   f"Host permissions: {', '.join(record.host_permissions) or '(none)'}\n\n"
                                   "Extensions can observe page content.", parent=self.root):
            return
        try:
            self.extensions.attach(pid, record.id)
            self.refresh_extensions()
            self.notice(f"Attached extension {record.name}; restart the profile to load")
        except Exception as exc:
            messagebox.showerror("Attach extension", str(exc), parent=self.root)

    def detach_extension(self):
        record, pid = self.selected_extension(), self.selected_id()
        if not record or not pid:
            return
        if self.manager.active(pid):
            messagebox.showwarning("Profile running", "Stop the profile before detaching extensions")
            return
        self.extensions.detach(pid, record.id)
        self.refresh_extensions()
        self.notice(f"Detached {record.name}")

    def remove_extension(self):
        record = self.selected_extension()
        if not record:
            return
        if any(self.manager.active(p.id) and record.id in self.extensions.attached_ids(p.id) for p in self.store.all()):
            messagebox.showwarning("Extension active", "Stop attached browser profiles first")
            return
        if messagebox.askyesno("Remove extension", f"Delete local files for {record.name}?", parent=self.root):
            try:
                self.extensions.remove(record.id)
                self.refresh_extensions()
                self.notice(f"Removed {record.name}")
            except Exception as exc:
                messagebox.showerror("Remove extension", str(exc), parent=self.root)

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

    def _run_ui_task(self, task, finished=None, *, title="Background operation",
                     failed=None):
        """Run potentially slow Playwright/SQLite work without blocking Tk."""
        if failed is None:
            failed=lambda message: messagebox.showerror(title,message,parent=self.root)
        def worker():
            completion=None
            try:
                result=task()
            except Exception as exc:
                # Display readable validation errors, never a raw browser trace
                # that could include page content or credentials.
                message=(str(exc) if isinstance(exc,(ValueError,RuntimeError))
                         else type(exc).__name__)
                completion=(failed,message)
            else:
                if finished is not None:
                    completion=(finished,result)
            finally:
                # Close thread-owned SQLite connections before reporting success
                # so the GUI can safely clean up temporary Windows data dirs.
                self.store.close_thread_connection()
            if completion is not None:
                self._ui_task_results.put(completion)
        threading.Thread(target=worker,daemon=True,name="autumn-ui-worker").start()

    def _copy(self, content):
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.notice("API token copied to clipboard")

    def update_profile_status(self, profile_id: str, status: str):
        """Update only the affected row; avoid DB re-queries on every event."""
        if not self.tree.exists(profile_id):
            return
        values = list(self.tree.item(profile_id, "values"))
        values[-1] = ("● Running" if status == "Running" else
                      "… Starting" if status.startswith("Starting") else "○ Stopped")
        self.tree.item(profile_id, values=values)

    def poll_events(self):
        try:
            for _ in range(100):
                try:
                    callback, value = self._ui_task_results.get_nowait()
                except queue.Empty:
                    break
                if self._ui_destroyed:
                    break
                callback(value)
            for _ in range(100):
                try:
                    pid, kind, message = self.manager.events.get_nowait()
                except queue.Empty:
                    break
                if kind == "status":
                    self.update_profile_status(pid, message)
                self.log(f"[{pid[:8]}] [{kind.upper()}] {message}")
                if kind == "error":
                    self.status.set("Browser error: " + message[:130])
        finally:
            if not self._ui_destroyed:
                try:
                    self._poll_after=self.root.after(150, self.poll_events)
                except tk.TclError:
                    self._ui_destroyed=True

    def _root_destroyed(self, event):
        if event.widget is self.root:
            self._ui_destroyed=True
            for ident in (getattr(self,"_poll_after",None),
                          getattr(self,"_search_after",None),
                          getattr(self,"_shutdown_after",None)):
                if ident:
                    try:
                        self.root.after_cancel(ident)
                    except tk.TclError:
                        pass
            self.batches.cancel_all()
            self.scheduler.stop()
            self.manager.stop_all()
            self.store.close_thread_connection()

    def on_quit(self):
        if self._quitting:
            return  # repeated window-close clicks cannot start duplicate shutdowns
        self._quitting = True
        self._shutdown_deadline = time.monotonic() + 8.0
        self.batches.cancel_all()
        self.scheduler.stop()
        self.manager.stop_all()
        # The local API can take time to stop; never do this on the Tk thread.
        if self.api.server:
            threading.Thread(target=self.api.stop, daemon=True,
                             name="autumn-api-shutdown").start()
        self._shutdown_after = self.root.after(100, self._exit_when_stopped)

    def _exit_when_stopped(self):
        if self._ui_destroyed:
            return
        self._shutdown_after = None
        if self.manager.count():
            if time.monotonic() < self._shutdown_deadline:
                self.status.set("Closing browser sessions...")
                self._shutdown_after = self.root.after(200, self._exit_when_stopped)
                return
            # A timed-out context may still hold files. Do not claim a clean
            # shutdown or call close_driver while contexts are alive.
            self.status.set("Shutdown incomplete: browser sessions still open")
            self.store.close_thread_connection()
            self.root.destroy()
            return
        if not self._driver_shutdown_started:
            self._driver_shutdown_started = True
            self._driver_shutdown_deadline = time.monotonic() + 38.0
            self.status.set("Closing shared Playwright driver...")

            def completed(_result):
                self.store.close_thread_connection()
                self.root.destroy()

            def failed(_message):
                self._driver_shutdown_failed = True
                self.status.set("Shared Playwright driver did not close cleanly")
                self.store.close_thread_connection()
                self.root.destroy()

            self._run_ui_task(self.manager.close_driver, completed,
                              title="Browser shutdown", failed=failed)
        elif time.monotonic() >= self._driver_shutdown_deadline:
            # close_driver itself has bounded waits. If something violates
            # those bounds, do not trap Tk in an infinite shutdown loop.
            self._driver_shutdown_failed = True
            self.status.set("Shared Playwright driver shutdown timed out")
            self.store.close_thread_connection()
            self.root.destroy()
            return
        self._shutdown_after = self.root.after(200, self._exit_when_stopped)
