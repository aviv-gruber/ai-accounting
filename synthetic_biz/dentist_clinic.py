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
    MaterialItem,
    MaterialUsage,
    OverheadPool,
    PaymentTerms,
    ServiceEvent,
    ServiceType,
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


# --- Hebrew patient names for realistic simulation ---
_PATIENT_FIRST = ["דוד", "שרה", "משה", "רחל", "יוסי", "מירי", "אבי", "נורית",
                   "עמית", "הילה", "רון", "דנה", "גיל", "ליאת", "אורי", "תמר"]
_PATIENT_LAST = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אברהם", "דהן", "חדד",
                  "אזולאי", "שלום", "גבאי", "אוחיון", "בן דוד", "יצחקי", "נחום", "סויסה"]


def _make_materials_catalog(vendors: list[Vendor]) -> list[MaterialItem]:
    """Create the dental materials catalog with realistic Israeli costs."""
    dental_vendor_id = next(v.id for v in vendors if "ציוד" in v.category)
    hygiene_vendor_id = next(v.id for v in vendors if "חיטוי" in v.category)

    return [
        # Restorative materials
        MaterialItem(id="mat_composite", name="קומפוזיט (שרף מילוי)", unit_cost=Decimal("45"),
                     unit="מנה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_bonding", name="חומר הדבקה (בונדינג)", unit_cost=Decimal("12"),
                     unit="טיפה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_etch", name="חומר חריטה (אצ׳)", unit_cost=Decimal("8"),
                     unit="מ״ל", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_anesthesia", name="אמפולת הרדמה", unit_cost=Decimal("18"),
                     unit="יחידה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_needle", name="מחט הרדמה", unit_cost=Decimal("5"),
                     unit="יחידה", vendor_id=dental_vendor_id),
        # Endodontic
        MaterialItem(id="mat_endo_file", name="שיבולי אנדו", unit_cost=Decimal("35"),
                     unit="ערכה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_gutta", name="גוטה פרצ׳ה", unit_cost=Decimal("15"),
                     unit="יחידה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_sealer", name="סילר (חומר איטום)", unit_cost=Decimal("20"),
                     unit="מנה", vendor_id=dental_vendor_id),
        # Hygiene / disposable
        MaterialItem(id="mat_gloves", name="כפפות", unit_cost=Decimal("2"),
                     unit="זוג", vendor_id=hygiene_vendor_id),
        MaterialItem(id="mat_mask", name="מסכה", unit_cost=Decimal("1"),
                     unit="יחידה", vendor_id=hygiene_vendor_id),
        MaterialItem(id="mat_bib", name="סינר חד פעמי", unit_cost=Decimal("1"),
                     unit="יחידה", vendor_id=hygiene_vendor_id),
        MaterialItem(id="mat_suction", name="יניקה חד פעמית", unit_cost=Decimal("3"),
                     unit="יחידה", vendor_id=hygiene_vendor_id),
        MaterialItem(id="mat_xray", name="סנסור צילום (פילם)", unit_cost=Decimal("8"),
                     unit="יחידה", vendor_id=dental_vendor_id),
        # Scaling / hygienist
        MaterialItem(id="mat_polish", name="משחת פולישינג", unit_cost=Decimal("10"),
                     unit="מנה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_fluoride", name="פלואוריד", unit_cost=Decimal("15"),
                     unit="מנה", vendor_id=dental_vendor_id),
        # Surgical
        MaterialItem(id="mat_suture", name="חוט תפר", unit_cost=Decimal("25"),
                     unit="יחידה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_gauze", name="גזה סטרילית", unit_cost=Decimal("3"),
                     unit="יחידה", vendor_id=hygiene_vendor_id),
        # Impression / prosthetics
        MaterialItem(id="mat_impression", name="חומר טביעה", unit_cost=Decimal("40"),
                     unit="מנה", vendor_id=dental_vendor_id),
        MaterialItem(id="mat_temp_crown", name="כתר זמני", unit_cost=Decimal("30"),
                     unit="יחידה", vendor_id=dental_vendor_id),
    ]


