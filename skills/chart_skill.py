"""Chart skill — generates interactive Plotly charts with Hebrew labels.

Supports:
- Bar charts (expenses by category, revenue by customer, etc.)
- Line charts (cashflow over time, trends)
- Pie charts (expense distribution)

All labels, titles, and tooltips are in Hebrew.
Charts are saved as interactive HTML files and can be opened in any browser.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

import plotly.graph_objects as go

from schema.standard_schema import BusinessSnapshot


# Hebrew month names
HEBREW_MONTHS = {
    1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל",
    5: "מאי", 6: "יוני", 7: "יולי", 8: "אוגוסט",
    9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר",
}

# RTL layout defaults for all charts
_RTL_LAYOUT = dict(
    font=dict(family="Arial, sans-serif", size=14),
    paper_bgcolor="#fafafa",
    plot_bgcolor="#fafafa",
    margin=dict(t=60, b=40, l=60, r=40),
)


def expenses_by_category(
    snapshot: BusinessSnapshot,
    output_path: str | Path = "data/expenses_by_category.html",
) -> Path:
    """Bar chart: total expenses grouped by supplier category.

    Maps each outgoing invoice to its vendor's category, then sums.
    """
    # Build vendor name → category lookup
    vendor_categories = {v.name: v.category for v in snapshot.vendors}

    # Sum expenses by category
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for inv in snapshot.invoices:
        if not inv.is_incoming:
            category = vendor_categories.get(inv.counterparty, "אחר")
            totals[category] += inv.total

    categories = list(totals.keys())
    values = [float(v) for v in totals.values()]

    fig = go.Figure(data=[
        go.Bar(
            x=categories,
            y=values,
            marker_color=["#2563eb", "#16a34a", "#ea580c", "#8b5cf6", "#dc2626"],
            text=[f"₪{v:,.0f}" for v in values],
            textposition="outside",
        )
    ])
    fig.update_layout(
        title="הוצאות לפי קטגוריה",
        xaxis_title="קטגוריה",
        yaxis_title="סכום (₪)",
        yaxis_tickformat=",",
        yaxis_tickprefix="₪",
        showlegend=False,
        **_RTL_LAYOUT,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output))
    return output


def monthly_revenue_vs_expenses(
    snapshot: BusinessSnapshot,
    output_path: str | Path = "data/revenue_vs_expenses.html",
) -> Path:
    """Grouped bar chart: monthly revenue vs expenses."""
    revenue_by_month: dict[str, Decimal] = defaultdict(Decimal)
    expense_by_month: dict[str, Decimal] = defaultdict(Decimal)

    for inv in snapshot.invoices:
        month_key = f"{HEBREW_MONTHS[inv.date.month]} {inv.date.year}"
        if inv.is_incoming:
            revenue_by_month[month_key] += inv.total
        else:
            expense_by_month[month_key] += inv.total

    # Ensure both dicts have the same keys in order
    all_months = list(dict.fromkeys(
        list(revenue_by_month.keys()) + list(expense_by_month.keys())
    ))

    fig = go.Figure(data=[
        go.Bar(
            name="הכנסות",
            x=all_months,
            y=[float(revenue_by_month.get(m, Decimal(0))) for m in all_months],
            marker_color="#16a34a",
            text=[f"₪{float(revenue_by_month.get(m, 0)):,.0f}" for m in all_months],
            textposition="outside",
        ),
        go.Bar(
            name="הוצאות",
            x=all_months,
            y=[float(expense_by_month.get(m, Decimal(0))) for m in all_months],
            marker_color="#dc2626",
            text=[f"₪{float(expense_by_month.get(m, 0)):,.0f}" for m in all_months],
            textposition="outside",
        ),
    ])
    fig.update_layout(
        title=f"הכנסות מול הוצאות — {snapshot.business_name}",
        xaxis_title="חודש",
        yaxis_title="סכום (₪)",
        yaxis_tickformat=",",
        yaxis_tickprefix="₪",
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        **_RTL_LAYOUT,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output))
    return output


def cashflow_timeline(
    snapshot: BusinessSnapshot,
    output_path: str | Path = "data/cashflow_timeline.html",
) -> Path:
    """Line chart: bank balance over time."""
    dates = [tx.date for tx in snapshot.bank_transactions]
    balances = [float(tx.balance_after) for tx in snapshot.bank_transactions]

    fig = go.Figure(data=[
        go.Scatter(
            x=dates,
            y=balances,
            mode="lines+markers",
            line=dict(color="#2563eb", width=2),
            marker=dict(size=4),
            hovertemplate="תאריך: %{x}<br>יתרה: ₪%{y:,.0f}<extra></extra>",
        )
    ])
    fig.update_layout(
        title=f"תזרים מזומנים — {snapshot.business_name}",
        xaxis_title="תאריך",
        yaxis_title="יתרת בנק (₪)",
        yaxis_tickformat=",",
        yaxis_tickprefix="₪",
        showlegend=False,
        **_RTL_LAYOUT,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output))
    return output


def expense_distribution_pie(
    snapshot: BusinessSnapshot,
    output_path: str | Path = "data/expense_pie.html",
) -> Path:
    """Pie chart: expense distribution by category."""
    vendor_categories = {v.name: v.category for v in snapshot.vendors}

    totals: dict[str, Decimal] = defaultdict(Decimal)
    for inv in snapshot.invoices:
        if not inv.is_incoming:
            category = vendor_categories.get(inv.counterparty, "אחר")
            totals[category] += inv.total

    fig = go.Figure(data=[
        go.Pie(
            labels=list(totals.keys()),
            values=[float(v) for v in totals.values()],
            textinfo="label+percent",
            texttemplate="%{label}<br>₪%{value:,.0f}<br>(%{percent})",
            marker_colors=["#2563eb", "#16a34a", "#ea580c", "#8b5cf6", "#dc2626"],
            hole=0.3,
        )
    ])
    fig.update_layout(
        title=f"פיזור הוצאות — {snapshot.business_name}",
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
        **_RTL_LAYOUT,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output))
    return output


def revenue_by_customer(
    snapshot: BusinessSnapshot,
    output_path: str | Path = "data/revenue_by_customer.html",
) -> Path:
    """Horizontal bar chart: revenue breakdown by customer/kupat cholim."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for inv in snapshot.invoices:
        if inv.is_incoming:
            totals[inv.counterparty] += inv.total

    # Sort by total descending
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    names = [item[0] for item in sorted_items]
    values = [float(item[1]) for item in sorted_items]

    fig = go.Figure(data=[
        go.Bar(
            x=values,
            y=names,
            orientation="h",
            marker_color=["#2563eb", "#16a34a", "#ea580c", "#8b5cf6", "#dc2626"],
            text=[f"₪{v:,.0f}" for v in values],
            textposition="outside",
        )
    ])
    fig.update_layout(
        title=f"הכנסות לפי לקוח — {snapshot.business_name}",
        xaxis_title="סכום (₪)",
        xaxis_tickformat=",",
        xaxis_tickprefix="₪",
        yaxis_autorange="reversed",
        showlegend=False,
        height=max(400, len(names) * 60),
        **_RTL_LAYOUT,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(output))
    return output
