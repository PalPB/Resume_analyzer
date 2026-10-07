import unittest

from services.analyzer import _extract_keywords, _format_score, _match_keywords


class AnalyzerTests(unittest.TestCase):
    def test_extract_keywords_preserves_technical_phrases(self):
        keywords = _extract_keywords(
            "Seeking Python, FastAPI, PostgreSQL, and Azure experience."
        )

        self.assertIn("python", keywords)
        self.assertIn("fastapi", keywords)
        self.assertIn("postgresql", keywords)
        self.assertIn("azure", keywords)

    def test_match_keywords_distinguishes_exact_and_missing_terms(self):
        matched, missing = _match_keywords(
            ["python", "postgresql", "docker"],
            "Built a Python application with PostgreSQL.",
        )

        self.assertEqual(matched, ["python", "postgresql"])
        self.assertEqual(missing, ["docker"])

    def test_format_score_rewards_structured_resume_features(self):
        resume = """EDUCATION
B.Tech, 2025
Contact: candidate@example.com
SKILLS
Python, FastAPI, PostgreSQL
PROJECTS
Built an API that reduced latency by 40%.
- Designed a data pipeline.
"""

        self.assertEqual(_format_score(resume), 87)

    def test_format_score_rejects_empty_resume(self):
        self.assertEqual(_format_score(""), 0)


if __name__ == "__main__":
    unittest.main()
