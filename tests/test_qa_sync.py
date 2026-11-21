"""Local test-only click mirror validation; real Chromium scenario in shared E2E."""
import unittest
from uuid import uuid4

from autumn_genlogin.qa_sync import local_origin, LocalQASynchronizer


class LocalQAOriginTests(unittest.TestCase):
    def test_accepts_strict_loopback_http_only(self):
        self.assertEqual(local_origin("http://127.0.0.1:4444/safe?x=1"),
                         "http://127.0.0.1:4444")
        for url in ("https://127.0.0.1:4444","http://localhost:4444",
                    "http://10.0.0.1:4444","http://127.0.0.1",
                    "http://example.com:4444","file:///tmp/file.html",
                    "http://user:password@127.0.0.1:4444"):
            with self.subTest(url=url),self.assertRaises(ValueError):
                local_origin(url)

    def test_rejects_missing_or_duplicate_follower_ids_before_start(self):
        class NoDriver:
            def _submit(self,*args,**kwargs):
                raise AssertionError("Must not start driver on invalid request")
        sync=LocalQASynchronizer(NoDriver())
        master=str(uuid4())
        follower=str(uuid4())
        for entries in ([], [master], [follower,follower],
                        [str(uuid4()) for _ in range(6)]):
            with self.subTest(entries=entries),self.assertRaises(ValueError):
                sync.start(master,entries)
        with self.assertRaises(ValueError):
            sync.start("../bad-id",[follower])


if __name__=="__main__":
    unittest.main()
