from django.contrib import admin

from .models import (
    BudgetLine,
    BudgetVersion,
    Obligation,
    ObligationApproval,
    PaymentAllocation,
    PaymentRecord,
)


admin.site.register(
    [
        BudgetVersion,
        BudgetLine,
        Obligation,
        ObligationApproval,
        PaymentRecord,
        PaymentAllocation,
    ]
)
