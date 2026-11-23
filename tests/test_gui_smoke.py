"""Windows UI layout smoke test; no real websites, no secrets."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.environ.get("AUTUMN_GUI_SMOKE") == "1", "requires Windows desktop runner and AUTUMN_GUI_SMOKE=1")
class TkinterSmokeTests(unittest.TestCase):
    def test_profile_extensions_and_visual_workflow_panels_construct(self):
        import tkinter as tk
        from autumn_genlogin.ui import App
        with tempfile.TemporaryDirectory() as temp:
            previous = os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"] = temp
            root = tk.Tk()
            root.withdraw()
            try:
                app = App(root)
                root.update_idletasks()
                self.assertEqual(len(app.builder.get_steps()), 4)
                self.assertIsNotNone(app.extension_tree)
                self.assertEqual(len(app.extensions.list()), 0)
                self.assertIsNotNone(app.miniapp_tree)
                self.assertEqual(len(app.miniapps.list()), 0)
                record = app.miniapps.install({
                    "format":"AutumnGenLogin/miniapp-1","name":"GUI smoke",
                    "version":"1.0.0","description":"Synthetic workflow preview",
                    "category":"QA",
                    "workflow":[{"action":"wait_for","selector":"h1"}]})
                app.refresh_miniapps()
                self.assertEqual(app.miniapp_tree.get_children(), (record.id,))
                self.assertIn("trust",app.miniapp_tree["columns"])
                self.assertEqual(app.miniapp_tree.set(record.id,"trust"),"unsigned")
                self.assertEqual(app.miniapps.list_publishers(),[])
                # The user must have an explicit UI path to resume a failed
                # encrypted archive rather than automatically replay uploads.
                from tkinter import ttk
                def descendants(node):
                    for child in node.winfo_children():
                        yield child
                        yield from descendants(child)
                buttons=[w.cget("text") for w in descendants(root)
                         if isinstance(w,ttk.Button)]
                self.assertIn("Resume interrupted encrypted backup upload",buttons)
                self.assertIn("List team archives (admin)",buttons)
                self.assertIn("Trust publisher key",buttons)
                self.assertIn("Untrust publisher key",buttons)
                app.refresh()
                variable_graph={
                    "format":"AutumnGenLogin/graph-1",
                    "nodes":[{"id":"start","type":"start"},
                             {"id":"define","type":"set_variable","name":"word","value":"hello"},
                             {"id":"use","type":"action","step":{
                                 "action":"fill","selector":"#input","text":"{{word}}"}},
                             {"id":"end","type":"end"}],
                    "edges":[{"from":"start","to":"define","branch":"next"},
                             {"from":"define","to":"use","branch":"next"},
                             {"from":"use","to":"end","branch":"next"}],
                }
                app.graph_builder.set_graph(variable_graph)
                self.assertEqual(app.graph_builder.get_graph(),variable_graph)
            finally:
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME", None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"] = previous

    def test_slow_profile_recorder_and_qa_start_leave_tk_responsive(self):
        import tkinter as tk
        from autumn_genlogin.ui import App
        from autumn_genlogin.models import Profile

        with tempfile.TemporaryDirectory() as temp:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=temp
            root=tk.Tk()
            root.withdraw()
            try:
                app=App(root)
                master=app.store.save(Profile(name="QA Master",group_name="fixture"))
                follower=app.store.save(Profile(name="QA Follower",group_name="fixture"))
                app.refresh()

                def pump(predicate,seconds=5):
                    deadline=time.monotonic()+seconds
                    while time.monotonic()<deadline:
                        root.update()
                        if predicate():
                            return True
                        time.sleep(0.01)
                    return False

                def run_slow(trigger,worker_patch,done):
                    entered=threading.Event()
                    release=threading.Event()
                    def slow(*_args,**_kwargs):
                        entered.set()
                        release.wait(timeout=4)
                        return done
                    with worker_patch(slow):
                        with patch.object(app,"selected_id",return_value=master.id):
                            trigger()
                            self.assertTrue(entered.wait(timeout=2))
                            heartbeat=threading.Event()
                            root.after(25,heartbeat.set)
                            self.assertTrue(pump(heartbeat.is_set,seconds=1),
                                            "Tk event loop froze behind a slow worker")
                            release.set()
                            self.assertTrue(pump(
                                lambda:app._ui_task_results.empty(),seconds=4))
                            # Consume any result posted just after the initial
                            # queue-empty check and verify no latent worker.
                            self.assertTrue(pump(
                                lambda:not app._recorder_starting and
                                not app._qa_starting,seconds=4))

                run_slow(app.open_profile,
                         lambda fn:patch.object(app.manager,"start",side_effect=fn),
                         None)
                run_slow(app.start_recorder,
                         lambda fn:patch.object(app.manager,"start_recording",side_effect=fn),
                         None)
                self.assertFalse(app._recorder_starting)

                with (patch.object(app.manager,"active",return_value=True),
                      patch("autumn_genlogin.ui.messagebox.askyesno",return_value=True)):
                    run_slow(
                        app.start_qa_sync,
                        lambda fn:patch.object(app.qa_sync,"start",side_effect=fn),
                        {"origin":"http://127.0.0.1:8123","active":True},
                    )
                self.assertFalse(app._qa_starting)
            finally:
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


if __name__ == "__main__":
    unittest.main()
