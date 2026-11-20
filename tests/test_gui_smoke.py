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
