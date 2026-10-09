"""Standard internal data model — all connectors map TO these schemas."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    PAYROLL = "payroll"
    VAT_PAYMENT = "vat_payment"
    TAX_PAYMENT = "tax_payment"


class PaymentTerms(str, Enum):
    IMMEDIATE = "מזומן"
    NET_30 = "שוטף+30"
    NET_60 = "שוטף+60"
    NET_90 = "שוטף+90"


class InvoiceStatus(str, Enum):
    DRAFT = "טיוטה"
    SENT = "נשלחה"
    PAID = "שולמה"
    OVERDUE = "באיחור"
    CANCELLED = "בוטלה"


class BankTransaction(BaseModel):
    """A single bank transaction."""
    id: str
    date: date
    amount: Decimal = Field(description="Positive=credit, Negative=debit")
    balance_after: Decimal
    description: str
    category: str
    transaction_type: TransactionType
    reference: Optional[str] = None
    counterparty: Optional[str] = None


class Invoice(BaseModel):
    """An invoice (חשבונית) or receipt (קבלה)."""
    id: str
    invoice_number: str
    date: date
    due_date: date
    amount: Decimal
    vat_amount: Decimal
    total: Decimal
    status: InvoiceStatus
    counterparty: str
    description: str
    payment_terms: PaymentTerms
    is_incoming: bool = Field(description="True=receivable, False=payable")


class Employee(BaseModel):
    """An employee on payroll."""
    id: str
    name: str
    role: str
    gross_salary: Decimal
    start_date: date
    bituach_leumi: Decimal = Field(description="ביטוח לאומי — employer portion")
    pension: Decimal = Field(description="פנסיה — employer portion")
    keren_hishtalmut: Decimal = Field(description="קרן השתלמות — employer portion")
    net_salary: Decimal = Field(description="Net pay after all deductions")


class Vendor(BaseModel):
    """A supplier/vendor."""
    id: str
    name: str
    category: str
    payment_terms: PaymentTerms
    contact: Optional[str] = None


class Customer(BaseModel):
    """A customer (B2B or institutional)."""
    id: str
    name: str
    customer_type: str  # e.g., "פרטי", "קופת חולים", "ביטוח"
    payment_terms: PaymentTerms
    contact: Optional[str] = None


class VATReport(BaseModel):
    """Bi-monthly VAT (מע"מ) report."""
    period_start: date
    period_end: date
    total_sales: Decimal
    total_purchases: Decimal
    output_vat: Decimal  # מע"מ עסקאות
    input_vat: Decimal   # מע"מ תשומות
    vat_payable: Decimal  # net VAT to pay


class BusinessSnapshot(BaseModel):
    """Complete financial state of a business at a point in time."""
    business_name: str
    business_type: str
    as_of: datetime
    bank_transactions: list[BankTransaction]
    invoices: list[Invoice]
    employees: list[Employee]
    vendors: list[Vendor]
    customers: list[Customer]
    vat_reports: list[VATReport]
    current_balance: Decimal
