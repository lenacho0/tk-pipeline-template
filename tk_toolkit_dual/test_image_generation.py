import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_routing
import image_generation


class ImageGenerationTests(unittest.TestCase):
    def test_run_image_generation_uses_aitgenne_image_to_image(self):
        submitter = Mock(return_value={"data": [{"url": "https://x.test/out.png"}]})
        saver = Mock()
        route = ai_routing.AiRoute(
            provider="Aitgenne",
            capability="图片",
            task_type="图生图/参考图重绘",
            model="Aitgenne / gpt-image-2",
            call_type="OpenAI兼容 /v1/images/generations",
            api_base="https://api.aitgenne.com",
            api_key="sk-test",
            params={"size": "720x1280", "aspect_ratio": "9:16"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            ref_path = Path(tmp) / "ref.png"
            ref_path.write_bytes(b"ref")
            out_path = Path(tmp) / "out.png"

            result = image_generation.run_image_generation(
                route,
                "Render from reference.",
                str(out_path),
                input_mode="image-to-image",
                image_path=str(ref_path),
                metadata={"reference_roles": ["product:1"]},
                size="720x1280",
                aspect_ratio="9:16",
                aitgenne_submitter=submitter,
                aitgenne_saver=saver,
            )

        self.assertEqual(result.provider, "Aitgenne")
        self.assertEqual(result.task_id, "")
        self.assertEqual(submitter.call_args.args[0]["model"], "gpt-image-2")
        self.assertEqual(submitter.call_args.args[1], "Render from reference.")
        self.assertEqual(submitter.call_args.kwargs["input_mode"], "image-to-image")
        self.assertEqual(submitter.call_args.kwargs["image_path"], str(ref_path))
        self.assertEqual(submitter.call_args.kwargs["metadata"], {"reference_roles": ["product:1"]})
        saver.assert_called_once()


if __name__ == "__main__":
    unittest.main()
