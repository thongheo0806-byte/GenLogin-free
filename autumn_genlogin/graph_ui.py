"""Native Tk workflow graph designer with draggable, labelled nodes and edges."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .graph import steps_to_graph, validate_graph
from .models import validated_steps


class GraphEditor(ttk.Frame):
    """A visual graph editor. Incomplete drafts are allowed, validation at run/save."""

    def __init__(self, master, initial=None):
        super().__init__(master)
        graph = initial or steps_to_graph([{"action": "goto", "url": "https://example.com"}])
        self.nodes = {n["id"]: dict(n) for n in graph["nodes"]}
        self.edges = [dict(e) for e in graph["edges"]]
        self.positions = {ident: (100 + (idx % 4) * 205, 80 + (idx // 4) * 120)
                          for idx, ident in enumerate(self.nodes)}
        self._drag = None
        controls = ttk.Frame(self)
        controls.pack(fill="x")
        for title, fn in (("+ Node", self.add_node), ("Edit", self.edit_node),
                          ("Link", self.link), ("Delete", self.delete_node),
                          ("Validate", self.check), ("Import", self.load), ("Export", self.save)):
            ttk.Button(controls, text=title, command=fn).pack(side="left", padx=3, pady=8)
        self.selected = tk.StringVar(value="Selected: none")
        ttk.Label(self, textvariable=self.selected).pack(anchor="w", pady=(0, 5))
        self.canvas = tk.Canvas(self, background="#152139", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<B1-Motion>", self._move)
        self.canvas.bind("<ButtonRelease-1>", lambda _: self._clear_drag())
        self.canvas.bind("<Double-1>", lambda _: self.edit_node())
        self._selection = None
        self.draw()

    def get_graph(self) -> dict:
        return validate_graph({"format": "AutumnGenLogin/graph-1",
                               "nodes": list(self.nodes.values()), "edges": self.edges})

    def set_graph(self, graph: dict):
        data = validate_graph(graph)
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.edges = data["edges"]
        self.positions = {ident: (100 + (idx % 4) * 205, 80 + (idx // 4) * 120)
                          for idx, ident in enumerate(self.nodes)}
        self._selection = None
        self.draw()

    def _click(self, event):
        items = self.canvas.find_overlapping(event.x, event.y, event.x, event.y)
        names = [tag[5:] for item in items for tag in self.canvas.gettags(item)
                 if tag.startswith("node:")]
        self._selection = names[-1] if names else None
        self._drag = (self._selection, event.x, event.y)
        self.selected.set("Selected: " + str(self._selection or "none"))
        self.draw()

    def _move(self, event):
        if not self._drag or not self._drag[0]: return
        ident, x, y = self._drag
        if ident not in self.positions: return
        oldx, oldy = self.positions[ident]
        self.positions[ident] = (max(90, oldx + event.x - x), max(50, oldy + event.y - y))
        self._drag = (ident, event.x, event.y)
        self.draw()

    def _clear_drag(self):
        self._drag = None

    def draw(self):
        if not hasattr(self, "canvas"): return
        c = self.canvas
        c.delete("all")
        for edge in self.edges:
            a, b = self.positions.get(edge["from"]), self.positions.get(edge["to"])
            if not a or not b: continue
            c.create_line(a[0], a[1], b[0], b[1], fill="#9db2cf", width=2, arrow="last")
            if edge["branch"] != "next":
                c.create_text((a[0]+b[0])/2, (a[1]+b[1])/2 - 10,
                              text=edge["branch"], fill="#ffd978", font=("Segoe UI", 9))
        for ident, node in self.nodes.items():
            x, y = self.positions[ident]
            fill = "#285da0" if ident == self._selection else "#293950"
            kind = node["type"]
            c.create_rectangle(x-80, y-28, x+80, y+28, fill=fill,
                               outline="#65a3ed", width=2, tags=(f"node:{ident}",))
            c.create_text(x, y-8, text=ident[:22], fill="white",
                          font=("Segoe UI Semibold", 10), tags=(f"node:{ident}",))
            detail = (" / " + node["step"]["action"] if kind == "action"
                      else " / " + node["name"] if kind in {"set_variable","capture_text"} else "")
            c.create_text(x, y+11, text=(kind + detail)[:27],
                          fill="#d9eaff", font=("Segoe UI", 9), tags=(f"node:{ident}",))

    def add_node(self):
        kind = simpledialog.askstring("New node",
            "Type: action, condition, repeat, set_variable, capture_text", parent=self)
        if kind is None: return
        if kind not in {"action", "condition", "repeat", "set_variable", "capture_text"}:
            messagebox.showerror("Node", "Choose action, condition, repeat, set_variable or capture_text")
            return
        ident = simpledialog.askstring("Node ID", "Unique ID (letters, numbers, _ or -):", parent=self)
        if not ident or ident in self.nodes: return
        node = {"id": ident, "type": kind}
        if kind == "action":
            raw = simpledialog.askstring("Step JSON", 'Example: {"action":"click","selector":"button"}', parent=self)
            if raw is None: return
            try: node["step"] = validated_steps([json.loads(raw)])[0]
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Step", str(exc)); return
        if kind == "condition":
            node["selector"] = simpledialog.askstring("Condition", "CSS/Playwright selector exists?", parent=self) or ""
        if kind == "repeat":
            node["times"] = simpledialog.askinteger("Repeat", "Maximum iterations (1-20)", minvalue=1,maxvalue=20,parent=self) or 1
        if kind in {"set_variable","capture_text"}:
            name = simpledialog.askstring("Variable", "Name (ASCII letters, digits and _, max 32):",parent=self)
            if name is None:
                return
            node["name"] = name
            if kind == "set_variable":
                value = simpledialog.askstring("Literal value", "Temporary value (not logged):",parent=self)
                if value is None:
                    return
                node["value"] = value
            else:
                selector = simpledialog.askstring("Capture text", "CSS/Playwright selector:",parent=self)
                if selector is None:
                    return
                node["selector"] = selector
        self.nodes[ident] = node
        i = len(self.positions)
        self.positions[ident] = (100 + (i % 4) * 205, 80 + (i // 4) * 120)
        self._selection = ident
        self.draw()

    def edit_node(self):
        if not self._selection or self._selection not in self.nodes: return
        node = self.nodes[self._selection]
        if node["type"] == "action":
            raw = simpledialog.askstring("Edit step", "Validated step JSON", initialvalue=json.dumps(node["step"]), parent=self)
            if raw is None: return
            try: node["step"] = validated_steps([json.loads(raw)])[0]
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Step", str(exc)); return
        elif node["type"] == "condition":
            value = simpledialog.askstring("Selector", "Element exists?", initialvalue=node["selector"], parent=self)
            if value is not None: node["selector"] = value
        elif node["type"] == "repeat":
            value = simpledialog.askinteger("Times", "Iterations 1-20", initialvalue=node["times"], minvalue=1,maxvalue=20,parent=self)
            if value is not None: node["times"] = value
        elif node["type"] in {"set_variable","capture_text"}:
            name = simpledialog.askstring("Variable name", "Name:",initialvalue=node["name"],parent=self)
            if name is None: return
            field = "value" if node["type"] == "set_variable" else "selector"
            label = "Literal value" if field == "value" else "Capture selector"
            value = simpledialog.askstring(label,label,initialvalue=node[field],parent=self)
            if value is None: return
            node["name"], node[field] = name, value
        self.draw()

    def link(self):
        source = self._selection
        if not source or self.nodes[source]["type"] == "end":
            messagebox.showinfo("Link", "Select a non-end source node first", parent=self); return
        branch = "next"
        if self.nodes[source]["type"] in {"condition", "repeat"}:
            branch = simpledialog.askstring("Branch", "yes or no?", parent=self)
            if branch not in {"yes", "no"}: return
        target = simpledialog.askstring("Link target", "Target node ID", parent=self)
        if not target or target not in self.nodes or target == source: return
        self.edges = [e for e in self.edges if (e["from"],e["branch"]) != (source,branch)]
        self.edges.append({"from":source,"to":target,"branch":branch})
        self.draw()

    def delete_node(self):
        ident = self._selection
        if not ident or self.nodes[ident]["type"] in {"start", "end"}: return
        del self.nodes[ident]
        self.positions.pop(ident,None)
        self.edges = [e for e in self.edges if ident not in (e["from"], e["to"])]
        self._selection = None
        self.draw()

    def check(self):
        try:
            graph = self.get_graph()
            messagebox.showinfo("Graph", f"Valid: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges.",parent=self)
        except ValueError as exc: messagebox.showerror("Graph invalid", str(exc),parent=self)

    def save(self):
        try: data = self.get_graph()
        except ValueError as exc:
            messagebox.showerror("Graph invalid", str(exc),parent=self); return
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if path:
            try:
                with open(path,encoding="utf-8") as f: data=json.load(f)
                self.set_graph(data)
            except (ValueError, OSError, TypeError) as exc:
                messagebox.showerror("Graph import",str(exc),parent=self)
