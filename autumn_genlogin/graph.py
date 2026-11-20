"""Bounded visual workflow graphs; no arbitrary Python/JavaScript evaluation.

Control nodes are explicit; graph execution is rate- and step-limited. Graphs
are data, not executable source. Recorder output can be converted to graphs.
"""
from __future__ import annotations

from copy import deepcopy
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any
import re

from .models import validated_steps

MAX_NODES = 100
MAX_EXECUTIONS = 500
MAX_REPEAT = 20
MAX_VARIABLES = 32
MAX_VARIABLE_VALUE = 4096
_VARIABLE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,31}\Z")
_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]{0,31})\}\}")


def validate_graph(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"format", "nodes", "edges"}:
        raise ValueError("Graph must contain format, nodes and edges")
    if value["format"] != "AutumnGenLogin/graph-1":
        raise ValueError("Unsupported graph format")
    nodes, edges = value["nodes"], value["edges"]
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= MAX_NODES:
        raise ValueError("Graph must contain 2-100 nodes")
    if not isinstance(edges, list) or len(edges) > MAX_NODES * 3:
        raise ValueError("Invalid graph edges")
    by_id = {}
    start_nodes, end_nodes = [], []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("Invalid graph node")
        ident, kind = node.get("id"), node.get("type")
        if not isinstance(ident, str) or not ident.isascii() or not ident.replace("_", "").replace("-", "").isalnum() or len(ident) > 64:
            raise ValueError("Invalid graph node ID")
        if ident in by_id:
            raise ValueError("Duplicate node ID")
        props = {"start": {"id", "type"}, "end": {"id", "type"},
                 "action": {"id", "type", "step"},
                 "condition": {"id", "type", "selector"},
                 "repeat": {"id", "type", "times"},
                 "set_variable": {"id", "type", "name", "value"},
                 "capture_text": {"id", "type", "name", "selector"}}
        if kind not in props or set(node) != props[kind]:
            raise ValueError(f"Invalid {kind} node fields")
        if kind == "action":
            validated_steps([node["step"]])
        if kind in {"condition","capture_text"}:
            selector = node["selector"]
            if not isinstance(selector, str) or not selector or len(selector) > 500 or any(x in selector for x in "\r\n\x00"):
                raise ValueError("Invalid graph selector")
        if kind in {"set_variable","capture_text"}:
            name = node["name"]
            if not isinstance(name,str) or not _VARIABLE_NAME.fullmatch(name):
                raise ValueError("Variable name must be 1-32 ASCII letters, digits or underscores")
        if kind == "set_variable":
            literal = node["value"]
            if (not isinstance(literal,str) or len(literal) > MAX_VARIABLE_VALUE or
                "\x00" in literal or "{{" in literal or "}}" in literal):
                raise ValueError("Variables must be literal strings up to 4096 characters")
        if kind == "repeat" and (type(node["times"]) is not int or not 1 <= node["times"] <= MAX_REPEAT):
            raise ValueError("Repeat must be 1-20 iterations")
        if kind == "start": start_nodes.append(ident)
        if kind == "end": end_nodes.append(ident)
        by_id[ident] = node
    if len(start_nodes) != 1 or len(end_nodes) != 1:
        raise ValueError("Graph requires exactly one start and one end")
    if len({n["name"] for n in nodes if n["type"] in {"set_variable","capture_text"}}) > MAX_VARIABLES:
        raise ValueError("Graph may define at most 32 distinct variables")
    successors: dict[str, dict[str, str]] = {i: {} for i in by_id}
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"from", "to", "branch"}:
            raise ValueError("Invalid edge")
        source, target, label = edge["from"], edge["to"], edge["branch"]
        if source not in by_id or target not in by_id or source == target:
            raise ValueError("Invalid edge source/target")
        if label not in ({"yes", "no"} if by_id[source]["type"] in {"condition", "repeat"} else {"next"}):
            raise ValueError("Invalid edge label")
        if label in successors[source]:
            raise ValueError("Duplicate graph edge")
        successors[source][label] = target
    for ident, node in by_id.items():
        labels = set(successors[ident]); kind = node["type"]
        expected = set() if kind == "end" else {"yes", "no"} if kind in {"condition", "repeat"} else {"next"}
        if labels != expected:
            raise ValueError(f"Node {ident} needs branches {sorted(expected)}")
    reachable = set()
    queue = deque(start_nodes)
    while queue:
        ident = queue.popleft()
        if ident not in reachable:
            reachable.add(ident)
            queue.extend(successors[ident].values())
    if len(reachable) != len(by_id):
        raise ValueError("Graph contains unreachable nodes")
    # The graph must be able to reach an exit from every node, even if a
    # conditional branch decides otherwise during an individual run.
    reverse = {ident: [] for ident in by_id}
    for source, links in successors.items():
        for target in links.values(): reverse[target].append(source)
    can_exit, queue = set(), deque(end_nodes)
    while queue:
        ident = queue.popleft()
        if ident not in can_exit:
            can_exit.add(ident); queue.extend(reverse[ident])
    if len(can_exit) != len(by_id):
        raise ValueError("Graph contains a cycle that cannot terminate")
    return deepcopy(value)


