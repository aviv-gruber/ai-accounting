"""Synthetic data generator for a dentist clinic (מרפאת שיניים).

Generates 12 months of realistic financial data including:
- Bank transactions (income from patients/kupot cholim, expenses for supplies/lab/rent)
- Invoices (patient treatments, supplier purchases)
- Payroll (dentist owner, hygienist, receptionist, assistant)
- Vendor agreements with payment terms
- Customer ledger (private patients + kupot cholim)
- VAT reports (bi-monthly)
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from schema.standard_schema import (
    BankTransaction,
    BusinessSnapshot,
    Customer,
    Employee,
    Invoice,
    InvoiceStatus,
    PaymentTerms,
    TransactionType,
    VATReport,
    Vendor,
)

# Israeli VAT rate
VAT_RATE = Decimal("0.18")

# Approximate Israeli payroll deduction rates (employer portion)
BITUACH_LEUMI_RATE = Decimal("0.0366")
PENSION_RATE = Decimal("0.0625")
KEREN_HISHTALMUT_RATE = Decimal("0.075")
INCOME_TAX_APPROX_RATE = Decimal("0.15")  # Simplified average


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_employees() -> list[Employee]:
    """Create the clinic's staff."""
    staff = [
        ("ד״ר יעל כהן", "רופאת שיניים — בעלים", Decimal("35000")),
        ("מיכל לוי", "שיננית", Decimal("14000")),
        ("נועה אברהם", "קבלנית", Decimal("9000")),
        ("דני חדד", "סייע/ת שיניים", Decimal("10000")),
    ]
    employees = []
    for name, role, gross in staff:
        bl = (gross * BITUACH_LEUMI_RATE).quantize(Decimal("1"))
        pension = (gross * PENSION_RATE).quantize(Decimal("1"))
        kh = (gross * KEREN_HISHTALMUT_RATE).quantize(Decimal("1"))
        tax = (gross * INCOME_TAX_APPROX_RATE).quantize(Decimal("1"))
        net = gross - bl - pension - kh - tax
        employees.append(Employee(
            id=_uid(),
            name=name,
            role=role,
            gross_salary=gross,
            start_date=date(2023, 1, 1),
            bituach_leumi=bl,
            pension=pension,
            keren_hishtalmut=kh,
            net_salary=net,
        ))
    return employees


def _make_vendors() -> list[Vendor]:
    """Create dental suppliers and service providers."""
    return [
        Vendor(id=_uid(), name="דנטל פלוס — ציוד ומתכלים", category="ציוד דנטלי",
               payment_terms=PaymentTerms.NET_60),
        Vendor(id=_uid(), name="מעבדת שיניים ארז", category="מעבדת שיניים",
               payment_terms=PaymentTerms.NET_30),
        Vendor(id=_uid(), name="מדיקל סאפלייז בע״מ", category="חומרי חיטוי ומגן",
               payment_terms=PaymentTerms.NET_30),
        Vendor(id=_uid(), name="נכסי ברוש — השכרת מבנה", category="שכירות",
               payment_terms=PaymentTerms.IMMEDIATE),
    ]


def _make_customers() -> list[Customer]:
    """Create the clinic's customers (kupot cholim + private)."""
    return [
        Customer(id=_uid(), name="קופת חולים כללית", customer_type="קופת חולים",
                 payment_terms=PaymentTerms.NET_90),
        Customer(id=_uid(), name="קופת חולים מכבי", customer_type="קופת חולים",
                 payment_terms=PaymentTerms.NET_90),
        Customer(id=_uid(), name="קופת חולים מאוחדת", customer_type="קופת חולים",
                 payment_terms=PaymentTerms.NET_60),
        Customer(id=_uid(), name="מטופלים פרטיים", customer_type="פרטי",
                 payment_terms=PaymentTerms.IMMEDIATE),
    ]


