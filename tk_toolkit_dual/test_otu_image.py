import sys
import tempfile
import unittest
import base64
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

    def test_submit_reference_image_paths_sends_json_metadata_urls(self):
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
        self.assertNotIn("files", kwargs)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        payload = kwargs["json"]
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertEqual(payload["input_mode"], "image-to-image")
        self.assertEqual(payload["metadata"]["reference_roles"], ["product:1", "human:owner"])
        self.assertEqual(payload["metadata"]["aspectRatio"], "16:9")
        self.assertEqual(payload["metadata"]["aspect_ratio"], "16:9")
        self.assertEqual(payload["metadata"]["size"], "1280x720")
        self.assertEqual(len(payload["metadata"]["urls"]), 2)
        self.assertTrue(payload["metadata"]["urls"][0].startswith("data:image/png;base64,"))
        self.assertTrue(payload["metadata"]["urls"][1].startswith("data:image/png;base64,"))

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

    def test_submit_image_path_uses_metadata_urls_data_url(self):
        submitted = Mock(status_code=200)
        submitted.json.return_value = {"id": "task_image_path"}

        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "product.png"
            first.write_bytes(b"product")

            with patch.object(otu_image.requests, "post", return_value=submitted) as poster:
                task_id, body = otu_image.submit_otu_image_task(
                    {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                    "prompt",
                    input_mode="image-to-image",
                    image_path=str(first),
                    metadata={"reference_roles": ["product:1"]},
                    aspect_ratio="9:16",
                )

        self.assertEqual(task_id, "task_image_path")
        self.assertEqual(body, {"id": "task_image_path"})
        self.assertEqual(poster.call_count, 1)
        payload = poster.call_args.kwargs["json"]
        self.assertNotIn("image_base64", payload)
        self.assertEqual(payload["metadata"]["reference_roles"], ["product:1"])
        self.assertEqual(len(payload["metadata"]["urls"]), 1)
        self.assertTrue(payload["metadata"]["urls"][0].startswith("data:image/png;base64,"))

    def test_submit_caps_metadata_urls_to_five_with_role_priority(self):
        submitted = Mock(status_code=200)
        submitted.json.return_value = {"id": "task_priority"}

        with tempfile.TemporaryDirectory() as tmp:
            primary = Path(tmp) / "primary.png"
            ordinary_one = Path(tmp) / "ordinary_one.png"
            model = Path(tmp) / "model.png"
            product_one = Path(tmp) / "product_one.png"
            ordinary_two = Path(tmp) / "ordinary_two.png"
            product_two = Path(tmp) / "product_two.png"
            for path in [primary, ordinary_one, model, product_one, ordinary_two, product_two]:
                path.write_bytes(path.stem.encode("utf-8"))

            with patch.object(otu_image.requests, "post", return_value=submitted) as poster:
                otu_image.submit_otu_image_task(
                    {"api_key": "test-key", "api_base": "https://otu.example", "model": "gpt-image-2"},
                    "prompt",
                    input_mode="image-to-image",
                    image_path=str(primary),
                    reference_image_paths=[str(ordinary_one), str(model), str(product_one), str(ordinary_two), str(product_two)],
                    metadata={
                        "reference_roles": [
                            "generated_primary",
                            "uploaded_reference:1",
                            "model_table:1",
                            "product_table:1",
                            "uploaded_reference:2",
                            "uploaded_product:1",
                        ],
                    },
                )

        urls = poster.call_args.kwargs["json"]["metadata"]["urls"]
        selected_payloads = [
            base64.b64decode(url.split(",", 1)[1]).decode("utf-8")
            for url in urls
        ]
        self.assertEqual(selected_payloads, ["product_one", "product_two", "primary", "model", "ordinary_one"])

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

    def test_poll_times_out_when_queued_zero_progress_exceeds_threshold(self):
        queued = Mock(status_code=200)
        queued.json.return_value = {
            "id": "task_stuck",
            "status": "queued",
            "progress": 0,
            "created_at": 1_000,
        }

        with patch.object(otu_image.requests, "get", return_value=queued), \
             patch.object(otu_image.time, "time", return_value=1_601), \
             patch.object(otu_image.time, "sleep"):
            with self.assertRaisesRegex(TimeoutError, "queued progress=0 timeout"):
                otu_image.poll_otu_image_task(
                    {"api_key": "test-key", "api_base": "https://otu.example"},
                    "task_stuck",
                    queued_zero_progress_timeout_seconds=600,
                )


if __name__ == "__main__":
    unittest.main()
