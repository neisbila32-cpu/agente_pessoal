import os
import unittest
from unittest.mock import patch

from agente_pessoal.config import Settings


class SettingsTests(unittest.TestCase):
    def test_default_log_level(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings.from_environment().log_level, "INFO")

    def test_log_level_is_normalized(self):
        with patch.dict(os.environ, {"AGENTE_PESSOAL_LOG_LEVEL": "debug"}, clear=True):
            self.assertEqual(Settings.from_environment().log_level, "DEBUG")

    def test_invalid_log_level_uses_safe_default(self):
        with patch.dict(os.environ, {"AGENTE_PESSOAL_LOG_LEVEL": "verbose"}, clear=True):
            self.assertEqual(Settings.from_environment().log_level, "INFO")


if __name__ == "__main__":
    unittest.main()
