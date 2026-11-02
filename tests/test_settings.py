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

    def test_database_path_can_be_configured_without_resolving_home(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                Settings.from_environment().database_path,
                "~/.agente_pessoal/agente_pessoal.sqlite3",
            )
        with patch.dict(os.environ, {"AGENTE_PESSOAL_DB_PATH": "D:/agent/state.db"}, clear=True):
            self.assertEqual(Settings.from_environment().database_path, "D:/agent/state.db")

    def test_ai_settings_use_model_and_credential_variable_name_only(self):
        with patch.dict(
            os.environ,
            {
                "AGENTE_PESSOAL_AI_MODEL": "model-choice",
                "AGENTE_PESSOAL_AI_CREDENTIAL_ENV": "MODEL_API_KEY",
                "AGENTE_PESSOAL_AI_MAX_ATTEMPTS": "3",
            },
            clear=True,
        ):
            settings = Settings.from_environment()

        self.assertEqual(settings.ai_model, "model-choice")
        self.assertEqual(settings.ai_credential_env_var, "MODEL_API_KEY")
        self.assertEqual(settings.ai_max_attempts, 3)

    def test_invalid_ai_attempt_limit_falls_back_to_safe_default(self):
        with patch.dict(
            os.environ, {"AGENTE_PESSOAL_AI_MAX_ATTEMPTS": "999"}, clear=True
        ):
            self.assertEqual(Settings.from_environment().ai_max_attempts, 2)


if __name__ == "__main__":
    unittest.main()
