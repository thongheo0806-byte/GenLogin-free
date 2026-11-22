"""Windows UI layout smoke test; no real websites, no secrets."""
import os
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
