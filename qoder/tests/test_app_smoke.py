"""Smoke test for the Streamlit UI (uses Streamlit's own AppTest runner).

    python tests/test_app_smoke.py

Checks that the app script runs without exceptions and that pressing
"开始审查" actually produces review findings.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest  # noqa: E402

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


class AppSmokeTests(unittest.TestCase):
    def test_app_runs_and_reviews(self) -> None:
        app = AppTest.from_file(APP, default_timeout=120).run()
        self.assertEqual([str(item.value) for item in app.exception], [])

        labels = [button.label for button in app.button]
        self.assertTrue(any("开始审查" in label for label in labels), labels)

        app.button[0].click().run()
        self.assertEqual([str(item.value) for item in app.exception], [])

        metrics = {metric.label: metric.value for metric in app.metric}
        self.assertIn("🔴 阻断", metrics)
        self.assertIn("🟠 警告", metrics)
        self.assertIn("🔵 提示", metrics)
        # the default sample SQL must trigger at least one warning
        self.assertNotEqual(metrics.get("🟠 警告"), "0")


if __name__ == "__main__":
    unittest.main()
