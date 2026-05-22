import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tk_shot_storyboard as storyboard


class ShotStoryboardReferenceTests(unittest.TestCase):
    def test_build_reference_urls_uses_feishu_tmp_download_urls(self):
        refs = [
            {"role": "pet:pet_hero", "file_token": "ft_pet"},
            {"role": "human:human_owner", "file_token": "ft_human"},
        ]
        response = {
            "code": 0,
            "data": {
                "tmp_download_urls": [
                    {"file_token": "ft_pet", "tmp_download_url": "https://x.test/pet.png"},
                    {"file_token": "ft_human", "tmp_download_url": "https://x.test/human.png"},
                ]
            },
        }
        with patch("tk_shot_storyboard.safe_request", return_value=response) as safe_request:
            urls = storyboard.build_reference_urls("token", refs)

        self.assertEqual(urls, ["https://x.test/pet.png", "https://x.test/human.png"])
        self.assertEqual(safe_request.call_count, 2)
        self.assertEqual(safe_request.call_args_list[0].kwargs["params"], {"file_tokens": "ft_pet"})
        self.assertEqual(safe_request.call_args_list[1].kwargs["params"], {"file_tokens": "ft_human"})


if __name__ == "__main__":
    unittest.main()
