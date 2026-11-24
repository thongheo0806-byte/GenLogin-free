"""Profiles pane and editor; selected IDs/group snapshots are public bridges."""
from __future__ import annotations

import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from .models import Profile
from .secrets import delete_password, set_password
from .services import save_profile_with_credentials
from .ui_theme import BG, MUTED

if TYPE_CHECKING:
    from .ui import App


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


class ProfilesTabMixin:
    def _build_profiles_tab(self, profile_tab):
        self.search = tk.StringVar()
        self.group = tk.StringVar(value="All groups")
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

    def selected_id(self, alert=True):
        selected = self.tree.selection()
        if selected:
            return selected[0]
        if alert:
            messagebox.showinfo("Select profile", "Select a profile in the Profiles tab first.")
        return None

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

    def update_profile_status(self, profile_id: str, status: str):
        """Update only the affected row; avoid DB re-queries on every event."""
        if not self.tree.exists(profile_id):
            return
        values = list(self.tree.item(profile_id, "values"))
        values[-1] = ("● Running" if status == "Running" else
                      "… Starting" if status.startswith("Starting") else "○ Stopped")
        self.tree.item(profile_id, values=values)

    def profile_group_snapshot(self):
        """Return selection and detached IDs on Tk; no foreign widgets escape."""
        group=self.group.get()
        return group, [p.id for p in self._cached_profiles if p.group_name==group]

    def cancel_profile_search(self):
        ident=getattr(self,"_search_after",None)
        self._search_after=None
        if ident:
            try:
                self.root.after_cancel(ident)
            except tk.TclError:
                pass

