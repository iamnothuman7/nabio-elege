from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field


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


class PublicFormOut(Schema):
    title: str
    version_id: UUID
    form_schema: dict
    privacy_notice: str
    privacy_notice_version: int


class PublicSubmissionIn(Schema):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
    fields: dict = Field(default_factory=dict)


class PublicSubmissionOut(Schema):
    receipt_id: str
    status: str
    message: str
    receipt_token: str
    next_action: str


class ProblemOut(Schema):
    type: str
    title: str
    status: int
    code: str
    detail: str
    request_id: str | None = None
    field_errors: dict[str, list[str]] | None = None
