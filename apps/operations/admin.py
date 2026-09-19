from django.contrib import admin

from .models import (
    Project,
    PurchaseItem,
    PurchaseOrder,
    PurchaseRequest,
    StockBalance,
    StockItem,
    StockMovement,
    Supplier,
    Task,
    TaskDependency,
    Warehouse,
)


admin.site.register(
    [
        Project,
        Task,
        TaskDependency,
        Supplier,
        PurchaseRequest,
        PurchaseItem,
        PurchaseOrder,
        Warehouse,
        StockItem,
        StockBalance,
        StockMovement,
    ]
)
