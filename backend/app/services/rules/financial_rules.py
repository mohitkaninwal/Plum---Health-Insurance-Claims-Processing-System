"""Financial rules: F01–F05 — amount calculations, co-pay, network discounts, line items."""
from __future__ import annotations

from typing import Any

from app.models import (
    ClaimDecision,
    ClaimDecisionType,
    ClaimSubmission,
    LineItemDecision,
    LineItemDecisionType,
)
from app.models.policy import PolicyTerms


# ── Public rule functions ─────────────────────────────────────────────────────


def approve_or_partially_approve(
    submission: ClaimSubmission, policy: PolicyTerms, confidence: float
) -> ClaimDecision:
    category_config = policy.opd_categories[submission.claim_category.lower()]
    items = line_items(submission)

    if submission.claim_category == "DENTAL":
        excluded = {item.lower() for item in (category_config.excluded_procedures or [])}
        decisions: list[LineItemDecision] = []
        approved_amount = 0.0
        for item in items:
            description = str(item.get("description", "Line item"))
            amount = float(item.get("amount", 0))
            is_excluded = any(term in description.lower() for term in excluded)
            if is_excluded:
                decisions.append(
                    LineItemDecision(
                        description=description,
                        claimed_amount=amount,
                        approved_amount=0,
                        decision=LineItemDecisionType.REJECTED,
                        reason="Excluded cosmetic dental procedure.",
                    )
                )
            else:
                approved_amount += amount
                decisions.append(
                    LineItemDecision(
                        description=description,
                        claimed_amount=amount,
                        approved_amount=amount,
                        decision=LineItemDecisionType.APPROVED,
                        reason="Covered dental procedure.",
                    )
                )
        decision_type = ClaimDecisionType.PARTIAL if approved_amount < submission.claimed_amount else ClaimDecisionType.APPROVED
        rejection_reasons = ["EXCLUDED_DENTAL_PROCEDURE"] if approved_amount == 0 else []
        if approved_amount == 0:
            decision_type = ClaimDecisionType.REJECTED
        return ClaimDecision(
            decision=decision_type,
            approved_amount=approved_amount,
            confidence_score=confidence,
            reason="Covered dental items were approved and excluded cosmetic items were rejected.",
            rejection_reasons=rejection_reasons,
            line_item_decisions=decisions,
        )

    base_amount = submission.claimed_amount
    hospital = submission.hospital_name or _hospital_name(submission)
    parts: list[str] = []
    if hospital in policy.network_hospitals and category_config.network_discount_percent:
        discount = base_amount * category_config.network_discount_percent / 100
        base_amount -= discount
        parts.append(
            f"Network discount {category_config.network_discount_percent:.0f}% applied before co-pay."
        )
    if category_config.copay_percent:
        copay = base_amount * category_config.copay_percent / 100
        base_amount -= copay
        parts.append(f"Co-pay {category_config.copay_percent:.0f}% deducted.")

    reason = " ".join(parts) or "Claim satisfies deterministic policy checks."
    return ClaimDecision(
        decision=ClaimDecisionType.APPROVED,
        approved_amount=round(base_amount, 2),
        confidence_score=confidence,
        reason=reason,
        line_item_decisions=[
            LineItemDecision(
                description="Claim total",
                claimed_amount=submission.claimed_amount,
                approved_amount=round(base_amount, 2),
                decision=LineItemDecisionType.APPROVED,
                reason=reason,
            )
        ],
    )


def line_items(submission: ClaimSubmission) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for doc in submission.documents:
        content = doc.content or {}
        items.extend(content.get("line_items", []))
        if "test_name" in content:
            items.append({"description": content["test_name"], "amount": submission.claimed_amount})
    return items or [{"description": "Claim total", "amount": submission.claimed_amount}]


# ── Private helpers ───────────────────────────────────────────────────────────


def _hospital_name(submission: ClaimSubmission) -> str | None:
    for doc in submission.documents:
        content = doc.content or {}
        if "hospital_name" in content:
            return str(content["hospital_name"])
    return None