def _generate_monthly_invoices(
    month_start: date,
    vendors: list[Vendor],
    customers: list[Customer],
) -> list[Invoice]:
    """Generate invoices for one month."""
    invoices: list[Invoice] = []
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    # --- Income invoices (from patients/kupot cholim) ---

    # Private patients: ~60 treatments/month, avg ₪400-1200 each
    n_private = random.randint(50, 70)
    for i in range(n_private):
        tx_date = month_start + timedelta(days=random.randint(0, (month_end - month_start).days))
        amount = Decimal(random.choice([350, 450, 600, 800, 1200, 1500, 2500]))
        vat = (amount * VAT_RATE).quantize(Decimal("1"))
        invoices.append(Invoice(
            id=_uid(), invoice_number=f"INV-{tx_date.strftime('%Y%m')}-{i:03d}",
            date=tx_date, due_date=tx_date,  # private = immediate
            amount=amount, vat_amount=vat, total=amount + vat,
            status=InvoiceStatus.PAID, counterparty="מטופל פרטי",
            description="טיפול שיניים", payment_terms=PaymentTerms.IMMEDIATE,
            is_incoming=True,
        ))

    # Kupot cholim: monthly batch invoices
    for kupa in [c for c in customers if c.customer_type == "קופת חולים"]:
        amount = Decimal(random.randint(8000, 22000))
        vat = (amount * VAT_RATE).quantize(Decimal("1"))
        terms = kupa.payment_terms
        days_offset = {"שוטף+30": 30, "שוטף+60": 60, "שוטף+90": 90, "מזומן": 0}
        due = month_end + timedelta(days=days_offset.get(terms.value, 30))
        # Determine status based on due date vs "today" (end of dataset)
        status = InvoiceStatus.SENT  # will be resolved later
        invoices.append(Invoice(
            id=_uid(), invoice_number=f"INV-{month_start.strftime('%Y%m')}-{kupa.name[:4]}",
            date=month_end, due_date=due,
            amount=amount, vat_amount=vat, total=amount + vat,
            status=status, counterparty=kupa.name,
            description=f"טיפולי שיניים — {kupa.name}", payment_terms=terms,
            is_incoming=True,
        ))

    # --- Expense invoices (to suppliers) ---

    # Dental supplies: 1-2 orders/month
    dental_vendor = [v for v in vendors if "ציוד" in v.category][0]
    for _ in range(random.randint(1, 2)):
        tx_date = month_start + timedelta(days=random.randint(1, 20))
        amount = Decimal(random.randint(3000, 18000))
        vat = (amount * VAT_RATE).quantize(Decimal("1"))
        days_offset = {"שוטף+30": 30, "שוטף+60": 60, "שוטף+90": 90, "מזומן": 0}
        due = tx_date + timedelta(days=days_offset.get(dental_vendor.payment_terms.value, 30))
        invoices.append(Invoice(
            id=_uid(), invoice_number=f"PO-{tx_date.strftime('%Y%m')}-{_uid()[:4]}",
            date=tx_date, due_date=due,
            amount=amount, vat_amount=vat, total=amount + vat,
            status=InvoiceStatus.SENT, counterparty=dental_vendor.name,
            description="הזמנת ציוד דנטלי", payment_terms=dental_vendor.payment_terms,
            is_incoming=False,
        ))

    # Dental lab: 1 invoice/month
    lab_vendor = [v for v in vendors if "מעבדת" in v.category][0]
    amount = Decimal(random.randint(4000, 8000))
    vat = (amount * VAT_RATE).quantize(Decimal("1"))
    invoices.append(Invoice(
        id=_uid(), invoice_number=f"LAB-{month_start.strftime('%Y%m')}",
        date=month_start + timedelta(days=random.randint(5, 25)),
        due_date=month_end + timedelta(days=30),
        amount=amount, vat_amount=vat, total=amount + vat,
        status=InvoiceStatus.SENT, counterparty=lab_vendor.name,
        description="עבודות מעבדה — כתרים ושתלים", payment_terms=lab_vendor.payment_terms,
        is_incoming=False,
    ))

    # Rent: 1st of month, immediate
    rent_vendor = [v for v in vendors if "שכירות" in v.category][0]
    rent = Decimal("12000")
    vat = (rent * VAT_RATE).quantize(Decimal("1"))
    invoices.append(Invoice(
        id=_uid(), invoice_number=f"RENT-{month_start.strftime('%Y%m')}",
        date=month_start, due_date=month_start,
        amount=rent, vat_amount=vat, total=rent + vat,
        status=InvoiceStatus.PAID, counterparty=rent_vendor.name,
        description="שכירות חודשית — מרפאה", payment_terms=PaymentTerms.IMMEDIATE,
        is_incoming=False,
    ))

    return invoices


