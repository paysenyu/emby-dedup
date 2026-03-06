import logging
from datetime import datetime, timezone

from src.emby.client import EmbyClient
from src.emby.models import MediaInfo
from src.database.db import db, Media, SyncLog

logger = logging.getLogger(__name__)


class EmbySyncService:
    def __init__(self, app=None):
        self.app = app

    def _get_client(self) -> EmbyClient:
        import os
        url = os.getenv('EMBY_SERVER_URL', 'http://localhost:8096')
        key = os.getenv('EMBY_API_KEY', '')
        return EmbyClient(url, key)

    def sync_all_libraries(self):
        client = self._get_client()
        libraries = client.get_libraries()
        if not libraries:
            logger.warning("No libraries found or connection failed")
            self._write_sync_log('error', 0, 'No libraries found')
            return
        total = 0
        try:
            for lib in libraries:
                count = self._sync_library(client, lib)
                total += count
            db.session.commit()
            self._write_sync_log('success', total)
            logger.info(f"Sync complete: {total} items synced")
        except Exception as e:
            db.session.rollback()
            self._write_sync_log('error', total, str(e))
            logger.error(f"Sync failed: {e}")
            raise

    def _sync_library(self, client: EmbyClient, library: dict) -> int:
        lib_id = library.get('ItemId', library.get('Id', ''))
        lib_name = library.get('Name', '')
        logger.info(f"Syncing library: {lib_name} ({lib_id})")
        count = 0
        start = 0
        limit = 500
        while True:
            result = client.get_items(lib_id, limit=limit, start_index=start)
            items = result.get('Items', [])
            if not items:
                break
            for item in items:
                try:
                    info = MediaInfo.from_emby_item(item, lib_id, lib_name)
                    self._upsert_media(info)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to sync item {item.get('Id')}: {e}")
            total_count = result.get('TotalRecordCount', 0)
            start += limit
            if start >= total_count:
                break
        logger.info(f"Library '{lib_name}': {count} items synced")
        return count

    def _upsert_media(self, info: MediaInfo):
        existing = Media.query.filter_by(emby_id=info.emby_id).first()
        if existing:
            existing.title = info.title
            existing.media_type = info.media_type
            existing.path = info.path
            existing.size = info.size
            existing.duration = info.duration
            existing.year = info.year
            existing.updated_at = datetime.now(timezone.utc)
        else:
            media = Media(
                emby_id=info.emby_id,
                title=info.title,
                media_type=info.media_type,
                path=info.path,
                size=info.size,
                duration=info.duration,
                year=info.year,
            )
            db.session.add(media)

    def _write_sync_log(self, status: str, items_synced: int, error_message: str = None):
        try:
            log = SyncLog(status=status, items_synced=items_synced, error_message=error_message)
            db.session.add(log)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to write sync log: {e}")
