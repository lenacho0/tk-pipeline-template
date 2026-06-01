import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aitgenne_image


class AitgenneImageTests(unittest.TestCase):
    def test_submit_image_generation_posts_openai_compatible_payload(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"url": "https://x.test/out.png"}]}
        post = Mock(return_value=response)

        result = aitgenne_image.submit_aitgenne_image_generation(
            {"api_key": "sk-test", "api_base": "https://api.aitgenne.com", "model": "gpt-image-2"},
            "Draw a clean product reference.",
            size="720x1280",
            aspect_ratio="9:16",
            post=post,
        )

        self.assertEqual(result["data"][0]["url"], "https://x.test/out.png")
        self.assertEqual(post.call_args.args[0], "https://api.aitgenne.com/v1/images/generations")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer sk-test")
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-image-2")
        self.assertEqual(post.call_args.kwargs["json"]["prompt"], "Draw a clean product reference.")
        self.assertEqual(post.call_args.kwargs["json"]["size"], "720x1280")
        self.assertEqual(post.call_args.kwargs["json"]["metadata"]["aspectRatio"], "9:16")
        self.assertEqual(post.call_args.kwargs["json"]["metadata"]["aspect_ratio"], "9:16")
        self.assertEqual(post.call_args.kwargs["json"]["metadata"]["size"], "720x1280")

    def test_submit_image_generation_with_references_posts_edit_multipart_images(self):
        response = Mock(status_code=200)
        response.json.return_value = {"data": [{"url": "https://x.test/out.png"}]}
        post = Mock(return_value=response)

        with tempfile.TemporaryDirectory() as tmp:
            product = Path(tmp) / "product.png"
            human = Path(tmp) / "human.png"
            product.write_bytes(b"product")
            human.write_bytes(b"human")

            result = aitgenne_image.submit_aitgenne_image_generation(
                {"api_key": "sk-test", "api_base": "https://api.aitgenne.com", "model": "gpt-image-2"},
                "Render the exact product and same human.",
                input_mode="image-to-image",
                reference_image_paths=[str(product), str(human)],
                metadata={"reference_roles": ["product:1", "human:owner"]},
                size="1280x720",
                aspect_ratio="16:9",
                post=post,
            )

        self.assertEqual(result["data"][0]["url"], "https://x.test/out.png")
        self.assertEqual(post.call_args.args[0], "https://api.aitgenne.com/v1/images/edits")
        kwargs = post.call_args.kwargs
        self.assertNotIn("json", kwargs)
        self.assertNotIn("Content-Type", kwargs["headers"])
        self.assertEqual(kwargs["data"]["model"], "gpt-image-2")
        self.assertEqual(kwargs["data"]["prompt"], "Render the exact product and same human.")
        self.assertEqual(kwargs["data"]["size"], "1280x720")
        self.assertIn('"reference_roles": ["product:1", "human:owner"]', kwargs["data"]["metadata"])
        self.assertIn('"aspectRatio": "16:9"', kwargs["data"]["metadata"])
        self.assertIn('"aspect_ratio": "16:9"', kwargs["data"]["metadata"])
        self.assertIn('"size": "1280x720"', kwargs["data"]["metadata"])
        self.assertEqual([item[0] for item in kwargs["files"]], ["image[]", "image[]"])
        self.assertEqual([item[1][0] for item in kwargs["files"]], ["product.png", "human.png"])

    def test_save_image_result_writes_b64_image(self):
        png_bytes = base64.b64encode(b"png-bytes").decode("ascii")
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.png"

            saved = aitgenne_image.save_aitgenne_image_result({"data": [{"b64_json": png_bytes}]}, str(out_path))

            self.assertEqual(saved, str(out_path))
            self.assertEqual(out_path.read_bytes(), b"png-bytes")

    def test_save_image_result_downloads_url(self):
        response = Mock(status_code=200, content=b"image-bytes")
        response.raise_for_status = Mock()
        get = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.png"

            saved = aitgenne_image.save_aitgenne_image_result({"data": [{"url": "https://x.test/out.png"}]}, str(out_path), get=get)

            self.assertEqual(saved, str(out_path))
            self.assertEqual(out_path.read_bytes(), b"image-bytes")
            self.assertEqual(get.call_args.args[0], "https://x.test/out.png")


if __name__ == "__main__":
    unittest.main()
