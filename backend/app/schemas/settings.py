"""Pydantic schemas for settings APIs."""

from pydantic import BaseModel, Field


class EmbySettings(BaseModel):
    base_url: str = ""
    api_key: str = ""
    user_id: str = ""


class ShenyiSettings(BaseModel):
    base_url: str = ""
    api_key: str = ""


class SyncSettings(BaseModel):
    concurrency: int = Field(default=1, ge=1)


class SettingsPayload(BaseModel):
    emby: EmbySettings = Field(default_factory=EmbySettings)
    libraries: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    shenyi: ShenyiSettings = Field(default_factory=ShenyiSettings)
    webhook_token: str = ""


class SettingsResponse(SettingsPayload):
    pass
