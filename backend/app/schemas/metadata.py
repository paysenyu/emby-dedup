"""Schemas for metadata issue APIs."""

from pydantic import BaseModel, Field


class MetadataIssueItem(BaseModel):
    title: str
    emby_item_id: str
    media_source_id: str
    tmdb_id: str
    imdb_id: str
    path: str
    issue_type: str


class MetadataIssuesResponse(BaseModel):
    items: list[MetadataIssueItem] = Field(default_factory=list)
    total: int