def steps_to_graph(steps: list[dict]) -> dict:
    steps = validated_steps(steps)
    nodes = [{"id": "start", "type": "start"}]
    nodes.extend({"id": f"step_{idx}", "type": "action", "step": step} for idx, step in enumerate(steps, 1))
    nodes.append({"id": "end", "type": "end"})
    edges = [{"from": a["id"], "to": b["id"], "branch": "next"} for a, b in zip(nodes, nodes[1:])]
    return validate_graph({"format": "AutumnGenLogin/graph-1", "nodes": nodes, "edges": edges})


def _expand(template: str, variables: dict[str, tuple[str, bool]], *, url: bool = False) -> str:
    """Expand only {{name}} placeholders, with no eval or expression support.

    Captured page text is tainted and cannot flow into navigation URLs, which
    could otherwise unintentionally leak page content to another origin.
    """
    def substitute(match: re.Match) -> str:
        name = match.group(1)
        if name not in variables:
            raise ValueError("Undefined workflow variable: " + name)
        value, captured = variables[name]
        if url and captured:
            raise ValueError("Captured page text cannot be inserted into a navigation URL")
        return value
    result = _PLACEHOLDER.sub(substitute, template)
    if "{{" in result or "}}" in result:
        raise ValueError("Invalid workflow variable placeholder")
    if len(result) > MAX_VARIABLE_VALUE:
        raise ValueError("Expanded step text exceeds 4096 characters")
    return result


async def execute_graph(graph: dict, *, action: Callable[[dict], Awaitable[None]],
                        exists: Callable[[str], Awaitable[bool]],
                        capture: Callable[[str], Awaitable[str]] | None = None,
                        cancelled: Callable[[], bool] = lambda: False) -> dict:
    graph = validate_graph(graph)
    nodes = {x["id"]: x for x in graph["nodes"]}
    edges = {(x["from"], x["branch"]): x["to"] for x in graph["edges"]}
    current = next(x["id"] for x in graph["nodes"] if x["type"] == "start")
    repeat_count: dict[str, int] = {}
    # Transient, per-execution state. Never return variable values in run status.
    variables: dict[str, tuple[str, bool]] = {}
    operations = 0
    while operations < MAX_EXECUTIONS:
        if cancelled():
            return {"status": "cancelled", "operations": operations}
        node = nodes[current]
        kind = node["type"]
        if kind == "end":
            return {"status": "succeeded", "operations": operations}
        operations += 1
        label = "next"
        if kind == "action":
            step = {
                key: _expand(value, variables, url=key == "url") if isinstance(value, str) else value
                for key, value in node["step"].items()
            }
            # Guard against a variable expansion changing a URL scheme, a step
            # shape or string-length limits after the initial graph validation.
            await action(validated_steps([step])[0])
        elif kind == "condition":
            label = "yes" if await exists(_expand(node["selector"], variables)) else "no"
        elif kind == "repeat":
            repeat_count[current] = repeat_count.get(current, 0) + 1
            label = "yes" if repeat_count[current] <= node["times"] else "no"
            if label == "no":
                repeat_count[current] = 0
        elif kind == "set_variable":
            variables[node["name"]] = (node["value"], False)
        elif kind == "capture_text":
            if capture is None:
                raise RuntimeError("Browser text capture is not available in this workflow runner")
            selector = _expand(node["selector"], variables)
            text = await capture(selector)
            if not isinstance(text, str):
                raise TypeError("Browser capture must return text")
            variables[node["name"]] = (text[:MAX_VARIABLE_VALUE], True)
        current = edges[(current, label)]
    raise RuntimeError(f"Graph exceeded its {MAX_EXECUTIONS}-operation safety limit")
