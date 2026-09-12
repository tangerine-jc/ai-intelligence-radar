"""Small smoke tests for configuration and URL normalization."""

import logging
import os
import tempfile
import unittest
from pathlib import Path

from src.config import Config
from src.processing.url_deduplicator import URLDeduplicator

logging.disable(logging.CRITICAL)


class ConfigSmokeTests(unittest.TestCase):
    def test_default_endpoint_is_normalized(self):
        config = Config()
        self.assertFalse(config.BLUE_CONVERSE_BASE_URL.endswith("/"))
        self.assertTrue(config.BLUE_CONVERSE_API_URL.endswith("/v1/chat/completions"))

    def test_anonymous_profiles_can_be_loaded(self):
        previous = os.environ.get("USER_PROFILES_FILE")
        os.environ["USER_PROFILES_FILE"] = str(
            Path(__file__).resolve().parents[1] / "config" / "users.example.json"
        )
        try:
            users = Config().TARGET_SITES["PERSONAL"]["users"]
        finally:
            if previous is None:
                os.environ.pop("USER_PROFILES_FILE", None)
            else:
                os.environ["USER_PROFILES_FILE"] = previous

        self.assertEqual(len(users), 2)
        self.assertTrue(all(user["email"].endswith("@example.com") for user in users))


class URLDeduplicatorSmokeTests(unittest.TestCase):
    def test_tracking_parameters_are_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            deduplicator = URLDeduplicator(temp_dir)
            normalized = deduplicator._normalize_url(
                "https://example.com/news/?utm_source=test&id=42#section"
            )

        self.assertEqual(normalized, "https://example.com/news?id=42")


if __name__ == "__main__":
    unittest.main()
