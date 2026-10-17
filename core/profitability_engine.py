"""Per-treatment profitability engine.

Provides analysis of service-level profitability:
- By treatment type (which services are most/least profitable)
- By patient (which patients generate the most value)
- Cost breakdown (materials, labor, overhead, lab)
- Margin analysis and ranking

All calculations are deterministic — the LLM narrates, never computes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from schema.standard_schema import BusinessSnapshot, ServiceEvent


@dataclass
class TreatmentTypeProfitability:
    """Aggregated profitability for one treatment type."""
    service_name: str
    category: str
    count: int = 0
    total_revenue: Decimal = Decimal("0")
    total_materials: Decimal = Decimal("0")
    total_lab: Decimal = Decimal("0")
    total_labor: Decimal = Decimal("0")
    total_overhead: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_profit: Decimal = Decimal("0")

    @property
    def avg_revenue(self) -> Decimal:
        return (self.total_revenue / self.count).quantize(Decimal("1")) if self.count else Decimal("0")

    @property
    def avg_profit(self) -> Decimal:
        return (self.total_profit / self.count).quantize(Decimal("1")) if self.count else Decimal("0")

    @property
    def gross_margin(self) -> Decimal:
        if self.total_revenue == 0:
            return Decimal("0")
        return (self.total_profit / self.total_revenue * 100).quantize(Decimal("0.1"))


@dataclass
class PatientProfitability:
    """Aggregated profitability for one patient."""
    patient_name: str
    visit_count: int = 0
    total_revenue: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    total_profit: Decimal = Decimal("0")
    treatments: list[str] = field(default_factory=list)

    @property
    def gross_margin(self) -> Decimal:
        if self.total_revenue == 0:
            return Decimal("0")
        return (self.total_profit / self.total_revenue * 100).quantize(Decimal("0.1"))


@dataclass
class CostBreakdown:
    """Overall cost structure breakdown."""
    total_materials: Decimal = Decimal("0")
    total_lab: Decimal = Decimal("0")
    total_labor: Decimal = Decimal("0")
    total_overhead: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")

    @property
    def materials_pct(self) -> Decimal:
        return (self.total_materials / self.total_cost * 100).quantize(Decimal("0.1")) if self.total_cost else Decimal("0")

    @property
    def lab_pct(self) -> Decimal:
        return (self.total_lab / self.total_cost * 100).quantize(Decimal("0.1")) if self.total_cost else Decimal("0")

    @property
    def labor_pct(self) -> Decimal:
        return (self.total_labor / self.total_cost * 100).quantize(Decimal("0.1")) if self.total_cost else Decimal("0")

    @property
    def overhead_pct(self) -> Decimal:
        return (self.total_overhead / self.total_cost * 100).quantize(Decimal("0.1")) if self.total_cost else Decimal("0")


def profitability_by_treatment_type(
    snapshot: BusinessSnapshot,
    start: date | None = None,
    end: date | None = None,
) -> list[TreatmentTypeProfitability]:
    """Analyze profitability grouped by treatment type.

    Returns list sorted by total profit descending.
    """
    events = _filter_events(snapshot.service_events, start, end)
    svc_types = {s.id: s for s in snapshot.service_types}

    by_type: dict[str, TreatmentTypeProfitability] = {}

    for ev in events:
        svc = svc_types.get(ev.service_type_id)
        category = svc.category if svc else "אחר"
        key = ev.service_name

        if key not in by_type:
            by_type[key] = TreatmentTypeProfitability(service_name=key, category=category)

        t = by_type[key]
        t.count += 1
        t.total_revenue += ev.revenue
        t.total_materials += sum(m.total_cost for m in ev.materials_used)
        t.total_lab += ev.lab_cost
        t.total_labor += ev.direct_labor_cost
        t.total_overhead += ev.overhead_allocated
        t.total_cost += ev.total_cost
        t.total_profit += ev.gross_profit

    return sorted(by_type.values(), key=lambda x: x.total_profit, reverse=True)


def profitability_by_patient(
    snapshot: BusinessSnapshot,
    start: date | None = None,
    end: date | None = None,
    top_n: int = 20,
) -> list[PatientProfitability]:
    """Analyze profitability grouped by patient.

    Returns top N patients sorted by total profit descending.
    """
    events = _filter_events(snapshot.service_events, start, end)

    by_patient: dict[str, PatientProfitability] = {}

    for ev in events:
        key = ev.patient_name
        if key not in by_patient:
            by_patient[key] = PatientProfitability(patient_name=key)

        p = by_patient[key]
        p.visit_count += 1
        p.total_revenue += ev.revenue
        p.total_cost += ev.total_cost
        p.total_profit += ev.gross_profit
        p.treatments.append(ev.service_name)

    sorted_patients = sorted(by_patient.values(), key=lambda x: x.total_profit, reverse=True)
    return sorted_patients[:top_n]


def overall_cost_breakdown(
    snapshot: BusinessSnapshot,
    start: date | None = None,
    end: date | None = None,
) -> CostBreakdown:
    """Break down total costs into materials, lab, labor, and overhead."""
    events = _filter_events(snapshot.service_events, start, end)

    breakdown = CostBreakdown()
    for ev in events:
        breakdown.total_materials += sum(m.total_cost for m in ev.materials_used)
        breakdown.total_lab += ev.lab_cost
        breakdown.total_labor += ev.direct_labor_cost
        breakdown.total_overhead += ev.overhead_allocated
        breakdown.total_cost += ev.total_cost

    return breakdown


def single_treatment_detail(
    snapshot: BusinessSnapshot,
    service_event_id: str,
) -> ServiceEvent | None:
    """Get full cost breakdown for a single treatment event."""
    for ev in snapshot.service_events:
        if ev.id == service_event_id:
            return ev
    return None


def _filter_events(
    events: list[ServiceEvent],
    start: date | None,
    end: date | None,
) -> list[ServiceEvent]:
    """Filter events by date range."""
    filtered = events
    if start:
        filtered = [e for e in filtered if e.date >= start]
    if end:
        filtered = [e for e in filtered if e.date <= end]
    return filtered
