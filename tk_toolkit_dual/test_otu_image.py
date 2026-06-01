import sys
import tempfile
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

    def test_submit_reference_image_paths_sends_multipart_input_references(self):
        submitted = Mock(status_code=200)
        submitted.json.return_value = {"id": "task_multi"}

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "product.png"
            second = Path(tmp) / "human.png"
            first.write_bytes(b"product")
            second.write_bytes(b"human")

            with patch.object(otu_image.requests, "post", return_value=submitted) as poster:
                task_id, body = otu_image.submit_otu_image_task(
                    {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                    "prompt",
                    input_mode="image-to-image",
                    reference_image_paths=[str(first), str(second)],
                    metadata={"reference_roles": ["product:1", "human:owner"]},
                    size="1280x720",
                    aspect_ratio="16:9",
                )

        self.assertEqual(task_id, "task_multi")
        self.assertEqual(body, {"id": "task_multi"})
        kwargs = poster.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertNotIn("Content-Type", kwargs["headers"])
        self.assertEqual(kwargs["data"]["model"], "gpt-image-2")
        self.assertEqual(kwargs["data"]["input_mode"], "image-to-image")
        self.assertIn('"reference_roles": ["product:1", "human:owner"]', kwargs["data"]["metadata"])
        self.assertIn('"aspectRatio": "16:9"', kwargs["data"]["metadata"])
        self.assertIn('"aspect_ratio": "16:9"', kwargs["data"]["metadata"])
        self.assertIn('"size": "1280x720"', kwargs["data"]["metadata"])
        self.assertEqual(kwargs["data"]["size"], "1280x720")
        self.assertEqual([item[0] for item in kwargs["files"]], ["input_reference[]", "input_reference[]"])
        self.assertEqual([item[1][0] for item in kwargs["files"]], ["product.png", "human.png"])

    def test_submit_json_image_payload_includes_aspect_ratio_metadata_aliases(self):
        submitted = Mock(status_code=200)
        submitted.json.return_value = {"id": "task_json"}

        with patch.object(otu_image.requests, "post", return_value=submitted) as poster:
            task_id, body = otu_image.submit_otu_image_task(
                {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                "prompt",
                input_mode="text-to-image",
                size="1024x1024",
                aspect_ratio="1:1",
            )

        self.assertEqual(task_id, "task_json")
        self.assertEqual(body, {"id": "task_json"})
        payload = poster.call_args.kwargs["json"]
        self.assertEqual(payload["size"], "1024x1024")
        self.assertEqual(payload["metadata"]["aspectRatio"], "1:1")
        self.assertEqual(payload["metadata"]["aspect_ratio"], "1:1")
        self.assertEqual(payload["metadata"]["size"], "1024x1024")

    def test_submit_reference_image_paths_does_not_fall_back_to_weak_url_refs(self):
        rejected = Mock(status_code=400)
        rejected.json.return_value = {"message": '{"error":{"message":"Invalid JSON body"}}'}

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "product.png"
            second = Path(tmp) / "human.png"
            first.write_bytes(b"product")
            second.write_bytes(b"human")

            with patch.object(otu_image.requests, "post", return_value=rejected) as poster:
                with self.assertRaises(RuntimeError) as ctx:
                    otu_image.submit_otu_image_task(
                        {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                        "prompt",
                        input_mode="image-to-image",
                        reference_image_paths=[str(first), str(second)],
                        metadata={
                            "urls": ["https://x.test/product.png", "https://x.test/human.png"],
                            "reference_roles": ["product:1", "human:owner"],
                            "aspectRatio": "9:16",
                        },
                        size="720x1280",
                    )

        self.assertIn("OTU 图片任务提交失败", str(ctx.exception))
        self.assertEqual(poster.call_count, 1)
        self.assertIn("files", poster.call_args.kwargs)
        self.assertNotIn("json", poster.call_args.kwargs)

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
