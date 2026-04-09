"""Metadata issues API router."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import MediaItem
from app.schemas.metadata import MetadataIssueItem, MetadataIssuesResponse

router = APIRouter(tags=["metadata"])


def _norm(value: object) -> str:
    return str(value or "").strip()


@router.get("/metadata/issues", response_model=MetadataIssuesResponse)
def get_metadata_issues(db: Session = Depends(get_db)) -> MetadataIssuesResponse:
    """List media items with missing or invalid TMDb metadata."""
    rows = db.query(MediaItem).order_by(MediaItem.id.asc()).all()

    issues: list[MetadataIssueItem] = []
    for row in rows:
        tmdb_id = _norm(row.tmdb_id)
        if tmdb_id == "0":
            issue_type = "invalid_tmdb"
        elif not tmdb_id:
            issue_type = "missing_tmdb"
        else:
            continue

        issues.append(
            MetadataIssueItem(
                title=row.title or row.series_title or "",
                emby_item_id=row.emby_item_id,
                media_source_id=row.media_source_id or "",
                tmdb_id=tmdb_id,
                imdb_id=row.imdb_id or "",
                path=row.path or "",
                issue_type=issue_type,
            )
        )

    return MetadataIssuesResponse(items=issues, total=len(issues))