def _make_service_types(materials: list[MaterialItem]) -> list[ServiceType]:
    """Define the clinic's treatment catalog with bill of materials."""
    mat = {m.id: m for m in materials}

    def _usage(mat_id: str, qty: int | float = 1) -> MaterialUsage:
        m = mat[mat_id]
        q = Decimal(str(qty))
        return MaterialUsage(
            material_id=m.id, material_name=m.name,
            quantity=q, unit_cost=m.unit_cost, total_cost=m.unit_cost * q,
        )

    # Base disposables used in every treatment
    base_disposables = [
        _usage("mat_gloves", 2), _usage("mat_mask"), _usage("mat_bib"),
        _usage("mat_suction"),
    ]

    return [
        ServiceType(
            id="svc_checkup", name="בדיקה + צילום", category="אבחון",
            standard_price=Decimal("350"), duration_minutes=20,
            materials=base_disposables + [_usage("mat_xray")],
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_filling_small", name="סתימת קומפוזיט — קטנה", category="טיפולים משמרים",
            standard_price=Decimal("450"), duration_minutes=30,
            materials=base_disposables + [
                _usage("mat_anesthesia"), _usage("mat_needle"),
                _usage("mat_composite"), _usage("mat_bonding"), _usage("mat_etch"),
            ],
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_filling_large", name="סתימת קומפוזיט — גדולה", category="טיפולים משמרים",
            standard_price=Decimal("800"), duration_minutes=45,
            materials=base_disposables + [
                _usage("mat_anesthesia"), _usage("mat_needle"),
                _usage("mat_composite", 2), _usage("mat_bonding"), _usage("mat_etch"),
            ],
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_root_canal", name="טיפול שורש", category="אנדודונטיה",
            standard_price=Decimal("2500"), duration_minutes=90,
            materials=base_disposables + [
                _usage("mat_anesthesia", 2), _usage("mat_needle", 2),
                _usage("mat_endo_file"), _usage("mat_gutta", 3),
                _usage("mat_sealer"), _usage("mat_xray", 3),
            ],
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_scaling", name="ניקוי אבנית (סקיילינג)", category="היגיינה",
            standard_price=Decimal("600"), duration_minutes=45,
            materials=base_disposables + [
                _usage("mat_polish"), _usage("mat_fluoride"),
            ],
            staff_roles_required=["שיננית"],
        ),
        ServiceType(
            id="svc_extraction", name="עקירת שן", category="כירורגיה",
            standard_price=Decimal("500"), duration_minutes=30,
            materials=base_disposables + [
                _usage("mat_anesthesia", 2), _usage("mat_needle", 2),
                _usage("mat_gauze", 3), _usage("mat_suture"),
            ],
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_crown", name="כתר חרסינה", category="פרותזה",
            standard_price=Decimal("3500"), duration_minutes=60,
            materials=base_disposables + [
                _usage("mat_anesthesia"), _usage("mat_needle"),
                _usage("mat_impression"), _usage("mat_temp_crown"),
                _usage("mat_xray"),
            ],
            requires_lab=True, lab_cost=Decimal("800"),
            staff_roles_required=["רופא", "סייעת"],
        ),
        ServiceType(
            id="svc_whitening", name="הלבנת שיניים", category="אסתטיקה",
            standard_price=Decimal("1500"), duration_minutes=60,
            materials=base_disposables + [_usage("mat_fluoride")],
            staff_roles_required=["שיננית"],
        ),
    ]


def _make_overhead_pools() -> list[OverheadPool]:
    """Define the clinic's overhead cost pools."""
    return [
        OverheadPool(name="שכירות", monthly_cost=Decimal("12000")),
        OverheadPool(name="חשמל ומים", monthly_cost=Decimal("2500")),
        OverheadPool(name="ביטוח מקצועי", monthly_cost=Decimal("1800")),
        OverheadPool(name="פחת ציוד רפואי", monthly_cost=Decimal("3500")),
        OverheadPool(name="ניקיון ותחזוקה", monthly_cost=Decimal("2000")),
        OverheadPool(name="תוכנות ומחשוב", monthly_cost=Decimal("800")),
    ]


