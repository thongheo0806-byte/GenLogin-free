"""Playwright browser workers; every profile is handled in one dedicated thread."""
from __future__ import annotations

import queue
import threading
import time
from copy import deepcopy
from uuid import uuid4
from datetime import datetime

from .models import Profile, validated_steps
from .locks import ProfileLease
from .extensions import ExtensionLibrary
from .secrets import get_password
from .storage import Store


class BrowserManager:
    MAX_BROWSERS = 6
    RUN_RESULT_TTL_SECONDS = 15 * 60

    def __init__(self, store: Store, *, headless: bool = False):
        self.store = store
        # Headless is a documented testing / CI option, not an anonymity feature.
        self.headless = headless
        self.extensions = ExtensionLibrary(store)
        self.events: queue.Queue[tuple[str, str, str]] = queue.Queue()
        self._lock = threading.RLock()
        self._workers: dict[str, tuple[threading.Thread, queue.Queue]] = {}
        self._active: set[str] = set()
        self._cancel: dict[str, threading.Event] = {}
        # Last workflow only, bounded and held in memory. Never written to logs.
        self._runs: dict[str, dict] = {}
        self._run_timestamps: dict[str, float] = {}

    def active(self, profile_id: str) -> bool:
        with self._lock:
            return profile_id in self._workers

    def count(self) -> int:
        with self._lock:
            return len(self._workers)

    def start(self, profile_id: str) -> None:
        profile = self.store.get(profile_id)
        with self._lock:
            if profile_id in self._workers:
                raise ValueError("This profile is already open")
            if len(self._workers) >= self.MAX_BROWSERS:
                raise ValueError(f"Maximum {self.MAX_BROWSERS} concurrent browsers")
            cmds: queue.Queue = queue.Queue()
            cancel = threading.Event()
            worker = threading.Thread(target=self._run, args=(profile, cmds, cancel), name=f"browser-{profile.id[:8]}", daemon=True)
            self._workers[profile_id] = (worker, cmds)
            self._cancel[profile_id] = cancel
            self.events.put((profile_id, "status", "Starting browser..."))
            worker.start()

    def stop(self, profile_id: str) -> None:
        with self._lock:
            if profile_id in self._workers:
                self._cancel[profile_id].set()
                self._workers[profile_id][1].put(("stop", None))

    def stop_all(self) -> None:
        with self._lock:
            for pid in list(self._workers):
                self.stop(pid)

    def run_steps(self, profile_id: str, steps: object) -> None:
        validated = validated_steps(steps)
        with self._lock:
            if profile_id not in self._workers:
                raise ValueError("Open the profile before running automation")
            if profile_id in self._active:
                raise ValueError("Automation already running on this profile")
            self._active.add(profile_id)
            self._cancel[profile_id].clear()
            self._runs[profile_id] = {"id": str(uuid4()), "status": "queued",
                                      "total_steps": len(validated), "extracted": [],
                                      "error": None}
            self._run_timestamps[profile_id] = time.monotonic()
            self._workers[profile_id][1].put(("automation", validated))

    def cancel(self, profile_id: str) -> None:
        with self._lock:
            if profile_id in self._cancel:
                self._cancel[profile_id].set()

    def last_run(self, profile_id: str) -> dict | None:
        with self._lock:
            when = self._run_timestamps.get(profile_id)
            if when is not None and time.monotonic() - when >= self.RUN_RESULT_TTL_SECONDS:
                self._runs.pop(profile_id, None)
                self._run_timestamps.pop(profile_id, None)
            result = self._runs.get(profile_id)
            return deepcopy(result) if result is not None else None

    def clear_run(self, profile_id: str) -> None:
        with self._lock:
            self._runs.pop(profile_id, None)
            self._run_timestamps.pop(profile_id, None)

    def _run_status(self, profile_id: str, status: str, error: str | None = None) -> None:
        with self._lock:
            if profile_id in self._runs:
                self._runs[profile_id]["status"] = status
                self._runs[profile_id]["error"] = error

    def _record_extract(self, profile_id: str, step_no: int, value: str) -> None:
        with self._lock:
            result = self._runs.get(profile_id)
            if result and len(result["extracted"]) < 20:
                # Bounded preview; callers must opt in to extract_text explicitly.
                result["extracted"].append({"step": step_no, "text": value[:4096],
                                            "truncated": len(value) > 4096})

    def _run(self, profile: Profile, cmds: queue.Queue, cancel: threading.Event) -> None:
        try:
            with ProfileLease(self.store.base, profile.id):
                self._run_session(profile, cmds, cancel)
        except Exception as exc:
            self.events.put((profile.id, "error", self._safe_error(exc, "")))
            with self._lock:
                self._workers.pop(profile.id, None)
                self._active.discard(profile.id)
                self._cancel.pop(profile.id, None)
                self._runs.pop(profile.id, None)
                self._run_timestamps.pop(profile.id, None)
            self.events.put((profile.id, "status", "Stopped"))

    def _run_session(self, profile: Profile, cmds: queue.Queue, cancel: threading.Event) -> None:
        pid = profile.id
        password = ""
        try:
            from playwright.sync_api import sync_playwright
            options = dict(
                user_data_dir=str(self.store.profile_path(pid)),
                headless=self.headless,
                locale=profile.locale,
                timezone_id=profile.timezone_id,
                viewport={"width": profile.viewport_width, "height": profile.viewport_height},
                accept_downloads=True,
            )
            extension_paths = self.extensions.paths_for(pid)
            if extension_paths:
                # Chrome and Edge no longer permit command-line sideloading.
                # Only bundled Playwright Chromium supports the official flags.
                locations = ",".join(str(path) for path in extension_paths)
                options["args"] = ["--disable-extensions-except=" + locations, "--load-extension=" + locations]
                options["channel"] = "chromium"
            if profile.browser in {"chrome", "msedge"}:
                options["channel"] = profile.browser
            if profile.user_agent:
                options["user_agent"] = profile.user_agent
            if profile.proxy_scheme:
                # RFC 3986 brackets are mandatory around IPv6 address literals.
                host = profile.proxy_host
                if ":" in host and not host.startswith("["):
                    host = "[" + host + "]"
                proxy = {"server": f"{profile.proxy_scheme}://{host}:{profile.proxy_port}"}
                if profile.proxy_username:
                    proxy["username"] = profile.proxy_username
                    password = get_password(pid)
                    if password:
                        proxy["password"] = password
                options["proxy"] = proxy
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(**options)
                browser_closed = threading.Event()
                # Playwright sync event handlers are dispatched only while its
                # message loop is pumped. We pump it on every queue timeout.
                context.on("close", lambda _context: browser_closed.set())
                try:
                    context.set_default_timeout(20000)
                    page = context.pages[0] if context.pages else context.new_page()
                    try:
                        page.goto(profile.start_url, wait_until="domcontentloaded", timeout=30000)
                    except Exception as exc:
                        if browser_closed.is_set():
                            return
                        self.events.put((pid, "log", "Start URL unavailable: " + self._safe_error(exc, password)))
                    if browser_closed.is_set():
                        return
                    self.events.put((pid, "status", "Running"))
                    while not browser_closed.is_set():
                        try:
                            command, payload = cmds.get(timeout=0.35)
                        except queue.Empty:
                            # A user closing the final browser window may leave
                            # an otherwise idle command worker waiting forever.
                            try:
                                pages = context.pages
                                if not pages:
                                    break
                                pages[0].wait_for_timeout(30)
                            except Exception as exc:
                                if browser_closed.is_set() or self._is_target_closed(exc):
                                    break
                                raise
                            continue
                        if command == "stop":
                            break
                        if command == "automation":
                            self._run_status(pid, "running")
                            try:
                                self._execute(pid, context, payload, cancel)
                            except Exception as exc:
                                if browser_closed.is_set() or self._is_target_closed(exc):
                                    self._run_status(pid, "failed", "Browser closed during automation")
                                else:
                                    safe = self._safe_error(exc, password)
                                    self._run_status(pid, "failed", safe)
                                    self.events.put((pid, "error", safe))
                            else:
                                self._run_status(pid, "cancelled" if cancel.is_set() else "succeeded")
                            finally:
                                with self._lock:
                                    self._active.discard(pid)
                                self.events.put((pid, "log", "Workflow finished"))
                finally:
                    if not browser_closed.is_set():
                        try:
                            context.close()
                        except Exception as exc:
                            if not self._is_target_closed(exc):
                                raise
        except Exception as exc:
            self.events.put((pid, "error", self._safe_error(exc, password)))
        finally:
            with self._lock:
                if self._runs.get(pid, {}).get("status") in {"queued", "running"}:
                    self._runs[pid]["status"] = "cancelled" if cancel.is_set() else "failed"
                    self._runs[pid]["error"] = self._runs[pid]["error"] or "Browser session ended"
                self._workers.pop(pid, None)
                self._active.discard(pid)
                self._cancel.pop(pid, None)
                self._runs.pop(pid, None)  # browser exit revokes extracted content
                self._run_timestamps.pop(pid, None)
            self.events.put((pid, "status", "Stopped"))

    @staticmethod
    def _is_target_closed(exc: Exception) -> bool:
        # The concrete Playwright exception avoids misclassifying e.g. a failed
        # selector saying 'closed page' as a browser shutdown.
        try:
            from playwright._impl._errors import TargetClosedError
            return isinstance(exc, TargetClosedError)
        except ImportError:
            return False

    @staticmethod
    def _safe_error(exc: Exception, password: str) -> str:
        message = f"{type(exc).__name__}: {exc}"
        if password:
            message = message.replace(password, "[REDACTED]")
        return message[:600]

    def _execute(self, pid: str, context, steps: list[dict], cancel: threading.Event) -> None:
        page = context.pages[0] if context.pages else context.new_page()
        for i, step in enumerate(steps, 1):
            if cancel.is_set():
                self.events.put((pid, "log", "Workflow cancelled"))
                return
            action = step["action"]
            self.events.put((pid, "log", f"Step {i}/{len(steps)}: {action}"))
            if action == "goto":
                page.goto(step["url"], wait_until="domcontentloaded", timeout=30000)
            elif action == "click":
                page.locator(step["selector"]).first.click(timeout=20000)
            elif action == "fill":
                page.locator(step["selector"]).first.fill(step["text"], timeout=20000)
            elif action == "press":
                page.locator(step["selector"]).first.press(step["key"], timeout=20000)
            elif action == "check":
                page.locator(step["selector"]).first.check(timeout=20000)
            elif action == "uncheck":
                page.locator(step["selector"]).first.uncheck(timeout=20000)
            elif action == "select_option":
                page.locator(step["selector"]).first.select_option(step["value"], timeout=20000)
            elif action == "scroll_into_view":
                page.locator(step["selector"]).first.scroll_into_view_if_needed(timeout=20000)
            elif action == "wait_for":
                page.locator(step["selector"]).first.wait_for(timeout=20000)
            elif action == "wait":
                remaining = step["seconds"]
                while remaining > 0 and not cancel.is_set():
                    amount = min(0.2, remaining)
                    cancel.wait(amount)
                    remaining -= amount
            elif action == "screenshot":
                directory = self.store.shot_dir / pid
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".png")
                page.screenshot(path=str(path), full_page=True)
                self.events.put((pid, "log", f"Screenshot saved: {path}"))
            elif action == "extract_text":
                value = page.locator(step["selector"]).first.inner_text(timeout=20000)
                # Captured data is kept in memory, protected by local API auth,
                # explicitly retrieved and never logged or written to disk.
                self._record_extract(pid, i, value)
                self.events.put((pid, "log", f"Text extracted ({len(value)} characters; not logged)"))