def _invoices_to_bank_transactions(
    invoices: list[Invoice],
    employees: list[Employee],
    opening_balance: Decimal,
) -> tuple[list[BankTransaction], Decimal]:
    """Convert paid invoices and payroll into bank transactions."""
    transactions: list[BankTransaction] = []
    balance = opening_balance

    # Sort all events chronologically
    events: list[tuple[date, str, Decimal, str, TransactionType]] = []

    for inv in invoices:
        if inv.status == InvoiceStatus.PAID:
            if inv.is_incoming:
                events.append((inv.date, inv.counterparty, inv.total,
                               inv.description, TransactionType.INCOME))
            else:
                events.append((inv.due_date, inv.counterparty, -inv.total,
                               inv.description, TransactionType.EXPENSE))

    # Payroll on the 9th of each month (common in Israel)
    months_seen = set()
    for inv in invoices:
        m = (inv.date.year, inv.date.month)
        if m not in months_seen:
            months_seen.add(m)
            payroll_date = inv.date.replace(day=9)
            total_payroll = sum(e.gross_salary + e.bituach_leumi + e.pension + e.keren_hishtalmut
                                for e in employees)
            events.append((payroll_date, "משכורות", -total_payroll, "תשלום משכורות",
                           TransactionType.PAYROLL))

    events.sort(key=lambda x: x[0])

    for ev_date, counterparty, amount, desc, tx_type in events:
        balance += amount
        transactions.append(BankTransaction(
            id=_uid(), date=ev_date, amount=amount, balance_after=balance,
            description=desc, category=tx_type.value, transaction_type=tx_type,
            counterparty=counterparty,
        ))

    return transactions, balance


def _generate_vat_reports(invoices: list[Invoice]) -> list[VATReport]:
    """Generate bi-monthly VAT reports from invoices."""
    # Group by bi-monthly period (Jan-Feb, Mar-Apr, etc.)
    periods: dict[tuple[int, int], list[Invoice]] = {}
    for inv in invoices:
        year = inv.date.year
        period = (inv.date.month - 1) // 2  # 0-5
        key = (year, period)
        periods.setdefault(key, []).append(inv)

    reports = []
    for (year, period), period_invs in sorted(periods.items()):
        start_month = period * 2 + 1
        end_month = start_month + 1
        period_start = date(year, start_month, 1)
        period_end = (date(year, end_month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

        total_sales = sum(inv.amount for inv in period_invs if inv.is_incoming)
        total_purchases = sum(inv.amount for inv in period_invs if not inv.is_incoming)
        output_vat = sum(inv.vat_amount for inv in period_invs if inv.is_incoming)
        input_vat = sum(inv.vat_amount for inv in period_invs if not inv.is_incoming)

        reports.append(VATReport(
            period_start=period_start, period_end=period_end,
            total_sales=total_sales, total_purchases=total_purchases,
            output_vat=output_vat, input_vat=input_vat,
            vat_payable=output_vat - input_vat,
        ))

    return reports


def generate_dentist_clinic(
    start_date: date = date(2025, 10, 1),
    months: int = 12,
    opening_balance: Decimal = Decimal("45000"),
    seed: int = 42,
) -> BusinessSnapshot:
    """Generate a complete synthetic dentist clinic dataset.

    Args:
        start_date: First month of data.
        months: Number of months to generate.
        opening_balance: Starting bank balance.
        seed: Random seed for reproducibility.

    Returns:
        A BusinessSnapshot with all financial data.
    """
    random.seed(seed)

    employees = _make_employees()
    vendors = _make_vendors()
    customers = _make_customers()

    all_invoices: list[Invoice] = []
    current_date = start_date

    for _ in range(months):
        month_invoices = _generate_monthly_invoices(current_date, vendors, customers)
        all_invoices.extend(month_invoices)
        # Advance to next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)

    # Resolve invoice statuses: anything due before "today" (end of dataset) → PAID or OVERDUE
    dataset_end = current_date
    for inv in all_invoices:
        if inv.status == InvoiceStatus.SENT:
            if inv.due_date < dataset_end:
                # 90% paid on time, 10% overdue
                inv.status = InvoiceStatus.PAID if random.random() < 0.9 else InvoiceStatus.OVERDUE
            # else: still SENT (not yet due)

    # Generate bank transactions from paid invoices
    bank_transactions, final_balance = _invoices_to_bank_transactions(
        all_invoices, employees, opening_balance
    )

    # Generate VAT reports
    vat_reports = _generate_vat_reports(all_invoices)

    from datetime import datetime
    return BusinessSnapshot(
        business_name="מרפאת שיניים ד״ר יעל כהן",
        business_type="מרפאת שיניים",
        as_of=datetime.now(),
        bank_transactions=bank_transactions,
        invoices=all_invoices,
        employees=employees,
        vendors=vendors,
        customers=customers,
        vat_reports=vat_reports,
        current_balance=final_balance,
    )
