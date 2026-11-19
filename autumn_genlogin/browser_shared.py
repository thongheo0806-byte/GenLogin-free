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
from uuid import uuid4

from .engines import browser_options
from .extensions import ExtensionLibrary
from .graph import execute_graph, validate_graph
from .locks import ProfileLease
from .models import validated_steps, valid_http_url
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
    const el=ev.target && ev.target.closest('button,a,input[type=button],input[type=submit]');
    if (el) { const s=selector(el); if (s) send({action:'click',selector:s}); }
  }, true);
  document.addEventListener('change', function(ev) {
    const el=ev.target;
    if (!el || !el.tagName) return;
    const s=selector(el);
    if (!s) return;
    if (el.tagName==='SELECT') return send({action:'select_option',selector:s,value:String(el.value).slice(0,256)});
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


class SharedBrowserManager:
    MAX_BROWSERS = 6
    RUN_RESULT_TTL_SECONDS = 15*60

    def __init__(self,store,*,headless=False):
        self.store=store
        self.headless=headless
        self.extensions=ExtensionLibrary(store)
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
            try: loop.run_until_complete(self._playwright.stop())
            except Exception: pass
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
        if self.count(): raise RuntimeError("Close profiles before stopping driver")
        if self._loop and self._loop.is_running():self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:self._thread.join(timeout=10)

    def run_steps(self,pid:str,steps:object):
        self._enqueue(pid,validated_steps(steps),"steps")

    def run_graph(self,pid:str,graph:object):
        self._enqueue(pid,validate_graph(graph),"graph")

    def start_workflow(self,pid:str,workflow:object):
        opened=False
        if not self.active(pid):
            self.start(pid);opened=True
        with self._lock:
            session=self._sessions[pid]
            if opened:session.auto_close=True
        if isinstance(workflow,list):self.run_steps(pid,workflow)
        else:self.run_graph(pid,workflow)

    def _enqueue(self,pid,payload,kind):
        with self._lock:
            session=self._sessions.get(pid)
            if not session: raise ValueError("Open the profile first")
            if pid in self._active: raise ValueError("Automation already running")
            self._active.add(pid)
            session.cancel.clear()
            self._runs[pid]={"id":str(uuid4()),"status":"queued","total_steps":len(payload),
                             "extracted":[],"error":None}
            self._run_timestamps[pid]=time.monotonic()
        try:
            fut=self._submit(self._perform(session,payload,kind))
        except Exception:
            with self._lock:self._active.discard(pid)
            raise
        # Task identity is tracked inside _perform rather than on this future.

    async def _perform(self,session,payload,kind):
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
                outcome=await execute_graph(payload,action=step_action,exists=exists,cancelled=session.cancel.is_set)
                if outcome["status"]=="cancelled":session.cancel.set()
            self._run_status(pid,"cancelled" if session.cancel.is_set() else "succeeded")
        except asyncio.CancelledError:
            self._run_status(pid,"cancelled")
        except Exception as exc:
            self._run_status(pid,"failed",self._error(exc,""))
            self.events.put((pid,"error",self._error(exc,"")))
        finally:
            with self._lock:self._active.discard(pid)
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
        with self._lock:
            session=self._sessions.get(pid)
            if session:session.cancel.set()

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
        session.recorded=[]
        session.recording=True
        if not session.binding_added:
            async def binding(source,payload):
                if not session.recording or len(session.recorded)>=100 or not isinstance(payload,dict):return
                try:record=validated_steps([payload])[0]
                except (ValueError,TypeError):return
                session.recorded.append(record)
                self.events.put((session.profile.id,"recorded",record["action"]))
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
            return deepcopy(session.recorded) if session else []

    @staticmethod
    def _error(exc,secret):
        message=f"{type(exc).__name__}: {exc}"
        return (message.replace(secret,"[REDACTED]") if secret else message)[:500]
