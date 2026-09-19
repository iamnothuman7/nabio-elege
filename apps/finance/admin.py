from django.contrib import admin

from .models import (
    BudgetLine,
    BudgetVersion,
    AccountingBatch,
    BankAccount,
    BankEntry,
    FilingRecord,
    FinancialReceipt,
    InKindContribution,
    Obligation,
    ObligationApproval,
    PaymentAllocation,
    PaymentRecord,
    ReconciliationLink,
)


admin.site.register(
    [
        BudgetVersion,
        BudgetLine,
        Obligation,
        ObligationApproval,
        PaymentRecord,
        PaymentAllocation,
        BankAccount,
        BankEntry,
        ReconciliationLink,
        FinancialReceipt,
        InKindContribution,
        AccountingBatch,
        FilingRecord,
    ]
)
