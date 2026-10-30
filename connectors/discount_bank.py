"""Connector: Discount Bank scraped JSON → standard BankTransaction schema.

Reads the output of israeli-bank-scrapers (scraped_raw.json) and converts
to our standard BankTransaction objects.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from schema.standard_schema import BankTransaction, TransactionType


def _classify_transaction(description: str, amount: Decimal) -> TransactionType:
    """Classify a bank transaction by its description."""
    desc = description.lower()
    if any(kw in desc for kw in ["משכורת", "שכר", "salary"]):
        return TransactionType.PAYROLL
    if any(kw in desc for kw in ["מע\"מ", "מס הכנסה", "ביטוח לאומי", "מס בפרעון"]):
        return TransactionType.TAX_PAYMENT
    if amount > 0:
        return TransactionType.INCOME
    return TransactionType.EXPENSE


def _extract_counterparty(description: str) -> Optional[str]:
    """Extract counterparty name from transaction description."""
    # Common patterns in Discount Bank descriptions
    for prefix in ["הו\"ק ל", "העברה ל", "העברה מ", "חיוב ל"]:
        if prefix in description:
            return description.split(prefix, 1)[1].split(" לסניף")[0].strip()
    return description.strip()


def load_discount_transactions(
    json_path: str | Path,
    account_number: str = "0174830426",
    last_n_months: int = 3,
) -> list[BankTransaction]:
    """Load transactions from a scraped_raw.json file.

    Args:
        json_path: Path to the scraped_raw.json file.
        account_number: Which account to extract (default: checking).
        last_n_months: Only include the most recent N months of data.

    Returns:
        List of BankTransaction objects sorted by date.
    """
    path = Path(json_path)
    with open(path) as f:
        raw = json.load(f)

    # Find the requested account
    accounts = raw.get("accounts", [])
    acct = None
    for a in accounts:
        if a.get("accountNumber") == account_number:
            acct = a
            break
    if acct is None:
        raise ValueError(f"Account {account_number} not found in {path}")

    raw_txns = acct.get("txns", [])

    # Parse and filter by date
    cutoff = None
    if last_n_months:
        from dateutil.relativedelta import relativedelta
        # Find the max date first
        max_date = max(
            datetime.fromisoformat(t["date"]).date()
            for t in raw_txns if t.get("date")
        )
        cutoff = max_date - relativedelta(months=last_n_months)

    transactions: list[BankTransaction] = []
    running_balance = Decimal("0")  # We don't have real balance; compute running

    # Sort by date
    raw_txns.sort(key=lambda t: t.get("date", ""))

    for i, txn in enumerate(raw_txns):
        date_str = txn.get("date", "")
        try:
            txn_date = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError):
            continue

        if cutoff and txn_date < cutoff:
            continue

        amount = Decimal(str(txn.get("chargedAmount", 0)))
        description = txn.get("description", "")
        running_balance += amount

        tx_type = _classify_transaction(description, amount)
        counterparty = _extract_counterparty(description)

        transactions.append(BankTransaction(
            id=f"disc-{account_number}-{i}",
            date=txn_date,
            amount=amount,
            balance_after=running_balance,
            description=description,
            category=tx_type.value,
            transaction_type=tx_type,
            counterparty=counterparty,
        ))

    return transactions
