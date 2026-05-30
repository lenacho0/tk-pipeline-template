import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import otu_image


class OtuImagePollingTests(unittest.TestCase):
    def test_submit_retries_transient_request_error(self):
        submitted = Mock(status_code=200)
        submitted.json.return_value = {"id": "task_123"}

        with patch.object(
            otu_image.requests,
            "post",
            side_effect=[requests.exceptions.ProxyError("broken pipe"), submitted],
        ) as poster, patch.object(otu_image.time, "sleep"):
            task_id, body = otu_image.submit_otu_image_task(
                {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                "prompt",
                input_mode="text-to-image",
            )

        self.assertEqual(task_id, "task_123")
        self.assertEqual(body, {"id": "task_123"})
        self.assertEqual(poster.call_count, 2)

    def test_poll_continues_after_transient_request_error(self):
        completed = Mock(status_code=200)
        completed.json.return_value = {
            "status": "completed",
            "result_url": "https://example.test/result.png",
        }

        with patch.object(
            otu_image.requests,
            "get",
            side_effect=[requests.exceptions.SSLError("temporary eof"), completed],
        ) as getter, patch.object(otu_image.time, "sleep"):
            result = otu_image.poll_otu_image_task(
                {"api_key": "test-key", "api_base": "https://otu.example"},
                "task_123",
            )

        self.assertEqual(result["result_url"], "https://example.test/result.png")
        self.assertEqual(getter.call_count, 2)


if __name__ == "__main__":
    unittest.main()
