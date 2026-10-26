# AI-Accounting Business Plan — "SmartBooks" (Working Name)

## Context

**Problem**: Small Israeli businesses (1-50 employees — barbers, garages, clinics, small factories) lack real-time financial visibility. Their accountant delivers monthly reports at best, or none at worst. Business owners make financial decisions (vendor terms, cash allocation) blindly, leading to cashflow crunches and missed opportunities.

**Example pain**: A business owner signs a client on Net-90 terms while negotiating with a supplier on Net-60. The system detects that in the month the supplier payment is due, cash reserves will be low — and recommends negotiating Net-90 with the supplier instead.

**Founders**: Aviv (Head of AI, tech lead) + Meital (Head of Global Finance, licensed accountant, domain expert). Both part-time, bootstrapped. Aviv builds the prototype; Meital defines the accounting logic, use cases, and validates correctness.

**Positioning**: Integration layer on top of existing systems (not a replacement). The licensed accountant (רו"ח) remains in the loop for tax filings and compliance.

---

## Phase 1: Foundation & Synthetic Data (Weeks 1-4)

### 1.1 Business Entity Simulation
Create a synthetic small business dataset simulating a **dentist clinic** (relatable, 3-5 employees: dentist owner, dental hygienist, receptionist, assistant):
- **Chart of accounts** (Israeli standard)
- **Bank transactions** (12 months of synthetic data): patient payments, supplier payments (dental supplies, lab fees), payroll, rent, VAT payments, tax
- **Invoices & receipts** (קבלות וחשבוניות): patients (private + קופת חולים), dental supply vendors, dental lab
- **Payroll records**: 3-5 employees, social benefits (ביטוח לאומי, פנסיה, קרן השתלמות)
- **Vendor agreements**: payment terms (שוטף+30, שוטף+60, שוטף+90)
- **Customer ledger**: private patients, קופות חולים (כללית, מכבי, מאוחדת) with agreed payment terms
- **VAT (מע"מ) reporting data**: bi-monthly cycle
- **Cash position**: daily bank balance

Deliverable: A Python package (`synthetic_biz`) that generates realistic, configurable financial data for any small business type.

### 1.2 Repository Setup
- New repo: `ai-accounting` on GitHub (gruberaviv)
- Structure:
  ```
  ai-accounting/
  ├── synthetic_biz/          # Synthetic data generation
  ├── agents/                 # Agentic AI modules
  │   ├── cashflow_agent.py
  │   ├── reconciliation_agent.py
  │   └── insights_agent.py
  ├── skills/                 # User-facing capabilities (charts, reports, queries)
  │   ├── chart_skill.py      # Generate bar/line/pie charts (Plotly)
  │   ├── report_skill.py     # Generate PDF/summary reports
  │   ├── query_skill.py      # Answer ad-hoc Hebrew questions
  │   └── comparison_skill.py # Period-over-period comparisons
  ├── connectors/             # Data source connectors (MCP-based)
  │   ├── bank_connector.py
  │   ├── spreadsheet_connector.py
  │   └── calendar_connector.py
  ├── core/                   # Domain logic
  │   ├── chart_of_accounts.py
  │   ├── vat_engine.py
  │   └── cashflow_engine.py
  ├── config/                 # Per-client YAML configurations
  ├── api/                    # Backend API (FastAPI)
  ├── frontend/               # Mobile-first PWA
  ├── whatsapp/               # WhatsApp Business integration
  ├── tests/
  ├── data/                   # Synthetic datasets
  └── docs/                   # Internal documentation
  ```

---

## Phase 2: Core Agentic Engine (Weeks 3-8)

### 2.1 Framework Recommendation: **Claude Agent SDK + MCP**

**Why not LangChain**: LangChain adds significant abstraction overhead, frequent breaking changes, and vendor lock-in to its own ecosystem. For your use case — structured financial reasoning with tool access — it's over-engineered.

**Recommended stack**:
| Layer | Technology | Rationale |
|-------|-----------|-----------|
| LLM | Claude (Anthropic) | Best structured reasoning, tool use, Hebrew support |
| Agent framework | Claude Agent SDK | Lightweight, native tool use, easy to maintain |
| Tool protocol | MCP (Model Context Protocol) | Standardized connectors, reusable across clients |
| Backend API | FastAPI (Python) | Fast, async, great for prototyping |
| Data layer | SQLite → PostgreSQL | Start simple, migrate when needed |
| Task queue | None initially → Celery later | Don't over-engineer early |

**Why MCP matters for your business**: Each client's systems are different. MCP lets you build standardized connectors (bank, spreadsheet, calendar, invoicing software) that plug into the agent without changing the core logic. This is your "auto-customisation" mechanism.

### 2.1b Client Tailoring Architecture (Critical Design)

The core challenge: every small business uses different systems. A dentist clinic uses spreadsheets + Bank Leumi; a garage uses Hashavshevet + Bank Hapoalim; a barber uses GreenInvoice + Bank Discount.

**Solution — Configuration-Driven Adapter Layer**:

```
┌──────────────────┐
│  Same AI Engine  │  ← identical for all clients
├──────────────────┤
│  Connector Layer │  ← per-client configuration (not code)
│  ┌────┐ ┌────┐  │
│  │MCP1│ │MCP2│  │  ← standardized MCP connectors (reusable)
│  └────┘ └────┘  │
├──────────────────┤
│  Client Config   │  ← JSON/YAML: which connectors, credentials, mappings
└──────────────────┘
```

The onboarding process:
1. **Discovery**: Which systems does this client use? (a questionnaire or guided setup)
2. **Connector selection**: Pick from a library of pre-built MCP connectors
3. **Field mapping**: Map their specific column names / account codes to your standard schema
4. **Validation**: Run on historical data, Meital validates correctness
5. **Activation**: Switch to live mode with monitoring

Connectors are built **once per system type** (one for Excel, one for GreenInvoice, one for each bank, etc.), and each new client just gets a **configuration** (YAML) that selects which connectors to activate and how to map their data.

### 2.2 Agent Architecture
Three specialized agents orchestrated by a coordinator:

1. **Cashflow Agent**: Monitors bank balance projections, flags upcoming shortfalls, recommends payment term adjustments (the core value prop)
2. **Reconciliation Agent**: Matches bank transactions to invoices/receipts, flags unmatched items, detects anomalies
3. **Insights Agent**: Generates periodic summaries, trends, comparisons (month-over-month, seasonal patterns), answers natural-language questions

### 2.3 Core Domain Logic (Meital-driven)
Meital defines the business rules — these are NOT LLM-generated:
- VAT calculation rules (Israeli מע"מ at 18%, exempt categories)
- Payroll deduction rules (bituach leumi tiers, pension minimums)
- Cashflow projection formulas
- Payment term optimization logic
- Chart of accounts structure (Israeli standard)

**Critical principle**: The AI reasons *over* deterministic financial logic. It does NOT invent financial rules. The LLM's role is natural language understanding, pattern recognition, and recommendation generation — not arithmetic.

---

## Phase 3: User Interface (Weeks 6-10)

### 3.1 שפת ממשק — הכל בעברית
כל ממשק המשתמש, הודעות, התראות, גרפים, תוויות, ותובנות — **בעברית בלבד**. קהל היעד הוא בעלי עסקים ישראלים שאינם בהכרח דוברי אנגלית. הממשק תומך ב-RTL מהיום הראשון.

### 3.2 WhatsApp Push (ממשק ראשי — MVP)
- שימוש ב-WhatsApp Business API (דרך ספק כמו Twilio או 360dialog)
- דחיפת סיכומים והתראות יומיות/שבועיות עם מספיק מידע כדי להבין את המצב *לפני* הלחיצה:
  - "⚠️ התראת תזרים מזומנים: יתרת הבנק צפויה לרדת מ-₪32,000 ל-₪4,800 בעוד 12 יום. הסיבה: תשלום לספק ציוד דנטלי (₪18,200, שוטף+60) נופל לפני קבלת תשלום מקופת חולים כללית (₪22,000, שוטף+90). לחץ לפרטים והמלצה →"
  - "📊 סיכום שבועי: הכנסות ₪18,200 | הוצאות ₪14,800 | נטו ₪3,400. לחץ לפירוט מלא →"
  - "💡 המלצה: כדאי לנהל משא ומתן עם ספק ציוד דנטלי לשנות מ-שוטף+60 ל-שוטף+90. זה יסגור פער תזרימי של ₪18,200. לחץ לניתוח מלא →"
- כל הודעה מקשרת לאפליקציה לפירוט מלא

### 3.3 Mobile-First PWA
- Progressive Web App (works on iPhone Safari, installable)
- Key screens:
  - **Dashboard**: Cash position, upcoming payments/receivables, alerts
  - **Cashflow forecast**: 30/60/90-day projection chart
  - **Chat**: Ask questions in Hebrew ("מה המצב עם התשלום של לקוח X?")
  - **Alerts feed**: History of all flags and recommendations
- Tech: React/Next.js or simple HTML+JS for prototype speed

### 3.4 Skills System (Extensible Capabilities)
User-facing "skills" the client can invoke — each skill is an agent-tool:
- **Chart skill**: "תראה לי גרף עמודות של ההוצאות החודש" → instant Hebrew-labeled chart
- **Report skill**: Generate weekly/monthly PDF summaries
- **Query skill**: Answer ad-hoc questions ("כמה שילמתי לספק X בחצי שנה האחרונה?")
- **Comparison skill**: Period-over-period analysis ("השווה הוצאות Q1 מול Q2")

The skills library grows without touching the core agent — each new skill is a standalone module.

### 3.5 Desktop
- Same PWA runs in browser on Mac — no separate app needed for prototype
- Later: consider Electron wrapper if offline access is needed

---

## Phase 4: Demo & Pilot Preparation (Weeks 9-12)

### 4.1 Demo Scenario
Build a compelling 10-minute demo using the synthetic dentist clinic:
1. Show the clinic's current "blind" state (scattered spreadsheets, bank app, paper invoices from dental suppliers)
2. Connect the AI system (simulated MCP connectors)
3. Watch it detect the cashflow problem (קופת חולים pays Net-90 vs dental supply vendor demands Net-60)
4. Show the WhatsApp alert (detailed, in Hebrew) → tap → mobile dashboard with full analysis and recommendation
5. Demo a skill: "תראה לי גרף עמודות של ההוצאות החודש" → instant Hebrew chart
6. Ask a question in Hebrew chat: "כמה הרווחתי החודש?" → get an instant, accurate answer

### 4.2 Pilot Client Onboarding Plan
- Start with read-only bank access (most Israeli banks support OFX export or screen scraping via services like Caspion)
- Import existing spreadsheets (manual upload initially)
- Connect Google Calendar for payment due dates
- Run in "shadow mode" for 2-4 weeks — generate insights but verify with the accountant before surfacing to owner

---

## Business Model Considerations

### Pricing (to be validated with pilot clients)
| Model | Pros | Cons |
|-------|------|------|
| **Monthly SaaS (₪200-500/mo)** | Predictable revenue, aligns with ongoing value | Harder sell for low-tech clients unfamiliar with SaaS |
| **One-time setup + monthly maintenance** | Feels familiar ("like paying the accountant") | Need to price correctly to cover LLM API costs |
| **Pay-per-insight** | Low barrier to entry, usage-based | Unpredictable revenue, hard to budget |

**Recommendation**: "Setup fee (₪1,500-3,000) + monthly service (₪200-400/mo)" — positions it like hiring a virtual bookkeeper, which these clients understand. The setup fee covers integration work and filters for serious clients.

### Competitive Landscape
- **Caspion**: Israeli open-banking aggregator (potential integration partner, not competitor)
- **Rivhit / Hashavshevet**: Established accounting software (you integrate with, not compete against)
- **Invoice4U, iCount, GreenInvoice**: Cloud invoicing (potential data sources)
- **International**: Vic.ai, Docyt, Zeni (AI accounting — but US-focused, different regulations)

### Legal & Compliance
- The product does NOT replace the רו"ח — this must be crystal clear in marketing and terms of service
- Data privacy: Financial data is sensitive. Need proper encryption, access controls, and compliance with Israeli Privacy Protection Law (חוק הגנת הפרטיות)
- Bank data access: Understand the legal framework for screen-scraping vs. open banking APIs in Israel

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Bank integration is technically difficult | High | Start with manual CSV/OFX upload; use Caspion as intermediary |
| LLM hallucination on financial data | Critical | All financial calculations are deterministic code; LLM only does NLU and narrative generation |
| Clients don't trust AI with their finances | High | Shadow mode, accountant-in-the-loop, gradual trust building |
| Part-time pace is too slow | Medium | Scope ruthlessly; prototype = cashflow agent only |
| API costs (Claude) eat margins | Medium | Cache common queries; use smaller models for routine tasks, Opus for complex reasoning |
| Regulatory changes | Low | Meital monitors; domain rules are modular and updatable |

---

## Verification Plan

- Run the synthetic data generator → inspect dentist clinic output for financial realism (Meital validates)
- Run the cashflow agent on synthetic data → verify it detects the Net-60/Net-90 conflict (dental supplier vs. kupat cholim)
- Test Hebrew NLU: ask questions in Hebrew, verify coherent Hebrew answers
- Test a skill: request a bar chart of expenses → verify Hebrew-labeled chart is generated
- Demo end-to-end: synthetic data → agent analysis → WhatsApp-formatted Hebrew output → mobile dashboard mockup

---

## Progress Tracker

### Phase 1: Foundation & Synthetic Data — ✅ COMPLETE
- [x] Repo created and pushed to GitHub (gruberaviv/ai-accounting)
- [x] Standard schema (Pydantic models) — transactions, invoices, payroll, VAT, vendors, customers
- [x] Synthetic dentist clinic generator — 12 months, ~3300 service events, 4 employees, kupot cholim
- [x] Cashflow engine — 90-day projection, alerts, payment term conflict detection
- [x] Profitability engine — per-treatment (activity-based costing), per-patient, cost breakdown
- [x] CLI demo with full Hebrew output

### Phase 2: Core Agentic Engine — ✅ CORE COMPLETE (connectors pending)
- [x] Claude Agent SDK with tool-use loop (11 tools)
- [x] Financial agent answering Hebrew questions
- [x] Chart skill (5 chart types, Hebrew-labeled, Plotly)
- [x] Per-treatment profitability with full cost allocation (materials, lab, labor, overhead)
- [x] Material shelf life tracking
- [ ] MCP connectors (bank, spreadsheet, calendar) — NOT STARTED
- [ ] Client YAML configuration system — SCAFFOLDED (example config exists)

### Phase 3: User Interface — ✅ MOSTLY COMPLETE
- [x] Interactive multi-page HTML report (6 pages)
- [x] Time period selector with presets and custom dates
- [x] JS-driven dynamic recomputation
- [x] Evidence panels behind AI insights
- [x] Treatment BOM selector with costs and expiry dates
- [x] Bank account page with balance, transactions, reconciliation (סגירה)
- [x] PWA with manifest + service worker + icons (installable on iPhone)
- [x] Mobile-responsive: bottom tab bar on small screens
- [x] Hebrew RTL throughout
- [ ] WhatsApp Business integration — NOT STARTED
- [ ] Chat interface ("ask a question") — NOT STARTED
- [ ] Additional skills (report, query, comparison) — NOT STARTED

### Phase 4: Demo & Pilot Preparation — 🟡 PARTIAL
- [x] Demo scenario works end-to-end (synthetic data → report → mobile PWA)
- [x] Meital reviewing and providing feedback (iterating on UI)
- [ ] Pilot client identified and onboarding planned — NOT STARTED
- [ ] Shadow mode implementation — NOT STARTED
- [ ] Bank API integration (Caspion / OFX) — NOT STARTED
