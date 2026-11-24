"""Tkinter desktop UI. The browser and HTTP API run off the GUI thread."""
from __future__ import annotations

from .schedule_tab import ScheduleTabMixin
from .batch_tab import BatchTabMixin
from .cloud_tab import CloudTabMixin
from .miniapp_tab import MiniappTabMixin
from .qa_sync_tab import QASyncTabMixin
from .backup_tab import BackupTabMixin
from .extension_tab import ExtensionTabMixin
from .profiles_tab import ProfileEditor, ProfilesTabMixin
from .ui_theme import ACCENT, BG, FG, MUTED, PANEL, PANEL2

import json
import threading
import queue
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .api import LocalAPI
from .batch import BatchRunner
from .qa_sync import LocalQASynchronizer
from .miniapps import MiniAppLibrary
from .browser_shared import SharedBrowserManager
from .graph_ui import GraphEditor
from .scheduler import ScheduleStore, Scheduler
from .diagnostics import audit_store
from .visual_workflow import WorkflowBuilder
from .models import validated_steps
from .storage import Store

EXAMPLE_STEPS = [
    {"action": "goto", "url": "https://example.com"},
    {"action": "wait_for", "selector": "h1"},
    {"action": "extract_text", "selector": "h1"},
    {"action": "screenshot"},
]


class App(ProfilesTabMixin, BackupTabMixin, ExtensionTabMixin, QASyncTabMixin, MiniappTabMixin,
          CloudTabMixin, BatchTabMixin, ScheduleTabMixin):
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
        self._build_profiles_tab(profile_tab)
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
        self._build_extensions_tab(extensions_tab)
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

    def notice(self, value):
        self.status.set(value)
        self.log(value)

    def log(self, text):
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def show_diagnostics(self):
        report = audit_store(self.store)
        lines = [f"{item['status'].upper():4}  {item['name']}: {item['detail']}"
                 for item in report["checks"]]
        summary = report["summary"]
        messagebox.showinfo("AutumnGenLogin diagnostics",
                            "\n".join(lines) + "\n\n" + str(summary), parent=self.root)
        self.notice(f"Diagnostics: {summary['failed']} failures, {summary['warnings']} warnings")

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

    def load_workflow_draft(self, workflow):
        """Public cross-tab bridge: load a reviewed draft, never execute it."""
        if isinstance(workflow, dict):
            self.graph_builder.set_graph(workflow)
            self.flow_tabs.select(2)
        else:
            self.builder.set_steps(validated_steps(workflow))
            self.flow_tabs.select(0)

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
            self.cancel_profile_search()
            for ident in (getattr(self,"_poll_after",None),
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
