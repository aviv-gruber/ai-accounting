"""Financial Agent — Hebrew NLU interface to the accounting data.

Uses Claude's tool-use to answer business owner questions in Hebrew,
backed by deterministic financial calculations.

The LLM's role:
  1. Understand the user's Hebrew question
  2. Choose which tool(s) to call
  3. Generate a Hebrew narrative from the tool results

The LLM does NOT:
  - Perform financial calculations (tools do that)
  - Invent data (all data comes from the snapshot)
  - Make up numbers
"""

from __future__ import annotations

import json
import os
from datetime import date
from decimal import Decimal
from pathlib import Path

import anthropic

from core.cashflow_engine import project_cashflow, detect_payment_term_conflicts
from schema.standard_schema import BusinessSnapshot, InvoiceStatus
from skills.chart_skill import (
    expenses_by_category,
    monthly_revenue_vs_expenses,
    cashflow_timeline,
    expense_distribution_pie,
    revenue_by_customer,
)


# --- Tool definitions (what the LLM can call) ---

TOOLS = [
    {
        "name": "get_business_overview",
        "description": "סקירת העסק: שם, סוג, מספר עובדים, ספקים, לקוחות, יתרת בנק נוכחית",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_cashflow_forecast",
        "description": "תחזית תזרים מזומנים ל-30/60/90 יום קדימה, כולל התראות",
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon_days": {
                    "type": "integer",
                    "description": "מספר ימים קדימה (ברירת מחדל: 90)",
                    "default": 90,
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_payment_term_conflicts",
        "description": "זיהוי קונפליקטים בתנאי תשלום בין ספקים ללקוחות",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_revenue_summary",
        "description": "סיכום הכנסות לפי לקוח או לפי חודש",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["customer", "month"],
                    "description": "קיבוץ לפי לקוח או חודש",
                }
            },
            "required": ["group_by"],
        },
    },
    {
        "name": "get_expense_summary",
        "description": "סיכום הוצאות לפי קטגוריה או לפי ספק",
        "input_schema": {
            "type": "object",
            "properties": {
                "group_by": {
                    "type": "string",
                    "enum": ["category", "vendor", "month"],
                    "description": "קיבוץ לפי קטגוריה, ספק, או חודש",
                }
            },
            "required": ["group_by"],
        },
    },
    {
        "name": "get_overdue_invoices",
        "description": "רשימת חשבוניות באיחור (שטרם שולמו לאחר תאריך הפירעון)",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_payroll_summary",
        "description": "סיכום שכר: עלות לכל עובד ועלות כוללת חודשית",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_vat_summary",
        "description": "סיכום מע״מ: דו״חות דו-חודשיים, מע״מ עסקאות, תשומות, ותשלום",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "generate_chart",
        "description": "יצירת גרף אינטראקטיבי (נפתח בדפדפן)",
        "input_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": [
                        "expenses_by_category",
                        "revenue_vs_expenses",
                        "cashflow_timeline",
                        "expense_pie",
                        "revenue_by_customer",
                    ],
                    "description": "סוג הגרף",
                }
            },
            "required": ["chart_type"],
        },
    },
]


# --- Tool implementations ---

