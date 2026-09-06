import json
import unittest
from datetime import date
from pathlib import Path

from ai_infrastructure_procurement.engine import evaluate_procurement


class ProcurementTests(unittest.TestCase):
    def setUp(self):
        self.bundle = json.loads((Path(__file__).parents[1] / "examples" / "retail-ai-rfp.json").read_text())
        self.report = evaluate_procurement(self.bundle, date(2026, 9, 6))

    def test_recommends_best_eligible_risk_adjusted_offer(self):
        self.assertEqual(self.report["decision"], "RECOMMEND")
        self.assertEqual(self.report["recommended"]["offer_id"], "OFFER-AZURE-NIM")

    def test_rejects_cheap_noncompliant_offer(self):
        rejected = self.report["rejected_offers"][0]
        self.assertIn("data_residency", rejected["violations"])
        self.assertIn("availability_slo", rejected["violations"])
        self.assertIn("required_controls", rejected["violations"])
        self.assertIn("unaccepted_provenance", rejected["violations"])

    def test_report_requires_human_review(self):
        self.assertTrue(self.report["review_required"])
        self.assertEqual(self.report["classification"], "MODELED_ADVISORY_NON_CONTRACTUAL")

    def test_report_has_integrity_digest_and_acceptance_tests(self):
        self.assertEqual(len(self.report["integrity"]["digest"]), 64)
        self.assertGreaterEqual(len(self.report["acceptance_criteria"]), 5)


if __name__ == "__main__":
    unittest.main()