def _generate_service_events(
    month_start: date,
    service_types: list[ServiceType],
    employees: list[Employee],
    overhead_pools: list[OverheadPool],
) -> list[ServiceEvent]:
    """Generate individual treatment events for one month with full cost allocation."""
    month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    working_days = sum(1 for d in range((month_end - month_start).days + 1)
                       if (month_start + timedelta(days=d)).weekday() < 5)  # Sun-Thu in Israel = 0-4

    # Total clinic minutes per month (~8 hours/day, working days)
    total_monthly_minutes = working_days * 8 * 60

    # Labor cost per minute by role
    role_to_employee = {}
    for emp in employees:
        total_cost = emp.gross_salary + emp.bituach_leumi + emp.pension + emp.keren_hishtalmut
        if "רופא" in emp.role:
            role_to_employee["רופא"] = total_cost
        elif "שינני" in emp.role:
            role_to_employee["שיננית"] = total_cost
        elif "סייע" in emp.role:
            role_to_employee["סייעת"] = total_cost

    # Overhead cost per minute
    total_overhead = sum(p.monthly_cost for p in overhead_pools)
    overhead_per_minute = total_overhead / Decimal(str(total_monthly_minutes))

    # Treatment mix — weighted by frequency (realistic dental clinic distribution)
    treatment_weights = {
        "svc_checkup": 25,
        "svc_filling_small": 20,
        "svc_filling_large": 10,
        "svc_root_canal": 5,
        "svc_scaling": 20,
        "svc_extraction": 5,
        "svc_crown": 5,
        "svc_whitening": 3,
    }

    svc_by_id = {s.id: s for s in service_types}
    total_weight = sum(treatment_weights.values())

    # ~12-15 treatments per day, ~working_days days
    total_treatments = working_days * random.randint(12, 15)

    events: list[ServiceEvent] = []
    for _ in range(total_treatments):
        # Pick treatment type by weight
        r = random.randint(1, total_weight)
        cumulative = 0
        chosen_id = list(treatment_weights.keys())[0]
        for svc_id, weight in treatment_weights.items():
            cumulative += weight
            if r <= cumulative:
                chosen_id = svc_id
                break

        svc = svc_by_id[chosen_id]
        tx_date = month_start + timedelta(days=random.randint(0, (month_end - month_start).days))

        # Random patient name
        patient = f"{random.choice(_PATIENT_FIRST)} {random.choice(_PATIENT_LAST)}"

        # Revenue: standard price +/- 10% variation (discounts, kupat cholim rates)
        price_variation = Decimal(str(random.uniform(0.85, 1.05)))
        revenue = (svc.standard_price * price_variation).quantize(Decimal("1"))

        # Duration: standard +/- 15%
        duration = max(10, int(svc.duration_minutes * random.uniform(0.85, 1.15)))

        # Material costs (with slight quantity variation)
        materials_used = []
        for mu in svc.materials:
            qty_var = Decimal(str(random.uniform(0.9, 1.1)))
            qty = (mu.quantity * qty_var).quantize(Decimal("0.1"))
            materials_used.append(MaterialUsage(
                material_id=mu.material_id, material_name=mu.material_name,
                quantity=qty, unit_cost=mu.unit_cost,
                total_cost=(mu.unit_cost * qty).quantize(Decimal("1")),
            ))
        total_materials = sum(m.total_cost for m in materials_used)

        # Lab cost
        lab_cost = svc.lab_cost

        # Direct labor cost: sum of staff roles × duration
        labor_cost = Decimal("0")
        for role in svc.staff_roles_required:
            role_monthly_cost = role_to_employee.get(role, Decimal("0"))
            role_per_minute = role_monthly_cost / Decimal(str(total_monthly_minutes))
            labor_cost += (role_per_minute * Decimal(str(duration))).quantize(Decimal("1"))

        # Overhead allocation: overhead_per_minute × duration
        overhead = (overhead_per_minute * Decimal(str(duration))).quantize(Decimal("1"))

        total_cost = total_materials + lab_cost + labor_cost + overhead
        gross_profit = revenue - total_cost
        gross_margin = (gross_profit / revenue).quantize(Decimal("0.01")) if revenue else Decimal("0")

        events.append(ServiceEvent(
            id=_uid(), date=tx_date,
            service_type_id=svc.id, service_name=svc.name,
            patient_name=patient, revenue=revenue,
            duration_minutes=duration,
            materials_used=materials_used,
            lab_cost=lab_cost,
            direct_labor_cost=labor_cost,
            overhead_allocated=overhead,
            total_cost=total_cost,
            gross_profit=gross_profit,
            gross_margin=gross_margin,
        ))

    return events


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
    materials = _make_materials_catalog(vendors)
    service_types = _make_service_types(materials)
    overhead_pools = _make_overhead_pools()

    all_invoices: list[Invoice] = []
    all_service_events: list[ServiceEvent] = []
    current_date = start_date

    for _ in range(months):
        month_invoices = _generate_monthly_invoices(current_date, vendors, customers)
        all_invoices.extend(month_invoices)

        month_events = _generate_service_events(
            current_date, service_types, employees, overhead_pools
        )
        all_service_events.extend(month_events)

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
        service_types=service_types,
        materials_catalog=materials,
        service_events=all_service_events,
        overhead_pools=overhead_pools,
    )
