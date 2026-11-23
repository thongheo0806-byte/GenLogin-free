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


    def test_mouse_keyboard_create_profile_through_real_gui(self):
        """Actual OS mouse/keyboard events drive a Tk modal and persisted profile."""
        import tkinter as tk
        from tkinter import ttk
        from pywinauto import Desktop, mouse, keyboard
        from autumn_genlogin.ui import App, ProfileEditor

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        def click_center(widget, root):
            root.update()
            self.assertTrue(widget.winfo_viewable(), "GUI target must be visible")
            point = (widget.winfo_rootx() + widget.winfo_width()//2,
                     widget.winfo_rooty() + widget.winfo_height()//2)
            mouse.click(button="left", coords=point)
            root.update()

        with tempfile.TemporaryDirectory() as home:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=home
            root=tk.Tk()
            try:
                app=App(root)
                root.update()
                new_buttons=[w for w in walk(root)
                             if isinstance(w,ttk.Button)
                             and w.cget("text")=="+ New profile"]
                self.assertEqual(len(new_buttons),1)
                click_center(new_buttons[0],root)
                modals=[w for w in root.winfo_children()
                        if isinstance(w,ProfileEditor)]
                self.assertEqual(len(modals),1,
                    "Real OS click did not open Create profile dialog")
                editor=modals[0]
                self.assertEqual(editor.title(),"Create profile")
                top_windows=[w for w in Desktop(backend="win32").windows()
                             if w.process_id()==os.getpid()
                             and w.window_text()=="Create profile"]
                self.assertEqual(len(top_windows),1,
                    "Win32 must enumerate the genuine new-profile dialog")
                name_fields=[w for w in walk(editor)
                             if isinstance(w,ttk.Entry)
                             and str(w.cget("textvariable"))==str(editor.fields["name"])]
                self.assertEqual(len(name_fields),1)
                click_center(name_fields[0],root)
                keyboard.send_keys("^a")
                keyboard.send_keys("Real_Win32_Input_QA",with_spaces=True,pause=0.01)
                root.update()
                self.assertEqual(editor.fields["name"].get(),"Real_Win32_Input_QA",
                    "Real OS keyboard input did not enter profile name")
                save_buttons=[w for w in walk(editor)
                              if isinstance(w,ttk.Button)
                              and w.cget("text")=="Save profile"]
                self.assertEqual(len(save_buttons),1)
                click_center(save_buttons[0],root)
                self.assertEqual(editor.winfo_exists(),0)
                profiles=app.store.all()
                self.assertEqual(len(profiles),1)
                self.assertEqual(profiles[0].name,"Real_Win32_Input_QA")
                self.assertIn(profiles[0].id,app.tree.get_children())
            finally:
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


    def test_win32_workflow_editor_pointer_and_json_roundtrip(self):
        """Real OS clicks, not invoke(), exercise notebook and workflow editing."""
        import json
        import tkinter as tk
        from tkinter import ttk
        from pywinauto import mouse
        from autumn_genlogin.ui import App

        def descendants(widget):
            yield widget
            for child in widget.winfo_children():
                yield from descendants(child)

        def click(widget, root, bbox=None):
            root.update()
            self.assertTrue(widget.winfo_viewable())
            x,y,w,h=(bbox if bbox is not None
                     else (0,0,widget.winfo_width(),widget.winfo_height()))
            self.assertGreater(w,0)
            self.assertGreater(h,0)
            mouse.click(button="left",coords=(
                widget.winfo_rootx()+x+w//2,widget.winfo_rooty()+y+h//2))
            root.update()

        with tempfile.TemporaryDirectory() as home:
            old=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=home
            root=tk.Tk()
            try:
                app=App(root)
                root.update()
                main=next(n for n in descendants(root)
                          if isinstance(n,ttk.Notebook) and len(n.tabs())==9)
                # Hosted Windows desktop may report an empty Notebook tab
                # bbox even when its contents are real Win32-visible widgets.
                # Select the container via Tk, then drive the editor controls
                # with genuine OS pointer events below.
                main.select(1)
                root.update()
                self.assertEqual(main.index("current"),1)
                initial=app.builder.get_steps()
                tree=app.builder.tree
                tree.see("0")
                root.update()
                x,y,w,h=tree.bbox("0")
                self.assertGreater(h,0)
                mouse.click(button="left",coords=(
                    tree.winfo_rootx()+x+min(30,w//2),
                    tree.winfo_rooty()+y+h//2))
                root.update()
                self.assertEqual(tree.selection(),("0",))
                buttons=[b for b in descendants(app.builder) if isinstance(b,ttk.Button)]
                click(next(b for b in buttons if b.cget("text")=="Duplicate"),root)
                self.assertEqual(len(app.builder.get_steps()),len(initial)+1)
                click(next(b for b in buttons if b.cget("text")=="Remove"),root)
                self.assertEqual(app.builder.get_steps(),initial)
                app.flow_tabs.select(1)
                root.update()
                self.assertEqual(app.flow_tabs.index("current"),1)
                self.assertEqual(json.loads(app.workflow.get("1.0","end")),initial)
            finally:
                root.destroy()
                if old is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=old


    def test_win32_cloud_pull_conflict_button_refuses_local_overwrite(self):
        """Genuine OS pointer clicks drive a value-free Cloud Pull warning."""
        import tkinter as tk
        from tkinter import ttk
        from types import SimpleNamespace
        from unittest.mock import patch
        from pywinauto import mouse
        from autumn_genlogin.ui import App
        from autumn_genlogin.models import Profile
        from autumn_genlogin.team_sync import safe_profile_metadata

        def walk(widget):
            yield widget
            for child in widget.winfo_children():
                yield from walk(child)

        with tempfile.TemporaryDirectory() as home:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=home
            root=tk.Tk()
            try:
                app=App(root)
                saved=app.store.save(Profile(name="Win32 local",group_name="QA"))
                app.refresh()
                document=safe_profile_metadata(app.store)
                changed={"format":document["format"],"profiles":[
                    {**document["profiles"][0],"name":"REMOTE_SHOULD_NOT_WIN"}
                ]}
                cloud=SimpleNamespace(
                    url="http://127.0.0.1:8899",
                    pull=lambda *_:(1,changed),
                )
                app.cloud=cloud
                app.cloud_fields["team_id"].set("qa-team")
                app.cloud_fields["passphrase"].set("synthetic shared passphrase")
                notebook=next(w for w in walk(root)
                              if isinstance(w,ttk.Notebook) and len(w.tabs())==9)
                notebook.select(7)  # Team sync tab
                root.update()
                team_tab=root.nametowidget(notebook.tabs()[7])
                button=next(w for w in walk(team_tab)
                            if isinstance(w,ttk.Button)
                            and w.cget("text")=="Pull metadata")
                self.assertTrue(button.winfo_viewable())
                self.assertGreater(button.winfo_width(),20)
                warnings=[]
                def immediate(fn,finished=None):
                    result=fn()
                    if finished is not None:finished(result)
                def click():
                    root.update()
                    mouse.click(button="left",coords=(
                        button.winfo_rootx()+button.winfo_width()//2,
                        button.winfo_rooty()+button.winfo_height()//2))
                    root.update()
                with (patch.object(app,"_cloud_action",side_effect=immediate),
                      patch("autumn_genlogin.ui.messagebox.showwarning",
                            side_effect=lambda *args,**kwargs:warnings.append(args)),
                      patch("autumn_genlogin.ui.messagebox.askyesno",
                            side_effect=AssertionError("No overwrite approval on conflict"))):
                    click()
                self.assertTrue(warnings)
                self.assertEqual(app.store.get(saved.id).name,"Win32 local")
                self.assertFalse(app.cloud_bases)

                remote=Profile(name="Win32 remote only",group_name="QA")
                cloud.pull=lambda *_:(2,{"format":document["format"],
                    "profiles":[{**document["profiles"][0],
                                 "id":remote.id,"name":remote.name}]})
                with (patch.object(app,"_cloud_action",side_effect=immediate),
                      patch("autumn_genlogin.ui.messagebox.askyesno",
                            return_value=True)):
                    click()
                self.assertEqual(app.store.get(saved.id).name,"Win32 local")
                self.assertEqual(app.store.get(remote.id).name,"Win32 remote only")
                self.assertEqual(len(app.cloud_bases),1)
            finally:
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


if __name__=="__main__":
    unittest.main()
