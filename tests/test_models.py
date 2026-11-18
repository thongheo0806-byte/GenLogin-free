import unittest

from autumn_genlogin.models import Profile, valid_http_url, validated_steps


class ModelTests(unittest.TestCase):
    def test_valid_profile(self):
        Profile(name="My browser", proxy_scheme="http", proxy_host="127.0.0.1", proxy_port=8080).validate()

    def test_invalid_proxy_and_browser(self):
        with self.assertRaises(ValueError):
            Profile(proxy_scheme="socks", proxy_host="localhost", proxy_port=1080).validate()
        with self.assertRaises(ValueError):
            Profile(browser="unknown").validate()
        with self.assertRaises(ValueError):
            Profile(proxy_scheme="http", proxy_host="../etc/passwd", proxy_port=80).validate()

    def test_disallow_non_http_urls_and_inline_credentials(self):
        for address in ("file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com", "http://", "https://example.com\r\nheader: evil"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                valid_http_url(address)

    def test_workflow_validation(self):
        valid = [{"action": "goto", "url": "https://example.com"}, {"action": "wait", "seconds": 2}, {"action": "screenshot"}]
        self.assertEqual(validated_steps(valid), valid)
        for invalid in ([], [{"action": "javascript", "script": "alert(1)"}], [{"action": "goto", "url": "file:///tmp/a"}], [{"action": "wait", "seconds": 40}], [{"action": "screenshot", "path": "../hi"}]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validated_steps(invalid)


if __name__ == "__main__":
    unittest.main()
