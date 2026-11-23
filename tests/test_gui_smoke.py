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
                    completed=threading.Event()
                    submit=app._run_ui_task
                    def tracked(task,finished=None,**kwargs):
                        def callback(result):
                            if finished is not None:
                                finished(result)
                            completed.set()
                        return submit(task,callback,**kwargs)
                    with worker_patch(slow), patch.object(app,"_run_ui_task",side_effect=tracked):
                        with patch.object(app,"selected_id",return_value=master.id):
                            trigger()
                            self.assertTrue(entered.wait(timeout=2))
                            heartbeat=threading.Event()
                            root.after(25,heartbeat.set)
                            self.assertTrue(pump(heartbeat.is_set,seconds=1),
                                            "Tk event loop froze behind a slow worker")
                            self.assertFalse(completed.is_set(),
                                             "Slow worker unexpectedly completed before release")
                            release.set()
                            self.assertTrue(pump(completed.is_set,seconds=4),
                                            "Worker completion was not handled on the Tk loop")

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


    def test_window_close_shuts_down_playwright_off_tk_thread(self):
        """Tk heartbeats continue until driver shutdown completes; close is once."""
        import tkinter as tk
        from autumn_genlogin.ui import App

        with tempfile.TemporaryDirectory() as temp:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=temp
            root=tk.Tk()
            root.withdraw()
            entered=threading.Event()
            release=threading.Event()
            destroyed=threading.Event()
            calls=[]
            def close_driver():
                calls.append("close")
                entered.set()
                self.assertTrue(release.wait(timeout=5), "Test did not release shutdown")
            def pump(predicate, seconds=5):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    try:
                        root.update()
                    except tk.TclError:
                        if predicate(): return True
                        raise
                    if predicate():return True
                    time.sleep(0.01)
                return False
            try:
                app=App(root)
                root.bind("<Destroy>",
                          lambda event:destroyed.set() if event.widget is root else None,
                          add="+")
                with patch.object(app.manager,"close_driver",side_effect=close_driver):
                    app.on_quit()
                    app.on_quit()
                    self.assertTrue(pump(entered.is_set), "Shutdown worker never started")
                    heartbeat=threading.Event()
                    root.after(25,heartbeat.set)
                    self.assertTrue(pump(heartbeat.is_set,seconds=1),
                                    "Closing driver blocked the Tk event loop")
                    self.assertFalse(destroyed.is_set())
                    release.set()
                    self.assertTrue(pump(destroyed.is_set),
                                    "GUI did not destroy after driver closed")
                    self.assertEqual(calls,["close"])
            finally:
                release.set()
                if not destroyed.is_set():
                    root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


    def test_cloud_pull_gui_refuses_unverified_overlap_and_adds_disjoint_profile(self):
        """Real Tk Pull callback never silently clobbers an edited local UUID."""
        import tkinter as tk
        from types import SimpleNamespace
        from autumn_genlogin.ui import App
        from autumn_genlogin.models import Profile
        from autumn_genlogin.team_sync import safe_profile_metadata
        with tempfile.TemporaryDirectory() as temp:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=temp
            root=tk.Tk()
            root.withdraw()
            try:
                app=App(root)
                local=app.store.save(Profile(name="Local profile"))
                app.refresh()
                original=safe_profile_metadata(app.store)
                conflicting={"format":original["format"],"profiles":[
                    {**original["profiles"][0],"name":"Remote overwrite"}
                ]}
                cloud=SimpleNamespace(
                    url="http://127.0.0.1:8899",
                    pull=lambda *args:(1,conflicting),
                )
                app.cloud=cloud
                app.cloud_fields["team_id"].set("synthetic-team")
                app.cloud_fields["passphrase"].set("synthetic shared password")
                warnings=[]
                def immediate(task,finished=None):
                    result=task()
                    if finished is not None:finished(result)
                with (patch.object(app,"_cloud_action",side_effect=immediate),
                      patch("autumn_genlogin.ui.messagebox.showwarning",
                            side_effect=lambda *args,**kwargs:warnings.append(args)),
                      patch("autumn_genlogin.ui.messagebox.askyesno",return_value=True)):
                    app.cloud_sync("profiles","pull")
                    self.assertTrue(warnings,"Conflict must be visible to user")
                    self.assertEqual(app.store.get(local.id).name,"Local profile")
                    self.assertFalse(app.cloud_bases)

                    added=Profile(name="Remote-only QA")
                    remote={"format":original["format"],"profiles":[
                        {**original["profiles"][0],
                         "id":added.id,"name":added.name}
                    ]}
                    cloud.pull=lambda *args:(2,remote)
                    app.cloud_sync("profiles","pull")
                    self.assertEqual(app.store.get(local.id).name,"Local profile")
                    self.assertEqual(app.store.get(added.id).name,"Remote-only QA")
                    self.assertEqual(len(app.cloud_bases),1)
            finally:
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


    def test_cloud_pull_slow_sqlite_apply_does_not_freeze_tk(self):
        """Full Tk heartbeat while a metadata merge holds a slow worker."""
        import tkinter as tk
        from types import SimpleNamespace
        from autumn_genlogin.ui import App
        from autumn_genlogin.models import Profile
        from autumn_genlogin.team_sync import merge_safe_profiles as real_apply
        with tempfile.TemporaryDirectory() as home:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=home
            root=tk.Tk()
            root.withdraw()
            entered=threading.Event()
            release=threading.Event()
            def pump(predicate,seconds=6):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    root.update()
                    if predicate():
                        return True
                    time.sleep(0.01)
                return False
            try:
                app=App(root)
                source=Profile(name="Remote QA profile")
                keys=("id","name","group_name","tags","browser","start_url",
                      "locale","timezone_id","viewport_width","viewport_height")
                document={"format":"AutumnGenLogin/profile-metadata-1",
                          "profiles":[{k:getattr(source,k) for k in keys}]}
                app.cloud=SimpleNamespace(
                    url="http://127.0.0.1:8899",
                    pull=lambda *args:(1,document))
                app.cloud_fields["team_id"].set("fixture-team")
                app.cloud_fields["passphrase"].set("synthetic team passphrase")
                def slow(*args,**kwargs):
                    entered.set()
                    if not release.wait(timeout=5):
                        raise RuntimeError("Test worker was never released")
                    return real_apply(*args,**kwargs)
                with (patch("autumn_genlogin.team_sync.merge_safe_profiles",
                            side_effect=slow),
                      patch("autumn_genlogin.ui.messagebox.askyesno",
                            return_value=True)):
                    app.cloud_sync("profiles","pull")
                    self.assertTrue(pump(entered.is_set),
                                    "Cloud apply worker was not reached")
                    self.assertIsNone(app.store.all()[0] if app.store.all() else None)
                    heartbeat=threading.Event()
                    root.after(25,heartbeat.set)
                    self.assertTrue(pump(heartbeat.is_set,seconds=1),
                                    "Slow metadata merge blocked Tk event loop")
                    release.set()
                    self.assertTrue(pump(
                        lambda:any(p.id==source.id and p.name==source.name
                                   for p in app.store.all())),
                        "Worker did not install metadata")
                    self.assertTrue(pump(lambda:bool(app.cloud_bases)),
                                    "Tk did not accept remote baseline after apply")
            finally:
                release.set()
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


    def test_slow_schedule_list_and_history_keep_tk_heartbeat_alive(self):
        import tkinter as tk
        from autumn_genlogin.ui import App

        with tempfile.TemporaryDirectory() as home:
            previous=os.environ.get("AUTUMN_GENLOGIN_HOME")
            os.environ["AUTUMN_GENLOGIN_HOME"]=home
            root=tk.Tk()
            root.withdraw()
            entered=threading.Event()
            release=threading.Event()
            done=threading.Event()
            def pump(predicate,seconds=6):
                deadline=time.monotonic()+seconds
                while time.monotonic()<deadline:
                    root.update()
                    if predicate():return True
                    time.sleep(0.01)
                return False
            try:
                app=App(root)
                original=app.schedule_store.list
                # Initial async refresh from app construction can be pending.
                self.assertTrue(pump(lambda:app._ui_task_results.empty(),seconds=3))
                def stalled_list():
                    entered.set()
                    if not release.wait(timeout=5):
                        raise RuntimeError("Scheduler test worker not released")
                    return original()
                with patch.object(app.schedule_store,"list",side_effect=stalled_list):
                    app.refresh_schedules()
                    self.assertTrue(pump(entered.is_set))
                    heartbeat=threading.Event()
                    root.after(25,heartbeat.set)
                    self.assertTrue(pump(heartbeat.is_set,seconds=1),
                                    "Schedule SQL blocked Tk event loop")
                    release.set()
                    self.assertTrue(pump(
                        lambda:not app._ui_task_results.qsize() and
                        not any(t.name=="autumn-ui-worker" for t in
                                threading.enumerate()),
                        seconds=5))
            finally:
                release.set()
                root.destroy()
                if previous is None:
                    os.environ.pop("AUTUMN_GENLOGIN_HOME",None)
                else:
                    os.environ["AUTUMN_GENLOGIN_HOME"]=previous


if __name__ == "__main__":
    unittest.main()
