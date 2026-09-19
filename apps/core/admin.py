from django.contrib import admin

from .models import (
    AuditEvent,
    Document,
    DocumentVersion,
    IdempotencyRecord,
    InboxEvent,
    OutboxEvent,
    RetentionPolicy,
)


admin.site.register(
    [
        RetentionPolicy,
        Document,
        DocumentVersion,
        AuditEvent,
        OutboxEvent,
        InboxEvent,
        IdempotencyRecord,
    ]
)
