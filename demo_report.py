#!/usr/bin/env python3
"""Generate a multi-page interactive HTML financial report.

Run: python3 demo_report.py
Opens the report in the default browser.

Features:
- Multi-page navigation (Overview, Treatments, Materials, Patients, AI Insights)
- Time period selector with presets and custom date range
- JS-driven dynamic recomputation when period changes
- Evidence panels behind each AI insight
- Treatment selector with BOM, costs, and expiry dates
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from synthetic_biz.dentist_clinic import generate_dentist_clinic
from core.cashflow_engine import project_cashflow, detect_payment_term_conflicts
from connectors.discount_bank import load_discount_transactions

# Path to real bank data (scraped from Discount Bank via israeli-bank-scrapers)
_REAL_BANK_DATA = Path(__file__).parent.parent / "agenticai" / "financial_documentation" / "data" / "scraped_raw.json"


class _DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return float(o)
        return super().default(o)


def _build_blended_bank_transactions(
    synthetic_txns: list,
) -> list[dict]:
    """Blend real Discount Bank transactions into the synthetic bank data.

    Real transactions are tagged with source='discount_bank' so the UI can
    distinguish them.  They are interleaved chronologically with the
    synthetic transactions and the running balance is recomputed.
    """
    # Serialize synthetic
    all_txns = [
        {
            "date": tx.date.isoformat(),
            "amount": float(tx.amount),
            "description": tx.description,
            "category": tx.category,
            "transactionType": tx.transaction_type.value,
            "counterparty": tx.counterparty or "",
            "source": "synthetic",
        }
        for tx in synthetic_txns
    ]

    # Load real transactions (last 3 months)
    if _REAL_BANK_DATA.exists():
        try:
            real_txns = load_discount_transactions(
                _REAL_BANK_DATA, account_number="0174830426", last_n_months=3,
            )
            for tx in real_txns:
                all_txns.append({
                    "date": tx.date.isoformat(),
                    "amount": float(tx.amount),
                    "description": tx.description,
                    "category": tx.category,
                    "transactionType": tx.transaction_type.value,
                    "counterparty": tx.counterparty or "",
                    "source": "discount_bank",
                })
            print(f"  Blended {len(real_txns)} real Discount Bank transactions")
        except Exception as e:
            print(f"  Warning: could not load real bank data: {e}")

    # Sort chronologically and recompute running balance
    all_txns.sort(key=lambda t: t["date"])
    balance = 25000.0  # opening balance
    for t in all_txns:
        balance += t["amount"]
        t["balanceAfter"] = round(balance, 2)

    return all_txns


def generate_report() -> str:
    clinic = generate_dentist_clinic(
        start_date=date(2025, 10, 1),
        months=12,
        opening_balance=Decimal("25000"),
    )

    cashflow_events, alerts = project_cashflow(
        clinic, horizon_days=90, alert_threshold=Decimal("10000")
    )
    conflicts = detect_payment_term_conflicts(clinic)

    # --- Build treatment BOM data ---
    mat_catalog = {m.id: m for m in clinic.materials_catalog}
    last_used: dict[str, date] = {}
    for ev in clinic.service_events:
        for mu in ev.materials_used:
            if mu.material_id not in last_used or ev.date > last_used[mu.material_id]:
                last_used[mu.material_id] = ev.date

    category_icons = {
        "אבחון": "🔍", "טיפולים משמרים": "🦷", "אנדודונטיה": "🔬",
        "היגיינה": "✨", "כירורגיה": "🔪", "פרותזה": "👑", "אסתטיקה": "💎",
    }

    treatment_bom = {}
    for svc in clinic.service_types:
        mats = []
        for mu in svc.materials:
            mat = mat_catalog.get(mu.material_id)
            shelf = mat.shelf_life_months if mat else None
            pdate = last_used.get(mu.material_id)
            exp = None
            if pdate and shelf:
                exp = (pdate + timedelta(days=shelf * 30)).isoformat()
            mats.append({
                "name": mu.material_name, "quantity": float(mu.quantity),
                "unitCost": float(mu.unit_cost), "totalCost": float(mu.total_cost),
                "unit": mat.unit if mat else "יחידה",
                "shelfLifeMonths": shelf, "expiryDate": exp,
            })
        treatment_bom[svc.name] = {
            "category": svc.category,
            "icon": category_icons.get(svc.category, "🦷"),
            "standardPrice": float(svc.standard_price),
            "durationMinutes": svc.duration_minutes,
            "requiresLab": svc.requires_lab,
            "labCost": float(svc.lab_cost),
            "materials": mats,
            "totalMaterialsCost": sum(m["totalCost"] for m in mats),
        }

    # --- Serialize data for JS ---
    data_obj = {
        "serviceEvents": [
            {
                "date": ev.date.isoformat(),
                "serviceName": ev.service_name,
                "serviceTypeId": ev.service_type_id,
                "patientName": ev.patient_name,
                "revenue": float(ev.revenue),
                "durationMinutes": ev.duration_minutes,
                "materialsUsed": [
                    {"materialId": m.material_id, "materialName": m.material_name,
                     "quantity": float(m.quantity), "unitCost": float(m.unit_cost),
                     "totalCost": float(m.total_cost)}
                    for m in ev.materials_used
                ],
                "labCost": float(ev.lab_cost),
                "directLaborCost": float(ev.direct_labor_cost),
                "overheadAllocated": float(ev.overhead_allocated),
                "totalCost": float(ev.total_cost),
                "grossProfit": float(ev.gross_profit),
                "grossMargin": float(ev.gross_margin),
            }
            for ev in clinic.service_events
        ],
        "cashflowEvents": [
            {"date": ce.date.isoformat(), "amount": float(ce.amount),
             "description": ce.description, "counterparty": ce.counterparty}
            for ce in cashflow_events
        ],
        "conflicts": [
            {"supplierName": c.supplier_name, "supplierTerms": c.supplier_terms.value,
             "customerName": c.customer_name, "customerTerms": c.customer_terms.value,
             "cashGapDays": c.cash_gap_days, "recommendation": c.recommendation}
            for c in conflicts
        ],
        "bankTransactions": _build_blended_bank_transactions(clinic.bank_transactions),
        "invoices": [
            {
                "id": inv.id,
                "invoiceNumber": inv.invoice_number,
                "date": inv.date.isoformat(),
                "dueDate": inv.due_date.isoformat(),
                "amount": float(inv.amount),
                "vatAmount": float(inv.vat_amount),
                "total": float(inv.total),
                "status": inv.status.value,
                "counterparty": inv.counterparty,
                "description": inv.description,
                "isIncoming": inv.is_incoming,
            }
            for inv in clinic.invoices
        ],
        "dateRange": {
            "min": min(ev.date for ev in clinic.service_events).isoformat(),
            "max": max(ev.date for ev in clinic.service_events).isoformat(),
        },
    }

    static_obj = {
        "treatmentBOM": treatment_bom,
        "employees": [
            {"name": e.name, "role": e.role,
             "totalCost": float(e.gross_salary + e.bituach_leumi + e.pension + e.keren_hishtalmut)}
            for e in clinic.employees
        ],
        "overheadPools": [
            {"name": p.name, "monthlyCost": float(p.monthly_cost)}
            for p in clinic.overhead_pools
        ],
        "materialsCatalog": {
            m.id: {"name": m.name, "unitCost": float(m.unit_cost),
                    "unit": m.unit, "shelfLifeMonths": m.shelf_life_months}
            for m in clinic.materials_catalog
        },
        "currentBalance": float(clinic.current_balance),
        "businessName": clinic.business_name,
        "selectorCards": [
            {"name": s.name, "category": s.category,
             "icon": category_icons.get(s.category, "🦷"),
             "duration": s.duration_minutes,
             "price": float(s.standard_price)}
            for s in clinic.service_types
        ],
    }

    data_json = json.dumps(data_obj, ensure_ascii=False, cls=_DecimalEncoder)
    static_json = json.dumps(static_obj, ensure_ascii=False, cls=_DecimalEncoder)

    return _build_html(data_json, static_json, clinic.business_name)


def _build_html(data_json: str, static_json: str, business_name: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="SmartBooks">
<meta name="theme-color" content="#0f172a">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="apple-touch-icon" href="icon-192.png">
<link rel="manifest" href="manifest.json">
<title>דו״ח פיננסי — {business_name}</title>
<style>
{_CSS}
</style>
</head>
<body>

<div class="header">
    <div class="header-brand">SmartBooks</div>
    <h1>{business_name}</h1>
    <div class="subtitle">דו״ח תובנות פיננסיות</div>
</div>

<div class="page-layout">

    <nav class="nav-sidebar" id="sideNav">
        <ul>
            <li><a href="#" class="active" data-page="page-overview" onclick="showPage('page-overview');return false;"><span class="nav-icon">🏠</span><span class="nav-label">ראשי</span></a></li>
            <li><a href="#" data-page="page-treatments" onclick="showPage('page-treatments');return false;"><span class="nav-icon">💰</span><span class="nav-label">רווחיות</span></a></li>
            <li><a href="#" data-page="page-insights" onclick="showPage('page-insights');return false;"><span class="nav-icon">🤖</span><span class="nav-label">תובנות</span></a></li>
            <li><a href="#" data-page="page-bank" onclick="showPage('page-bank');return false;"><span class="nav-icon">🏦</span><span class="nav-label">בנק</span></a></li>
            <li class="mobile-only"><a href="#" onclick="toggleMore(event);return false;"><span class="nav-icon">☰</span><span class="nav-label">עוד</span></a>
                <div class="more-menu" id="moreMenu">
                    <a href="#" data-page="page-materials" onclick="showPage('page-materials');closeMore();return false;"><span class="nav-icon">🔧</span> חומרים ומלאי</a>
                    <a href="#" data-page="page-patients" onclick="showPage('page-patients');closeMore();return false;"><span class="nav-icon">👥</span> מטופלים</a>
                </div>
            </li>
            <!-- Desktop-only items (hidden on mobile, visible in sidebar) -->
            <li class="desktop-only"><a href="#" data-page="page-materials" onclick="showPage('page-materials');return false;"><span class="nav-icon">🔧</span><span class="nav-label">חומרים ומלאי</span></a></li>
            <li class="desktop-only"><a href="#" data-page="page-patients" onclick="showPage('page-patients');return false;"><span class="nav-icon">👥</span><span class="nav-label">מטופלים</span></a></li>
        </ul>
        <div class="more-backdrop" id="moreBackdrop" onclick="closeMore()"></div>
    </nav>

    <div class="main-content">

        <!-- Period selector -->
        <div class="period-bar">
            <span class="period-label">תקופה:</span>
            <div class="period-buttons">
                <button class="pbtn active" onclick="setPeriod('all',this)">הכל</button>
                <button class="pbtn" onclick="setPeriod('12m',this)">12 חודשים</button>
                <button class="pbtn" onclick="setPeriod('6m',this)">6 חודשים</button>
                <button class="pbtn" onclick="setPeriod('3m',this)">רבעון אחרון</button>
                <button class="pbtn" onclick="setPeriod('1m',this)">חודש אחרון</button>
            </div>
            <div class="period-custom">
                <label>מ-</label><input type="date" id="dateFrom" onchange="setCustomPeriod()">
                <label>עד</label><input type="date" id="dateTo" onchange="setCustomPeriod()">
            </div>
            <div class="period-info" id="periodInfo"></div>
        </div>

        <!-- PAGE: Overview -->
        <div class="page active" id="page-overview">
            <div class="hero-card" id="heroCard">
                <div class="hero-label">יתרת חשבון בנק</div>
                <div class="hero-value" id="heroBalance">—</div>
                <div class="hero-sub" id="heroSub"></div>
            </div>
            <div class="card"><div class="kpi-grid" id="kpiGrid"></div></div>
            <div class="card">
                <h2><span class="emoji">💸</span> לאן הולך הכסף?</h2>
                <p class="hint">לחצי על קטגוריה לפירוט</p>
                <div class="cost-grid" id="costGrid"></div>
                <div id="costDetailPanel"></div>
            </div>
            <div class="card" id="overviewInsights"></div>
        </div>

        <!-- PAGE: Treatment Profitability -->
        <div class="page" id="page-treatments" style="display:none;">
            <div class="card">
                <h2><span class="emoji">📊</span> כמה את מרוויחה מכל טיפול?</h2>
                <p class="hint">לחצי על שורה לפירוט עלויות</p>
                <div class="table-scroll" id="treatmentTableContainer"></div>
            </div>
        </div>

        <!-- PAGE: Materials -->
        <div class="page" id="page-materials" style="display:none;">
            <div class="card">
                <h2><span class="emoji">🔧</span> בחירת סוג טיפול — חומרים, עלויות ותוקף</h2>
                <p class="hint">בחרי טיפול לצפייה בפירוט החומרים הנדרשים</p>
                <div class="selector-grid" id="selectorGrid"></div>
                <div id="bomDetail"></div>
            </div>
        </div>

        <!-- PAGE: Patients -->
        <div class="page" id="page-patients" style="display:none;">
            <div class="card">
                <h2><span class="emoji">👥</span> המטופלים הרווחיים ביותר</h2>
                <p class="hint">לחצי על שורה לפירוט הטיפולים</p>
                <div class="table-scroll" id="patientTableContainer"></div>
            </div>
        </div>

        <!-- PAGE: AI Insights -->
        <div class="page" id="page-insights" style="display:none;">
            <div class="card agent-section">
                <div class="agent-header-bar">
                    <div class="agent-avatar">🤖</div>
                    <div>
                        <div class="agent-title">סוכן AI — תובנות אוטומטיות</div>
                        <div class="agent-subtitle">ניתוח אוטומטי מבוסס על הנתונים הפיננסיים שלך</div>
                    </div>
                </div>
                <div id="insightCards"></div>
            </div>
        </div>

        <!-- PAGE: Bank Account -->
        <div class="page" id="page-bank" style="display:none;">
            <div class="card">
                <h2><span class="emoji">🏦</span> יתרת חשבון בנק</h2>
                <div class="kpi-grid" id="bankKPIs"></div>
            </div>
            <div class="card">
                <h2><span class="emoji">📋</span> תנועות אחרונות</h2>
                <div class="table-scroll" id="bankTransactionsTable"></div>
            </div>
            <div class="card">
                <h2><span class="emoji">🔗</span> סגירה — התאמה בנק ↔ חשבוניות</h2>
                <p class="hint">התאמה אוטומטית בין תנועות הבנק לחשבוניות פתוחות</p>
                <div id="reconciliationView"></div>
            </div>
        </div>

        <div class="footer">
            <div class="brand">SmartBooks</div>
            <div style="margin-top:6px;">נוצר אוטומטית · ללא התערבות ידנית</div>
        </div>

    </div>
</div>

<script>
var DATA = {data_json};
var STATIC = {static_json};

{_JS}
</script>
</body>
</html>"""


