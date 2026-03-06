"""
Emby API Client Module
Handles all communication with Emby Server
"""

import requests
import logging
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


class EmbyClient:
    """Client for interacting with Emby Server API"""
    
    def __init__(self, server_url: str, api_key: str):
        """
        Initialize Emby Client
        
        Args:
            server_url: URL of Emby server
            api_key: API key for authentication
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
    
    def test_connection(self) -> bool:
        """
        Test connection to Emby server
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            url = f"{self.server_url}/System/Info"
            headers = self._get_headers()
            response = self.session.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info("Successfully connected to Emby server")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Emby server: {e}")
            return False
    
    def get_libraries(self) -> List[Dict[str, Any]]:
        """
        Get list of media libraries from Emby server
        
        Returns:
            List of library dictionaries
        """
        try:
            url = f"{self.server_url}/Library/VirtualFolders"
            headers = self._get_headers()
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            logger.info("Retrieved libraries from Emby server")
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get libraries: {e}")
            return []
    
    def get_items(self, library_id: str, limit: int = 500, start_index: int = 0) -> Dict[str, Any]:
        """
        Get items from a specific library
        
        Args:
            library_id: ID of the library
            limit: Maximum number of items to return
            start_index: Starting index for pagination
            
        Returns:
            Dictionary containing items and metadata
        """
        try:
            url = (f"{self.server_url}/Users/Default/Items?"
                   f"ParentId={library_id}&Limit={limit}&StartIndex={start_index}")
            headers = self._get_headers()
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get items from library {library_id}: {e}")
            return {}
    
    def get_item_details(self, item_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific item
        
        Args:
            item_id: ID of the item
            
        Returns:
            Item details dictionary or None if failed
        """
        try:
            url = f"{self.server_url}/Users/Default/Items/{item_id}"
            headers = self._get_headers()
            response = self.session.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Failed to get item details for {item_id}: {e}")
            return None
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Get request headers with authentication
        
        Returns:
            Dictionary of headers
        """
        return {
            'X-MediaBrowser-Token': self.api_key,
            'User-Agent': 'Emby-Media-Manager/1.0'
        }