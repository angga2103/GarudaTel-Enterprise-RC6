"""
WhatsApp Adapter - Driver layer untuk WhatsApp communication

Architecture: Adapter Pattern
- Decoupled dari Notification Engine
- Support multiple backend (Evolution API, Baileys, dll)
- Easy to switch backend tanpa ubah Notification Engine

Backend saat ini: Evolution API (REST)
Alternative: Baileys native, whatsapp-web.js, dll
"""

import requests
import json
from typing import Dict, List, Optional, Any
from datetime import datetime


class WhatsAppAdapter:
    """
    WhatsApp Adapter menggunakan Evolution API.
    
    Evolution API adalah REST API wrapper untuk Baileys.
    Menyediakan session management, pairing code, auto-reconnect.
    
    Jika suatu hari perlu ganti backend, tinggal implement
    adapter baru dengan interface yang sama.
    """
    
    def __init__(self, api_url: str = "http://localhost:8080", api_key: str = ""):
        """
        Initialize WhatsApp Adapter.
        
        Args:
            api_url: Evolution API base URL
            api_key: API Key untuk authentication
        """
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.instance_name = "garudatel"  # Default instance
        self.headers = {
            "Content-Type": "application/json",
            "apikey": api_key
        }
    
    def is_configured(self) -> bool:
        """Check if WhatsApp adapter is configured."""
        return bool(self.api_url and self.api_key)
    
    def get_connection_status(self, instance: str = None) -> Dict[str, Any]:
        """
        Get connection status dari instance.
        
        Returns:
            Dict with:
            - connected: bool
            - phone_number: str
            - device_name: str
            - platform: str
            - session_status: str
            - error: str (if any)
        """
        if not self.is_configured():
            return {
                "connected": False,
                "error": "WhatsApp not configured"
            }
        
        instance = instance or self.instance_name
        
        try:
            response = requests.get(
                f"{self.api_url}/instance/connectionState/{instance}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                return {
                    "connected": data.get("state") == "open",
                    "phone_number": data.get("instance", {}).get("phoneNumber", ""),
                    "device_name": data.get("instance", {}).get("deviceName", ""),
                    "platform": data.get("instance", {}).get("platform", ""),
                    "session_status": data.get("state", "unknown"),
                    "error": None
                }
            else:
                return {
                    "connected": False,
                    "error": f"API Error: {response.status_code}"
                }
                
        except Exception as e:
            return {
                "connected": False,
                "error": str(e)
            }
    
    def generate_pairing_code(self, phone_number: str, instance: str = None) -> Dict[str, Any]:
        """
        Generate pairing code untuk connect WhatsApp.
        
        Args:
            phone_number: Nomor WA (format: 6281234567890)
            instance: Instance name (optional)
            
        Returns:
            Dict with:
            - success: bool
            - code: str (pairing code)
            - expires_in: int (seconds)
            - error: str (if any)
        """
        if not self.is_configured():
            return {"success": False, "error": "WhatsApp not configured"}
        
        instance = instance or self.instance_name
        
        try:
            # Create instance if not exists
            payload = {
                "instanceName": instance,
                "qrcode": False,  # Pairing code mode
                "number": phone_number
            }
            
            response = requests.post(
                f"{self.api_url}/instance/create",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 201 or response.status_code == 200:
                data = response.json()
                
                # Get pairing code
                code_response = requests.get(
                    f"{self.api_url}/instance/pairingCode/{instance}",
                    headers=self.headers,
                    timeout=10
                )
                
                if code_response.status_code == 200:
                    code_data = code_response.json()
                    
                    return {
                        "success": True,
                        "code": code_data.get("code", ""),
                        "expires_in": 60,  # Evolution API default 60 seconds
                        "error": None
                    }
            
            return {
                "success": False,
                "error": f"Failed to generate code: {response.status_code}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_message(self, phone_number: str, message: str, instance: str = None) -> Dict[str, Any]:
        """
        Send text message via WhatsApp.
        
        Args:
            phone_number: Recipient WA number (format: 6281234567890)
            message: Text message
            instance: Instance name (optional)
            
        Returns:
            Dict with:
            - success: bool
            - message_id: str
            - error: str (if any)
        """
        if not self.is_configured():
            return {"success": False, "error": "WhatsApp not configured"}
        
        instance = instance or self.instance_name
        
        try:
            payload = {
                "number": phone_number,
                "text": message
            }
            
            response = requests.post(
                f"{self.api_url}/message/sendText/{instance}",
                headers=self.headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200 or response.status_code == 201:
                data = response.json()
                
                return {
                    "success": True,
                    "message_id": data.get("key", {}).get("id", ""),
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to send: {response.status_code}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def send_broadcast(self, phone_numbers: List[str], message: str, instance: str = None) -> Dict[str, Any]:
        """
        Send broadcast message ke multiple numbers.
        
        Args:
            phone_numbers: List of recipient WA numbers
            message: Text message
            instance: Instance name (optional)
            
        Returns:
            Dict with:
            - success_count: int
            - failed_count: int
            - results: list of individual results
        """
        if not self.is_configured():
            return {"success_count": 0, "failed_count": len(phone_numbers)}
        
        success_count = 0
        failed_count = 0
        results = []
        
        for number in phone_numbers:
            result = self.send_message(number, message, instance)
            if result.get("success"):
                success_count += 1
            else:
                failed_count += 1
            
            results.append({
                "number": number,
                "success": result.get("success"),
                "error": result.get("error")
            })
        
        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "results": results
        }
    
    def disconnect(self, instance: str = None) -> Dict[str, Any]:
        """
        Disconnect WhatsApp session.
        
        Args:
            instance: Instance name (optional)
            
        Returns:
            Dict with success status
        """
        if not self.is_configured():
            return {"success": False, "error": "WhatsApp not configured"}
        
        instance = instance or self.instance_name
        
        try:
            response = requests.delete(
                f"{self.api_url}/instance/logout/{instance}",
                headers=self.headers,
                timeout=10
            )
            
            return {
                "success": response.status_code == 200,
                "error": None if response.status_code == 200 else f"Error: {response.status_code}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def restart_session(self, instance: str = None) -> Dict[str, Any]:
        """
        Restart WhatsApp session.
        
        Args:
            instance: Instance name (optional)
            
        Returns:
            Dict with success status
        """
        if not self.is_configured():
            return {"success": False, "error": "WhatsApp not configured"}
        
        instance = instance or self.instance_name
        
        try:
            response = requests.put(
                f"{self.api_url}/instance/restart/{instance}",
                headers=self.headers,
                timeout=10
            )
            
            return {
                "success": response.status_code == 200,
                "error": None if response.status_code == 200 else f"Error: {response.status_code}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def delete_session(self, instance: str = None) -> Dict[str, Any]:
        """
        Delete WhatsApp session completely.
        
        Args:
            instance: Instance name (optional)
            
        Returns:
            Dict with success status
        """
        if not self.is_configured():
            return {"success": False, "error": "WhatsApp not configured"}
        
        instance = instance or self.instance_name
        
        try:
            response = requests.delete(
                f"{self.api_url}/instance/delete/{instance}",
                headers=self.headers,
                timeout=10
            )
            
            return {
                "success": response.status_code == 200,
                "error": None if response.status_code == 200 else f"Error: {response.status_code}"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }


# Global instance
_whatsapp_adapter = None

def get_whatsapp_adapter(api_url: str = None, api_key: str = None) -> WhatsAppAdapter:
    """
    Get global WhatsAppAdapter instance.
    
    If api_url and api_key provided, will create new instance.
    Otherwise returns cached instance.
    """
    global _whatsapp_adapter
    
    if api_url and api_key:
        _whatsapp_adapter = WhatsAppAdapter(api_url, api_key)
    
    if _whatsapp_adapter is None:
        # Load from ConfigManager
        try:
            from config_manager import get_config_manager
            cm = get_config_manager()
            
            provider = cm.get_provider("whatsapp")
            if provider and provider["is_configured"]:
                config = provider["config"]
                api_url = config.get("WHATSAPP_API_URL", "http://localhost:8080")
                api_key = config.get("WHATSAPP_API_KEY", "")
                _whatsapp_adapter = WhatsAppAdapter(api_url, api_key)
            else:
                # Return unconfigured instance
                _whatsapp_adapter = WhatsAppAdapter()
        except Exception:
            _whatsapp_adapter = WhatsAppAdapter()
    
    return _whatsapp_adapter
