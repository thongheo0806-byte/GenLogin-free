"""Interactive, no-code browser workflow editor using native Tk controls.

This is a sequential visual step editor, NOT a GenLogin-like graph recorder.
It exports the same strict JSON steps as the automation engine.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from .actions import ACTIONS, NUMERIC_FIELDS
from .models import validated_steps

FIELDS = {name: definition.fields for name, definition in ACTIONS.items()}
DEFAULTS = {"url": "https://example.com", "selector": "h1", "text": "example", "seconds": "1", "confidence": "0.94", "template_id": "", "key": "Enter", "value": "value"}


class StepDialog(tk.Toplevel):
    def __init__(self, parent, initial: dict | None = None):
        super().__init__(parent)
        self.title("Edit workflow step" if initial else "Add workflow step")
        self.geometry("570x460")
        self.minsize(500, 380)
        self.transient(parent.winfo_toplevel())
        self.grab_set()
        self.result = None
        body = ttk.Frame(self, padding=22)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Automation step", font=("Segoe UI Semibold", 15)).pack(anchor="w")
        ttk.Label(body, text="Steps run in order. All parameters are validated before use.").pack(anchor="w", pady=(6, 14))
        self.action = tk.StringVar(value=(initial or {}).get("action", "goto"))
        ttk.Label(body, text="Action").pack(anchor="w")
        chooser = ttk.Combobox(body, textvariable=self.action, values=tuple(FIELDS), state="readonly")
        chooser.pack(fill="x", pady=(4, 14))
        chooser.bind("<<ComboboxSelected>>", lambda *_: self.render())
        self.fields = ttk.Frame(body)
        self.fields.pack(fill="both", expand=True)
        self.inputs = {}
        self.initial = initial or {}
        self._field_cache = dict(self.initial)
        self.render()
        foot = ttk.Frame(body)
        foot.pack(fill="x", pady=(12, 0))
        ttk.Button(foot, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        ttk.Button(foot, text="Save step", command=self.save).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def render(self):
        self._field_cache.update({k: v.get() for k, v in getattr(self, "inputs", {}).items()})
        for child in self.fields.winfo_children():
            child.destroy()
        self.inputs = {}
        for key in FIELDS[self.action.get()]:
            ttk.Label(self.fields, text=key.replace("_", " ").capitalize()).pack(anchor="w", pady=(2, 4))
            var = tk.StringVar(value=str(self._field_cache.get(key, DEFAULTS.get(key, ""))))
            ttk.Entry(self.fields, textvariable=var).pack(fill="x", pady=(0, 10))
            self.inputs[key] = var

    def save(self):
        entry = {"action": self.action.get()}
        try:
            entry.update({k: float(v.get()) if k in NUMERIC_FIELDS else v.get() for k, v in self.inputs.items()})
            validated_steps([entry])
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid step", str(exc), parent=self)
            return
        self.result = entry
        self.destroy()


class WorkflowBuilder(ttk.Frame):
    def __init__(self, parent, initial: list[dict] | None = None):
        super().__init__(parent)
        self._steps: list[dict] = []
        self._drag_origin = None
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 12))
        for label, command in (("+ Add step", self.add), ("Edit", self.edit),
                               ("Duplicate", self.duplicate), ("Remove", self.remove),
                               ("Move up", lambda: self.move(-1)), ("Move down", lambda: self.move(1))):
            ttk.Button(controls, text=label, command=command).pack(side="left", padx=(0, 7))
        ttk.Label(self, text="Visual sequence editor: double-click to edit, drag rows to reorder. Export to JSON for reuse.").pack(anchor="w", pady=(0, 10))
        self.tree = ttk.Treeview(self, columns=("step", "action", "parameters"), show="headings", selectmode="browse")
        for name, width in (("step", 60), ("action", 155), ("parameters", 700)):
            self.tree.heading(name, text=name.title())
            self.tree.column(name, width=width, stretch=(name == "parameters"))
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda *_: self.edit())
        self.tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.tree.bind("<ButtonRelease-1>", self._drag_end, add="+")
        self.set_steps(initial or [])

    def get_steps(self) -> list[dict]:
        return validated_steps(self._steps)

    def set_steps(self, steps: list[dict]):
        self._steps = validated_steps(steps) if steps else []
        self.refresh()

    def refresh(self, focus: int | None = None):
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self._steps):
            summary = ", ".join(f"{k}: {v}" for k, v in item.items() if k != "action")
            self.tree.insert("", "end", iid=str(i), values=(i + 1, item["action"], summary[:220]))
        if focus is not None and 0 <= focus < len(self._steps):
            self.tree.selection_set(str(focus))
            self.tree.see(str(focus))

    def selected(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def add(self):
        if len(self._steps) >= 100:
            messagebox.showerror("Workflow", "Maximum 100 steps")
            return
        dialog = StepDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            self._steps.append(dialog.result)
            self.refresh(len(self._steps) - 1)

    def edit(self):
        i = self.selected()
        if i is None:
            return
        dialog = StepDialog(self, self._steps[i])
        self.wait_window(dialog)
        if dialog.result:
            self._steps[i] = dialog.result
            self.refresh(i)

    def duplicate(self):
        i = self.selected()
        if i is not None and len(self._steps) < 100:
            self._steps.insert(i + 1, self._steps[i].copy())
            self.refresh(i + 1)

    def remove(self):
        i = self.selected()
        if i is not None:
            del self._steps[i]
            self.refresh(min(i, len(self._steps) - 1))

    def move(self, offset: int):
        i = self.selected()
        if i is None or not 0 <= i + offset < len(self._steps):
            return
        self._steps[i], self._steps[i + offset] = self._steps[i + offset], self._steps[i]
        self.refresh(i + offset)

    def _drag_start(self, event):
        row = self.tree.identify_row(event.y)
        self._drag_origin = int(row) if row else None

    def _drag_end(self, event):
        row = self.tree.identify_row(event.y)
        source = self._drag_origin
        self._drag_origin = None
        if source is None or not row:
            return
        target = int(row)
        if source != target:
            step = self._steps.pop(source)
            self._steps.insert(target, step)
            self.refresh(target)
