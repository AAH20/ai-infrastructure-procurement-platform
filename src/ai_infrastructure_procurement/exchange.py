"""Private, file-based RFQ comparison protocol built on the procurement evaluator."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

from .engine import evaluate_procurement

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _number(value: object, name: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite number >= {minimum}")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ValueError(f"{name} must be a finite number >= {minimum}")
    return result


def _identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError(f"{name} must be a nonempty string up to 128 characters")
    return value


def _validate_rfp(rfp: dict) -> None:
    if not isinstance(rfp, dict):
        raise TypeError("RFP must be an object")
    _identity(rfp.get("rfp_id"), "rfp_id")
    _identity(rfp.get("workload"), "workload")
    for field in ("monthly_requests", "contract_months"):
        value = rfp.get(field)
        if type(value) is not int or value < 1:
            raise ValueError(f"{field} must be a positive integer")
    for field in ("revenue_per_success_usd", "monthly_revenue_at_risk_usd"):
        _number(rfp.get(field), field)
    req = rfp.get("requirements")
    if not isinstance(req, dict) or not isinstance(req.get("allowed_regions"), list) or not req["allowed_regions"]:
        raise ValueError("requirements.allowed_regions is required")
    if not all(isinstance(region, str) and region for region in req["allowed_regions"]):
        raise ValueError("allowed_regions must contain region names")
    for field in ("max_p99_ttft_ms", "min_gpu_memory_gb", "max_evidence_age_months"):
        _number(req.get(field), field)
    for field in ("min_workflow_success_rate", "min_availability"):
        if _number(req.get(field), field) > 1:
            raise ValueError(f"{field} must be <= 1")
    if not isinstance(req.get("accepted_provenance"), list) or not req["accepted_provenance"]:
        raise ValueError("accepted_provenance is required")
    if not isinstance(req.get("required_controls", []), list):
        raise TypeError("required_controls must be a list")


def _validate_submission(rfp: dict, submission: dict) -> dict:
    if not isinstance(submission, dict) or submission.get("schema_version") != "1.0":
        raise ValueError("supplier submission schema_version must be 1.0")
    if submission.get("rfp_id") != rfp["rfp_id"]:
        raise ValueError("supplier submission targets another RFP")
    offer = submission.get("offer")
    benchmark = submission.get("benchmark")
    if not isinstance(offer, dict) or not isinstance(benchmark, dict):
        raise TypeError("offer and benchmark are required")
    supplier = _identity(offer.get("supplier"), "supplier")
    offer_id = _identity(offer.get("offer_id"), "offer_id")
    if benchmark.get("rfp_digest") != digest(rfp):
        raise ValueError(f"{offer_id}: benchmark is not bound to this RFP")
    if benchmark.get("offer_id") != offer_id or benchmark.get("supplier") != supplier:
        raise ValueError(f"{offer_id}: benchmark identity mismatch")
    if benchmark.get("workload") != rfp["workload"]:
        raise ValueError(f"{offer_id}: benchmark workload mismatch")
    if benchmark.get("region") != offer.get("region") or benchmark.get("runtime") != offer.get("runtime"):
        raise ValueError(f"{offer_id}: benchmark region or runtime mismatch")
    evidence = offer.get("evidence")
    if not isinstance(evidence, dict) or evidence.get("digest") != "sha256:" + digest(benchmark):
        raise ValueError(f"{offer_id}: offer evidence digest mismatch")
    for claim in ("p99_ttft_ms", "workflow_success_rate", "availability", "gpu_memory_gb"):
        if _number(offer.get(claim), claim) != _number(benchmark.get(claim), f"benchmark.{claim}"):
            raise ValueError(f"{offer_id}: {claim} differs from benchmark")
    requests = benchmark.get("requests")
    successes = benchmark.get("successful_workflows")
    if (type(requests) is not int or requests < 20 or type(successes) is not int
            or not 0 <= successes <= requests):
        raise ValueError(f"{offer_id}: benchmark requires at least 20 reconciled requests")
    if abs(successes / requests - offer["workflow_success_rate"]) > 0.000001:
        raise ValueError(f"{offer_id}: workflow success rate does not reconcile")
    for claim in ("workflow_success_rate", "availability"):
        if offer[claim] > 1:
            raise ValueError(f"{claim} must be <= 1")
    for field in ("monthly_platform_usd", "variable_cost_per_request_usd",
                  "monthly_support_usd", "monthly_egress_usd", "migration_cost_usd",
                  "capacity_shortfall_probability", "supplier_failure_probability"):
        _number(offer.get(field, 0), field)
    for field in ("capacity_shortfall_probability", "supplier_failure_probability"):
        if offer.get(field, 0) > 1:
            raise ValueError(f"{field} must be <= 1")
    if (not isinstance(offer.get("region"), str) or not offer["region"]
            or not isinstance(offer.get("runtime"), str) or not offer["runtime"]
            or not isinstance(offer.get("controls"), list)):
        raise TypeError("offer region, runtime and controls are required")
    if benchmark.get("observed_at") != evidence.get("observed_at"):
        raise ValueError(f"{offer_id}: benchmark observation date mismatch")
    if benchmark.get("provenance") != evidence.get("provenance"):
        raise ValueError(f"{offer_id}: benchmark provenance mismatch")
    if not isinstance(benchmark.get("dataset_sha256"), str) or not HEX64.fullmatch(benchmark["dataset_sha256"]):
        raise ValueError(f"{offer_id}: dataset SHA-256 is required")
    if benchmark["dataset_sha256"] == "0" * 64:
        raise ValueError(f"{offer_id}: placeholder dataset digest")
    return offer


def compare(rfp: dict, submissions: list[dict], today: date) -> dict[str, Any]:
    """Return a private advisory ranking; never issue an award or deployment authorization."""
    _validate_rfp(rfp)
    if not 2 <= len(submissions) <= 20:
        raise ValueError("first release requires 2..20 supplier submissions")
    offers: list[dict] = []
    suppliers: set[str] = set()
    ids: set[str] = set()
    datasets: set[str] = set()
    evidence_digests: list[str] = []
    for submission in submissions:
        offer = _validate_submission(rfp, submission)
        if offer["supplier"] in suppliers or offer["offer_id"] in ids:
            raise ValueError("duplicate supplier or offer ID")
        suppliers.add(offer["supplier"])
        ids.add(offer["offer_id"])
        datasets.add(submission["benchmark"]["dataset_sha256"])
        offers.append(offer)
        evidence_digests.append(offer["evidence"]["digest"])
    if len(datasets) != 1:
        raise ValueError("supplier benchmarks must use the same dataset SHA-256")
    ranked = evaluate_procurement({"rfp": rfp, "offers": offers}, today)
    selected = ranked["recommended"]
    report = {
        "schema_version": "1.0",
        "classification": "PRIVATE_ADVISORY_NON_CONTRACTUAL",
        "rfp_id": rfp["rfp_id"],
        "rfp_digest": digest(rfp),
        "supplier_count": len(offers),
        "evidence_digests": sorted(evidence_digests),
        "comparison": ranked,
        "deployment_handoff": {
            "offer_id": selected["offer_id"] if selected else None,
            "supplier": selected["supplier"] if selected else None,
            "buyer_award_required": True,
            "deployment_authorized": False,
            "switchboard_traffic_authorized": False,
        },
        "claim_boundary": "Supplier benchmark and price inputs are declarations, not independently attested or binding quotes. Human buyer award, supplier confirmation, deployment and traffic approval are separate steps.",
    }
    report["comparison_digest"] = digest(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare private AI capacity supplier submissions")
    parser.add_argument("--rfp", required=True, type=Path)
    parser.add_argument("--offers-dir", required=True, type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    paths = sorted(args.offers_dir.glob("*.json"))
    report = compare(json.loads(args.rfp.read_text()),
                     [json.loads(path.read_text()) for path in paths], args.as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"{report['classification']}: {report['supplier_count']} offers, "
          f"{report['comparison']['decision']}; output={args.output}")


if __name__ == "__main__":
    main()