def _json_serialize(obj):
    """Handle Decimal and date serialization."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Cannot serialize {type(obj)}")


def _execute_tool(name: str, args: dict, snapshot: BusinessSnapshot) -> str:
    """Execute a tool and return the result as a JSON string."""

    if name == "get_business_overview":
        result = {
            "שם_העסק": snapshot.business_name,
            "סוג": snapshot.business_type,
            "עובדים": len(snapshot.employees),
            "ספקים": len(snapshot.vendors),
            "לקוחות": len(snapshot.customers),
            "יתרת_בנק": float(snapshot.current_balance),
            "חשבוניות_פתוחות": len([
                i for i in snapshot.invoices
                if i.status in (InvoiceStatus.SENT, InvoiceStatus.OVERDUE)
            ]),
        }

    elif name == "get_cashflow_forecast":
        horizon = args.get("horizon_days", 90)
        events, alerts = project_cashflow(snapshot, horizon_days=horizon)
        result = {
            "אירועים_צפויים": len(events),
            "התראות": [
                {
                    "תאריך": a.alert_date.isoformat(),
                    "יתרה_צפויה": float(a.projected_balance),
                    "ימים_עד": a.days_until,
                    "חומרה": a.severity,
                    "סיבה": f"{a.trigger_event.description} — {a.trigger_event.counterparty}",
                    "סכום": float(a.trigger_event.amount),
                }
                for a in alerts
            ],
        }

    elif name == "get_payment_term_conflicts":
        conflicts = detect_payment_term_conflicts(snapshot)
        result = {
            "קונפליקטים": [
                {
                    "ספק": c.supplier_name,
                    "תנאי_ספק": c.supplier_terms.value,
                    "תאריך_תשלום_לספק": c.supplier_payment_date.isoformat(),
                    "סכום_ספק": float(c.supplier_amount),
                    "לקוח": c.customer_name,
                    "תנאי_לקוח": c.customer_terms.value,
                    "תאריך_קבלה_מלקוח": c.customer_payment_date.isoformat(),
                    "פער_ימים": c.cash_gap_days,
                    "המלצה": c.recommendation,
                }
                for c in conflicts
            ],
        }

    elif name == "get_revenue_summary":
        from collections import defaultdict
        totals: dict[str, float] = defaultdict(float)
        for inv in snapshot.invoices:
            if inv.is_incoming:
                if args["group_by"] == "customer":
                    key = inv.counterparty
                else:
                    key = f"{inv.date.year}-{inv.date.month:02d}"
                totals[key] += float(inv.total)
        result = {"הכנסות": dict(sorted(totals.items(), key=lambda x: -x[1]))}

    elif name == "get_expense_summary":
        from collections import defaultdict
        vendor_categories = {v.name: v.category for v in snapshot.vendors}
        totals: dict[str, float] = defaultdict(float)
        for inv in snapshot.invoices:
            if not inv.is_incoming:
                if args["group_by"] == "category":
                    key = vendor_categories.get(inv.counterparty, "אחר")
                elif args["group_by"] == "vendor":
                    key = inv.counterparty
                else:
                    key = f"{inv.date.year}-{inv.date.month:02d}"
                totals[key] += float(inv.total)
        result = {"הוצאות": dict(sorted(totals.items(), key=lambda x: -x[1]))}

    elif name == "get_overdue_invoices":
        overdue = [i for i in snapshot.invoices if i.status == InvoiceStatus.OVERDUE]
        result = {
            "חשבוניות_באיחור": [
                {
                    "מספר": i.invoice_number,
                    "לקוח_ספק": i.counterparty,
                    "סכום": float(i.total),
                    "תאריך_פירעון": i.due_date.isoformat(),
                    "סוג": "הכנסה" if i.is_incoming else "הוצאה",
                }
                for i in overdue
            ],
            "סה_כ": float(sum(i.total for i in overdue)),
        }

    elif name == "get_payroll_summary":
        result = {
            "עובדים": [
                {
                    "שם": e.name,
                    "תפקיד": e.role,
                    "ברוטו": float(e.gross_salary),
                    "נטו": float(e.net_salary),
                    "ביטוח_לאומי": float(e.bituach_leumi),
                    "פנסיה": float(e.pension),
                    "קרן_השתלמות": float(e.keren_hishtalmut),
                }
                for e in snapshot.employees
            ],
            "עלות_חודשית_כוללת": float(sum(
                e.gross_salary + e.bituach_leumi + e.pension + e.keren_hishtalmut
                for e in snapshot.employees
            )),
        }

    elif name == "get_vat_summary":
        result = {
            "דוחות": [
                {
                    "תקופה": f"{v.period_start.isoformat()} — {v.period_end.isoformat()}",
                    "עסקאות": float(v.total_sales),
                    "תשומות": float(v.total_purchases),
                    "מעמ_עסקאות": float(v.output_vat),
                    "מעמ_תשומות": float(v.input_vat),
                    "לתשלום": float(v.vat_payable),
                }
                for v in snapshot.vat_reports
            ],
        }

    elif name == "generate_chart":
        chart_type = args["chart_type"]
        chart_funcs = {
            "expenses_by_category": expenses_by_category,
            "revenue_vs_expenses": monthly_revenue_vs_expenses,
            "cashflow_timeline": cashflow_timeline,
            "expense_pie": expense_distribution_pie,
            "revenue_by_customer": revenue_by_customer,
        }
        func = chart_funcs[chart_type]
        path = func(snapshot)
        # Open in browser
        os.system(f"open {path}")
        result = {"גרף_נוצר": str(path), "הודעה": "הגרף נפתח בדפדפן"}

    else:
        result = {"שגיאה": f"כלי לא מוכר: {name}"}

    return json.dumps(result, ensure_ascii=False, default=_json_serialize)


# --- Agent loop ---

SYSTEM_PROMPT = """אתה עוזר פיננסי חכם של עסק קטן בישראל.

