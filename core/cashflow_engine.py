"""Deterministic cashflow projection engine.

All financial logic is here — the LLM never invents financial rules.
Rules defined/validated by Meital (domain expert).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from schema.standard_schema import BusinessSnapshot, Invoice, InvoiceStatus, PaymentTerms


@dataclass
class CashflowEvent:
    """A projected cash inflow or outflow."""
    date: date
    amount: Decimal  # positive=inflow, negative=outflow
    description: str
    counterparty: str
    invoice_id: str | None = None


@dataclass
class CashflowAlert:
    """An alert when projected balance drops below threshold."""
    alert_date: date
    projected_balance: Decimal
    trigger_event: CashflowEvent
    days_until: int
    severity: str  # "warning" | "critical"


@dataclass
class PaymentTermConflict:
    """A detected mismatch between incoming and outgoing payment terms."""
    supplier_name: str
    supplier_terms: PaymentTerms
    supplier_payment_date: date
    supplier_amount: Decimal
    customer_name: str
    customer_terms: PaymentTerms
    customer_payment_date: date
    customer_amount: Decimal
    cash_gap_days: int
    projected_balance_at_payment: Decimal
    recommendation: str


def project_cashflow(
    snapshot: BusinessSnapshot,
    horizon_days: int = 90,
    alert_threshold: Decimal = Decimal("10000"),
) -> tuple[list[CashflowEvent], list[CashflowAlert]]:
    """Project cashflow for the next N days based on outstanding invoices.

    Returns:
        Tuple of (projected_events, alerts).
    """
    today = snapshot.as_of.date()
    horizon_end = today + timedelta(days=horizon_days)

    events: list[CashflowEvent] = []

    # Collect all unpaid invoices with due dates in the horizon
    for inv in snapshot.invoices:
        if inv.status in (InvoiceStatus.SENT, InvoiceStatus.OVERDUE):
            if inv.due_date <= horizon_end:
                amount = inv.total if inv.is_incoming else -inv.total
                events.append(CashflowEvent(
                    date=inv.due_date,
                    amount=amount,
                    description=inv.description,
                    counterparty=inv.counterparty,
                    invoice_id=inv.id,
                ))

    # Add recurring payroll (9th of each month)
    total_payroll = sum(
        e.gross_salary + e.bituach_leumi + e.pension + e.keren_hishtalmut
        for e in snapshot.employees
    )
    current = today.replace(day=9)
    if current <= today:
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)
    while current <= horizon_end:
        events.append(CashflowEvent(
            date=current,
            amount=-total_payroll,
            description="משכורות",
            counterparty="עובדים",
        ))
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # Add recurring rent (1st of each month)
    rent_invoices = [inv for inv in snapshot.invoices if "שכירות" in inv.description]
    if rent_invoices:
        monthly_rent = rent_invoices[-1].total
        current = today.replace(day=1)
        if current <= today:
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        while current <= horizon_end:
            events.append(CashflowEvent(
                date=current,
                amount=-monthly_rent,
                description="שכירות חודשית",
                counterparty="נכסי ברוש",
            ))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)

    # Sort by date
    events.sort(key=lambda e: e.date)

    # Walk through and detect alerts
    balance = snapshot.current_balance
    alerts: list[CashflowAlert] = []

    for event in events:
        balance += event.amount
        if balance < alert_threshold:
            severity = "critical" if balance < Decimal("0") else "warning"
            alerts.append(CashflowAlert(
                alert_date=event.date,
                projected_balance=balance,
                trigger_event=event,
                days_until=(event.date - today).days,
                severity=severity,
            ))

    return events, alerts


def detect_payment_term_conflicts(
    snapshot: BusinessSnapshot,
    horizon_days: int = 90,
) -> list[PaymentTermConflict]:
    """Detect cases where supplier payment terms create cashflow pressure
    relative to customer payment terms.

    The core insight: if you pay a supplier on Net-60 but collect from a customer
    on Net-90, you have a 30-day cash gap.
    """
    today = snapshot.as_of.date()
    horizon_end = today + timedelta(days=horizon_days)

    # Collect upcoming outgoing payments (to suppliers)
    outgoing = [
        inv for inv in snapshot.invoices
        if not inv.is_incoming
        and inv.status in (InvoiceStatus.SENT,)
        and inv.due_date <= horizon_end
    ]

    # Collect upcoming incoming payments (from customers)
    incoming = [
        inv for inv in snapshot.invoices
        if inv.is_incoming
        and inv.status in (InvoiceStatus.SENT,)
        and inv.due_date <= horizon_end
    ]

    conflicts: list[PaymentTermConflict] = []

    # Project balance day by day to find the balance at each supplier payment date
    events, _ = project_cashflow(snapshot, horizon_days)

    _terms_days = {
        PaymentTerms.IMMEDIATE: 0, PaymentTerms.NET_30: 30,
        PaymentTerms.NET_60: 60, PaymentTerms.NET_90: 90,
    }

    # Find structural timing mismatches: you pay suppliers BEFORE you collect
    # from customers, creating a financing gap — even if the absolute balance is OK.
    seen_pairs: set[tuple[str, str]] = set()

    for sup_inv in outgoing:
        for cust_inv in incoming:
            # Skip if customer pays BEFORE or ON the supplier due date (no gap)
            if cust_inv.due_date <= sup_inv.due_date:
                continue

            gap_days = (cust_inv.due_date - sup_inv.due_date).days

            # Only flag meaningful gaps (>= 15 days)
            if gap_days < 15:
                continue

            # Deduplicate by supplier-customer pair
            pair = (sup_inv.counterparty, cust_inv.counterparty)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Calculate projected balance at supplier payment date
            balance = snapshot.current_balance
            for event in events:
                if event.date <= sup_inv.due_date:
                    balance += event.amount
                else:
                    break

            # Recommend extending supplier terms to cover the gap
            current_sup_days = _terms_days.get(sup_inv.payment_terms, 30)
            cust_days = _terms_days.get(cust_inv.payment_terms, 30)

            if current_sup_days >= cust_days:
                continue  # Supplier terms already longer — no issue

            recommended_terms = PaymentTerms.NET_90

            conflicts.append(PaymentTermConflict(
                supplier_name=sup_inv.counterparty,
                supplier_terms=sup_inv.payment_terms,
                supplier_payment_date=sup_inv.due_date,
                supplier_amount=sup_inv.total,
                customer_name=cust_inv.counterparty,
                customer_terms=cust_inv.payment_terms,
                customer_payment_date=cust_inv.due_date,
                customer_amount=cust_inv.total,
                cash_gap_days=gap_days,
                projected_balance_at_payment=balance,
                recommendation=(
                    f"מומלץ לבקש מהספק '{sup_inv.counterparty}' "
                    f"תנאי תשלום {recommended_terms.value} במקום {sup_inv.payment_terms.value}. "
                    f"כך התשלום לספק ייפול אחרי קבלת ₪{cust_inv.total:,.0f} "
                    f"מ-{cust_inv.counterparty}, ותימנע ממימון פער של {gap_days} ימים."
                ),
            ))

    return conflicts
