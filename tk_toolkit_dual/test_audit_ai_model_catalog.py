import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit_ai_model_catalog


class AuditAiModelCatalogTests(unittest.TestCase):
    def test_report_marks_known_models_and_redacts_source_errors(self):
        api_results = {
            "OTU": {"models": ["gpt-image-2", "nano_banana_pro-4K", "veo_3_1-fast-fl"], "error": "Bearer sk-secret"},
            "AIHubMix": {"models": ["gemini-3.1-pro-preview", "sora-2-pro"], "error": ""},
            "Aitgenne": {"models": ["gpt-5.5", "happyhorse-1.0-r2v"], "error": "token=abc"},
        }
        pricing_models = [
            {
                "provider": "Aitgenne",
                "model": "veo-3.1-fast",
                "display_name": "Aitgenne / veo-3.1-fast",
                "capability": "视频",
                "endpoint_type": "官网模型广场",
                "price": "待人工确认",
                "source": "Aitgenne pricing",
            }
        ]

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.md"
            report = audit_ai_model_catalog.write_candidate_report(api_results, pricing_models, output_path=output)

        self.assertIn("OTU / gpt-image-2", report)
        self.assertIn("discard", report)
        self.assertIn("Aitgenne / veo-3.1-fast", report)
        self.assertIn("[REDACTED]", report)
        self.assertNotIn("sk-secret", report)
        self.assertNotIn("token=abc", report)


if __name__ == "__main__":
    unittest.main()
