from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class Coverage(BaseModel):
    covered_days: int
    expected_days: int
    ratio: float
    complete: bool
    message: str


class Provenance(BaseModel):
    sources: list[str]
    date_start: date | None
    date_end: date | None
    method_version: str


class SeriesPoint(BaseModel):
    date: date
    value: float | None
    covered: bool = True


class Comparison(BaseModel):
    recent_value: float | None
    baseline_median: float | None
    baseline_p10: float | None
    baseline_p90: float | None
    difference: float | None
    difference_percent: float | None
    baseline_days: int
    direction: Literal["above", "below", "within", "unavailable"]
    description: str


class MetricSummary(BaseModel):
    key: str
    label: str
    value: float | None
    unit: str
    comparison: Comparison
    series: list[SeriesPoint]
    coverage: Coverage


class ReadinessComponent(BaseModel):
    key: Literal["sleep_duration", "hrv", "resting_hr"]
    label: str
    value: float
    unit: str
    score: int
    baseline_median: float
    baseline_days: int


class ReadinessScore(BaseModel):
    score: int | None
    label: Literal["low", "moderate", "high", "unavailable"]
    message: str
    components: list[ReadinessComponent]
    baseline_days: int
    method_version: str


class DailyReadiness(BaseModel):
    date: date
    score: int | None
    label: Literal["low", "moderate", "high", "unavailable"]


class WeeklyReport(BaseModel):
    week_start: date
    generated_at: datetime
    method_version: str
    summary: str
    payload: dict[str, Any]


class WeeklyReportsResponse(BaseModel):
    generated_at: datetime
    reports: list[WeeklyReport]


class HomeResponse(BaseModel):
    generated_at: datetime
    as_of: date
    sentence: str
    metrics: list[MetricSummary]
    coverage: Coverage
    provenance: Provenance
    report: WeeklyReport | None
    sync: dict[str, Any]
    readiness: ReadinessScore
    readiness_history: list[DailyReadiness]
    today_metrics: list[MetricSummary]
    overnight_metrics: list[MetricSummary]


class DomainResponse(BaseModel):
    generated_at: datetime
    domain: Literal["fitness", "sleep", "nutrition"]
    range: Literal["7d", "28d", "90d"]
    summary: str
    metrics: list[MetricSummary]
    coverage: Coverage
    provenance: Provenance
    details: dict[str, Any] = Field(default_factory=dict)


class SessionSummary(BaseModel):
    id: str
    kind: Literal["sleep", "exercise"]
    start_at: datetime
    end_at: datetime
    title: str
    duration_minutes: float
    details: dict[str, Any]
    provenance: Provenance


class SessionsResponse(BaseModel):
    generated_at: datetime
    sessions: list[SessionSummary]
    coverage: Coverage
    provenance: Provenance


class Profile(BaseModel):
    goal: str | None = None
    time_horizon: str | None = None
    training_frequency: str | None = None
    dietary_preferences: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    timezone: str = "America/Los_Angeles"
    distance_unit: Literal["miles", "kilometers"] = "miles"
    weight_unit: Literal["lb", "kg"] = "lb"
    updated_at: datetime | None = None


class NutritionRange(BaseModel):
    low: float = Field(ge=0)
    high: float = Field(ge=0)

    @field_validator("high")
    @classmethod
    def high_is_not_lower(cls, value: float, info):
        low = info.data.get("low")
        if low is not None and value < low:
            raise ValueError("high must be greater than or equal to low")
        return value


class MealAnalysis(BaseModel):
    description: str
    meal_type: str
    calories: NutritionRange
    protein_g: NutritionRange
    carbs_g: NutritionRange
    fat_g: NutritionRange
    sodium_mg: NutritionRange | None = None
    ingredients: list[str]
    confidence: float = Field(ge=0, le=1)
    uncertainty_note: str


class NutritionDraft(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    status: Literal["uploaded", "analyzing", "ready", "confirmed", "failed", "expired"]
    note: str | None
    thumbnail_url: str
    analysis: MealAnalysis | None


class ConfirmMealRequest(BaseModel):
    eaten_at: datetime
    analysis: MealAnalysis


class AssistantThreadCreate(BaseModel):
    title: str | None = None
    disclosure_accepted: bool


class AssistantThread(BaseModel):
    id: UUID
    provider: str
    created_at: datetime
    title: str | None


class AssistantTurn(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    image_draft_id: UUID | None = None


class AssistantStatus(BaseModel):
    provider: str
    running: bool
    authenticated: bool
    image_capable_model: bool
    model: str | None
    login_url: str | None = None
    reason: str | None = None


class RelationshipResult(BaseModel):
    key: str
    label: str
    coefficient: float | None
    confidence_low: float | None
    confidence_high: float | None
    paired_days: int
    coverage: float
    available: bool
    message: str
    method_version: str = "spearman-bootstrap-v1"
