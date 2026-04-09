"""Schemas for delete preview, queue execution, and webhook confirmation APIs."""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analysis import AnalysisGroupItem, ComparisonMetadata


class DeletePreviewPayload(BaseModel):
    group_ids: list[str] = Field(default_factory=list)


class DeletePreviewGroup(BaseModel):
    group_id: str
    title: str
    media_kind: str
    comparison: ComparisonMetadata
    keep_item: AnalysisGroupItem | None = None
    delete_candidates: list[AnalysisGroupItem] = Field(default_factory=list)
    protected_items: list[AnalysisGroupItem] = Field(default_factory=list)


class DeletePreviewResponse(BaseModel):
    groups: list[DeletePreviewGroup] = Field(default_factory=list)
    delete_count: int
    protected_count: int


class DeleteExecutePayload(BaseModel):
    group_ids: list[str] = Field(default_factory=list)
    item_ids: list[int] = Field(default_factory=list)


class DeleteExecuteItemResult(BaseModel):
    group_id: str
    item_id: int
    emby_item_id: str
    media_source_id: str
    delete_target_item_id: str = ""
    action: str = ""
    id: int | None = None
    delete_status: str = "pending"
    status_reason: str = ""
    deleted_paths: list[str] = Field(default_factory=list)
    status: str
    status_code: int | None
    message: str


class DeleteExecuteResponse(BaseModel):
    success_count: int
    failed_count: int
    results: list[DeleteExecuteItemResult] = Field(default_factory=list)


class DeleteQueueEntry(BaseModel):
    id: int
    group_id: str
    item_id: int
    emby_item_id: str
    delete_target_item_id: str
    delete_status: str
    status_reason: str = ""
    retry_count: int = 0
    status_code: int | None = None
    message: str = ""
    deleted_paths: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class DeleteQueueStatusResponse(BaseModel):
    items: list[DeleteQueueEntry] = Field(default_factory=list)


class DeleteWebhookEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    delete_target_item_id: str = ""
    emby_item_id: str = ""
    deleted_paths: list[str] = Field(default_factory=list)
    item_id: str = Field(default="", alias="ItemId")
    user_id: str = Field(default="", alias="UserId")
    name: str = Field(default="", alias="Name")
    deleted_files: list[str] = Field(default_factory=list, alias="DeletedFiles")
    date_deleted: str = Field(default="", alias="DateDeleted")


class WebhookUser(BaseModel):
    name: str = Field(default="", alias="Name")
    id: str = Field(default="", alias="Id")


class WebhookServer(BaseModel):
    name: str = Field(default="", alias="Name")
    id: str = Field(default="", alias="Id")
    version: str = Field(default="", alias="Version")


class DeleteWebhookPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    delete_target_item_id: str = ""
    emby_item_id: str = ""
    deleted_paths: list[str] = Field(default_factory=list)
    events: list[DeleteWebhookEvent] = Field(default_factory=list)
    item_id: str = Field(default="", alias="ItemId")
    user_id: str = Field(default="", alias="UserId")
    name: str = Field(default="", alias="Name")
    deleted_files: list[str] = Field(default_factory=list, alias="DeletedFiles")
    date_deleted: str = Field(default="", alias="DateDeleted")
    title: str = Field(default="", alias="Title")
    description: str = Field(default="", alias="Description")
    date: str = Field(default="", alias="Date")
    event: str = Field(default="", alias="Event")
    severity: str = Field(default="", alias="Severity")
    user: WebhookUser = Field(default_factory=WebhookUser, alias="User")
    server: WebhookServer = Field(default_factory=WebhookServer, alias="Server")
    item: dict = Field(default_factory=dict, alias="Item")
    token: str = Field(default="", alias="Token")


class DeleteWebhookResponse(BaseModel):
    status: str
    matched: int
    updated: int
