"""Schemas for library discovery API."""

from pydantic import BaseModel, Field


class LibraryItem(BaseModel):
    id: str
    name: str
    collection_type: str = ""


class LibrariesResponse(BaseModel):
    items: list[LibraryItem] = Field(default_factory=list)
