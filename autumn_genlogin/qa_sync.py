"""Live click mirroring for synthetic localhost QA pages, not real accounts.

All Playwright operations use SharedBrowserManager's single owning asyncio
loop. Only explicitly marked synthetic buttons are mirrored across matching
loopback tabs and same-origin QA iframes. This deliberately does not copy
text, form input, cookies, navigation, keyboard events, credentials or
external-site actions. Not a GenLogin-equivalent live synchronizer.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from urllib.parse import urlsplit
from uuid import UUID

from .browser_shared import FRAME_ELEMENT_SELECTOR

QA_CLICK_SCRIPT = r"""(() => {
  if (window.__autumnQaClickListenerInstalled) return;
  window.__autumnQaClickListenerInstalled = true;
  document.addEventListener('click', function(event) {
    const el=event.target && event.target.closest('button[data-autumn-qa-click="1"]');
    if (!el || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(el.id)) return;
    if (window.__autumnQaMirror) {
      window.__autumnQaMirror({action:'click',id:el.id}).catch(() => {});
    }
  }, true);
})();"""

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
MAX_FOLLOWERS = 5
MAX_MIRRORED_CLICKS = 50


def local_origin(url: str) -> str:
    """Require a literal loopback HTTP origin; not DNS names or private LAN."""
    if not isinstance(url, str):
        raise ValueError("Live QA requires a literal loopback page")
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != "127.0.0.1" or parts.port is None:
        raise ValueError("QA click mirror is limited to http://127.0.0.1:port")
    if parts.username or parts.password:
        raise ValueError("URLs with embedded credentials are prohibited")
    return f"http://127.0.0.1:{parts.port}"


@dataclass
class QASyncState:
    master_id: str
    follower_ids: tuple[str, ...]
    origin: str
    mirrored_clicks: int = 0
    failures: int = 0
    delivered_clicks: int = 0

    def snapshot(self) -> dict:
        return {
            "active": True,
            "master_id": self.master_id,
            "follower_ids": list(self.follower_ids),
            "origin": self.origin,
            "mirrored_clicks": self.mirrored_clicks,
            "delivered_clicks": self.delivered_clicks,
            "failed_clicks": self.failures,
        }


class LocalQASynchronizer:
    def __init__(self, manager):
        self.manager = manager
        self._state: QASyncState | None = None
        self._relay_lock = None

    def start(self, master_id: str, follower_ids: list[str] | tuple[str,...]) -> dict:
        master_id = str(UUID(master_id))
        if not isinstance(follower_ids, (tuple,list)) or not 1 <= len(follower_ids) <= MAX_FOLLOWERS:
            raise ValueError("Choose 1-5 explicit local QA followers")
        followers = tuple(str(UUID(pid)) for pid in follower_ids)
        if master_id in followers or len(set(followers)) != len(followers):
            raise ValueError("Master/followers must be separate unique profiles")
        return self.manager._submit(self._start(master_id,followers)).result(timeout=25)

    async def _start(self, master_id: str, followers: tuple[str,...]) -> dict:
        if self._state:
            raise ValueError("Stop the existing QA click mirror first")
        ids = (master_id, *followers)
        with self.manager._lock:
            sessions = [self.manager._sessions.get(pid) for pid in ids]
            occupied = any(pid in self.manager._active for pid in ids)
        if occupied or any(s is None for s in sessions):
            raise ValueError("Open every QA profile and stop any active workflows")
        for session in sessions:
            await asyncio.wait_for(session.ready.wait(),timeout=15)
            if session.closed.is_set() or session.context is None:
                raise ValueError("A QA browser session failed to open")
        pages = [s.context.pages[0] if s.context.pages else await s.context.new_page()
                 for s in sessions]
        origins = [local_origin(page.url) for page in pages]
        if len(set(origins)) != 1:
            raise ValueError("All QA profiles must show the same loopback origin")
        master = sessions[0]
        if not getattr(master,"qa_mirror_binding_added",False):
            async def binding(source,payload):
                await self._relay(master,source,payload)
            await master.context.expose_binding("__autumnQaMirror",binding)
            master.qa_mirror_binding_added=True
        if not getattr(master,"qa_mirror_script_added",False):
            await master.context.add_init_script(QA_CLICK_SCRIPT)
            master.qa_mirror_script_added=True
        for frame in pages[0].frames:
            try:
                await frame.evaluate(QA_CLICK_SCRIPT)
            except Exception:
                # A detached QA frame may be ignored; init scripts will
                # instrument future documents.
                pass
        self._relay_lock=asyncio.Lock()
        self._state=QASyncState(master_id,followers,origins[0])
        return self._state.snapshot()

    async def _relay(self, master, source, payload):
        state=self._state
        if state is None or master.profile.id != state.master_id:
            return
        if not isinstance(payload,dict) or set(payload)!={"action","id"}:
            return
        ident=payload.get("id")
        if (payload.get("action")!="click" or not isinstance(ident,str)
                or not _ID.fullmatch(ident)):
            return
        page,frame=source.get("page"),source.get("frame")
        if page is None or frame is None:
            return
        try:
            if local_origin(page.url)!=state.origin:
                return
        except (ValueError,TypeError):
            return
        masters=list(master.context.pages)
        if page not in masters or len(masters)>12:
            return
        tab_index=masters.index(page)
        # This mirror is ONLY for local synthetic QA. Refuse external iframe
        # documents even if their parent browser tab is on the QA origin.
        chain=[]
        cursor=frame
        try:
            while cursor is not page.main_frame:
                if len(chain)>=4 or cursor.parent_frame is None:
                    return
                child_url=cursor.url
                if (child_url not in ("about:blank","about:srcdoc")
                        and local_origin(child_url)!=state.origin):
                    return
                element=await cursor.frame_element()
                css=await element.evaluate(FRAME_ELEMENT_SELECTOR)
                if not isinstance(css,str) or not css or len(css)>240:
                    return
                chain.insert(0,css)
                cursor=cursor.parent_frame
        except Exception:
            return
        async with self._relay_lock:
            if self._state is not state or state.mirrored_clicks>=MAX_MIRRORED_CLICKS:
                return
            # Count master GESTURES, never per-follower deliveries.
            state.mirrored_clicks+=1
            for pid in state.follower_ids:
                with self.manager._lock:
                    follower=self.manager._sessions.get(pid)
                    busy=pid in self.manager._active
                if (follower is None or follower.context is None
                        or follower.closed.is_set() or busy):
                    state.failures+=1
                    continue
                followers=list(follower.context.pages)
                if len(followers)!=len(masters):
                    state.failures+=1
                    continue
                target=followers[tab_index]
                try:
                    if local_origin(target.url)!=state.origin:
                        raise ValueError("Follower left the local QA origin")
                    scope=target
                    for css in chain:
                        if await scope.locator(css).count()!=1:
                            raise ValueError("QA iframe target is missing or ambiguous")
                        scope=scope.frame_locator(css)
                    await scope.locator(
                        f'button#{ident}[data-autumn-qa-click="1"]'
                    ).click(timeout=2000)
                    state.delivered_clicks+=1
                except Exception:
                    state.failures+=1
            if state.mirrored_clicks>=MAX_MIRRORED_CLICKS:
                self._state=None

    def stop(self) -> dict:
        return self.manager._submit(self._stop()).result(timeout=15)

    async def _stop(self) -> dict:
        previous=self._state
        self._state=None
        return previous.snapshot() if previous else {"active":False}

    def status(self) -> dict:
        return self.manager._submit(self._status()).result(timeout=15)

    async def _status(self) -> dict:
        return self._state.snapshot() if self._state else {"active":False}
