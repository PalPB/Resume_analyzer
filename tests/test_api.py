import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.api_key_patch = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        self.api_key_patch.start()

    def tearDown(self):
        self.api_key_patch.stop()

    def test_health_endpoint(self):
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "healthy")
        self.assertFalse(response.json()["openai_key_configured"])

    def test_analyze_rejects_empty_resume_text(self):
        response = self.client.post(
            "/analyze",
            json={"resume_text": "   ", "job_description": "Python developer"},
        )

        self.assertEqual(response.status_code, 422)

    def test_analyze_requires_api_key(self):
        response = self.client.post(
            "/analyze",
            json={"resume_text": "Python developer", "job_description": "Python developer"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("OpenAI API key is missing", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
