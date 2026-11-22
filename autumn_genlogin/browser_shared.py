"""One async Playwright driver, one event loop, many isolated persistent contexts.

All Playwright objects stay on the dedicated async loop thread. Tk/HTTP threads
only schedule work through call_soon_threadsafe. No stealth or fingerprint
spoofing: standard browser engine/context options only.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

from .engines import browser_options
from .extensions import ExtensionLibrary
from .image_actions import ImageTemplateLibrary, find_image_center
from .graph import execute_graph, validate_graph
from .locks import ProfileLease
from .models import validated_steps, valid_http_url
from .recording import append_recorded_event, review_recording
from .secrets import get_password

RECORD_SCRIPT = r"""(() => {
  if (window.__autumnRecordingInstalled) return;
  window.__autumnRecordingInstalled = true;
  function esc(s) { return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&'); }
  function selector(el) {
    if (!el || !el.tagName) return null;
    if (el.id) return '#' + esc(el.id);
    const test = el.getAttribute('data-testid');
    if (test && /^[\w-]{1,100}$/.test(test)) return '[data-testid="' + test + '"]';
    const name = el.getAttribute('name');
    if (name && /^[\w-]{1,100}$/.test(name)) return el.tagName.toLowerCase() + '[name="' + name + '"]';
    let path=[];
    while (el && el.tagName && path.length<5) {
      let part=el.tagName.toLowerCase();
      const parent=el.parentElement;
      if (parent) {
        const siblings=Array.from(parent.children).filter(x => x.tagName===el.tagName);
        if (siblings.length>1) part+=':nth-of-type('+(siblings.indexOf(el)+1)+')';
      }
      path.unshift(part);
      el=parent;
    }
    return path.join(' > ');
  }
  function send(event) {
    if (window.__autumnRecord) window.__autumnRecord(event).catch(() => {});
  }
  document.addEventListener('click', function(ev) {
    const el=ev.target && ev.target.closest('button,a,input[type=button],input[type=submit],[role=button]');
    if (el) { const s=selector(el); if (s) send({action:'click',selector:s}); }
  }, true);
  // Capture only structural browser actions. Never read input values or page URL.
  document.addEventListener('keydown', function(ev) {
    if (!['Enter','Escape'].includes(ev.key) || !ev.target || !ev.target.closest) return;
    // Never record keystrokes on credentials, email, telephone or number inputs.
    const el=ev.target.closest('button,a,[role=button],textarea,input:not([type]),input[type=search],input[type=text]');
    if (!el || el.closest('input[type=password]')) return;
    const s=selector(el);
    if (s) send({action:'press',selector:s,key:ev.key});
  }, true);
  document.addEventListener('change', function(ev) {
    const el=ev.target;
    if (!el || !el.tagName) return;
    const s=selector(el);
    if (!s) return;
    if (el.tagName==='SELECT') return send({action:'select_option',selector:s,value:'REVIEW_OPTION'}); // option values can contain PII
    if (el.type==='checkbox') return send({action:el.checked?'check':'uncheck',selector:s});
    if (el.tagName==='INPUT' || el.tagName==='TEXTAREA')
      send({action:'fill',selector:s,text:''}); // NEVER record passwords, secrets or PII.
  }, true);
})();"""


@dataclass
class Session:
    profile: object
    cancel: threading.Event = field(default_factory=threading.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)
    context: object = None
    task: asyncio.Task | None = None
    automation: asyncio.Task | None = None
    auto_close: bool = False
    recording: bool = False
    recorded: list[dict] = field(default_factory=list)
    binding_added: bool = False
    recorded_navigation_count: int = 0
    recorder_page_observers: set[int] = field(default_factory=set)
    recorder_page_hooked: bool = False
    recorder_page: object = None
    recorder_ignored_pages: set[int] = field(default_factory=set)
    recorder_selected_page_closed: bool = False


class SharedBrowserManager:
    MAX_BROWSERS = 6
    RUN_RESULT_TTL_SECONDS = 15*60

    def __init__(self,store,*,headless=False):
        self.store=store
        self.headless=headless
        self.extensions=ExtensionLibrary(store)
        self.image_templates=ImageTemplateLibrary(store)
        self.events: queue.Queue[tuple[str,str,str]]=queue.Queue()
        self._lock=threading.RLock()
        self._sessions:dict[str,Session]={}
        self._active:set[str]=set()
        self._runs:dict[str,dict]={}
        self._run_timestamps:dict[str,float]={}
        self._loop=None
        self._thread=None
        self._playwright=None
        self._started=threading.Event()
        self._start_error=None
        self._startup_lock=threading.Lock()

    def _ensure_loop(self):
        with self._startup_lock:
            if self._thread is None:
                self._thread=threading.Thread(target=self._thread_main,name="autumn-playwright-shared",daemon=True)
                self._thread.start()
        if not self._started.wait(15): raise RuntimeError("Playwright driver startup timed out")
        if self._start_error: raise RuntimeError("Playwright driver unavailable") from self._start_error

    def _thread_main(self):
        loop=asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop=loop
        try:
            from playwright.async_api import async_playwright
            self._playwright=loop.run_until_complete(async_playwright().start())
        except Exception as exc:
            self._start_error=exc
        finally:
            self._started.set()
        if self._start_error:
            loop.close();return
        try: loop.run_forever()
        finally:
            tasks=asyncio.all_tasks(loop)
            for task in tasks: task.cancel()
            if tasks:
                loop.run_until_complete(asyncio.gather(*tasks,return_exceptions=True))
            if self._playwright is not None:
                try: loop.run_until_complete(self._playwright.stop())
                except Exception: pass
                self._playwright = None
            # Drain subprocess/pipe callbacks before closing the Proactor loop.
            try: loop.run_until_complete(asyncio.sleep(0.4))
            except Exception: pass
            try:
                self.store.close_thread_connection()
            except Exception:
                pass
            loop.close()

    def _submit(self,coro):
        self._ensure_loop()
        return asyncio.run_coroutine_threadsafe(coro,self._loop)

    def active(self,pid:str)->bool:
        with self._lock:return pid in self._sessions

    def count(self)->int:
        with self._lock:return len(self._sessions)

    def start(self,pid:str)->None:
        profile=self.store.get(pid)
        with self._lock:
            if pid in self._sessions: raise ValueError("This profile is already open")
            if len(self._sessions)>=self.MAX_BROWSERS: raise ValueError("Maximum six browser profiles")
            self._sessions[pid]=Session(profile)
        try: self._submit(self._open(self._sessions[pid]))
        except BaseException:
            with self._lock: self._sessions.pop(pid,None)
            raise
        self.events.put((pid,"status","Starting browser..."))

    async def _open(self,session:Session):
        profile=session.profile;pid=profile.id
        lease=ProfileLease(self.store.base,pid)
        acquired=False
        password=""
        try:
            lease.__enter__();acquired=True
            paths=self.extensions.paths_for(pid)
            if profile.proxy_username: password=get_password(pid) or ""
            kind,opts=browser_options(profile,str(self.store.profile_path(pid)),headless=self.headless,
                                      extension_paths=paths,proxy_password=password)
            browser_type=getattr(self._playwright,kind)
            context=await browser_type.launch_persistent_context(**opts)
            session.context=context
            if session.closed.is_set():
                await context.close()
                return
            context.on("close",lambda _:session.closed.set())
            def page_added(page):
                page.on("close",lambda _:asyncio.create_task(self._on_page_closed(session)))
            context.on("page",page_added)
            for page in context.pages:page_added(page)
            page=context.pages[0] if context.pages else await context.new_page()
            try: await page.goto(profile.start_url,wait_until="domcontentloaded",timeout=30000)
            except Exception as exc:
                from playwright._impl._errors import TargetClosedError
                if isinstance(exc,TargetClosedError) or session.closed.is_set(): return
                self.events.put((pid,"log","Start URL unavailable: "+self._error(exc,password)))
            session.ready.set()
            self.events.put((pid,"status","Running"))
            await session.closed.wait()
        except asyncio.CancelledError: raise
        except Exception as exc:
            self.events.put((pid,"error",self._error(exc,password)))
        finally:
            session.closed.set()
            session.cancel.set()
            session.ready.set()  # queued jobs must wake even after a failed launch
            if session.automation and not session.automation.done():
                session.automation.cancel()
            if session.context:
                try: await session.context.close()
                except Exception: pass
            if acquired:
                lease.__exit__(None,None,None)
            with self._lock:
                self._sessions.pop(pid,None)
                self._active.discard(pid)
                self._runs.pop(pid,None)
                self._run_timestamps.pop(pid,None)
            self.events.put((pid,"status","Stopped"))

    async def _on_page_closed(self,session):
        if session.context and not session.context.pages:
            try: await session.context.close()
            except Exception: pass

    def stop(self,pid:str):
        with self._lock:
            session=self._sessions.get(pid)
            if session: session.cancel.set()
        if session and self._loop:
            self._loop.call_soon_threadsafe(lambda:asyncio.create_task(self._stop_session(session)))

    async def _stop_session(self,session:Session):
        if session.automation and session.automation is not asyncio.current_task() and not session.automation.done():session.automation.cancel()
        if session.context:
            try: await session.context.close()
            except Exception:pass
        else:
            session.closed.set()

    def stop_all(self):
        with self._lock: ids=list(self._sessions)
        for pid in ids:self.stop(pid)

    def close_driver(self):
        """Gracefully stop the shared Playwright subprocess before closing its loop.

        An abruptly stopped Windows Proactor loop can leave Chromium profile files
        locked even after the last context has reported closed. Waiting for the
        async driver shutdown to finish is a correctness requirement, not a sleep
        substituted for cancellation.
        """
        if self.count():
            raise RuntimeError("Close profiles before stopping driver")
        loop = self._loop
        if loop and loop.is_running():
            async def finalize():
                if self._playwright is not None:
                    driver = self._playwright
                    await driver.stop()
                    self._playwright = None
                # Allow Windows Proactor pipe close callbacks to run while
                # the event loop is still alive.
                await asyncio.sleep(0.4)
            future = asyncio.run_coroutine_threadsafe(finalize(), loop)
            future.result(timeout=20)
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                raise RuntimeError("Shared Playwright driver did not shut down")

    def run_steps(self,pid:str,steps:object,*,run_id=None,on_finish=None):
        return self._enqueue(pid,validated_steps(steps),"steps",run_id=run_id,on_finish=on_finish)

    def run_graph(self,pid:str,graph:object,*,run_id=None,on_finish=None):
        return self._enqueue(pid,validate_graph(graph),"graph",run_id=run_id,on_finish=on_finish)

    def start_workflow(self,pid:str,workflow:object,*,run_id=None,on_finish=None):
        opened=False
        if not self.active(pid):
            self.start(pid);opened=True
        with self._lock:
            session=self._sessions[pid]
            if opened:session.auto_close=True
        try:
            if isinstance(workflow,list):
                return self.run_steps(pid,workflow,run_id=run_id,on_finish=on_finish)
            return self.run_graph(pid,workflow,run_id=run_id,on_finish=on_finish)
        except BaseException:
            if opened:
                self.stop(pid)
            raise

    def _enqueue(self,pid,payload,kind,*,run_id=None,on_finish=None):
        ident = str(UUID(run_id)) if run_id is not None else str(uuid4())
        with self._lock:
            session=self._sessions.get(pid)
            if not session: raise ValueError("Open the profile first")
            if pid in self._active: raise ValueError("Automation already running")
            self._active.add(pid)
            session.cancel.clear()
            self._runs[pid]={"id":ident,"status":"queued","total_steps":len(payload),
                             "extracted":[],"error":None}
            self._run_timestamps[pid]=time.monotonic()
        try:
            self._submit(self._perform(session,payload,kind,on_finish=on_finish))
        except BaseException:
            with self._lock:
                self._active.discard(pid)
                self._runs.pop(pid,None)
                self._run_timestamps.pop(pid,None)
            raise
        return ident

    async def _perform(self,session,payload,kind,*,on_finish=None):
        pid=session.profile.id
        task=asyncio.current_task()
        session.automation=task
        try:
            await session.ready.wait()
            if session.closed.is_set() or not session.context:
                raise RuntimeError("Browser failed to open")
            self._run_status(pid,"running")
            if kind=="steps":
                for i,step in enumerate(payload,1):
                    if session.cancel.is_set(): break
                    await self._action(session,step,i)
            else:
                async def step_action(step):await self._action(session,step,0)
                async def exists(selector):
                    page=await self._page(session)
                    return await page.locator(selector).first.count()>0
                async def capture(selector):
                    # Data is held only inside execute_graph's transient variables;
                    # never put captured text into extracted results or activity logs.
                    page=await self._page(session)
                    content=await page.locator(selector).first.inner_text(timeout=20000)
                    return content[:4096]
                outcome=await execute_graph(payload,action=step_action,exists=exists,
                                            capture=capture,cancelled=session.cancel.is_set)
                if outcome["status"]=="cancelled":session.cancel.set()
            self._run_status(pid,"cancelled" if session.cancel.is_set() else "succeeded")
        except asyncio.CancelledError:
            self._run_status(pid,"cancelled")
        except Exception as exc:
            self._run_status(pid,"failed",self._error(exc,""))
            self.events.put((pid,"error",self._error(exc,"")))
        finally:
            with self._lock:
                self._active.discard(pid)
                record = self._runs.get(pid)
                terminal_status = record["status"] if record else "failed"
                # Only the exception type is stored by the scheduler's durable
                # journal. Never persist browser page content or extracted text.
                error = record["error"] if record else None
            if on_finish is not None:
                try:
                    on_finish(terminal_status, error)
                except Exception:
                    self.events.put((pid,"error","Unable to persist scheduled run outcome"))
            self.events.put((pid,"log","Workflow finished"))
            if session.auto_close:
                await self._stop_session(session)

    async def _page(self,session):
        context=session.context
        return context.pages[0] if context.pages else await context.new_page()

    async def _action(self,session,step,i):
        pid=session.profile.id
        page=await self._page(session)
        action=step["action"]
        self.events.put((pid,"log",f"Step {i}: {action}"))
        if action=="goto":await page.goto(step["url"],wait_until="domcontentloaded",timeout=30000)
        elif action=="click":await page.locator(step["selector"]).first.click(timeout=20000)
        elif action=="click_image":
            template = self.image_templates.read(step["template_id"])
            # Keep screenshot transient. CSS scale avoids device-pixel-ratio drift.
            screen = await page.screenshot(full_page=False, scale="css")
            x, y = await asyncio.to_thread(find_image_center,screen,template,step["confidence"])
            if session.cancel.is_set():
                raise asyncio.CancelledError()
            await page.mouse.click(x,y)
        elif action=="fill":await page.locator(step["selector"]).first.fill(step["text"],timeout=20000)
        elif action=="press":await page.locator(step["selector"]).first.press(step["key"],timeout=20000)
        elif action=="check":await page.locator(step["selector"]).first.check(timeout=20000)
        elif action=="uncheck":await page.locator(step["selector"]).first.uncheck(timeout=20000)
        elif action=="select_option":await page.locator(step["selector"]).first.select_option(step["value"],timeout=20000)
        elif action=="scroll_into_view":await page.locator(step["selector"]).first.scroll_into_view_if_needed(timeout=20000)
        elif action=="wait_for":await page.locator(step["selector"]).first.wait_for(timeout=20000)
        elif action=="wait":
            remaining=step["seconds"]
            while remaining>0 and not session.cancel.is_set():
                delay=min(0.25,remaining)
                await asyncio.sleep(delay)
                remaining-=delay
        elif action=="screenshot":
            directory=self.store.shot_dir/pid;directory.mkdir(parents=True,exist_ok=True)
            target=directory/(datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".png")
            await page.screenshot(path=str(target),full_page=True)
            self.events.put((pid,"log",f"Screenshot saved: {target}"))
        elif action=="extract_text":
            value=await page.locator(step["selector"]).first.inner_text(timeout=20000)
            with self._lock:
                result=self._runs.get(pid)
                if result and len(result["extracted"])<20:
                    result["extracted"].append({"step":i,"text":value[:4096],"truncated":len(value)>4096})
            self.events.put((pid,"log",f"Extracted {len(value)} characters (not logged)"))

    def _run_status(self,pid,status,error=None):
        with self._lock:
            if pid in self._runs:
                self._runs[pid]["status"]=status
                self._runs[pid]["error"]=error

    def cancel(self,pid):
        """Interrupt an in-flight Playwright wait, not just the next step.

        Browser objects and asyncio tasks must only be touched on the shared
        driver's event loop. A cancellation before task startup remains latched
        through session.cancel for the next action/graph check.
        """
        with self._lock:
            session=self._sessions.get(pid)
            task=session.automation if session else None
            if session:
                session.cancel.set()
            loop=self._loop
        if task and loop and loop.is_running():
            def interrupt():
                if not task.done():
                    task.cancel()
            try:
                loop.call_soon_threadsafe(interrupt)
            except RuntimeError:
                # Driver already shutting down: session cancellation is latched.
                pass

    def last_run(self,pid):
        with self._lock:
            age=self._run_timestamps.get(pid)
            if age is not None and time.monotonic()-age>=self.RUN_RESULT_TTL_SECONDS:
                self.clear_run(pid)
            return deepcopy(self._runs.get(pid))

    def clear_run(self,pid):
        with self._lock:
            self._runs.pop(pid,None);self._run_timestamps.pop(pid,None)

    def start_recording(self,pid):
        with self._lock:
            session=self._sessions.get(pid)
            if not session:raise ValueError("Open profile before recording")
        return self._submit(self._install_recorder(session)).result(timeout=15)

    async def _install_recorder(self,session):
        await session.ready.wait()
        if not session.context or session.closed.is_set(): return
        # The runner replays actions against the FIRST page of a context.
        # Capturing arbitrary other tabs into that workflow is misleading
        # and could click a different element when replayed.
        selected = (session.context.pages[0] if session.context.pages
                    else await session.context.new_page())
        with self._lock:
            session.recorded=[]
            session.recorded_navigation_count=0
            session.recorder_page=selected
            session.recorder_ignored_pages={id(p) for p in session.context.pages
                                            if p is not selected}
            session.recorder_selected_page_closed=False
            session.recording=True
        if not session.recorder_page_hooked:
            def observe_page(page):
                identity = id(page)
                if identity in session.recorder_page_observers:
                    return
                session.recorder_page_observers.add(identity)
                def count_navigation():
                    with self._lock:
                        if session.recording and page is session.recorder_page:
                            session.recorded_navigation_count = min(
                                session.recorded_navigation_count + 1, 1000)
                def closing():
                    session.recorder_page_observers.discard(identity)
                    with self._lock:
                        if session.recording and page is session.recorder_page:
                            session.recording=False
                            session.recorder_selected_page_closed=True
                page.on("domcontentloaded", lambda *_: count_navigation())
                page.on("close", lambda *_: closing())
                with self._lock:
                    if session.recording and page is not session.recorder_page:
                        session.recorder_ignored_pages.add(identity)
            session.context.on("page", observe_page)
            for existing_page in session.context.pages:
                observe_page(existing_page)
            session.recorder_page_hooked=True
        if not session.binding_added:
            async def binding(source,payload):
                if not session.recording:
                    return
                # Only main-frame CSS selectors currently replay correctly.
                # Reject iframes instead of later pretending that a selector
                # from a nested browsing context can be used on the top page.
                frame, page = source.get("frame"), source.get("page")
                if frame is None or page is None or frame != page.main_frame:
                    return
                with self._lock:
                    if page is not session.recorder_page:
                        # Content of another browser tab must never be mixed
                        # into the first-tab replay plan.
                        session.recorder_ignored_pages.add(id(page))
                        return
                    if not append_recorded_event(session.recorded,payload):
                        return
                    action=session.recorded[-1]["action"]
                self.events.put((session.profile.id,"recorded",action))
            await session.context.expose_binding("__autumnRecord",binding)
            session.binding_added=True
        await session.context.add_init_script(RECORD_SCRIPT)
        for page in session.context.pages:
            try:await page.evaluate(RECORD_SCRIPT)
            except Exception:pass
        self.events.put((session.profile.id,"log","Recorder ON: text values are redacted"))

    def stop_recording(self,pid):
        with self._lock:
            session=self._sessions.get(pid)
            if session:session.recording=False

    def recorded_steps(self,pid):
        with self._lock:
            session=self._sessions.get(pid)
            return review_recording(session.recorded).steps if session else []

    def recording_review(self,pid):
        with self._lock:
            session=self._sessions.get(pid)
            if not session:
                return None
            report=review_recording(
                session.recorded,
                navigation_boundaries=session.recorded_navigation_count,
                ignored_tabs=len(session.recorder_ignored_pages)
            ).public_summary()
            report["still_recording"]=bool(session.recording)
            report["selected_tab_closed"]=session.recorder_selected_page_closed
            if session.recorder_selected_page_closed:
                report["warnings"].append(
                    "The originally selected tab closed; re-record in the intended tab before replay."
                )
            return report

    @staticmethod
    def _error(exc,secret):
        message=f"{type(exc).__name__}: {exc}"
        return (message.replace(secret,"[REDACTED]") if secret else message)[:500]
