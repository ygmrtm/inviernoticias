import os
import sys
import json
import unittest
from unittest.mock import patch, MagicMock

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Mock google.genai in sys.modules to enable 100% sandboxed execution without network/keychain calls
mock_genai_module = MagicMock()
mock_types_module = MagicMock()
mock_genai_module.types = mock_types_module
sys.modules["google"] = MagicMock()
sys.modules["google.genai"] = mock_genai_module
sys.modules["google.genai.types"] = mock_types_module

# Use a test SQLite database
TEST_DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "test_inviernoticias.db"))
os.environ["DATABASE_PATH"] = TEST_DB_PATH

from app import db, gemini

class TestGeminiQuotaRotation(unittest.TestCase):
    def setUp(self):
        # Initialize DB and reset settings before each test
        db.init_db()
        conn = db.get_connection()
        try:
            conn.execute("DELETE FROM settings;")
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        if os.path.exists(TEST_DB_PATH):
            try:
                os.remove(TEST_DB_PATH)
            except Exception:
                pass

    def test_key_management_operations(self):
        # Initial empty state
        self.assertEqual(gemini.get_api_keys(), [])

        # Set multiple keys
        keys = ["AIzaSyKey111111111", "AIzaSyKey222222222", "AIzaSyKey333333333"]
        gemini.set_api_keys(keys)
        self.assertEqual(gemini.get_api_keys(), keys)

        # Backward compatibility check
        self.assertEqual(gemini.get_primary_api_key(), keys[0])
        self.assertEqual(gemini.get_backup_api_key(), keys[1])

        # Add single key
        new_key = "AIzaSyKey444444444"
        added = gemini.add_api_key(new_key)
        self.assertTrue(added)
        self.assertEqual(len(gemini.get_api_keys()), 4)

        # Prevent duplicate key addition
        added_again = gemini.add_api_key(new_key)
        self.assertFalse(added_again)
        self.assertEqual(len(gemini.get_api_keys()), 4)

        # Remove key at index 1
        removed = gemini.remove_api_key(1)
        self.assertTrue(removed)
        self.assertEqual(gemini.get_api_keys(), ["AIzaSyKey111111111", "AIzaSyKey333333333", "AIzaSyKey444444444"])

    def test_tokens_status_structure_and_backward_compatibility(self):
        keys = ["AIzaSyAlpha123456", "AIzaSyBeta789012", "AIzaSyGamma345678"]
        gemini.set_api_keys(keys)

        status = gemini.get_tokens_status()
        # Rich keys list
        self.assertIn("keys", status)
        self.assertEqual(len(status["keys"]), 3)
        self.assertEqual(status["total_keys"], 3)
        self.assertEqual(status["active_index"], 0)
        self.assertTrue(status["keys"][0]["is_active"])
        self.assertFalse(status["keys"][0]["quota_exceeded"])
        self.assertFalse(status["all_quotas_exceeded"])

        # Postman backward-compatible properties
        self.assertTrue(status["primary_configured"])
        self.assertTrue(status["backup_configured"])
        self.assertEqual(status["active_token_type"], "primary")
        self.assertFalse(status["primary_quota_exceeded"])
        self.assertFalse(status["backup_quota_exceeded"])

    def test_sequential_quota_fallback_rotation(self):
        keys = [
            "AIzaSyKeyA_11111111",
            "AIzaSyKeyB_22222222",
            "AIzaSyKeyC_33333333"
        ]
        gemini.set_api_keys(keys)
        gemini.reset_quota_status()

        call_log = []

        def mock_generate_content(*args, **kwargs):
            # Inspect which key was used by checking the last client created
            current_key = mock_genai_client.call_args[1].get("api_key")
            call_log.append(current_key)

            if current_key == keys[0]:
                raise Exception("429 Resource has been exhausted (quota exceeded).")
            elif current_key == keys[1]:
                raise Exception("429 Quota exceeded: check rate limits.")
            elif current_key == keys[2]:
                resp = MagicMock()
                resp.text = json.dumps({
                    "isSatire": True,
                    "truthScore": 15,
                    "sarcasmScore": 85,
                    "mexicoMagicoAward": True,
                    "refran": "Al mal paso, darle prisa.",
                    "historicalQuote": None,
                    "foreignerExplanation": "Mexican political joke.",
                    "newsSummary": "Resumen.",
                    "mexicanCultureReferences": "Tacos y burócratas.",
                    "analysisSummary": "Sátira confirmada.",
                    "relatedSources": []
                })
                return resp
            else:
                raise ValueError("Unexpected key")

        with patch("app.gemini.genai.Client") as mock_genai_client:
            instance = MagicMock()
            instance.models.generate_content.side_effect = mock_generate_content
            mock_genai_client.return_value = instance

            # Analyze content: Key 0 fails -> Key 1 fails -> Key 2 succeeds!
            result = gemini.analyze_content("Diputados aprueban tacos espaciales", "Noticia satírica")

            self.assertIsNotNone(result)
            self.assertTrue(result["isSatire"])
            self.assertEqual(result["tokenUsed"], "key_3")
            self.assertEqual(result["tokenIndex"], 2)

            # Verify that keys[0] and keys[1] were tried and failed, then keys[2] was called
            self.assertEqual(call_log, [keys[0], keys[1], keys[2]])

            # Check persistent quota status: keys[0] and keys[1] are marked exhausted, keys[2] is active!
            exhausted = gemini.get_exhausted_keys()
            self.assertIn(keys[0], exhausted)
            self.assertIn(keys[1], exhausted)
            self.assertNotIn(keys[2], exhausted)
            self.assertEqual(gemini.get_active_key_index(), 2)

    def test_next_call_reuses_active_working_key(self):
        keys = ["AIzaSyKeyA", "AIzaSyKeyB", "AIzaSyKeyC"]
        gemini.set_api_keys(keys)
        # Mark key 0 and 1 as exhausted, active index is 2
        gemini.mark_key_exhausted(keys[0])
        gemini.mark_key_exhausted(keys[1])
        gemini.set_active_key_index(2)

        call_log = []

        def mock_generate_content(*args, **kwargs):
            current_key = mock_genai_client.call_args[1].get("api_key")
            call_log.append(current_key)
            resp = MagicMock()
            resp.text = json.dumps({"isSatire": False, "truthScore": 90, "sarcasmScore": 10})
            return resp

        with patch("app.gemini.genai.Client") as mock_genai_client:
            instance = MagicMock()
            instance.models.generate_content.side_effect = mock_generate_content
            mock_genai_client.return_value = instance

            result = gemini.analyze_content("Noticia Real", "Contenido real")
            self.assertEqual(result["tokenIndex"], 2)
            # It immediately called Key 2 without calling exhausted Key 0 or Key 1
            self.assertEqual(call_log, [keys[2]])

    def test_all_keys_quota_exhausted_raises_error(self):
        keys = ["AIzaSyKeyA", "AIzaSyKeyB"]
        gemini.set_api_keys(keys)
        gemini.reset_quota_status()

        with patch("app.gemini.genai.Client") as mock_genai_client:
            instance = MagicMock()
            instance.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED")
            mock_genai_client.return_value = instance

            with self.assertRaises(gemini.AllTokensQuotaExceededError):
                gemini.analyze_content("Cualquier título", "Cualquier texto")

            status = gemini.get_tokens_status()
            self.assertTrue(status["all_quotas_exceeded"])

    def test_reset_quota_status(self):
        keys = ["AIzaSyKeyA", "AIzaSyKeyB"]
        gemini.set_api_keys(keys)
        gemini.mark_key_exhausted(keys[0])
        gemini.mark_key_exhausted(keys[1])
        gemini.set_active_key_index(1)

        self.assertEqual(len(gemini.get_exhausted_keys()), 2)

        # Reset
        gemini.reset_quota_status()

        self.assertEqual(gemini.get_exhausted_keys(), [])
        self.assertEqual(gemini.get_active_key_index(), 0)
        status = gemini.get_tokens_status()
        self.assertFalse(status["all_quotas_exceeded"])
        self.assertEqual(status["active_token_type"], "primary")

    def test_environment_variable_fallbacks(self):
        # When DB setting is empty, GEMINI_API_KEYS is respected
        with patch.dict(os.environ, {"GEMINI_API_KEYS": "AIzaEnv1, AIzaEnv2, AIzaEnv3"}):
            keys = gemini.get_api_keys()
            self.assertEqual(keys, ["AIzaEnv1", "AIzaEnv2", "AIzaEnv3"])

        # When GEMINI_API_KEYS is a JSON string
        with patch.dict(os.environ, {"GEMINI_API_KEYS": '["AIzaJson1", "AIzaJson2"]'}):
            keys = gemini.get_api_keys()
            self.assertEqual(keys, ["AIzaJson1", "AIzaJson2"])

        # When legacy GEMINI_API_KEY and GEMINI_BACKUP_API_KEY are used
        with patch.dict(os.environ, {"GEMINI_API_KEYS": "", "GEMINI_API_KEY": "AIzaPrimary", "GEMINI_BACKUP_API_KEY": "AIzaBackup"}):
            keys = gemini.get_api_keys()
            self.assertEqual(keys, ["AIzaPrimary", "AIzaBackup"])

    def test_set_tokens_backward_compatibility(self):
        # Test set_tokens with primary and backup
        gemini.set_tokens(primary_key="AIzaLegacyP", backup_key="AIzaLegacyB")
        keys = gemini.get_api_keys()
        self.assertEqual(keys, ["AIzaLegacyP", "AIzaLegacyB"])

        # Updating backup only
        gemini.set_tokens(backup_key="AIzaLegacyB_Updated")
        keys = gemini.get_api_keys()
        self.assertEqual(keys, ["AIzaLegacyP", "AIzaLegacyB_Updated"])

    def test_button_grayout_and_disabled_frontend_assets(self):
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        css_path = os.path.join(root_dir, "app", "static", "style.css")
        js_path = os.path.join(root_dir, "app", "static", "app.js")
        base_html_path = os.path.join(root_dir, "app", "templates", "base.html")

        # Verify style.css contains disabled rules and grayscale filter
        with open(css_path, "r", encoding="utf-8") as f:
            css_content = f.read()
        self.assertIn("button:disabled", css_content)
        self.assertIn(".btn-disabled-grayout", css_content)
        self.assertIn("filter: grayscale(100%)", css_content)
        self.assertIn("cursor: not-allowed", css_content)

        # Verify app.js contains disabling and enabling event handlers
        with open(js_path, "r", encoding="utf-8") as f:
            js_content = f.read()
        self.assertIn("disableButtons", js_content)
        self.assertIn("enableButtons", js_content)
        self.assertIn("btn-disabled-grayout", js_content)
        self.assertIn("pageshow", js_content)
        self.assertIn("fetch", js_content)

        # Verify base.html includes app.js
        with open(base_html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
        self.assertIn('/static/app.js', html_content)

if __name__ == "__main__":
    unittest.main()
