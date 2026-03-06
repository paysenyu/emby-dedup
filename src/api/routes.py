import os
import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from sqlalchemy import func
from src.database.db import db, Media, SyncLog
from src.emby.client import EmbyClient
from src.emby.sync import EmbySyncService

api_bp = Blueprint('api', __name__)
logger = logging.getLogger(__name__)

def get_emby_client():
    return EmbyClient(
        os.getenv('EMBY_SERVER_URL', 'http://localhost:8096'),
        os.getenv('EMBY_API_KEY', '')
    )

@api_bp.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': '1.0.0',
                    'timestamp': datetime.now(timezone.utc).isoformat()})

@api_bp.route('/emby/test-connection')
def test_connection():
    try:
        client = get_emby_client()
        ok = client.test_connection()
        return jsonify({'connected': ok, 'server_url': os.getenv('EMBY_SERVER_URL', '')})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/emby/libraries')
def get_libraries():
    try:
        libs = get_emby_client().get_libraries()
        return jsonify({'libraries': libs, 'count': len(libs)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/emby/sync', methods=['POST'])
def trigger_sync():
    try:
        EmbySyncService().sync_all_libraries()
        return jsonify({'message': 'Sync completed successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/media')
def get_media():
    try:
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)
        media_type = request.args.get('type')
        query = Media.query
        if media_type:
            query = query.filter_by(media_type=media_type)
        p = query.order_by(Media.title).paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            'items': [{'id': m.id, 'emby_id': m.emby_id, 'title': m.title,
                       'media_type': m.media_type, 'year': m.year, 'path': m.path,
                       'size': m.size, 'duration': m.duration,
                       'created_at': m.created_at.isoformat() if m.created_at else None}
                      for m in p.items],
            'total': p.total, 'page': page, 'per_page': per_page, 'pages': p.pages
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/media/<emby_id>')
def get_media_item(emby_id):
    try:
        m = Media.query.filter_by(emby_id=emby_id).first()
        if not m:
            return jsonify({'error': 'Not found'}), 404
        return jsonify({'id': m.id, 'emby_id': m.emby_id, 'title': m.title,
                        'media_type': m.media_type, 'year': m.year, 'path': m.path,
                        'size': m.size, 'duration': m.duration,
                        'created_at': m.created_at.isoformat() if m.created_at else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/sync/logs')
def get_sync_logs():
    try:
        logs = SyncLog.query.order_by(SyncLog.sync_time.desc()).limit(50).all()
        return jsonify({'logs': [{'id': l.id,
            'sync_time': l.sync_time.isoformat() if l.sync_time else None,
            'status': l.status, 'items_synced': l.items_synced,
            'error_message': l.error_message} for l in logs]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/emby/sync/incremental', methods=['POST'])
def trigger_incremental_sync():
    try:
        count = EmbySyncService().sync_incremental()
        return jsonify({'message': 'Incremental sync completed successfully', 'items_synced': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/stats/overview')
def stats_overview():
    try:
        total_items = db.session.query(func.count(Media.id)).scalar() or 0
        total_size_bytes = db.session.query(func.sum(Media.size)).scalar() or 0
        total_duration_seconds = db.session.query(func.sum(Media.duration)).scalar() or 0

        # 媒体类型分布（过滤 BoxSet）
        SKIP_TYPES = {'BoxSet'}
        by_type_rows = (
            db.session.query(
                Media.media_type,
                func.count(Media.id).label('count'),
                func.sum(Media.size).label('size'),
            )
            .group_by(Media.media_type)
            .all()
        )
        by_type = {}
        for row in by_type_rows:
            t = row.media_type or 'Unknown'
            if t in SKIP_TYPES:
                continue
            by_type[t] = {
                'count': row.count,
                'size_gb': round((row.size or 0) / (1024 ** 3), 2),
            }

        last_log = (
            SyncLog.query
            .filter(SyncLog.status.in_(['success', 'partial']))
            .order_by(SyncLog.sync_time.desc())
            .first()
        )
        last_sync = last_log.sync_time.isoformat() if last_log and last_log.sync_time else None

        return jsonify({
            'total_items': total_items,
            'total_size_bytes': total_size_bytes,
            'total_size_gb': round(total_size_bytes / (1024 ** 3), 2),
            'total_duration_hours': round(total_duration_seconds / 3600, 2),
            'by_type': by_type,
            'last_sync': last_sync,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/stats/libraries')
def stats_libraries():
    """
    直接从 Emby API 获取媒体库列表（/Users/{id}/Views），
    每个库的 ChildCount / ItemCount 就是库内顶层条目数。
    存储大小从 DB 按 lib_name 字段聚合。
    """
    try:
        client = get_emby_client()
        emby_libs = client.get_libraries()  # [{Id, Name, ChildCount, ...}, ...]

        # DB 按库名聚合存储大小（lib_name 列存的就是 Emby 库名）
        size_rows = (
            db.session.query(
                Media.lib_name,
                func.sum(Media.size).label('size'),
                func.count(Media.id).label('count'),
            )
            .filter(Media.lib_name.isnot(None))
            .group_by(Media.lib_name)
            .all()
        )
        size_map = {r.lib_name: {'size': r.size or 0, 'count': r.count} for r in size_rows}

        libraries = []
        for lib in emby_libs:
            name = lib.get('Name', '')
            # Emby Views API 返回的子项数量字段
            item_count = (
                lib.get('ChildCount') or
                lib.get('ItemCount') or
                size_map.get(name, {}).get('count', 0)
            )
            size_bytes = size_map.get(name, {}).get('size', 0)
            libraries.append({
                'name': name,
                'count': item_count,
                'size_gb': round(size_bytes / (1024 ** 3), 2),
                'collection_type': lib.get('CollectionType', ''),
            })

        libraries.sort(key=lambda x: x['count'], reverse=True)
        return jsonify({'libraries': libraries, 'total': len(libraries)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@api_bp.route('/stats/years')
def stats_years():
    try:
        rows = (
            db.session.query(
                Media.year,
                func.count(Media.id).label('count'),
            )
            .filter(Media.year.isnot(None))
            .group_by(Media.year)
            .order_by(Media.year.desc())
            .all()
        )
        return jsonify({'years': [{'year': r.year, 'count': r.count} for r in rows]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
