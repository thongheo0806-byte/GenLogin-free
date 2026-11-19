"""Bounded visual workflow graphs; no arbitrary Python/JavaScript evaluation.

Control nodes are explicit; graph execution is rate- and step-limited. Graphs
are data, not executable source. Recorder output can be converted to graphs.
"""
from __future__ import annotations

from copy import deepcopy
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from .models import validated_steps

MAX_NODES = 100
MAX_EXECUTIONS = 500
MAX_REPEAT = 20


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
                 "repeat": {"id", "type", "times"}}
        if kind not in props or set(node) != props[kind]:
            raise ValueError(f"Invalid {kind} node fields")
        if kind == "action":
            validated_steps([node["step"]])
        if kind == "condition":
            selector = node["selector"]
            if not isinstance(selector, str) or not selector or len(selector) > 500 or any(x in selector for x in "\r\n\x00"):
                raise ValueError("Invalid graph condition selector")
        if kind == "repeat" and (type(node["times"]) is not int or not 1 <= node["times"] <= MAX_REPEAT):
            raise ValueError("Repeat must be 1-20 iterations")
        if kind == "start": start_nodes.append(ident)
        if kind == "end": end_nodes.append(ident)
        by_id[ident] = node
    if len(start_nodes) != 1 or len(end_nodes) != 1:
        raise ValueError("Graph requires exactly one start and one end")
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


async def execute_graph(graph: dict, *, action: Callable[[dict], Awaitable[None]],
                        exists: Callable[[str], Awaitable[bool]],
                        cancelled: Callable[[], bool] = lambda: False) -> dict:
    graph = validate_graph(graph)
    nodes = {x["id"]: x for x in graph["nodes"]}
    edges = {(x["from"], x["branch"]): x["to"] for x in graph["edges"]}
    current = next(x["id"] for x in graph["nodes"] if x["type"] == "start")
    repeat_count: dict[str, int] = {}
    operations = 0
    while operations < MAX_EXECUTIONS:
        if cancelled():
            return {"status": "cancelled", "operations": operations}
        node = nodes[current]
        if node["type"] == "end":
            return {"status": "succeeded", "operations": operations}
        operations += 1
        label = "next"
        if node["type"] == "action":
            await action(node["step"])
        elif node["type"] == "condition":
            label = "yes" if await exists(node["selector"]) else "no"
        elif node["type"] == "repeat":
            repeat_count[current] = repeat_count.get(current, 0) + 1
            label = "yes" if repeat_count[current] <= node["times"] else "no"
            if label == "no":
                repeat_count[current] = 0
        current = edges[(current, label)]
    raise RuntimeError(f"Graph exceeded its {MAX_EXECUTIONS}-operation safety limit")