# ─── CSS ────────────────────────────────────────────────────────────────
_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }
body {
    font-family: 'Heebo', -apple-system, BlinkMacSystemFont, sans-serif;
    background:#faf9f7; color:#1e293b; line-height:1.6; direction:rtl;
    -webkit-font-smoothing:antialiased;
}

/* === LAYOUT === */
.header {
    background:linear-gradient(135deg,#0f172a 0%,#164e63 60%,#0d9488 100%);
    color:white; padding:28px 32px; text-align:center;
    max-width:960px; margin:16px auto 0; border-radius:20px;
    position:relative; overflow:hidden;
}
.header::after {
    content:''; position:absolute; top:-50%; right:-30%; width:60%; height:200%;
    background:radial-gradient(circle,rgba(255,255,255,.06) 0%,transparent 70%);
    pointer-events:none;
}
.header-brand { font-size:11px; font-weight:600; letter-spacing:.1em; text-transform:uppercase; opacity:.5; position:relative; margin-bottom:4px; }
.header h1 { font-size:22px; font-weight:700; margin-bottom:2px; position:relative; }
.header .subtitle { opacity:.7; font-size:13px; font-weight:300; position:relative; }
.page-layout {
    display:flex; gap:20px; max-width:960px; margin:0 auto; padding:16px;
}
.main-content { flex:1; min-width:0; }

/* === NAVIGATION — Desktop sidebar === */
.nav-sidebar {
    width:180px; flex-shrink:0; position:sticky; top:16px;
    height:fit-content; max-height:calc(100vh - 32px); overflow-y:auto;
    background:white; border-radius:16px; padding:12px 0;
    box-shadow:0 1px 4px rgba(0,0,0,.06);
}
.nav-sidebar ul { list-style:none; padding:0; }
.nav-sidebar li { margin-bottom:2px; }
.nav-sidebar a {
    display:flex; align-items:center; gap:10px;
    padding:12px 18px; color:#64748b; text-decoration:none;
    font-size:14px; font-weight:500; transition:all .2s;
    border-right:3px solid transparent; min-height:44px;
}
.nav-sidebar a:hover { background:#f0fdfa; color:#0f172a; }
.nav-sidebar a.active { background:#f0fdfa; color:#0d9488; font-weight:600; border-right-color:#0d9488; }
.nav-sidebar .nav-icon { font-size:18px; width:24px; text-align:center; flex-shrink:0; }
.nav-sidebar .nav-label { white-space:nowrap; }
.nav-sidebar li.mobile-only { display:none; }
/* "More" sub-items hidden on desktop sidebar — shown inline */
.more-menu { display:none; position:absolute; bottom:100%; left:0; right:0;
    background:white; border-radius:16px 16px 0 0; box-shadow:0 -4px 20px rgba(0,0,0,.12);
    padding:8px 0; z-index:101; }
.more-menu.visible { display:block; }
.more-menu a { display:flex; align-items:center; gap:10px; padding:14px 20px;
    color:#64748b; text-decoration:none; font-size:14px; font-weight:500;
    min-height:48px; transition:background .15s; }
.more-menu a:hover { background:#f0fdfa; color:#0d9488; }
.more-backdrop { display:none; position:fixed; inset:0; z-index:99; }
.more-backdrop.visible { display:block; }

/* === NAVIGATION — Mobile bottom bar (5 tabs) === */
@media(max-width:960px) {
    .page-layout { flex-direction:column; padding:12px 12px calc(72px + env(safe-area-inset-bottom,0px)); }
    .nav-sidebar {
        display:flex; position:fixed; bottom:0; left:0; right:0; z-index:100;
        width:100%; border-radius:0; padding:0; flex-shrink:unset;
        height:auto; max-height:none; top:auto;
        box-shadow:0 -1px 12px rgba(0,0,0,.08);
        border-top:1px solid #e2e8f0;
        background:rgba(255,255,255,.96); backdrop-filter:blur(12px); -webkit-backdrop-filter:blur(12px);
        padding-bottom:env(safe-area-inset-bottom,0px);
    }
    .nav-sidebar ul { display:flex; width:100%; padding:0; }
    .nav-sidebar li { flex:1; margin:0; }
    .nav-sidebar li.desktop-only { display:none; }
    .nav-sidebar li.mobile-only { display:block; }
    .nav-sidebar a {
        padding:8px 4px 6px; text-align:center; font-size:10px; font-weight:500;
        border-right:none; border-top:2px solid transparent;
        display:flex; flex-direction:column; align-items:center; gap:1px;
        min-height:56px; justify-content:center;
    }
    .nav-sidebar .nav-icon { font-size:22px; width:auto; }
    .nav-sidebar .nav-label { font-size:10px; }
    .nav-sidebar a.active { border-right:none; border-top-color:#0d9488; color:#0d9488; background:transparent; }
    .header { margin:0 0 4px; padding:20px 16px; border-radius:16px; }
    .header h1 { font-size:20px; }
    .header .subtitle { font-size:12px; }
}

/* === PAGES === */
.page { display:none; }
.page.active { display:block; }

/* === HERO CARD (Cash balance) === */
.hero-card {
    background:linear-gradient(135deg,#0f172a 0%,#164e63 100%);
    border-radius:20px; padding:28px; margin-bottom:16px; color:white;
    position:relative; overflow:hidden;
}
.hero-card::after {
    content:''; position:absolute; top:-40%; left:-20%; width:50%; height:180%;
    background:radial-gradient(circle,rgba(13,148,136,.3) 0%,transparent 70%);
    pointer-events:none;
}
.hero-label { font-size:13px; font-weight:400; opacity:.7; position:relative; }
.hero-value { font-size:42px; font-weight:800; direction:ltr; text-align:right;
    position:relative; margin:4px 0 8px; letter-spacing:-1px; }
.hero-sub { font-size:12px; opacity:.6; position:relative; }
@media(max-width:960px) {
    .hero-value { font-size:36px; }
    .hero-card { padding:22px 20px; }
}

/* === PERIOD BAR === */
.period-bar {
    background:white; border-radius:14px; padding:12px 16px; margin-bottom:16px;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
    display:flex; align-items:center; gap:10px; flex-wrap:wrap;
}
.period-label { font-weight:600; color:#0f172a; font-size:13px; }
.period-buttons { display:flex; gap:4px; overflow-x:auto; -webkit-overflow-scrolling:touch; }
.period-buttons::-webkit-scrollbar { display:none; }
.pbtn {
    padding:8px 16px; border:1px solid #e2e8f0; border-radius:20px;
    background:white; cursor:pointer; font-size:13px; font-family:inherit;
    transition:all .15s; min-height:36px; font-weight:500; white-space:nowrap;
}
.pbtn:hover { border-color:#0d9488; background:#f0fdfa; }
.pbtn.active { background:#0d9488; color:white; border-color:#0d9488; }
.period-custom { display:flex; align-items:center; gap:6px; font-size:13px; }
.period-custom input[type=date] {
    padding:8px 10px; border:1px solid #e2e8f0; border-radius:10px;
    font-family:inherit; font-size:16px; min-height:36px;
}
.period-info { font-size:11px; color:#94a3b8; width:100%; }
@media(max-width:960px) {
    .period-bar { padding:10px 12px; gap:6px; border-radius:12px; }
    .period-buttons { flex-wrap:nowrap; }
    .pbtn { padding:7px 14px; font-size:12px; flex-shrink:0; }
    .period-custom { display:none; }
    .period-label { display:none; }
}

/* === CARDS === */
.card {
    background:white; border-radius:16px; padding:24px; margin-bottom:16px;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
}
.card h2 {
    font-size:18px; color:#0f172a; margin-bottom:16px; font-weight:700;
    display:flex; align-items:center; gap:8px;
}
.card h2 .emoji { font-size:20px; }
.hint { font-size:12px; color:#94a3b8; margin:-8px 0 14px; font-weight:400; }
@media(max-width:960px) { .card { padding:18px 16px; border-radius:14px; } }

/* === KPI GRID === */
.kpi-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:10px; }
.kpi-tile {
    background:white; border-radius:16px; padding:16px; text-align:right;
    border:1px solid #f1f0ee; position:relative; overflow:hidden;
}
.kpi-tile::before {
    content:''; position:absolute; top:0; right:0; width:4px; height:100%;
    background:var(--kpi-accent,#0d9488); border-radius:0 4px 4px 0;
}
.kpi-icon { font-size:20px; margin-bottom:6px; }
.kpi-label { font-size:11px; color:#94a3b8; font-weight:500; letter-spacing:.02em; }
.kpi-value { font-size:22px; font-weight:800; color:#0f172a; margin-top:2px; direction:ltr; text-align:right; }
@media(min-width:700px) { .kpi-grid { grid-template-columns:repeat(4,1fr); } }

/* === TABLE SCROLL WRAPPER === */
.table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:0 -4px; padding:0 4px; }
table { width:100%; border-collapse:collapse; min-width:500px; }
th {
    background:#faf9f7; color:#64748b; font-weight:600;
    padding:12px 14px; text-align:right; font-size:12px;
    border-bottom:2px solid #f1f0ee; white-space:nowrap;
}
td { padding:12px 14px; border-bottom:1px solid #f5f4f2; font-size:13px; }
td.num { text-align:left; font-variant-numeric:tabular-nums; direction:ltr; }
td.name { font-weight:500; color:#0f172a; }
td.bold { font-weight:700; }
tr:hover { background:#faf9f7; }

/* === EXPANDABLE ROWS === */
.expandable { cursor:pointer; }
.expandable:hover { background:#f0fdfa !important; }
.expand-arrow { margin-left:6px; font-size:11px; color:#94a3b8; transition:transform .2s; }
.detail-row td { padding:0 !important; border-bottom:2px solid #f1f0ee; }
.detail-content { padding:14px 16px; background:#faf9f7; border-radius:12px; margin:8px; }
.detail-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.detail-item {
    display:flex; justify-content:space-between; padding:10px 12px;
    background:white; border-radius:10px; font-size:13px;
}
.detail-label { color:#94a3b8; font-weight:400; }
.detail-value { font-weight:600; direction:ltr; color:#0f172a; }

/* === MARGIN BAR === */
.bar-cell { display:flex; align-items:center; gap:8px; direction:ltr; }
.bar-track { background:#f1f0ee; border-radius:8px; height:22px; flex:1; overflow:hidden; min-width:60px; }
.bar { height:100%; border-radius:8px; min-width:4px; transition:width .3s ease; }
.bar-cell span { font-size:13px; font-weight:700; white-space:nowrap; min-width:40px; }

/* === COST TILES === */
.cost-grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.cost-tile {
    background:#faf9f7; border-radius:14px; padding:18px; text-align:center;
    cursor:pointer; transition:all .2s; border:2px solid transparent;
}
.cost-tile:hover { border-color:#0d9488; background:#f0fdfa; }
.cost-tile.expanded { border-color:#0d9488; }
.cost-tile .pct { font-size:28px; font-weight:800; color:#0d9488; }
.cost-tile .amt { font-size:14px; color:#64748b; margin-top:2px; direction:ltr; }
.cost-tile .lbl { font-size:13px; color:#94a3b8; margin-top:6px; font-weight:500; }
.cost-detail-panel {
    display:none; margin-top:12px; background:#faf9f7;
    border-radius:14px; padding:16px;
}
.cost-detail-panel.visible { display:block; }
.cdi { display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid #f1f0ee; font-size:13px; }
.cdi:last-child { border-bottom:none; }

/* === TREATMENT SELECTOR === */
.selector-grid {
    display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr));
    gap:10px; margin-bottom:16px;
}
.selector-card {
    background:#faf9f7; border:2px solid #f1f0ee; border-radius:14px;
    padding:14px 10px; text-align:center; cursor:pointer; transition:all .2s;
    min-height:44px;
}
.selector-card:hover { border-color:#0d9488; background:#f0fdfa; }
.selector-card.selected { border-color:#0d9488; background:#f0fdfa; box-shadow:0 0 0 3px rgba(13,148,136,.12); }
.selector-icon { font-size:26px; margin-bottom:6px; }
.selector-name { font-weight:600; font-size:12px; color:#0f172a; }
.selector-meta { font-size:11px; color:#94a3b8; margin-top:3px; }
.bom-detail { background:#faf9f7; border-radius:14px; padding:20px; margin-top:12px; }
.bom-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:14px; flex-wrap:wrap; gap:8px; }
.bom-header h3 { font-size:16px; color:#0f172a; font-weight:700; border:none; margin:0; padding:0; }
.expiry-warning { color:#dc2626; font-weight:600; font-size:12px; }
.expiry-ok { color:#0d9488; font-size:12px; }
@media(max-width:960px) { .selector-grid { grid-template-columns:repeat(2,1fr); } }

/* === PATIENT DETAIL TABLE === */
.pd-table { width:100%; border-collapse:collapse; font-size:12px; min-width:400px; }
.pd-table th { background:white; color:#94a3b8; font-weight:600; padding:8px 10px; text-align:right; font-size:11px; border-bottom:1px solid #f1f0ee; }
.pd-table td { padding:8px 10px; border-bottom:1px solid #f5f4f2; }

/* === QUICK INSIGHTS (overview page) === */
.insight-row { display:flex; gap:12px; padding:14px 16px; background:#f0fdfa; border-radius:12px; margin-bottom:10px; border-right:4px solid #0d9488; }
.insight-row.warning { background:#fffbeb; border-right-color:#f59e0b; }

/* === AGENT SECTION === */
.agent-section { background:linear-gradient(135deg,#f0fdfa 0%,#e0f8f5 100%); border:1px solid #99f6e4; }
.agent-header-bar { display:flex; align-items:center; gap:12px; margin-bottom:18px; }
.agent-avatar {
    width:44px; height:44px; background:linear-gradient(135deg,#0d9488,#0f172a);
    border-radius:50%; display:flex; align-items:center; justify-content:center;
    font-size:22px; color:white;
}
.agent-title { font-size:18px; font-weight:700; color:#0f172a; }
.agent-subtitle { font-size:12px; color:#64748b; }
.agent-bubble {
    background:white; border-radius:14px; padding:18px; margin-bottom:12px;
    border-right:4px solid; box-shadow:0 1px 3px rgba(0,0,0,.04);
}
.ab-warning { border-right-color:#f59e0b; }
.ab-info { border-right-color:#0d9488; }
.ab-success { border-right-color:#16a34a; }
.ab-insight { border-right-color:#7c3aed; }
.ab-title { font-weight:700; font-size:14px; margin-bottom:8px; display:flex; align-items:center; gap:8px; }
.ab-badge { display:inline-block; background:#f0fdfa; color:#0d9488; padding:2px 10px; border-radius:12px; font-size:11px; font-weight:600; }
.ab-body { font-size:13px; line-height:1.8; color:#334155; }
.evidence-btn {
    display:inline-block; margin-top:10px; padding:8px 18px;
    background:white; border:1px solid #e2e8f0; border-radius:10px;
    cursor:pointer; font-size:12px; font-family:inherit; color:#0d9488;
    transition:all .15s; min-height:36px; font-weight:500;
}
.evidence-btn:hover { background:#f0fdfa; border-color:#0d9488; }
.evidence-panel {
    display:none; margin-top:10px; background:white; border-radius:12px;
    padding:14px; border:1px solid #f1f0ee; max-height:400px; overflow-y:auto;
}
.evidence-panel.visible { display:block; }

/* === BANK PAGE === */
.recon-section { margin-bottom:20px; }
.recon-section h3 { font-size:15px; color:#0f172a; font-weight:700; margin-bottom:10px; border-bottom:1px solid #f1f0ee; padding-bottom:8px; }
.recon-match {
    display:flex; gap:12px; align-items:center; padding:14px 16px;
    background:#f0fdf4; border-radius:12px; margin-bottom:8px; border-right:3px solid #16a34a;
}
.recon-unmatched-bank {
    display:flex; gap:12px; align-items:center; padding:14px 16px;
    background:#fffbeb; border-radius:12px; margin-bottom:8px; border-right:3px solid #f59e0b;
}
.recon-unmatched-inv {
    display:flex; gap:12px; align-items:center; padding:14px 16px;
    background:#fef2f2; border-radius:12px; margin-bottom:8px; border-right:3px solid #dc2626;
}
.recon-icon { font-size:18px; flex-shrink:0; }
.recon-body { flex:1; font-size:13px; line-height:1.6; }
.recon-body strong { color:#0f172a; }
.recon-amount { font-weight:700; font-variant-numeric:tabular-nums; direction:ltr; white-space:nowrap; font-size:14px; }
.recon-summary {
    display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-bottom:20px;
}
.recon-stat {
    background:#faf9f7; border-radius:14px; padding:16px; text-align:center;
    border:1px solid #f1f0ee;
}
.recon-stat .rs-val { font-size:22px; font-weight:700; color:#0f172a; }
.recon-stat .rs-lbl { font-size:12px; color:#94a3b8; margin-top:4px; }
@media(max-width:700px) { .recon-summary { grid-template-columns:1fr; } }

/* === FOOTER === */
.footer { text-align:center; padding:28px 16px; color:#94a3b8; font-size:12px; border-top:1px solid #f1f0ee; margin-top:12px; }
.footer .brand { font-weight:700; color:#0d9488; font-size:14px; }

/* === ALERTS === */
.alert { display:flex; gap:14px; padding:18px; border-radius:14px; margin-bottom:14px; }
.alert-red { background:#fef2f2; border:1px solid #fecaca; }
.alert-orange { background:#fff7ed; border:1px solid #fed7aa; }
.alert-icon { font-size:24px; }
.alert-title { font-weight:700; font-size:15px; margin-bottom:4px; }
.alert-detail { font-size:12px; color:#64748b; margin-top:4px; }
.recommendation { margin-top:8px; padding:10px 12px; background:white; border-radius:10px; font-size:13px; line-height:1.8; }
"""

# ─── JavaScript ─────────────────────────────────────────────────────────
_JS = r"""
// === STATE ===
var currentPage = 'page-overview';
var filterStart = null;
var filterEnd = null;

// === UTILS ===
function ils(n) {
    var v = Math.round(n);
    if (v >= 0) return '₪' + v.toLocaleString('he-IL');
    return '-₪' + Math.abs(v).toLocaleString('he-IL');
}
function pct1(n) { return n.toFixed(1); }

// === FILTERING ===
function getFiltered() {
    var evts = DATA.serviceEvents;
    if (filterStart) evts = evts.filter(function(e){ return e.date >= filterStart; });
    if (filterEnd) evts = evts.filter(function(e){ return e.date <= filterEnd; });
    return evts;
}

// === COMPUTATION (mirrors Python profitability_engine) ===
function computeKPIs(evts) {
    var rev=0, cost=0;
    evts.forEach(function(e){ rev += e.revenue; cost += e.totalCost; });
    var profit = rev - cost;
    return {
        revenue: rev, profit: profit,
        margin: rev ? pct1(profit/rev*100) : '0.0',
        count: evts.length
    };
}

function computeTreatments(evts) {
    var m = {};
    evts.forEach(function(e){
        var k = e.serviceName;
        if (!m[k]) m[k] = {name:k, count:0, rev:0, mats:0, lab:0, labor:0, over:0, cost:0, profit:0};
        var t = m[k]; t.count++;
        t.rev += e.revenue;
        t.mats += e.materialsUsed.reduce(function(s,x){return s+x.totalCost;},0);
        t.lab += e.labCost; t.labor += e.directLaborCost;
        t.over += e.overheadAllocated; t.cost += e.totalCost; t.profit += e.grossProfit;
    });
    var arr = Object.values(m);
    arr.forEach(function(t){
        t.avgRev = t.count ? Math.round(t.rev/t.count) : 0;
        t.avgCost = t.count ? Math.round(t.cost/t.count) : 0;
        t.avgProfit = t.count ? Math.round(t.profit/t.count) : 0;
        t.margin = t.rev ? parseFloat(pct1(t.profit/t.rev*100)) : 0;
    });
    arr.sort(function(a,b){ return b.margin - a.margin; });
    return arr;
}

function computePatients(evts, n) {
    var m = {};
    evts.forEach(function(e){
        var k = e.patientName;
        if (!m[k]) m[k] = {name:k, visits:0, rev:0, cost:0, profit:0, treatments:[], events:[]};
        var p = m[k]; p.visits++; p.rev += e.revenue; p.cost += e.totalCost;
        p.profit += e.grossProfit; p.treatments.push(e.serviceName); p.events.push(e);
    });
    var arr = Object.values(m);
    arr.forEach(function(p){ p.margin = p.rev ? parseFloat(pct1(p.profit/p.rev*100)) : 0; });
    arr.sort(function(a,b){ return b.profit - a.profit; });
    return arr.slice(0, n || 10);
}

function computeCosts(evts) {
    var b = {mats:0, lab:0, labor:0, over:0, total:0};
    evts.forEach(function(e){
        b.mats += e.materialsUsed.reduce(function(s,x){return s+x.totalCost;},0);
        b.lab += e.labCost; b.labor += e.directLaborCost;
        b.over += e.overheadAllocated; b.total += e.totalCost;
    });
    return b;
}

function computeUsageRates(evts) {
    var u = {};
    evts.forEach(function(e){
        e.materialsUsed.forEach(function(m){
            if (!u[m.materialId]) {
                var cat = STATIC.materialsCatalog[m.materialId] || {};
                u[m.materialId] = {name:m.materialName, qty:0, cost:0, unit:cat.unit||'יחידה', shelf:cat.shelfLifeMonths};
            }
            u[m.materialId].qty += m.quantity;
            u[m.materialId].cost += m.totalCost;
        });
    });
    var dates = evts.map(function(e){return e.date;}).sort();
    var months = 1;
    if (dates.length > 1) {
        var d0 = new Date(dates[0]), d1 = new Date(dates[dates.length-1]);
        months = Math.max(1, (d1-d0)/(30.44*86400000));
    }
    Object.values(u).forEach(function(x){ x.mQty=x.qty/months; x.mCost=x.cost/months; });
    return u;
}

// === MORE MENU ===
function toggleMore(e) {
    e.stopPropagation();
    var menu = document.getElementById('moreMenu');
    var backdrop = document.getElementById('moreBackdrop');
    var vis = menu.classList.contains('visible');
    menu.classList.toggle('visible');
    backdrop.classList.toggle('visible');
}
function closeMore() {
    document.getElementById('moreMenu').classList.remove('visible');
    document.getElementById('moreBackdrop').classList.remove('visible');
}

// === PAGE NAVIGATION ===
function showPage(id) {
    document.querySelectorAll('.page').forEach(function(p){ p.classList.remove('active'); p.style.display='none'; });
    var t = document.getElementById(id);
    if (t) { t.classList.add('active'); t.style.display='block'; }
    document.querySelectorAll('.nav-sidebar a').forEach(function(a){
        a.classList.toggle('active', a.getAttribute('data-page')===id);
    });
    currentPage = id;
    renderPage(id);
    window.scrollTo(0,0);
}

// === PERIOD SELECTOR ===
function setPeriod(preset, btn) {
    document.querySelectorAll('.pbtn').forEach(function(b){ b.classList.remove('active'); });
    if (btn) btn.classList.add('active');
    var mx = DATA.dateRange.max;
    var mxD = new Date(mx);
    switch(preset) {
        case 'all': filterStart=null; filterEnd=null; break;
        case '12m': var d=new Date(mxD); d.setMonth(d.getMonth()-12); filterStart=d.toISOString().slice(0,10); filterEnd=null; break;
        case '6m':  var d=new Date(mxD); d.setMonth(d.getMonth()-6);  filterStart=d.toISOString().slice(0,10); filterEnd=null; break;
        case '3m':  var d=new Date(mxD); d.setMonth(d.getMonth()-3);  filterStart=d.toISOString().slice(0,10); filterEnd=null; break;
        case '1m':  var d=new Date(mxD); d.setMonth(d.getMonth()-1);  filterStart=d.toISOString().slice(0,10); filterEnd=null; break;
    }
    document.getElementById('dateFrom').value = filterStart || DATA.dateRange.min;
    document.getElementById('dateTo').value = filterEnd || DATA.dateRange.max;
    updateInfo();
    renderPage(currentPage);
}

function setCustomPeriod() {
    var f = document.getElementById('dateFrom').value;
    var t = document.getElementById('dateTo').value;
    filterStart = f || null;
    filterEnd = t || null;
    document.querySelectorAll('.pbtn').forEach(function(b){ b.classList.remove('active'); });
    updateInfo();
    renderPage(currentPage);
}

function updateInfo() {
    var evts = getFiltered();
    var s = 'מציג ' + evts.length.toLocaleString('he-IL') + ' טיפולים';
    if (evts.length) {
        var dates = evts.map(function(e){return e.date;}).sort();
        s += ' · ' + dates[0] + ' — ' + dates[dates.length-1];
    }
    document.getElementById('periodInfo').textContent = s;
}

// === RENDERERS ===
function renderPage(id) {
    var evts = getFiltered();
    if (id === 'page-overview') renderOverview(evts);
    else if (id === 'page-treatments') renderTreatments(evts);
    else if (id === 'page-materials') renderMaterials();
    else if (id === 'page-patients') renderPatients(evts);
    else if (id === 'page-insights') renderInsights(evts);
    else if (id === 'page-bank') renderBank();
}

// --- Overview ---
function renderOverview(evts) {
    // Hero balance card
    var txs = DATA.bankTransactions;
    if (txs && txs.length > 0) {
        var lastBal = txs[txs.length - 1].balanceAfter;
        var balClr = lastBal >= 0 ? '#4ade80' : '#f87171';
        document.getElementById('heroBalance').innerHTML = '<span style="color:'+balClr+'">'+ils(lastBal)+'</span>';
        document.getElementById('heroSub').textContent = txs.length + ' תנועות · עודכן ' + txs[txs.length-1].date;
    } else {
        document.getElementById('heroBalance').textContent = ils(STATIC.currentBalance);
        document.getElementById('heroSub').textContent = '';
    }

    var kpi = computeKPIs(evts);
    document.getElementById('kpiGrid').innerHTML =
        tile('💰', 'הכנסה כוללת', ils(kpi.revenue), '#0d9488') +
        tile('📈', 'רווח גולמי', ils(kpi.profit), kpi.profit >= 0 ? '#16a34a' : '#dc2626') +
        tile('📊', 'מרג׳ין ממוצע', kpi.margin + '%', parseFloat(kpi.margin) >= 40 ? '#16a34a' : '#f59e0b') +
        tile('🦷', 'מספר טיפולים', kpi.count.toLocaleString('he-IL'), '#7c3aed');

    var bd = computeCosts(evts);
    var items = [
        {id:'labor', pct: bd.total?pct1(bd.labor/bd.total*100):'0', amt:bd.labor, lbl:'כוח אדם'},
        {id:'over',  pct: bd.total?pct1(bd.over/bd.total*100):'0',  amt:bd.over,  lbl:'תקורה'},
        {id:'mats',  pct: bd.total?pct1(bd.mats/bd.total*100):'0',  amt:bd.mats,  lbl:'חומרים ומתכלים'},
        {id:'lab',   pct: bd.total?pct1(bd.lab/bd.total*100):'0',   amt:bd.lab,   lbl:'מעבדת שיניים'},
    ];
    var cg = '';
    items.forEach(function(it){
        cg += '<div class="cost-tile" onclick="showCostDetail(\''+it.id+'\')">' +
              '<div class="pct">'+it.pct+'%</div>' +
              '<div class="amt">'+ils(it.amt)+'</div>' +
              '<div class="lbl">'+it.lbl+'</div></div>';
    });
    document.getElementById('costGrid').innerHTML = cg;

    // Cost detail panels data
    window._costEvts = evts;

    // Quick insights
    var treats = computeTreatments(evts);
    var best = treats[0], worst = treats[treats.length-1];
    var h = '';
    if (best) {
        h += '<div class="insight-row"><div style="font-size:20px;flex-shrink:0">✅</div><div style="font-size:13px;line-height:1.7">' +
             '<strong>'+best.name+'</strong> — הכי רווחי<br>' +
             '<span style="color:#0d9488;font-weight:700;font-size:16px">'+best.margin+'%</span> מרג׳ין · '+ils(best.avgProfit)+' רווח ממוצע</div></div>';
    }
    if (worst && worst.name !== best.name) {
        h += '<div class="insight-row warning"><div style="font-size:20px;flex-shrink:0">⚠️</div><div style="font-size:13px;line-height:1.7">' +
             '<strong>'+worst.name+'</strong> — דורש תשומת לב<br>' +
             '<span style="color:#f59e0b;font-weight:700;font-size:16px">'+worst.margin+'%</span> מרג׳ין · עלות '+ils(worst.avgCost)+' מול מחיר '+ils(worst.avgRev)+'</div></div>';
    }
    document.getElementById('overviewInsights').innerHTML = h ? '<h2><span class="emoji">💡</span> במבט חטוף</h2>' + h : '';
}

function tile(icon, lbl, val, accent) {
    return '<div class="kpi-tile" style="--kpi-accent:'+accent+'">' +
           '<div class="kpi-icon">'+icon+'</div>' +
           '<div class="kpi-label">'+lbl+'</div>' +
           '<div class="kpi-value" style="color:'+accent+'">'+val+'</div></div>';
}

var _activeCostDetail = null;
function showCostDetail(id) {
    var panel = document.getElementById('costDetailPanel');
    if (_activeCostDetail === id) { panel.innerHTML = ''; _activeCostDetail = null; return; }
    _activeCostDetail = id;
    var h = '<div class="cost-detail-panel visible">';
    if (id === 'labor') {
        h += '<div style="font-weight:600;margin-bottom:8px;color:#0f172a">פירוט כוח אדם (עלות מעסיק חודשית)</div>';
        STATIC.employees.forEach(function(e){
            h += '<div class="cdi"><span>'+e.name+' ('+e.role+')</span><span style="direction:ltr">'+ils(e.totalCost)+' / חודש</span></div>';
        });
    } else if (id === 'over') {
        h += '<div style="font-weight:600;margin-bottom:8px;color:#0f172a">פירוט תקורה (חודשי)</div>';
        STATIC.overheadPools.forEach(function(p){
            h += '<div class="cdi"><span>'+p.name+'</span><span style="direction:ltr">'+ils(p.monthlyCost)+' / חודש</span></div>';
        });
    } else if (id === 'mats') {
        h += '<div style="font-weight:600;margin-bottom:8px;color:#0f172a">8 חומרים מובילים לפי צריכה</div>';
        var evts = window._costEvts || [];
        var spend = {};
        evts.forEach(function(e){ e.materialsUsed.forEach(function(m){
            spend[m.materialName] = (spend[m.materialName]||0) + m.totalCost;
        });});
        var sorted = Object.entries(spend).sort(function(a,b){return b[1]-a[1];}).slice(0,8);
        sorted.forEach(function(s){
            h += '<div class="cdi"><span>'+s[0]+'</span><span style="direction:ltr">'+ils(s[1])+'</span></div>';
        });
    } else if (id === 'lab') {
        h += '<div style="font-weight:600;margin-bottom:8px;color:#0f172a">עלויות מעבדה לפי סוג טיפול</div>';
        var evts = window._costEvts || [];
        var byType = {};
        evts.forEach(function(e){ if(e.labCost>0) byType[e.serviceName]=(byType[e.serviceName]||0)+e.labCost; });
        var sorted = Object.entries(byType).sort(function(a,b){return b[1]-a[1];});
        if (sorted.length === 0) h += '<div class="cdi"><span>אין עלויות מעבדה בתקופה זו</span></div>';
        sorted.forEach(function(s){ h += '<div class="cdi"><span>'+s[0]+'</span><span style="direction:ltr">'+ils(s[1])+'</span></div>'; });
    }
    h += '</div>';
    panel.innerHTML = h;
}

// --- Treatments ---
function renderTreatments(evts) {
    var treats = computeTreatments(evts);
    var h = '<table><thead><tr><th>סוג טיפול</th><th>כמות</th><th>מחיר ממוצע</th><th>עלות ממוצעת</th><th>רווח ממוצע</th><th>מרג׳ין</th></tr></thead><tbody>';
    treats.forEach(function(t, i) {
        var bw = Math.min(Math.max(Math.round(t.margin),0),100);
        var clr = t.margin>=50?'#0d9488':t.margin>=35?'#f59e0b':'#dc2626';
        var matP = t.cost?pct1(t.mats/t.cost*100):'0';
        var labP = t.cost?pct1(t.lab/t.cost*100):'0';
        var lbrP = t.cost?pct1(t.labor/t.cost*100):'0';
        var ovrP = t.cost?pct1(t.over/t.cost*100):'0';
        h += '<tr class="expandable" onclick="toggleRow(\'tr-'+i+'\')">' +
             '<td class="name"><span class="expand-arrow" id="arr-tr-'+i+'">&#9656;</span>'+t.name+'</td>' +
             '<td class="num">'+t.count+'</td>' +
             '<td class="num">'+ils(t.avgRev)+'</td>' +
             '<td class="num">'+ils(t.avgCost)+'</td>' +
             '<td class="num bold">'+ils(t.avgProfit)+'</td>' +
             '<td class="num"><div class="bar-cell"><span style="color:'+clr+'">'+t.margin+'%</span><div class="bar-track"><div class="bar" style="width:'+bw+'%;background:'+clr+'"></div></div></div></td>' +
             '</tr>';
        h += '<tr class="detail-row" id="tr-'+i+'" style="display:none"><td colspan="6"><div class="detail-content"><div class="detail-grid">' +
             '<div class="detail-item"><span class="detail-label">חומרים</span><span class="detail-value">'+ils(t.mats)+' ('+matP+'%)</span></div>' +
             '<div class="detail-item"><span class="detail-label">מעבדה</span><span class="detail-value">'+ils(t.lab)+' ('+labP+'%)</span></div>' +
             '<div class="detail-item"><span class="detail-label">כוח אדם</span><span class="detail-value">'+ils(t.labor)+' ('+lbrP+'%)</span></div>' +
             '<div class="detail-item"><span class="detail-label">תקורה</span><span class="detail-value">'+ils(t.over)+' ('+ovrP+'%)</span></div>' +
             '</div><div style="margin-top:12px;font-size:13px;color:#64748b">' +
             'סה״כ הכנסה: '+ils(t.rev)+' · סה״כ עלות: '+ils(t.cost)+' · סה״כ רווח: '+ils(t.profit)+
             '</div></div></td></tr>';
    });
    h += '</tbody></table>';
    document.getElementById('treatmentTableContainer').innerHTML = h;
}

// --- Materials (NOT date-filtered) ---
function renderMaterials() {
    var cards = '';
    STATIC.selectorCards.forEach(function(s){
        cards += '<div class="selector-card" onclick="selectTreatment(\''+s.name+'\')">' +
                 '<div class="selector-icon">'+s.icon+'</div>' +
                 '<div class="selector-name">'+s.name+'</div>' +
                 '<div class="selector-meta">'+s.duration+' דק׳ · '+ils(s.price)+'</div></div>';
    });
    document.getElementById('selectorGrid').innerHTML = cards;
    document.getElementById('bomDetail').innerHTML = '';
}

function selectTreatment(name) {
    document.querySelectorAll('.selector-card').forEach(function(c){ c.classList.remove('selected'); });
    document.querySelectorAll('.selector-card').forEach(function(c){
        if (c.querySelector('.selector-name').textContent === name) c.classList.add('selected');
    });
    var d = STATIC.treatmentBOM[name];
    if (!d) return;
    var h = '<div class="bom-detail"><div class="bom-header">' +
            '<h3>'+d.icon+' '+name+' — '+d.category+'</h3>' +
            '<span style="font-size:14px;color:#64748b">מחירון: '+ils(d.standardPrice)+' · '+d.durationMinutes+' דקות</span></div>';
    h += '<table><thead><tr><th>חומר</th><th>כמות</th><th>עלות ליחידה</th><th>עלות כוללת</th><th>חיי מדף</th><th>תוקף משוער</th></tr></thead><tbody>';
    d.materials.forEach(function(m){
        var exp = '—';
        if (m.expiryDate) {
            var ed = new Date(m.expiryDate), now = new Date();
            var days = Math.floor((ed-now)/86400000);
            var ds = ed.toLocaleDateString('he-IL');
            if (days<0) exp='<span class="expiry-warning">'+ds+' (פג תוקף!)</span>';
            else if (days<90) exp='<span class="expiry-warning">'+ds+' ('+days+' ימים)</span>';
            else exp='<span class="expiry-ok">'+ds+' ('+days+' ימים)</span>';
        }
        h += '<tr><td class="name">'+m.name+'</td>' +
             '<td class="num">'+m.quantity+' '+m.unit+'</td>' +
             '<td class="num" style="direction:ltr">'+ils(m.unitCost)+'</td>' +
             '<td class="num" style="direction:ltr">'+ils(m.totalCost)+'</td>' +
             '<td class="num">'+(m.shelfLifeMonths?m.shelfLifeMonths+' חודשים':'—')+'</td>' +
             '<td>'+exp+'</td></tr>';
    });
    h += '</tbody></table>';
    h += '<div style="margin-top:16px;display:flex;justify-content:space-between;font-weight:600;padding:12px;background:white;border-radius:8px">' +
         '<span>סה״כ עלות חומרים</span><span style="direction:ltr">'+ils(d.totalMaterialsCost)+'</span></div>';
    if (d.requiresLab) {
        h += '<div style="margin-top:8px;display:flex;justify-content:space-between;padding:12px;background:white;border-radius:8px">' +
             '<span>עלות מעבדה</span><span style="direction:ltr">'+ils(d.labCost)+'</span></div>';
    }
    h += '</div>';
    document.getElementById('bomDetail').innerHTML = h;
}

// --- Patients ---
function renderPatients(evts) {
    var patients = computePatients(evts, 10);
    var h = '<table><thead><tr><th>מטופל</th><th>ביקורים</th><th>הכנסה</th><th>רווח</th><th>מרג׳ין</th><th>טיפולים</th></tr></thead><tbody>';
    patients.forEach(function(p, i) {
        var txSet = {}; p.treatments.forEach(function(t){txSet[t]=1;}); var txList = Object.keys(txSet).join(', ');
        // Build drill-down mini-table
        var sorted = p.events.slice().sort(function(a,b){return b.date.localeCompare(a.date);}).slice(0,10);
        var detail = '<div style="font-size:13px;font-weight:600;margin-bottom:10px;color:#0f172a">10 טיפולים אחרונים</div>';
        detail += '<table class="pd-table"><thead><tr><th>תאריך</th><th>טיפול</th><th>הכנסה</th><th>עלות</th><th>רווח</th></tr></thead><tbody>';
        sorted.forEach(function(ev){
            var pc = ev.grossProfit>0?'#16a34a':'#dc2626';
            detail += '<tr><td class="num" style="direction:ltr;white-space:nowrap">'+ev.date+'</td>' +
                      '<td class="name">'+ev.serviceName+'</td>' +
                      '<td class="num">'+ils(ev.revenue)+'</td>' +
                      '<td class="num">'+ils(Math.round(ev.totalCost))+'</td>' +
                      '<td class="num" style="color:'+pc+';font-weight:600">'+ils(Math.round(ev.grossProfit))+'</td></tr>';
        });
        detail += '</tbody></table>';

        h += '<tr class="expandable" onclick="toggleRow(\'pt-'+i+'\')">' +
             '<td class="name"><span class="expand-arrow" id="arr-pt-'+i+'">&#9656;</span>'+p.name+'</td>' +
             '<td class="num">'+p.visits+'</td>' +
             '<td class="num">'+ils(p.rev)+'</td>' +
             '<td class="num bold">'+ils(Math.round(p.profit))+'</td>' +
             '<td class="num">'+p.margin+'%</td>' +
             '<td style="font-size:12px;color:#64748b;max-width:200px">'+txList+'</td></tr>';
        h += '<tr class="detail-row" id="pt-'+i+'" style="display:none"><td colspan="6"><div class="detail-content">'+detail+'</div></td></tr>';
    });
    h += '</tbody></table>';
    document.getElementById('patientTableContainer').innerHTML = h;
}

// --- AI Insights ---
function renderInsights(evts) {
    var treats = computeTreatments(evts);
    var patients = computePatients(evts, 999);
    var usage = computeUsageRates(evts);
    var h = '';

    // 1. Cashflow
    var cfText = '';
    if (DATA.cashflowEvents.length > 0) {
        var bigPay = DATA.cashflowEvents.find(function(c){return c.amount < -10000;});
        if (bigPay) {
            cfText = 'שימי לב — ב-'+bigPay.date+' יש תשלום של <strong>'+ils(Math.abs(bigPay.amount))+'</strong> ל-'+bigPay.description+'.<br>' +
                     'כדאי לוודא שהכנסות צפויות נכנסות לפני תאריך זה.';
        } else {
            cfText = 'אין תשלומים גדולים (מעל ₪10,000) ב-90 הימים הקרובים. התזרים נראה יציב.';
        }
    }
    // Cashflow evidence
    var cfEvidence = '<table><thead><tr><th>תאריך</th><th>תיאור</th><th>סכום</th><th>יתרה מצטברת</th></tr></thead><tbody>';
    var bal = STATIC.currentBalance;
    DATA.cashflowEvents.forEach(function(ce){
        bal += ce.amount;
        var cls = bal<10000?' style="color:#dc2626;font-weight:600"':'';
        var amtCls = ce.amount<0?' style="color:#dc2626"':'';
        cfEvidence += '<tr><td class="num" style="direction:ltr;white-space:nowrap">'+ce.date+'</td>' +
                      '<td>'+ce.description+' — '+ce.counterparty+'</td>' +
                      '<td class="num"'+amtCls+'>'+ils(ce.amount)+'</td>' +
                      '<td class="num"'+cls+'>'+ils(bal)+'</td></tr>';
    });
    cfEvidence += '</tbody></table>';

    h += bubble('ab-warning', '⚠️ התראת תזרים', 'תזרים מזומנים', cfText, 'ev-cf', cfEvidence);

    // 2. Treatment mix
    var best = treats[0];
    var tmText = '';
    if (best) {
        var potMonthly = best.avgProfit * 2;
        tmText = 'הטיפול <strong>'+best.name+'</strong> מייצר מרג׳ין של <strong>'+best.margin+'%</strong> — הכי גבוה מכל הטיפולים.<br>' +
                 'בוצעו '+best.count+' טיפולים מסוג זה בתקופה הנבחרת.<br>' +
                 'אם תגדילי ב-2 טיפולים נוספים בחודש, תוסיפי כ-<strong>'+ils(potMonthly)+'</strong> לרווח החודשי.';
    }
    var tmEvidence = '<table><thead><tr><th>טיפול</th><th>כמות</th><th>מרג׳ין</th><th>רווח ממוצע</th><th>סה"כ רווח</th></tr></thead><tbody>';
    treats.forEach(function(t){
        var mc = t.margin>=50?'#0d9488':t.margin>=35?'#f59e0b':'#dc2626';
        tmEvidence += '<tr><td class="name">'+t.name+'</td><td class="num">'+t.count+'</td>' +
                      '<td class="num" style="color:'+mc+';font-weight:600">'+t.margin+'%</td>' +
                      '<td class="num">'+ils(t.avgProfit)+'</td><td class="num bold">'+ils(Math.round(t.profit))+'</td></tr>';
    });
    tmEvidence += '</tbody></table>';
    h += bubble('ab-info', '📈 המלצה לתמהיל טיפולים', 'רווחיות', tmText, 'ev-tm', tmEvidence);

    // 3. Inventory
    var sorted = Object.entries(usage).sort(function(a,b){return b[1].mCost-a[1].mCost;});
    var topMat = sorted.length ? sorted[0][1] : null;
    var invText = '';
    if (topMat) {
        var reorder = topMat.shelf ? Math.min(topMat.shelf, 3) : 3;
        invText = 'קצב השימוש ב<strong>'+topMat.name+'</strong> — כ-'+topMat.mQty.toFixed(0)+' '+topMat.unit+' בחודש' +
                  ' (עלות חודשית: '+ils(Math.round(topMat.mCost))+').<br>' +
                  (topMat.shelf ? 'חיי מדף: '+topMat.shelf+' חודשים.<br>' : '') +
                  'מומלץ להזמין מנה כל '+reorder+' חודשים כדי לשמור על מלאי טרי.';
    }
    var invEvidence = '<table><thead><tr><th>חומר</th><th>צריכה חודשית</th><th>עלות חודשית</th><th>חיי מדף</th><th>הזמנה מומלצת</th></tr></thead><tbody>';
    sorted.forEach(function(s){
        var u = s[1];
        var ro = u.shelf ? Math.min(u.shelf,3)+' חודשים' : '—';
        invEvidence += '<tr><td class="name">'+u.name+'</td><td class="num">'+u.mQty.toFixed(1)+' '+u.unit+'</td>' +
                       '<td class="num">'+ils(Math.round(u.mCost))+'</td>' +
                       '<td class="num">'+(u.shelf?u.shelf+' חודשים':'—')+'</td><td class="num">'+ro+'</td></tr>';
    });
    invEvidence += '</tbody></table>';
    h += bubble('ab-success', '📦 ניהול מלאי', 'חומרים', invText, 'ev-inv', invEvidence);

    // 4. Patient retention
    var oneVisit = patients.filter(function(p){ return p.visits===1 && p.rev>500; });
    var retText = '';
    if (oneVisit.length > 0) {
        var names = oneVisit.slice(0,3).map(function(p){return p.name;}).join(', ');
        var potRev = oneVisit.slice(0,5).reduce(function(s,p){return s+p.rev;},0);
        retText = 'יש <strong>'+oneVisit.length+' מטופלים</strong> שביקרו פעם אחת בלבד עם טיפול מעל ₪500.<br>' +
                  'ביניהם: '+names+'.<br>' +
                  'שווה לשלוח להם תזכורת לבדיקה תקופתית — פוטנציאל הכנסה של כ-<strong>'+ils(Math.round(potRev))+'</strong>.';
    } else {
        retText = 'כל המטופלים עם טיפולים מעל ₪500 חזרו ליותר מביקור אחד — מצוין!';
    }
    var retEvidence = '<table><thead><tr><th>מטופל</th><th>טיפול</th><th>תאריך</th><th>הכנסה</th><th>רווח</th></tr></thead><tbody>';
    oneVisit.forEach(function(p){
        var ev = p.events[0];
        retEvidence += '<tr><td class="name">'+p.name+'</td><td>'+ev.serviceName+'</td>' +
                       '<td class="num" style="direction:ltr;white-space:nowrap">'+ev.date+'</td>' +
                       '<td class="num">'+ils(ev.revenue)+'</td><td class="num">'+ils(Math.round(ev.grossProfit))+'</td></tr>';
    });
    retEvidence += '</tbody></table>';
    if (oneVisit.length === 0) retEvidence = '<div style="padding:12px;color:#64748b">כל המטופלים הגדולים חזרו ליותר מביקור אחד.</div>';
    h += bubble('ab-insight', '👥 שימור מטופלים', 'לקוחות', retText, 'ev-ret', retEvidence);

    // Conflicts
    if (DATA.conflicts.length > 0) {
        var c = DATA.conflicts[0];
        h += '<div class="agent-bubble ab-warning">' +
             '<div class="ab-title">💰 קונפליקט תנאי תשלום <span class="ab-badge">ספקים</span></div>' +
             '<div class="ab-body">תשלום ל<strong>'+c.supplierName+'</strong> ב-'+c.supplierTerms+
             ' אבל קבלה מ<strong>'+c.customerName+'</strong> ב-'+c.customerTerms+'.<br>' +
             'פער של '+c.cashGapDays+' ימים שבהם את ממנת מהכיס.<br>' +
             '<div class="recommendation">'+c.recommendation+'</div></div></div>';
    }

    document.getElementById('insightCards').innerHTML = h;
}

function bubble(cls, title, badge, body, evidenceId, evidenceHtml) {
    return '<div class="agent-bubble '+cls+'">' +
           '<div class="ab-title">'+title.split(' ')[0]+' '+title.split(' ').slice(1).join(' ')+' <span class="ab-badge">'+badge+'</span></div>' +
           '<div class="ab-body">'+body+'</div>' +
           '<button class="evidence-btn" onclick="toggleEvidence(\''+evidenceId+'\',this)">הצג נתונים ▾</button>' +
           '<div class="evidence-panel" id="'+evidenceId+'">'+evidenceHtml+'</div></div>';
}

// === SHARED HELPERS ===
function toggleRow(id) {
    var row = document.getElementById(id);
    if (!row) return;
    var vis = row.style.display !== 'none';
    row.style.display = vis ? 'none' : 'table-row';
    var arr = document.getElementById('arr-'+id);
    if (arr) arr.innerHTML = vis ? '&#9656;' : '&#9662;';
}

function toggleEvidence(id, btn) {
    var panel = document.getElementById(id);
    if (!panel) return;
    var vis = panel.classList.contains('visible');
    panel.classList.toggle('visible');
    if (btn) btn.textContent = vis ? 'הצג נתונים ▾' : 'הסתר נתונים ▴';
}

// --- Bank Account (NOT date-filtered — shows full account state) ---
function renderBank() {
    var txs = DATA.bankTransactions;
    if (!txs || txs.length === 0) {
        document.getElementById('bankKPIs').innerHTML = '<div style="padding:20px;color:#64748b">אין תנועות בנק</div>';
        return;
    }
    var last = txs[txs.length - 1];
    var totalIn = 0, totalOut = 0;
    txs.forEach(function(t) { if (t.amount > 0) totalIn += t.amount; else totalOut += Math.abs(t.amount); });

    // KPIs
    var balClr = last.balanceAfter >= 0 ? '#16a34a' : '#dc2626';
    document.getElementById('bankKPIs').innerHTML =
        tile('🏦', 'יתרה נוכחית', ils(last.balanceAfter), balClr) +
        tile('📥', 'סה״כ נכנס', ils(totalIn), '#16a34a') +
        tile('📤', 'סה״כ יצא', ils(totalOut), '#dc2626') +
        tile('📋', 'מספר תנועות', txs.length.toLocaleString('he-IL'), '#64748b');

    // Count real vs synthetic
    var realCount = txs.filter(function(t){return t.source==='discount_bank';}).length;
    var synthCount = txs.length - realCount;

    // Source summary
    var srcH = '<div style="display:flex;gap:16px;margin-bottom:16px;font-size:13px">' +
               '<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#0d9488;margin-left:4px"></span> בנק דיסקונט (נתונים אמיתיים): '+realCount+'</span>' +
               '<span><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#94a3b8;margin-left:4px"></span> סימולציה: '+synthCount+'</span></div>';

    // Transactions table (last 50)
    var recent = txs.slice().reverse().slice(0, 50);
    var h = srcH + '<table><thead><tr><th>תאריך</th><th>מקור</th><th>תיאור</th><th>צד נגדי</th><th>סכום</th><th>יתרה</th></tr></thead><tbody>';
    recent.forEach(function(t) {
        var amtClr = t.amount >= 0 ? '#16a34a' : '#dc2626';
        var balC = t.balanceAfter < 10000 ? 'color:#dc2626;font-weight:600' : '';
        var isReal = t.source === 'discount_bank';
        var srcBadge = isReal ?
            '<span style="background:#f0fdfa;color:#0d9488;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">דיסקונט</span>' :
            '<span style="background:#f1f5f9;color:#94a3b8;padding:2px 8px;border-radius:10px;font-size:11px">סימולציה</span>';
        var rowBg = isReal ? 'background:#f0fdfa;' : '';
        h += '<tr style="'+rowBg+'">' +
             '<td class="num" style="direction:ltr;white-space:nowrap">'+t.date+'</td>' +
             '<td>'+srcBadge+'</td>' +
             '<td>'+t.description+'</td>' +
             '<td class="name">'+(t.counterparty||'—')+'</td>' +
             '<td class="num" style="color:'+amtClr+'">'+ils(t.amount)+'</td>' +
             '<td class="num" style="'+balC+'">'+ils(t.balanceAfter)+'</td></tr>';
    });
    h += '</tbody></table>';
    document.getElementById('bankTransactionsTable').innerHTML = h;

    // Reconciliation
    renderReconciliation();
}

function renderReconciliation() {
    var txs = DATA.bankTransactions;
    var invs = DATA.invoices;

    // Build lookup of invoices by counterparty+approx amount for matching
    var matched = [];
    var unmatchedBank = [];
    var unmatchedInv = [];
    var usedInvIds = {};
    var usedTxIdx = {};

    // For each income bank tx, try to match to an incoming invoice
    // For each expense bank tx, try to match to an outgoing invoice
    txs.forEach(function(tx, idx) {
        var found = false;
        for (var i = 0; i < invs.length; i++) {
            if (usedInvIds[invs[i].id]) continue;
            var inv = invs[i];
            // Match: same counterparty, same direction, amount within 1 NIS
            var sameDirection = (tx.amount > 0 && inv.isIncoming) || (tx.amount < 0 && !inv.isIncoming);
            var amtMatch = Math.abs(Math.abs(tx.amount) - inv.total) < 1;
            var cpMatch = tx.counterparty && inv.counterparty &&
                          tx.counterparty.trim() === inv.counterparty.trim();
            if (sameDirection && amtMatch && cpMatch) {
                matched.push({tx: tx, txIdx: idx, inv: inv});
                usedInvIds[inv.id] = true;
                usedTxIdx[idx] = true;
                found = true;
                break;
            }
        }
    });

    // Collect unmatched
    txs.forEach(function(tx, idx) {
        if (!usedTxIdx[idx]) unmatchedBank.push(tx);
    });
    invs.forEach(function(inv) {
        if (!usedInvIds[inv.id] && (inv.status === 'נשלחה' || inv.status === 'באיחור'))
            unmatchedInv.push(inv);
    });

    // Summary
    var h = '<div class="recon-summary">' +
            '<div class="recon-stat"><div class="rs-val" style="color:#16a34a">'+matched.length+'</div><div class="rs-lbl">תנועות מותאמות</div></div>' +
            '<div class="recon-stat"><div class="rs-val" style="color:#f59e0b">'+unmatchedBank.length+'</div><div class="rs-lbl">תנועות בנק ללא חשבונית</div></div>' +
            '<div class="recon-stat"><div class="rs-val" style="color:#dc2626">'+unmatchedInv.length+'</div><div class="rs-lbl">חשבוניות פתוחות</div></div>' +
            '</div>';

    // Matched section (show last 10)
    if (matched.length > 0) {
        h += '<div class="recon-section"><h3>✅ תנועות מותאמות (אחרונות '+Math.min(matched.length,10)+')</h3>';
        matched.slice(-10).reverse().forEach(function(m) {
            h += '<div class="recon-match">' +
                 '<div class="recon-icon">✅</div>' +
                 '<div class="recon-body">' +
                 '<strong>'+m.tx.counterparty+'</strong> · '+m.tx.date+'<br>' +
                 'חשבונית '+m.inv.invoiceNumber+' — '+m.inv.description+
                 '</div><div class="recon-amount" style="color:#16a34a">'+ils(Math.abs(m.tx.amount))+'</div></div>';
        });
        h += '</div>';
    }

    // Unmatched bank transactions (show last 10)
    if (unmatchedBank.length > 0) {
        h += '<div class="recon-section"><h3>⚠️ תנועות בנק ללא חשבונית מתאימה ('+unmatchedBank.length+')</h3>';
        unmatchedBank.slice(-10).reverse().forEach(function(tx) {
            h += '<div class="recon-unmatched-bank">' +
                 '<div class="recon-icon">⚠️</div>' +
                 '<div class="recon-body">' +
                 '<strong>'+(tx.counterparty||tx.description)+'</strong> · '+tx.date+'<br>' +
                 tx.description+
                 '</div><div class="recon-amount" style="color:'+(tx.amount>=0?'#16a34a':'#dc2626')+'">'+ils(tx.amount)+'</div></div>';
        });
        h += '</div>';
    }

    // Unpaid invoices
    if (unmatchedInv.length > 0) {
        h += '<div class="recon-section"><h3>🔴 חשבוניות פתוחות — לא נפרעו ('+unmatchedInv.length+')</h3>';
        unmatchedInv.forEach(function(inv) {
            var statusClr = inv.status === 'באיחור' ? '#dc2626' : '#f59e0b';
            var direction = inv.isIncoming ? 'לקבל מ-' : 'לשלם ל-';
            var overdue = inv.status === 'באיחור' ? ' · <span style="color:#dc2626;font-weight:600">באיחור!</span>' : '';
            h += '<div class="recon-unmatched-inv">' +
                 '<div class="recon-icon">📄</div>' +
                 '<div class="recon-body">' +
                 '<strong>'+direction+inv.counterparty+'</strong> · חשבונית '+inv.invoiceNumber+overdue+'<br>' +
                 inv.description+' · תאריך פירעון: '+inv.dueDate+
                 '</div><div class="recon-amount" style="color:'+statusClr+'">'+ils(inv.total)+'</div></div>';
        });
        h += '</div>';
    }

    if (matched.length === 0 && unmatchedBank.length === 0 && unmatchedInv.length === 0) {
        h += '<div style="padding:20px;text-align:center;color:#64748b">אין נתונים להצגה</div>';
    }

    document.getElementById('reconciliationView').innerHTML = h;
}

// === INIT ===
document.getElementById('dateFrom').value = DATA.dateRange.min;
document.getElementById('dateTo').value = DATA.dateRange.max;
updateInfo();
renderPage('page-overview');

// === SERVICE WORKER ===
if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('./sw.js', {updateViaCache: 'none'}).then(function(reg) {
        // Check for updates immediately on every load
        reg.update();
        // Auto-reload when a new SW takes over
        var refreshing = false;
        navigator.serviceWorker.addEventListener('controllerchange', function() {
            if (!refreshing) { refreshing = true; window.location.reload(); }
        });
    }).catch(function(){});
}
"""


def main() -> None:
    html = generate_report()

    # Write to data/ for local dev
    output = Path("data/report.html")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")

    # Write to docs/ for GitHub Pages PWA
    pwa_output = Path("docs/index.html")
    pwa_output.parent.mkdir(parents=True, exist_ok=True)
    pwa_output.write_text(html, encoding="utf-8")

    print(f"Report generated: {output}")
    print(f"PWA version: {pwa_output}")
    os.system(f"open {output}")


if __name__ == "__main__":
    main()
