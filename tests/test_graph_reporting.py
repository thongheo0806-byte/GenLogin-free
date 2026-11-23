"""Graph run accounting regressions using synthetic pages only."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autumn_genlogin.browser_shared import Session, SharedBrowserManager
from autumn_genlogin.graph import steps_to_graph
from autumn_genlogin.models import Profile
from autumn_genlogin.storage import Store


class FakeLocator:
    first = None

    def __init__(self):
        self.first = self

    async def inner_text(self, **_kwargs):
        return "SYNTHETIC_FIXTURE_TEXT"


class FakePage:
    def locator(self, _selector):
        return FakeLocator()


class GraphReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name))
        self.profile = self.store.save(Profile(name="Graph reporting synthetic fixture"))
        self.manager = SharedBrowserManager(self.store, headless=True)
        self.session = Session(self.profile)
        self.manager._sessions[self.profile.id] = self.session

    def tearDown(self):
        self.store.close_thread_connection()
        self.temp.cleanup()

    def test_graph_total_steps_reports_nodes_not_json_keys(self):
        graph = steps_to_graph([
            {"action": "wait", "seconds": 0},
            {"action": "extract_text", "selector": "h1"},
            {"action": "wait", "seconds": 0},
        ])
        self.assertEqual(len(graph["nodes"]), 5)
        def consume(coroutine):
            coroutine.close()  # test enqueue accounting without running browser
        with patch.object(self.manager, "_submit", side_effect=consume):
            self.manager.run_graph(self.profile.id, graph)
        record = self.manager.last_run(self.profile.id)
        self.assertEqual(record["total_steps"], 5)
        self.assertEqual(record["status"], "queued")

    def test_graph_extract_text_reports_actual_positive_action_ordinal(self):
        graph = steps_to_graph([
            {"action": "wait", "seconds": 0},
            {"action": "extract_text", "selector": "h1"},
        ])
        self.session.context = type("SyntheticContext", (), {"pages": [FakePage()]})()
        self.session.ready.set()
        self.manager._runs[self.profile.id] = {
            "id": "synthetic-run", "status": "queued",
            "total_steps": len(graph["nodes"]), "extracted": [], "error": None,
        }
        self.manager._active.add(self.profile.id)
        asyncio.run(self.manager._perform(self.session, graph, "graph"))
        result = self.manager.last_run(self.profile.id)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["extracted"], [{
            "step": 2, "text": "SYNTHETIC_FIXTURE_TEXT", "truncated": False,
        }])


if __name__ == "__main__":
    unittest.main()
