"""CaseSnapshot input schema, vendored from ai-case-service.

Mirrors the wire format of ai_case_service.shared.schema so JSON sent by
existing callers validates here without modification. Camel/snake aliases
match the original via ALIAS_GENERATOR_CONFIG.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    AliasGenerator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
)
from pydantic.alias_generators import to_camel


def _validation_aliases(snake: str) -> AliasChoices:
    return AliasChoices(snake, to_camel(snake))


ALIAS_GENERATOR_CONFIG = ConfigDict(
    alias_generator=AliasGenerator(
        validation_alias=_validation_aliases,
        serialization_alias=to_camel,
    )
)


LenientStr = Annotated[str, BeforeValidator(lambda x: str(x) if x is not None else None)]


class SystemType(StrEnum):
    RAW_DYNAMICS_INCIDENT = "raw_dynamics_incident"
    DWELLANT_TASK = "dwellant_task"
    CASE_SNAPSHOT = "case_snapshot"
    RAW_EMAIL = "raw_email"


class SystemFields(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    id: str | None = None
    domain: str
    type: SystemType
    external_id: LenientStr | None = None
    collection: str | None = None
    source_system: str
    parent: LenientStr | None = None


class SourceSystem(StrEnum):
    DYNAMICS = "dynamics"
    DWELLANT = "dwellant"
    EMAIL = "email"
    OTHER = "other"


class PermissionGroup(StrEnum):
    FINANCIAL = "FINANCIAL"


class RelationshipState(StrEnum):
    ACTIVE = "Active"
    INACTIVE = "Inactive"


class CaseSnapshotAttachment(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    source_filename: str | None = None
    filename: str
    storage_type: str
    size: int
    internal_blob_url: HttpUrl | None = Field(default=None)
    type: str


class ActivityType(StrEnum):
    USER_MESSAGE = "USER_MESSAGE"
    SYSTEM_MESSAGE = "SYSTEM_MESSAGE"
    SYSTEM_EVENT = "SYSTEM_EVENT"
    INTERNAL_MESSAGE = "INTERNAL_MESSAGE"
    PROPERTY_MANAGER_MESSAGE = "PROPERTY_MANAGER_MESSAGE"
    PHONE_CALL = "PHONE_CALL"
    OTHER = "OTHER"


class MessageDirection(StrEnum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"


class ActivitySender(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    id: str | None = None
    name: str | None = None
    email: str | None = None
    organization_id: str | None = None
    organization_name: str | None = None
    sender_recognized: bool | None = None


class ActivityMetadata(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    external_id: str
    created_at: int
    updated_at: int | None = None
    sender: ActivitySender | None = None
    recipients: list[str] | None = None
    direction: MessageDirection | None = None
    status: str | None = None

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _coerce_timestamp(cls, v: Any) -> int | None:
        if v is None or isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
        return v


class Activity(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    type: ActivityType
    sub_type: str | None = None
    subject: str | None = None
    content: str | dict[str, Any] | None = None
    metadata: ActivityMetadata
    reused_from_case_snapshot_id: str | None = None
    attachments: list[CaseSnapshotAttachment] = []


class CaseEvent(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    timestamp: int
    actor: str | None = None
    field: str
    old_value: str | None = None
    new_value: str | None = None


class PropertyDevelopment(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    external_id: str | None = None
    name: str | None = None


class PropmanCode(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    id: str | None = None
    code: str | None = None
    client_code: str | None = None
    property_code: str | None = None
    estate_code: str | None = None
    unit_code: str | None = None
    lease_code: str | None = None
    tenant_code: str | None = None
    billing_type: str | None = None
    state: str | None = None
    state_reason: str | None = None

    @field_validator("state", "state_reason", mode="before")
    @classmethod
    def coerce_int_to_str(cls, v: object) -> object:
        return str(v) if isinstance(v, int) else v


class Premises(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    id: str | None = None
    name: str | None = None
    premises_type: str | None = None
    address: str | None = None
    city: str | None = None
    county: str | None = None
    postcode: str | None = None
    country: str | None = None
    state: str | None = None
    state_reason: str | None = None
    in_breach: bool = False
    propman_codes: list[PropmanCode] = []

    @field_validator("premises_type", "state", "state_reason", mode="before")
    @classmethod
    def coerce_int_to_str(cls, v: object) -> object:
        return str(v) if isinstance(v, int) else v


class ContactRelationship(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    id: str | None = None
    name: str | None = None
    description: str | None = None
    state: RelationshipState | None = None
    state_reason: str | None = None
    premises: Premises | None = None
    property_development: PropertyDevelopment | None = None
    relationship: str | None = None
    relationship_type: str | None = None
    permission_groups: list[PermissionGroup] = []

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v: object) -> object:
        if isinstance(v, int):
            v = str(v)
        if isinstance(v, str):
            normalized_state = v.strip()
            if not normalized_state:
                return None
            return normalized_state.capitalize()
        return v

    @field_validator("state_reason", mode="before")
    @classmethod
    def coerce_state_reason_int_to_str(cls, v: object) -> object:
        return str(v) if isinstance(v, int) else v


class Contact(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    external_id: str | None = None
    email_address: str | None = None
    email_address2: str | None = None
    email_address3: str | None = None
    full_name: str | None = None
    phone_number: str | None = None
    contact_relationships: list[ContactRelationship] = []


class CaseSourceEnum(BaseModel):
    label: str | int
    enum: int


class CaseSourceEmail(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    email_address: str
    inbox: str


type CaseSource = CaseSourceEnum | CaseSourceEmail


class CaseMetadata(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    external_parent_id: LenientStr | None = None
    title: str | None = None
    description: str | None = None
    ticket_number: str | None = None
    assigned_to: str | None = None
    contact: Contact | None = None
    related_contact_relationship: ContactRelationship | None = None
    property_development: PropertyDevelopment | None = None
    external_source: CaseSource | None = None


class CaseSnapshotMetadata(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    case_created_at: int | None = None
    case_updated_at: int | None = None
    last_activity_created_at: int | None = None


class CaseClassifications(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    sentiment: str | None = None
    case: dict[str, dict[str, str]] | None = None
    case_faqs: dict[str, bool] | None = None
    primary_case_label: str | None = None


class CaseSnapshotState(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    rerun_agent_processing: bool | None = None
    agent_processed_at: int | None = None
    agent_eligible: bool | None = None
    dedupe: bool | None = Field(exclude=True, default=None)


class CaseSnapshot(BaseModel):
    model_config = ALIAS_GENERATOR_CONFIG

    system: SystemFields
    activities: list[Activity] = []
    events: list[CaseEvent] = []
    metadata: CaseSnapshotMetadata
    post_activities: list[Activity] = []
    case_summary: str | None = None
    classifications: CaseClassifications | None = None

    case_metadata: CaseMetadata
    raw_document_ids: list[str] | None = None
    attachments: list[CaseSnapshotAttachment] = []
    state: CaseSnapshotState | None = None

    @field_validator("activities", mode="after")
    @classmethod
    def sort_activities_chronologically(cls, v: list[Activity]) -> list[Activity]:
        return sorted(
            v,
            key=lambda a: (
                a.metadata.created_at,
                a.metadata.updated_at if a.metadata.updated_at is not None else a.metadata.created_at,
            ),
        )
