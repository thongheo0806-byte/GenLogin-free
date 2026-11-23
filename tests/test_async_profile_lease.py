"""Real OS lease ownership and cancelled slow-acquire regression tests."""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from autumn_genlogin.locks import AsyncProfileLease, ProfileLease, ProfileBusyError


class AsyncProfileLeaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.pid=str(uuid4())

    def test_lock_is_exclusive_until_worker_releases_it(self):
        async def run():
            lease=AsyncProfileLease(self.home,self.pid)
            await lease.acquire()
            try:
                with self.assertRaises(ProfileBusyError):
                    with ProfileLease(self.home,self.pid):
                        pass
            finally:
                await lease.release()
            # A completed close must release the same OS-backed byte lock.
            with ProfileLease(self.home,self.pid):
                pass
            await lease.release()
        asyncio.run(run())

    def test_slow_acquire_does_not_block_event_loop_and_unlocks_on_same_worker(self):
        seen=[]
        class SlowLease:
            def __init__(self, *_args):
                pass
            def __enter__(self):
                seen.append(("enter",threading.get_ident()))
                time.sleep(0.6)
                return self
            def __exit__(self,*_args):
                seen.append(("exit",threading.get_ident()))

        async def run():
            event=asyncio.Event()
            started=asyncio.get_running_loop().time()
            asyncio.get_running_loop().call_later(0.03,event.set)
            lease=AsyncProfileLease(self.home,self.pid)
            acquisition=asyncio.create_task(lease.acquire())
            await asyncio.wait_for(event.wait(),timeout=0.4)
            self.assertLess(asyncio.get_running_loop().time()-started,0.4,
                            "Slow OS lease acquisition stalled the browser event loop")
            await asyncio.wait_for(acquisition,timeout=3)
            await asyncio.wait_for(lease.release(),timeout=3)
        with patch("autumn_genlogin.locks.ProfileLease",SlowLease):
            asyncio.run(run())
        self.assertEqual([name for name,_ in seen],["enter","exit"])
        self.assertNotEqual(seen[0][1],threading.get_ident())
        self.assertEqual(seen[0][1],seen[1][1])

    def test_cancel_during_inflight_lock_acquisition_cannot_leak_lock(self):
        started,allow=threading.Event(),threading.Event()
        seen=[]
        class DelayedLease:
            def __init__(self,*_args):
                pass
            def __enter__(self):
                started.set()
                if not allow.wait(timeout=5):
                    raise RuntimeError("Synthetic lock acquisition stalled")
                seen.append(("enter",threading.get_ident()))
                return self
            def __exit__(self,*_args):
                seen.append(("exit",threading.get_ident()))
        async def run():
            lease=AsyncProfileLease(self.home,self.pid)
            acquiring=asyncio.create_task(lease.acquire())
            self.assertTrue(await asyncio.to_thread(started.wait,2))
            acquiring.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await acquiring
            allow.set()
            # Even if the lock arrives AFTER coroutine cancellation, the
            # lock-owning worker must observe release and unlock itself.
            await asyncio.wait_for(asyncio.wrap_future(lease._done),timeout=4)
            await asyncio.wait_for(lease.release(),timeout=2)
        with patch("autumn_genlogin.locks.ProfileLease",DelayedLease):
            asyncio.run(run())
        self.assertEqual([name for name,_ in seen],["enter","exit"])
        self.assertEqual(seen[0][1],seen[1][1])


if __name__=="__main__":
    unittest.main()
