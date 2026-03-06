import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
    DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'

    DB_HOST = os.getenv('DATABASE_HOST', 'postgres')
    DB_PORT = os.getenv('DATABASE_PORT', '5432')
    DB_NAME = os.getenv('DATABASE_NAME', 'emby')
    DB_USER = os.getenv('DATABASE_USER', 'emby')
    DB_PASSWORD = os.getenv('DATABASE_PASSWORD', 'emby123')
    SQLALCHEMY_DATABASE_URI = (
        f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    EMBY_SERVER_URL = os.getenv('EMBY_SERVER_URL', 'http://localhost:8096')
    EMBY_API_KEY = os.getenv('EMBY_API_KEY', '')

    SYNC_INTERVAL_HOURS = int(os.getenv('SYNC_INTERVAL_HOURS', '6'))
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_DIR = os.getenv('LOG_DIR', '/app/logs')