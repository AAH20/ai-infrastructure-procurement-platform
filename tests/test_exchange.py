import json
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from ai_infrastructure_procurement.exchange import compare, digest

ROOT = Path(__file__).resolve().parents[1] / "examples" / "exchange-synthetic"


def fixtures():
    rfp = json.loads((ROOT / "rfp.json").read_text())
    submissions = [json.loads(path.read_text()) for path in sorted((ROOT / "offers").glob("*.json"))]
    return rfp, submissions


class ExchangeTests(unittest.TestCase):
    def test_synthetic_submissions_produce_private_advisory_hold(self):
        rfp, submissions = fixtures()
        result = compare(rfp, submissions, date(2026, 9, 24))
        self.assertEqual(result["classification"], "PRIVATE_ADVISORY_NON_CONTRACTUAL")
        self.assertEqual(result["supplier_count"], 2)
        self.assertEqual(result["comparison"]["decision"], "NO_ELIGIBLE_OFFER")
        self.assertFalse(result["deployment_handoff"]["deployment_authorized"])
        self.assertFalse(result["deployment_handoff"]["switchboard_traffic_authorized"])
        self.assertEqual(len(result["evidence_digests"]), 2)

    def test_declared_measured_offers_are_ranked_but_never_awarded(self):
        rfp, submissions = fixtures()
        for item in submissions:
            item["benchmark"]["provenance"] = "measured"
            item["offer"]["evidence"]["provenance"] = "measured"
            item["offer"]["evidence"]["digest"] = "sha256:" + digest(item["benchmark"])
        result = compare(rfp, submissions, date(2026, 9, 24))
        self.assertEqual(result["comparison"]["decision"], "RECOMMEND")
        self.assertTrue(result["comparison"]["review_required"])
        self.assertFalse(result["deployment_handoff"]["deployment_authorized"])
        self.assertEqual(result["deployment_handoff"]["offer_id"],
                         result["comparison"]["recommended"]["offer_id"])

    def test_mismatched_workload_and_claimed_measurement_rejected(self):
        rfp, submissions = fixtures()
        wrong = deepcopy(submissions)
        wrong[0]["benchmark"]["rfp_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "not bound"):
            compare(rfp, wrong, date(2026, 9, 24))
        wrong = deepcopy(submissions)
        wrong[0]["benchmark"]["successful_workflows"] = 1
        wrong[0]["offer"]["evidence"]["digest"] = "sha256:" + digest(wrong[0]["benchmark"])
        with self.assertRaisesRegex(ValueError, "does not reconcile"):
            compare(rfp, wrong, date(2026, 9, 24))
        wrong = deepcopy(submissions)
        wrong[0]["offer"]["monthly_platform_usd"] = -1
        with self.assertRaisesRegex(ValueError, "finite number"):
            compare(rfp, wrong, date(2026, 9, 24))
        wrong = deepcopy(submissions)
        wrong[1]["benchmark"]["dataset_sha256"] = "2" * 64
        wrong[1]["offer"]["evidence"]["digest"] = "sha256:" + digest(wrong[1]["benchmark"])
        with self.assertRaisesRegex(ValueError, "same dataset"):
            compare(rfp, wrong, date(2026, 9, 24))
        wrong = deepcopy(submissions)
        wrong[1]["benchmark"]["region"] = "us-east-1"
        wrong[1]["offer"]["evidence"]["digest"] = "sha256:" + digest(wrong[1]["benchmark"])
        with self.assertRaisesRegex(ValueError, "region or runtime mismatch"):
            compare(rfp, wrong, date(2026, 9, 24))

    def test_duplicate_supplier_and_single_bid_rejected(self):
        rfp, submissions = fixtures()
        with self.assertRaisesRegex(ValueError, "2..20"):
            compare(rfp, submissions[:1], date(2026, 9, 24))
        duplicate = deepcopy(submissions)
        duplicate[1]["offer"]["supplier"] = duplicate[0]["offer"]["supplier"]
        duplicate[1]["benchmark"]["supplier"] = duplicate[0]["offer"]["supplier"]
        duplicate[1]["offer"]["evidence"]["digest"] = "sha256:" + digest(duplicate[1]["benchmark"])
        with self.assertRaisesRegex(ValueError, "duplicate supplier"):
            compare(rfp, duplicate, date(2026, 9, 24))


if __name__ == "__main__":
    unittest.main()
