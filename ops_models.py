"""Pydantic models and workflow constants for URA-PROMET operations."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

RETURN_TRANSITIONS = {
    "draft": {"submitted", "archived"},
    "submitted": {"under_review", "voided", "archived"},
    "under_review": {"needs_correction", "accepted", "rejected", "voided", "archived"},
    "needs_correction": {"submitted", "voided", "archived"},
    "accepted": {"archived"},
    "rejected": {"archived"},
    "voided": {"archived"},
    "archived": set(),
}
ASSESSMENT_STATES = {"draft", "issued", "disputed", "adjusted", "satisfied", "voided", "archived"}
CASE_STATES = {"open", "suspended", "reopened", "closed", "voided", "archived"}
NOTICE_STATES = {"draft", "approved", "issued", "cancelled", "archived"}


class TaxpayerPatch(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None
    reason: str | None = None


class NoteIn(BaseModel):
    note: str = Field(min_length=1)


class ReturnReviewPatch(BaseModel):
    state: str
    reviewer_notes: str | None = None
    reason: str | None = None


class AssessmentLineIn(BaseModel):
    line_type: Literal["adjustment", "other"] = "adjustment"
    amount: float
    reason: str | None = None


class AssessmentCreate(BaseModel):
    taxpayer_id: str
    return_id: str | None = None
    principal: float = 0
    penalty: float = 0
    interest: float = 0
    adjustments: list[AssessmentLineIn] = []
    reason: str | None = None


class AssessmentPatch(BaseModel):
    status: str | None = None
    principal: float | None = None
    penalty: float | None = None
    interest: float | None = None
    reason: str | None = None


class CompliancePatch(BaseModel):
    filing_compliance: str | None = None
    payment_compliance: str | None = None
    risk_flags: list[str] | None = None
    notes: str | None = None
    next_action_date: str | None = None


class PaymentAllocationIn(BaseModel):
    taxpayer_id: str
    liability_id: str
    amount: float = Field(gt=0)
    payment_reference: str | None = None
    reason: str | None = None


class ReversalIn(BaseModel):
    reason: str = Field(min_length=1)


class InstallmentCreate(BaseModel):
    taxpayer_id: str
    liability_id: str | None = None
    total_amount: float = Field(gt=0)
    installment_count: int = Field(gt=0)
    frequency: str
    start_date: str


class InstallmentPatch(BaseModel):
    status: str
    reason: str | None = None


class NoticeCreate(BaseModel):
    taxpayer_id: str
    notice_type: str
    subject: str
    content: str
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    supersedes_notice_id: str | None = None


class NoticePatch(BaseModel):
    subject: str | None = None
    content: str | None = None
    status: str | None = None
    reason: str | None = None


class CaseCreate(BaseModel):
    taxpayer_id: str
    case_type: str
    title: str
    description: str | None = None
    priority: str = "normal"
    assigned_to: str | None = None


class CasePatch(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    assigned_to: str | None = None
    status: str | None = None
    reason: str | None = None


class CaseEventIn(BaseModel):
    event_type: str
    note: str | None = None
    metadata: dict[str, Any] = {}
