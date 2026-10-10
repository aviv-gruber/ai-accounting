#!/usr/bin/env python3
"""Demo: interactive Hebrew financial agent.

Run: python3 demo_agent.py
     python3 demo_agent.py --verbose    (show tool calls)
     python3 demo_agent.py --auto       (run preset questions, no interaction)

Requires: ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal

from synthetic_biz.dentist_clinic import generate_dentist_clinic
from agents.financial_agent import run_agent, interactive_session


DEMO_QUESTIONS = [
    "כמה הרווחתי השנה?",
    "מה מצב התזרים ל-90 יום קדימה?",
    "תראה לי גרף עמודות של ההוצאות לפי קטגוריה",
    "יש חשבוניות באיחור?",
    "כמה עולה לי כוח אדם בחודש?",
    "יש קונפליקטים בתנאי תשלום עם ספקים?",
]


def main() -> None:
    verbose = "--verbose" in sys.argv
    auto = "--auto" in sys.argv

    print("מייצר נתונים סינתטיים של מרפאת שיניים...")
    clinic = generate_dentist_clinic(
        start_date=date(2025, 10, 1),
        months=12,
        opening_balance=Decimal("25000"),
    )
    print(f"נתונים מוכנים: {clinic.business_name}\n")

    if auto:
        # Run preset demo questions
        for q in DEMO_QUESTIONS:
            print(f"שאלה: {q}")
            print("-" * 40)
            answer = run_agent(clinic, q, verbose=verbose)
            print(f"{answer}\n")
            print("=" * 50)
            print()
    else:
        # Interactive session
        interactive_session(clinic, verbose=verbose)


if __name__ == "__main__":
    main()
