"""Controlled vocabularies shared by the DB, the LLM I/O schemas, and the API.

Keeping these as real enums lets both Pydantic (backend) and the generated Zod
schemas (frontend) reject out-of-vocabulary values instead of silently
accepting whatever the model returns (spec §15).
"""

from __future__ import annotations

from enum import Enum


class SectionType(str, Enum):
    prepared_remarks = "prepared_remarks"
    qa = "qa"


class SpeakerRole(str, Enum):
    operator = "operator"
    ceo = "ceo"
    cfo = "cfo"
    other_management = "other_management"
    analyst = "analyst"


class Direction(str, Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"
    mixed = "mixed"


class JobStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    partially_completed = "partially_completed"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    needs_manual_review = "needs_manual_review"


class VerificationMethod(str, Enum):
    exact_substring = "exact_substring"
    fuzzy_candidate = "fuzzy_candidate"
    numeric = "numeric"


class VerificationStatus(str, Enum):
    verified = "verified"
    needs_manual_review = "needs_manual_review"
    failed = "failed"
    insufficient_evidence = "insufficient_evidence"


class Conviction(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class NarrativeConfirmationStatus(str, Enum):
    confirmed_acceleration = "Confirmed Acceleration"
    narrative_ahead_of_numbers = "Narrative Ahead of Numbers"
    conservative_or_underpromising = "Conservative or Underpromising"
    mixed_signals = "Mixed Signals"
    confirmed_deterioration = "Confirmed Deterioration"


class UniverseType(str, Enum):
    core = "core"
    specialist = "specialist"
    dynamic = "dynamic"


class SignalRole(str, Enum):
    capex_sensor = "capex_sensor"
    demand_sensor = "demand_sensor"
    pricing_sensor = "pricing_sensor"
    credit_sensor = "credit_sensor"
    inventory_sensor = "inventory_sensor"
    labor_sensor = "labor_sensor"
    technology_adoption_sensor = "technology_adoption_sensor"
    commodity_sensor = "commodity_sensor"
    supply_chain_sensor = "supply_chain_sensor"
    consumer_health_sensor = "consumer_health_sensor"
