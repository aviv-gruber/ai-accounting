#!/usr/bin/env python3
"""CLI demo — shows cashflow analysis for the synthetic dentist clinic.

Run: python demo_cli.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal

from synthetic_biz.dentist_clinic import generate_dentist_clinic
from core.cashflow_engine import project_cashflow, detect_payment_term_conflicts


def print_header(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}")


def print_section(text: str) -> None:
    print(f"\n--- {text} ---")


def format_ils(amount: Decimal) -> str:
    """Format amount in ILS."""
    if amount >= 0:
        return f"₪{amount:,.0f}"
    return f"-₪{abs(amount):,.0f}"


def main() -> None:
    # Generate synthetic data
    print_header("מרפאת שיניים ד״ר יעל כהן — ניתוח פיננסי")
    print("מייצר נתונים סינתטיים...")

    clinic = generate_dentist_clinic(
        start_date=date(2025, 10, 1),
        months=12,
        opening_balance=Decimal("25000"),
    )

    # Business overview
    print_section("סקירת העסק")
    print(f"  שם העסק: {clinic.business_name}")
    print(f"  סוג: {clinic.business_type}")
    print(f"  עובדים: {len(clinic.employees)}")
    print(f"  ספקים: {len(clinic.vendors)}")
    print(f"  לקוחות מוסדיים: {len([c for c in clinic.customers if c.customer_type != 'פרטי'])}")
    print(f"  יתרת בנק נוכחית: {format_ils(clinic.current_balance)}")

    # Employees
    print_section("עובדים")
    for emp in clinic.employees:
        print(f"  {emp.name} | {emp.role} | ברוטו: {format_ils(emp.gross_salary)} | "
              f"נטו: {format_ils(emp.net_salary)}")

    total_payroll_cost = sum(
        e.gross_salary + e.bituach_leumi + e.pension + e.keren_hishtalmut
        for e in clinic.employees
    )
    print(f"  עלות שכר חודשית כוללת (כולל מעסיק): {format_ils(total_payroll_cost)}")

    # Vendors and payment terms
    print_section("ספקים ותנאי תשלום")
    for v in clinic.vendors:
        print(f"  {v.name} | {v.category} | תנאים: {v.payment_terms.value}")

    # Customers and payment terms
    print_section("לקוחות מוסדיים ותנאי תשלום")
    for c in clinic.customers:
        print(f"  {c.name} | {c.customer_type} | תנאים: {c.payment_terms.value}")

    # Invoice summary
    print_section("סיכום חשבוניות (12 חודשים)")
    incoming = [inv for inv in clinic.invoices if inv.is_incoming]
    outgoing = [inv for inv in clinic.invoices if not inv.is_incoming]
    total_revenue = sum(inv.total for inv in incoming)
    total_expenses = sum(inv.total for inv in outgoing)

    print(f"  הכנסות (חשבוניות): {format_ils(total_revenue)}")
    print(f"  הוצאות (חשבוניות): {format_ils(total_expenses)}")
    print(f"  חשבוניות פתוחות (טרם שולמו): "
          f"{len([i for i in clinic.invoices if i.status.value in ('נשלחה', 'באיחור')])}")

    overdue = [i for i in clinic.invoices if i.status.value == "באיחור"]
    if overdue:
        overdue_total = sum(i.total for i in overdue)
        print(f"  ⚠️  חשבוניות באיחור: {len(overdue)} בסך {format_ils(overdue_total)}")

    # VAT summary
    print_section("דו״חות מע״מ (דו-חודשי)")
    for vat in clinic.vat_reports:
        print(f"  {vat.period_start.strftime('%m/%Y')}-{vat.period_end.strftime('%m/%Y')}: "
              f"עסקאות {format_ils(vat.total_sales)} | "
              f"תשומות {format_ils(vat.total_purchases)} | "
              f"מע״מ לתשלום: {format_ils(vat.vat_payable)}")

    # === CASHFLOW ANALYSIS ===
    print_header("ניתוח תזרים מזומנים — 90 יום קדימה")

    events, alerts = project_cashflow(
        clinic,
        horizon_days=90,
        alert_threshold=Decimal("10000"),
    )

    print(f"\n  אירועים צפויים: {len(events)}")
    print(f"  התראות: {len(alerts)}")

    if alerts:
        print_section("⚠️  התראות תזרים")
        for alert in alerts[:5]:  # Show top 5
            severity_icon = "🔴" if alert.severity == "critical" else "🟡"
            print(f"\n  {severity_icon} בעוד {alert.days_until} ימים ({alert.alert_date}):")
            print(f"     יתרה צפויה: {format_ils(alert.projected_balance)}")
            print(f"     הסיבה: {alert.trigger_event.description} — "
                  f"{alert.trigger_event.counterparty} "
                  f"({format_ils(alert.trigger_event.amount)})")

    # === PAYMENT TERM CONFLICTS ===
    print_header("ניתוח תנאי תשלום — זיהוי קונפליקטים")

    conflicts = detect_payment_term_conflicts(clinic, horizon_days=90)

    if conflicts:
        for i, conflict in enumerate(conflicts[:3], 1):  # Show top 3
            print(f"\n  קונפליקט #{i}:")
            print(f"  ├── ספק: {conflict.supplier_name}")
            print(f"  │   תנאים: {conflict.supplier_terms.value} | "
                  f"תשלום ב: {conflict.supplier_payment_date} | "
                  f"סכום: {format_ils(conflict.supplier_amount)}")
            print(f"  ├── לקוח: {conflict.customer_name}")
            print(f"  │   תנאים: {conflict.customer_terms.value} | "
                  f"קבלה ב: {conflict.customer_payment_date} | "
                  f"סכום: {format_ils(conflict.customer_amount)}")
            print(f"  ├── פער: {conflict.cash_gap_days} ימים")
            print(f"  ├── יתרה צפויה בתאריך תשלום לספק: "
                  f"{format_ils(conflict.projected_balance_at_payment)}")
            print(f"  └── 💡 {conflict.recommendation}")
    else:
        print("\n  ✅ לא זוהו קונפליקטים בתנאי תשלום")

    # === WHATSAPP-STYLE ALERT ===
    print_header("דוגמה — הודעת WhatsApp")

    if alerts:
        alert = alerts[0]
        conflict = conflicts[0] if conflicts else None
        print()
        print("  ⚠️ התראת תזרים מזומנים — מרפאת ד״ר כהן")
        print(f"  יתרת הבנק צפויה לרדת מ-{format_ils(clinic.current_balance)} "
              f"ל-{format_ils(alert.projected_balance)} בעוד {alert.days_until} ימים.")
        print(f"  הסיבה: {alert.trigger_event.description} "
              f"({format_ils(alert.trigger_event.amount)}) "
              f"לטובת {alert.trigger_event.counterparty}.")
        if conflict:
            print(f"\n  💡 {conflict.recommendation}")
        print("\n  לחץ לפרטים מלאים →")
    else:
        print("\n  📊 סיכום שבועי — מרפאת ד״ר כהן")
        print("  אין התראות — תזרים המזומנים יציב ל-90 הימים הבאים. ✅")

    print(f"\n{'=' * 60}")
    print("  סוף הדגמה")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
