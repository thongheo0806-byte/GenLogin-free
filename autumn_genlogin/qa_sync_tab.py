"""Tk QASyncTabMixin controller; App provides the cross-tab service bridge."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class QASyncTabMixin:
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

