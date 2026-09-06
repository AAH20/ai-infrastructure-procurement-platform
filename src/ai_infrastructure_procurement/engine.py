from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any


def _months_old(value: str, today: date) -> int:
    observed = datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return max(0, (today.year - observed.year) * 12 + today.month - observed.month)


def evaluate_offer(rfp: dict[str, Any], offer: dict[str, Any], today: date) -> dict[str, Any]:
    requirements = rfp["requirements"]
    evidence = offer["evidence"]
    violations: list[str] = []
    if offer["region"] not in requirements["allowed_regions"]:
        violations.append("data_residency")
    if offer["p99_ttft_ms"] > requirements["max_p99_ttft_ms"]:
        violations.append("latency_slo")
    if offer["workflow_success_rate"] < requirements["min_workflow_success_rate"]:
        violations.append("quality_floor")
    if offer["availability"] < requirements["min_availability"]:
        violations.append("availability_slo")
    if offer["gpu_memory_gb"] < requirements["min_gpu_memory_gb"]:
        violations.append("gpu_memory")
    missing_controls = sorted(set(requirements.get("required_controls", [])) - set(offer.get("controls", [])))
    if missing_controls:
        violations.append("required_controls")
    age_months = _months_old(evidence["observed_at"], today)
    if age_months > requirements["max_evidence_age_months"]:
        violations.append("stale_evidence")
    if evidence["provenance"] not in requirements["accepted_provenance"]:
        violations.append("unaccepted_provenance")

    volume = rfp["monthly_requests"]
    revenue = volume * rfp["revenue_per_success_usd"] * offer["workflow_success_rate"]
    delivery = offer["monthly_platform_usd"] + volume * offer["variable_cost_per_request_usd"]
    delivery += offer.get("monthly_support_usd", 0) + offer.get("monthly_egress_usd", 0)
    amortized_migration = offer.get("migration_cost_usd", 0) / max(rfp["contract_months"], 1)
    outage_loss = rfp["monthly_revenue_at_risk_usd"] * max(0, 1 - offer["availability"])
    capacity_loss = rfp["monthly_revenue_at_risk_usd"] * offer.get("capacity_shortfall_probability", 0)
    supplier_loss = rfp["monthly_revenue_at_risk_usd"] * offer.get("supplier_failure_probability", 0)
    risk_adjusted_cost = delivery + amortized_migration + outage_loss + capacity_loss + supplier_loss
    margin = revenue - risk_adjusted_cost
    score = margin
    result = {
        "supplier": offer["supplier"],
        "offer_id": offer["offer_id"],
        "eligible": not violations,
        "violations": violations,
        "missing_controls": missing_controls,
        "evidence_age_months": age_months,
        "monthly_delivery_cost_usd": round(delivery, 2),
        "monthly_risk_adjusted_cost_usd": round(risk_adjusted_cost, 2),
        "monthly_revenue_usd": round(revenue, 2),
        "monthly_contribution_margin_usd": round(margin, 2),
        "contribution_margin_pct": round(margin / revenue * 100, 2) if revenue else None,
        "modeled_risk_components_usd": {
            "amortized_migration": round(amortized_migration, 2),
            "availability": round(outage_loss, 2),
            "capacity": round(capacity_loss, 2),
            "supplier": round(supplier_loss, 2),
        },
        "ranking_value": round(score, 2),
    }
    return result


def evaluate_procurement(bundle: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rfp = bundle["rfp"]
    results = [evaluate_offer(rfp, offer, today) for offer in bundle["offers"]]
    eligible = sorted(
        (item for item in results if item["eligible"]),
        key=lambda item: (-item["ranking_value"], item["monthly_risk_adjusted_cost_usd"]),
    )
    selected = eligible[0] if eligible else None
    acceptance = []
    if selected:
        requirements = rfp["requirements"]
        acceptance = [
            f"P99 TTFT <= {requirements['max_p99_ttft_ms']} ms under the disclosed workload",
            f"Workflow success rate >= {requirements['min_workflow_success_rate']:.3f}",
            f"Monthly availability >= {requirements['min_availability']:.4f}",
            "Benchmark context and provenance must remain reproducible",
            "Cost variance beyond the contractual threshold requires review",
        ]
    report = {
        "schema_version": "0.1.0",
        "rfp_id": rfp["rfp_id"],
        "classification": "MODELED_ADVISORY_NON_CONTRACTUAL",
        "decision": "RECOMMEND" if selected else "NO_ELIGIBLE_OFFER",
        "recommended": selected,
        "eligible_offers": eligible,
        "rejected_offers": [item for item in results if not item["eligible"]],
        "acceptance_criteria": acceptance,
        "review_required": True,
        "assumptions": "Financial and risk inputs are buyer-supplied estimates; authorized humans approve awards.",
    }
    encoded = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["integrity"] = {"algorithm": "sha256", "digest": hashlib.sha256(encoded).hexdigest()}
    return report

