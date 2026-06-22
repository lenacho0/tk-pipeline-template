import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common


class CommonFeishuProxyTests(unittest.TestCase):
    def test_safe_request_uses_proxy_free_session_for_feishu_urls(self):
        class FakeSession:
            instances = []

            def __init__(self):
                self.trust_env = True
                self.request_args = None
                self.closed = False
                FakeSession.instances.append(self)

            def request(self, *args, **kwargs):
                self.request_args = (args, kwargs)
                response = Mock()
                response.raise_for_status.return_value = None
                response.json.return_value = {"code": 0, "data": {"ok": True}}
                return response

            def close(self):
                self.closed = True

        with patch.object(common.requests, "Session", FakeSession), \
             patch.object(common.requests, "request", side_effect=AssertionError("default request used")):
            data = common.safe_request(
                "get",
                "https://open.feishu.cn/open-apis/bitable/v1/apps/app/tables/table/records",
                max_attempts=1,
            )

        self.assertEqual(data, {"code": 0, "data": {"ok": True}})
        self.assertEqual(len(FakeSession.instances), 1)
        session = FakeSession.instances[0]
        self.assertFalse(session.trust_env)
        self.assertTrue(session.closed)
        self.assertEqual(session.request_args[0][0], "get")

    def test_safe_request_keeps_default_requests_for_non_feishu_urls(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"ok": True}

        with patch.object(common.requests, "request", return_value=response) as request, \
             patch.object(common.requests, "Session", side_effect=AssertionError("session used")):
            data = common.safe_request("get", "https://example.com/status", acceptable_codes=None, max_attempts=1)

        self.assertEqual(data, {"ok": True})
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
