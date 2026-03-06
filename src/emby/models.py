from dataclasses import dataclass
from typing import Optional


@dataclass
class MediaInfo:
    emby_id: str
    title: str
    media_type: str
    path: Optional[str] = None
    size: Optional[int] = None
    duration: Optional[int] = None
    year: Optional[int] = None
    library_id: Optional[str] = None
    library_name: Optional[str] = None

    @classmethod
    def from_emby_item(cls, item: dict, library_id: str = '', library_name: str = '') -> 'MediaInfo':
        ticks = item.get('RunTimeTicks')
        duration = int(ticks / 10_000_000) if ticks else None
        path = None
        media_sources = item.get('MediaSources', [])
        if media_sources:
            path = media_sources[0].get('Path')
        size = None
        if media_sources:
            sizes = [s.get('Size', 0) for s in media_sources if s.get('Size')]
            size = sum(sizes) if sizes else None
        return cls(
            emby_id=str(item.get('Id', '')),
            title=item.get('Name', 'Unknown'),
            media_type=item.get('Type', 'Unknown'),
            path=path,
            size=size,
            duration=duration,
            year=item.get('ProductionYear'),
            library_id=library_id,
            library_name=library_name,
        )
