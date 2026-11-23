"""Scheduler tab controller extracted from the Tk App God-class.

Scheduler methods deliberately remain on a mixin so existing App callbacks,
external API dispatch wiring and Tk ownership semantics are unchanged.
All actual DB I/O is performed by App._run_ui_task workers.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import tkinter as tk
from tkinter import messagebox, ttk


class ScheduleTabMixin:
    def _dispatch_scheduled_job(self, job):
        """Attach an exactly-once terminal callback to each scheduled run."""
        self.manager.start_workflow(
            job.profile_id, job.workflow, run_id=job.dispatch_id,
            on_finish=lambda status, error, ident=job.dispatch_id:
                self.schedule_store.record_completion(ident, status, error),
        )

    def _build_schedule_tab(self, frame):
        ttk.Label(frame, text="Durable local schedules (UTC storage; local clock entry)", style="Heading.TLabel").pack(anchor="w", pady=8)
        box = ttk.Frame(frame)
        box.pack(fill="x", pady=10)
        ttk.Label(box, text="Start in minutes").pack(side="left")
        self.schedule_delay = tk.StringVar(value="1")
        ttk.Entry(box, textvariable=self.schedule_delay, width=7).pack(side="left", padx=8)
        ttk.Label(box, text="Repeat every minutes (0 = once)").pack(side="left")
        self.schedule_interval = tk.StringVar(value="0")
        ttk.Entry(box, textvariable=self.schedule_interval, width=7).pack(side="left", padx=8)
        ttk.Button(box, text="Schedule selected workflow", command=self.schedule_workflow).pack(side="left", padx=8)
        ttk.Button(box, text="Delete selected", command=self.remove_schedule).pack(side="left", padx=8)
        ttk.Button(box, text="Retry failed/uncertain", command=self.retry_schedule).pack(side="left", padx=8)
        ttk.Button(box, text="Refresh", command=self.refresh_schedules).pack(side="left")
        self.schedule_tree = ttk.Treeview(frame, columns=("profile","due","interval","status"), show="headings")
        for column in ("profile","due","interval","status"):
            self.schedule_tree.heading(column, text=column.title())
            self.schedule_tree.column(column, width=250 if column == "profile" else 170)
        self.schedule_tree.pack(fill="both", expand=True)
        ttk.Label(frame, text="Recent scheduled runs (no page content or extracted values stored)",
                  style="Heading.TLabel").pack(anchor="w", pady=(12, 4))
        self.schedule_history_tree = ttk.Treeview(
            frame, columns=("job","profile","started","finished","status","error"),
            show="headings", height=7)
        for column, width in (("job",88),("profile",88),("started",190),
                              ("finished",190),("status",130),("error",145)):
            self.schedule_history_tree.heading(column, text=column.title())
            self.schedule_history_tree.column(column, width=width, anchor="w")
        self.schedule_history_tree.pack(fill="x")
        ttk.Label(frame, text="Tasks run only while AutumnGenLogin is open. Submitted means accepted, not finished.\n"
                  "Dispatch pending means execution is uncertain; never automatically replay a one-time job.",
                  style="Muted.TLabel").pack(anchor="w", pady=8)
        self.refresh_schedules()

    def refresh_schedules(self):
        """Snapshot schedules off-Tk, discard older out-of-order replies."""
        self._schedule_refresh_generation = (
            getattr(self, "_schedule_refresh_generation", 0) + 1)
        generation = self._schedule_refresh_generation

        def snapshot():
            return (self.schedule_store.list(),
                    self.schedule_store.history(limit=50))

        def render(results):
            if generation != self._schedule_refresh_generation:
                return
            jobs, runs = results
            previous = set(self.schedule_tree.selection())
            self.schedule_tree.delete(*self.schedule_tree.get_children())
            for job in jobs:
                self.schedule_tree.insert("", "end", iid=job.id,
                    values=(job.profile_id[:8], job.next_run_utc,
                            job.interval_seconds or "once", job.last_status))
            still_here = [pid for pid in previous if self.schedule_tree.exists(pid)]
            if still_here:
                self.schedule_tree.selection_set(still_here)
            self.schedule_history_tree.delete(
                *self.schedule_history_tree.get_children())
            for run in runs:
                self.schedule_history_tree.insert("", "end", iid=run.id,
                    values=(run.job_id[:8], run.profile_id[:8], run.started_utc,
                            run.finished_utc or "", run.status, run.error_type))

        self._run_ui_task(snapshot, render, title="Schedule refresh")

    def schedule_workflow(self):
        pid = self.selected_id()
        if not pid:
            return
        try:
            delay = float(self.schedule_delay.get())
            interval = float(self.schedule_interval.get())
            if delay < 0 or delay > 365*24*60 or interval < 0:
                raise ValueError("Invalid schedule time")
            if interval and (interval < 1 or not interval.is_integer()):
                raise ValueError("Repeat every 1 minute or longer in whole minutes")
            # Read the workflow editor exclusively on Tk; do disk/database
            # work on the worker and only touch widgets in the completion.
            flow = self.current_steps()
            due = datetime.now().astimezone() + timedelta(minutes=delay)
        except Exception as exc:
            return messagebox.showerror("Schedule error", str(exc), parent=self.root)

        def done(ident):
            self.refresh_schedules()
            self.notice("Scheduled job " + ident[:8])

        self._run_ui_task(
            lambda: self.schedule_store.add(
                pid, flow, due, int(interval * 60) if interval else None),
            done, title="Schedule save")

    def remove_schedule(self):
        selection = self.schedule_tree.selection()
        if selection:
            ident = selection[0]
            self._run_ui_task(
                lambda: self.schedule_store.remove(ident),
                lambda _: self.refresh_schedules(), title="Schedule remove")

    def retry_schedule(self):
        selection = self.schedule_tree.selection()
        if not selection:
            return
        # An uncertain task may already have reached the external website.
        # Never automatically replay a one-time job after a crash.
        if not messagebox.askyesno("Retry scheduled task",
                                   "Retry only a failed/uncertain one-time task.\n\n"
                                   "WARNING: an uncertain task may already have started, "
                                   "so retrying could perform the operation twice.\n\n"
                                   "Do you want to retry?",
                                   parent=self.root):
            return
        ident = selection[0]

        def done(_):
            self.refresh_schedules()
            self.notice("One-time schedule queued for explicit retry")

        self._run_ui_task(
            lambda: self.schedule_store.retry_one_shot(ident), done,
            title="Schedule retry")

