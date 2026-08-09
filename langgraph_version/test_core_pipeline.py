"""Dependency-light tests for the deterministic parts of the optimize pipeline."""

from __future__ import annotations

import os
import unittest

os.environ["MOCK_LLM"] = "1"

from graph import (  # noqa: E402
    analyze_jd,
    load_resume,
    optimize,
    review,
    route_after_stage,
)


class CorePipelineTests(unittest.TestCase):
    def test_mock_nodes_complete_without_retries(self) -> None:
        state = {
            "resume_text": "Candidate with Python, Django, MySQL, and Redis experience.",
            "jd_text": "Python backend engineer; Django, MySQL, Redis, and Docker required.",
            "target_company": "Mock Company Ltd.",
            "attempts": 0,
        }
        state.update(load_resume(state))
        self.assertEqual(route_after_stage(state), "continue")

        state.update(analyze_jd(state))
        self.assertEqual(route_after_stage(state), "continue")
        self.assertIn("Python", state["jd_analysis"]["required_skills"])

        state.update(optimize(state))
        self.assertEqual(route_after_stage(state), "continue")
        self.assertTrue(state["optimized_text"])

        state.update(review(state))
        self.assertTrue(state["review_verdict"]["pass"])
        self.assertEqual(state.get("attempts", 0), 0)

    def test_invalid_input_stops_before_downstream_nodes(self) -> None:
        result = load_resume({"resume_text": "", "jd_text": "A valid JD"})
        self.assertTrue(result["error"])
        self.assertNotEqual(route_after_stage(result), "continue")


if __name__ == "__main__":
    unittest.main()
