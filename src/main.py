"""
Flask Application Entry Point
"""
import os
import logging
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from dotenv import load_dotenv

from src.database.db import db
from src.api.routes import api_bp
from src.emby.sync import EmbySyncService
from src.utils.logger import setup_logger

# Load environment variables
load_dotenv()

def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)
    
    # Configuration
    app.config['SQLALCHEMY_DATABASE_URI'] = (
        f"postgresql://{os.getenv('DATABASE_USER', 'emby_user')}:"
        f"{os.getenv('DATABASE_PASSWORD', 'your_db_password_here')}@"
        f"{os.getenv('DATABASE_HOST', 'localhost')}:"
        f"{os.getenv('DATABASE_PORT', '5432')}/"
        f"{os.getenv('DATABASE_NAME', 'emby_db')}"
    )
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    
    # Initialize extensions
    db.init_app(app)
    
    # Register blueprints
    app.register_blueprint(api_bp, url_prefix='/api')
    
    # Create tables
    with app.app_context():
        db.create_all()
    
    return app

def start_scheduler(app):
    """Start APScheduler for background tasks"""
    scheduler = BackgroundScheduler()
    
    def sync_emby_data():
        with app.app_context():
            try:
                sync_service = EmbySyncService()
                sync_service.sync_all_libraries()
                logging.info("Scheduled Emby sync completed successfully")
            except Exception as e:
                logging.error(f"Scheduled Emby sync failed: {e}")
    
    # Schedule sync every 6 hours
    scheduler.add_job(
        func=sync_emby_data,
        trigger=IntervalTrigger(hours=6),
        id='emby_sync_job',
        name='Sync Emby media data',
        replace_existing=True
    )
    
    scheduler.start()
    return scheduler

if __name__ == '__main__':
    # Setup logging
    setup_logger()
    
    # Create Flask app
    app = create_app()
    
    # Start scheduler
    scheduler = start_scheduler(app)
    
    try:
        # Run Flask app
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        scheduler.shutdown()