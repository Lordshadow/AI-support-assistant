import unittest
import json
import logging
from unittest.mock import MagicMock
from ingestion.manifest_engine import _safe_error, _sanitize_obj, _sanitize_string


class TestIngestionLogging(unittest.TestCase):
    def test_pii_and_credential_sanitization(self):
        # 1. Bearer tokens
        raw_msg = "Request failed with Bearer secret-token-xyz-12345 after retry."
        cleaned = _sanitize_string(raw_msg)
        self.assertNotIn("secret-token-xyz-12345", cleaned)
        self.assertIn("Bearer [redacted]", cleaned)

        # 2. API Key and Secrets
        raw_key = "Connection error: api_key: nim-nvapi-supersecret-99999"
        cleaned_key = _sanitize_string(raw_key)
        self.assertNotIn("nim-nvapi-supersecret-99999", cleaned_key)
        self.assertIn("api_key: [redacted]", cleaned_key)

        # 3. Customer Email
        raw_email = "User customer.doe@example.com reported catalog issue"
        cleaned_email = _sanitize_string(raw_email)
        self.assertNotIn("customer.doe@example.com", cleaned_email)
        self.assertIn("[email redacted]", cleaned_email)

        # 4. Indian Phone number
        raw_phone = "Contact customer at +919876543210 immediately"
        cleaned_phone = _sanitize_string(raw_phone)
        self.assertNotIn("9876543210", cleaned_phone)
        self.assertIn("[phone redacted]", cleaned_phone)

    def test_safe_error_redaction(self):
        class MockException(Exception):
            pass

        exc = MockException("Failed to call https://api.nvidia.com/v1 with Bearer abc123secret and secret=xyz")
        sanitized = _safe_error(exc)
        self.assertNotIn("abc123secret", sanitized)
        self.assertNotIn("xyz", sanitized)
        self.assertIn("[redacted]", sanitized)

    def test_sanitize_nested_object(self):
        payload = {
            "token": "token: my-secret-jwt-payload",
            "user_email": "jane.smith@novaretail.com",
            "nested": {
                "auth": "Bearer secret-access-token",
                "phone": "9812345678",
                "normal_val": 42
            },
            "list": ["clean text", "Authorization: basic-creds-12345"]
        }
        sanitized = _sanitize_obj(payload)
        self.assertNotIn("my-secret-jwt-payload", str(sanitized))
        self.assertNotIn("jane.smith@novaretail.com", str(sanitized))
        self.assertNotIn("secret-access-token", str(sanitized))
        self.assertNotIn("9812345678", str(sanitized))
        self.assertNotIn("basic-creds-12345", str(sanitized))
        self.assertEqual(sanitized["nested"]["normal_val"], 42)

    def test_structured_log_line_format(self):
        # Verify single-line JSON formatting contract
        sample_event = {
            "timestamp": "2026-11-05T11:45:00.000Z",
            "run_id": "run_123",
            "job_id": "job_456",
            "event": "run_finished",
            "api_latency_ms": 12.5,
            "embedding_time_ms": 45.2,
            "counts": {"added": 2, "updated": 0, "unchanged": 1, "deleted": 0}
        }
        line = json.dumps(sample_event, ensure_ascii=False, separators=(",", ":"))
        self.assertNotIn("\n", line)
        parsed = json.loads(line)
        self.assertEqual(parsed["run_id"], "run_123")
        self.assertEqual(parsed["job_id"], "job_456")
        self.assertEqual(parsed["event"], "run_finished")
        self.assertEqual(parsed["api_latency_ms"], 12.5)
        self.assertEqual(parsed["embedding_time_ms"], 45.2)


if __name__ == "__main__":
    unittest.main()
