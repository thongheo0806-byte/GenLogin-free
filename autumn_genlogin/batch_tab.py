"""Batch tasks Tk tab, backed by App's shared worker-completion queue.

All browser, history SQLite and OS lease activity runs off the GUI thread.
Only App and Tk callbacks touch widgets. Keep consent before dispatch.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk


class BatchTabMixin:
    def _build_batch_tab(self, frame):
        ttk.Label(frame, text="Run the current workflow across a selected profile group",
                  style="Heading.TLabel").pack(anchor="w",pady=(0,8))
        ttk.Label(frame, text="Select a specific Group in Profiles first, then review the workflow in Automation.\n"
                  "Each profile gets an independent run; parallelism is capped to six local browsers.\n"
                  "This is NOT a live synchronizer. Batch history is saved locally; interrupted runs are never auto-replayed.",
                  style="Muted.TLabel").pack(anchor="w",pady=(0,12))
        controls = ttk.Frame(frame)
        controls.pack(fill="x",pady=(0,10))
        ttk.Label(controls,text="Parallel profiles:").pack(side="left")
        self.batch_parallel=tk.StringVar(value="2")
        ttk.Combobox(controls,values=("1","2","3","4","5","6"),
                     textvariable=self.batch_parallel,state="readonly",width=4).pack(side="left",padx=8)
        ttk.Button(controls,text="Start selected group",style="Accent.TButton",
                   command=self.start_group_batch).pack(side="left",padx=8)
        ttk.Button(controls,text="Cancel selected",command=self.cancel_group_batch).pack(side="left",padx=8)
        ttk.Button(controls,text="Refresh",command=self.refresh_batches).pack(side="left")
        self.batch_tree=ttk.Treeview(frame,
            columns=("group","status","success","failed","active","queued"),
            show="headings",height=12)
        for column,width in (("group",155),("status",130),("success",100),
                             ("failed",100),("active",100),("queued",100)):
            self.batch_tree.heading(column,text=column.title())
            self.batch_tree.column(column,width=width)
        self.batch_tree.pack(fill="both",expand=True)
        self.batch_details=tk.StringVar(value="Select a batch and Refresh to see individual profile states.")
        ttk.Label(frame,textvariable=self.batch_details,style="Muted.TLabel").pack(anchor="w",pady=10)
        self.batch_tree.bind("<<TreeviewSelect>>",lambda *_:self.show_batch_details())
        self.refresh_batches()

    def start_group_batch(self):
        group=self.group.get()
        if not group or group=="All groups":
            messagebox.showwarning("Batch group","Select one specific Group in Profiles first.",parent=self.root)
            return
        # Capture Tk widget/editor state BEFORE crossing the thread boundary.
        ids=[p.id for p in self._cached_profiles if p.group_name==group]
        if not ids:
            messagebox.showwarning("Batch group","No profiles in the selected group.",parent=self.root)
            return
        try:
            steps=self.current_steps()
            parallel=int(self.batch_parallel.get())
        except Exception as exc:
            return messagebox.showerror("Batch automation",type(exc).__name__,parent=self.root)
        if not messagebox.askyesno(
                "Confirm group automation",
                f"Run the current workflow on {len(ids)} profiles in group '{group}' "
                f"with at most {parallel} running at once?\n\n"
                "The workflow may change website data. Review it before confirming.",
                parent=self.root):
            return

        def started(ident):
            self.refresh_batches()
            self.notice(f"Batch started: {ident[:8]} ({len(ids)} profiles)")

        self._run_ui_task(
            lambda:self.batches.start(ids,steps,max_parallel=parallel),
            started,title="Batch automation")

    def cancel_group_batch(self):
        selection=self.batch_tree.selection()
        if not selection:
            return
        if not messagebox.askyesno(
                "Cancel batch",
                "Cancel queued runs and request cancellation of active runs?\n"
                "A browser action already submitted to a website may still complete.",
                parent=self.root):
            return
        ident=selection[0]

        def failed(message):
            if message=="KeyError":
                messagebox.showinfo(
                    "Batch history",
                    "This batch is no longer active in this app. "
                    "Historical runs cannot be cancelled.",
                    parent=self.root)
            else:
                messagebox.showerror("Batch cancellation",message,parent=self.root)

        self._run_ui_task(
            lambda:self.batches.cancel(ident),
            lambda _:self.refresh_batches(),title="Batch cancellation",
            failed=failed)

    def refresh_batches(self):
        """Read history outside Tk; never let stale worker results redraw it."""
        self._batch_refresh_generation=(
            getattr(self,"_batch_refresh_generation",0)+1)
        generation=self._batch_refresh_generation

        def render(batches):
            if generation!=self._batch_refresh_generation:
                return
            selected=set(self.batch_tree.selection())
            self.batch_tree.delete(*self.batch_tree.get_children())
            for batch in batches:
                statuses=[item["status"] for item in batch["items"]]
                success=statuses.count("succeeded")
                failed=sum(s in ("failed","uncertain") for s in statuses)
                active=sum(s in ("running","submitting") for s in statuses)
                queued=statuses.count("queued")
                group=f'{len(batch["items"])} profiles'
                self.batch_tree.insert("", "end",iid=batch["id"],
                    values=(group,batch["status"],success,failed,active,queued))
            retained=[ident for ident in selected if self.batch_tree.exists(ident)]
            if retained:
                self.batch_tree.selection_set(retained)

        self._run_ui_task(
            lambda:self.batches.list(),render,title="Batch history")

    def show_batch_details(self):
        selection=self.batch_tree.selection()
        if not selection:
            return
        ident=selection[0]
        def render(batch):
            if ident not in self.batch_tree.selection():
                return
            detail=", ".join(
                f'{item["profile_id"][:8]}:{item["status"]}'
                for item in batch["items"][:20])
            if len(batch["items"])>20:
                detail+=f' (+{len(batch["items"])-20} more)'
            self.batch_details.set(detail or "No runs")
        self._run_ui_task(lambda:self.batches.get(ident),render,
                          title="Batch details")