כללים:
1. תמיד ענה בעברית
2. אל תמציא מספרים — השתמש אך ורק בכלים כדי לקבל נתונים
3. כשהמשתמש שואל שאלה כספית, קרא לכלי המתאים ואז הצג את התוצאה בצורה ברורה ומובנת
4. כשהמשתמש מבקש גרף, השתמש בכלי generate_chart
5. תן תשובות קצרות וענייניות — בעל העסק עסוק
6. כשיש התראה או בעיה, הדגש אותה בבירור והצע פתרון

שם העסק: {business_name}
סוג העסק: {business_type}
"""


def run_agent(
    snapshot: BusinessSnapshot,
    user_message: str,
    model: str = "claude-sonnet-4-20250514",
    verbose: bool = False,
) -> str:
    """Run a single agent turn: user asks a question, gets a Hebrew answer.

    Args:
        snapshot: The business financial data.
        user_message: The user's question in Hebrew.
        model: Claude model to use.
        verbose: Print tool calls for debugging.

    Returns:
        The agent's Hebrew response.
    """
    client = anthropic.Anthropic()

    system = SYSTEM_PROMPT.format(
        business_name=snapshot.business_name,
        business_type=snapshot.business_type,
    )

    messages = [{"role": "user", "content": user_message}]

    # Agent loop — handle tool calls
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        # Check if there are tool calls
        tool_calls = [b for b in response.content if b.type == "tool_use"]

        if not tool_calls:
            # No tool calls — extract text response
            text_blocks = [b.text for b in response.content if b.type == "text"]
            return "\n".join(text_blocks)

        # Execute tool calls and build tool results
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tc in tool_calls:
            if verbose:
                print(f"  [tool] {tc.name}({json.dumps(tc.input, ensure_ascii=False)})")
            result = _execute_tool(tc.name, tc.input, snapshot)
            if verbose:
                print(f"  [result] {result[:200]}...")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})


def interactive_session(snapshot: BusinessSnapshot, verbose: bool = False) -> None:
    """Run an interactive chat session with the financial agent."""
    print(f"\n{'=' * 50}")
    print(f"  {snapshot.business_name} — עוזר פיננסי")
    print(f"  הקלד שאלה בעברית (או 'יציאה' לסיום)")
    print(f"{'=' * 50}\n")

    while True:
        try:
            question = input("אתה: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nלהתראות!")
            break

        if not question:
            continue
        if question in ("יציאה", "exit", "quit"):
            print("להתראות!")
            break

        try:
            answer = run_agent(snapshot, question, verbose=verbose)
            print(f"\nעוזר: {answer}\n")
        except Exception as e:
            print(f"\nשגיאה: {e}\n")
