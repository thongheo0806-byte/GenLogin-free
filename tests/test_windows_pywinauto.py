"""Actual Win32 window inspection and OS-level GUI controls through pywinauto.

Unlike the Tk 'structure-only' smoke test, this asks the operating system
whether the real AutumnGenLogin top-level window exists and is interactable.
It still does not prove every nested Tk widget is exposed to Windows UIA,
screen-reader access or keyboard navigation. An interactive desktop is
required for deeper click/keyboard tests and must be provisioned separately.
"""
import os
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(os.name == "nt" and os.environ.get("AUTUMN_PYWINAUTO_SMOKE") == "1",
                     "requires Windows, explicit UIA flag and pywinauto")
class WindowsPywinautoSmokeTests(unittest.TestCase):
    def test_real_application_window_is_visible_to_os_and_managed(self):
        import tkinter as tk
        from pywinauto import Desktop
        from autumn_genlogin.models import Profile
        from autumn_genlogin.ui import App

        with tempfile.TemporaryDirectory() as temp:
            old = os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"] = temp
            root = tk.Tk()
            try:
                app = App(root)
                app.store.save(Profile(name="UIA fixture",group_name="QA"))
                app.refresh()
                root.update()
                windows = [w for w in Desktop(backend="win32").windows()
                           if w.process_id() == os.getpid()
                           and "AutumnGenLogin" in w.window_text()]
                self.assertEqual(len(windows),1,
                                 "OS must enumerate exactly one GUI root window")
                win = windows[0]
                self.assertTrue(win.is_visible())
                self.assertTrue(win.is_enabled())
                self.assertIn("Local Browser Studio",win.window_text())
                rect = win.rectangle()
                self.assertGreater(rect.width(),750)
                self.assertGreater(rect.height(),400)
                self.assertEqual(len(app.store.all()),1)
                self.assertEqual(app.store.all()[0].name,"UIA fixture")

                # A real OS message, not a Tk-only view assertion.
                win.minimize()
                root.update()
                self.assertTrue(win.is_minimized(),"Win32 minimize must affect GUI state")
                win.restore()
                root.update()
                self.assertFalse(win.is_minimized(),"Win32 restore must affect GUI state")
                self.assertIsNotNone(app.extension_tree)
                self.assertIsNotNone(app.graph_builder)
                self.assertIsNotNone(app.builder)
            finally:
                root.destroy()
                if old is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"] = old


if __name__=="__main__":
    unittest.main()
