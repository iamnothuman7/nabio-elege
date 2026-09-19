from datetime import datetime
from uuid import UUID

from ninja import Schema


class UserOut(Schema):
    id: int
    username: str
    email: str


class CampaignOut(Schema):
    id: UUID
    tenant_id: UUID
    code: str
    name: str
    phase: str
    timezone: str
    is_demo: bool
    row_version: int


class AuditEventOut(Schema):
    id: UUID
    action: str
    resource_type: str
    resource_id: str
    reason: str
    minimized_diff: dict
    occurred_at: datetime


class PublishFormIn(Schema):
    expected_row_version: int


class MessageOut(Schema):
    message: str


class ProblemOut(Schema):
    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: str | None = None
    field_errors: dict[str, list[str]] | None = None
