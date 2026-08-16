"""
Notification Engine - Enterprise Notification Center

Modular notification engine untuk GarudaTel Enterprise.
Mendukung multiple channels: Firebase, WhatsApp, Telegram, Email, dll.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any
from models import get_conn


class NotificationEngine:
    """Enterprise Notification Engine dengan multi-channel support."""
    
    def __init__(self):
        """Initialize Notification Engine."""
        self.channels = self._load_channels()
    
    def _load_channels(self) -> Dict[str, Dict]:
        """Load channel configuration dari database."""
        conn = get_conn()
        try:
            cursor = conn.execute("""
                SELECT channel_name, channel_type, is_active, configuration, last_status
                FROM notification_channels
            """)
            
            channels = {}
            for row in cursor.fetchall():
                channels[row['channel_name']] = {
                    'type': row['channel_type'],
                    'active': bool(row['is_active']),
                    'config': row['configuration'],
                    'status': row['last_status']
                }
            
            return channels
        except Exception as e:
            print(f"Error loading channels: {e}")
            return {}
        finally:
            conn.close()
    
    def get_available_channels(self) -> List[str]:
        """Get list of available (active) channels."""
        return [name for name, info in self.channels.items() if info['active']]
    
    def get_all_channels(self) -> Dict[str, Dict]:
        """Get all channels with their info."""
        return self.channels
    
    def create_broadcast(self, title: str, message: str, target_type: str, 
                        channels: List[str], created_by: int, 
                        image_url: Optional[str] = None) -> Optional[int]:
        """
        Create new broadcast entry.
        
        Args:
            title: Broadcast title
            message: Broadcast message
            target_type: Target audience (all, reseller, member, kasir, admin)
            channels: List of channels to use
            created_by: User ID who created the broadcast
            image_url: Optional image URL
            
        Returns:
            Broadcast ID if success, None if failed
        """
        conn = get_conn()
        try:
            # Calculate target count
            target_count = self._count_targets(target_type)
            
            # Create broadcast entry
            cursor = conn.execute("""
                INSERT INTO notification_broadcasts 
                (title, message, image_url, target_type, channels, total_target, 
                 status, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                title, message, image_url, target_type, 
                ','.join(channels), target_count, created_by,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))
            
            broadcast_id = cursor.lastrowid
            conn.commit()
            
            return broadcast_id
            
        except Exception as e:
            print(f"Error creating broadcast: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()
    
    def _count_targets(self, target_type: str) -> int:
        """Count target users based on type."""
        conn = get_conn()
        try:
            if target_type == 'all':
                cursor = conn.execute("SELECT COUNT(*) FROM users")
            elif target_type == 'reseller':
                cursor = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'reseller'")
            elif target_type == 'member':
                cursor = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'user'")
            elif target_type == 'kasir':
                cursor = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'kasir'")
            elif target_type == 'admin':
                cursor = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
            else:
                return 0
            
            result = cursor.fetchone()
            return result[0] if result else 0
            
        except Exception as e:
            print(f"Error counting targets: {e}")
            return 0
        finally:
            conn.close()
    
    def add_to_queue(self, broadcast_id: int, target_type: str, channels: List[str]):
        """
        Add broadcast targets to queue.
        
        Args:
            broadcast_id: Broadcast ID
            target_type: Target audience type
            channels: List of channels
        """
        conn = get_conn()
        try:
            # Get target users
            users = self._get_target_users(target_type)
            
            # Add to queue for each channel
            for user_id in users:
                for channel in channels:
                    conn.execute("""
                        INSERT INTO notification_queue 
                        (broadcast_id, user_id, channel, status, created_at)
                        VALUES (?, ?, ?, 'pending', ?)
                    """, (
                        broadcast_id, user_id, channel,
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ))
            
            conn.commit()
            
        except Exception as e:
            print(f"Error adding to queue: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def _get_target_users(self, target_type: str) -> List[int]:
        """Get list of target user IDs."""
        conn = get_conn()
        try:
            if target_type == 'all':
                cursor = conn.execute("SELECT id FROM users")
            elif target_type == 'reseller':
                cursor = conn.execute("SELECT id FROM users WHERE role = 'reseller'")
            elif target_type == 'member':
                cursor = conn.execute("SELECT id FROM users WHERE role = 'user'")
            elif target_type == 'kasir':
                cursor = conn.execute("SELECT id FROM users WHERE role = 'kasir'")
            elif target_type == 'admin':
                cursor = conn.execute("SELECT id FROM users WHERE role = 'admin'")
            else:
                return []
            
            return [row['id'] for row in cursor.fetchall()]
            
        except Exception as e:
            print(f"Error getting target users: {e}")
            return []
        finally:
            conn.close()
    
    def send_broadcast(self, broadcast_id: int) -> Dict[str, int]:
        """
        Send broadcast (execute queue).
        
        Args:
            broadcast_id: Broadcast ID
            
        Returns:
            Dict with success_count and failed_count
        """
        conn = get_conn()
        try:
            # Update broadcast status to sending
            conn.execute("""
                UPDATE notification_broadcasts 
                SET status = 'sending', sent_at = ?
                WHERE id = ?
            """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), broadcast_id))
            conn.commit()
            
            # Get broadcast info
            broadcast = conn.execute("""
                SELECT title, message, channels FROM notification_broadcasts WHERE id = ?
            """, (broadcast_id,)).fetchone()
            
            if not broadcast:
                return {'success_count': 0, 'failed_count': 0}
            
            channels = broadcast['channels'].split(',')
            
            success_count = 0
            failed_count = 0
            
            # Process each channel
            for channel in channels:
                if channel == 'firebase':
                    result = self._send_firebase(broadcast_id, broadcast['title'], broadcast['message'])
                    success_count += result['success']
                    failed_count += result['failed']
                elif channel == 'whatsapp':
                    result = self._send_whatsapp(broadcast_id, broadcast['message'])
                    success_count += result['success']
                    failed_count += result['failed']
                # Future: Telegram, Email
            
            # Update broadcast final status
            final_status = 'success' if failed_count == 0 else 'partial' if success_count > 0 else 'failed'
            
            conn.execute("""
                UPDATE notification_broadcasts 
                SET status = ?, success_count = ?, failed_count = ?
                WHERE id = ?
            """, (final_status, success_count, failed_count, broadcast_id))
            conn.commit()
            
            return {'success_count': success_count, 'failed_count': failed_count}
            
        except Exception as e:
            print(f"Error sending broadcast: {e}")
            # Update to failed
            conn.execute("""
                UPDATE notification_broadcasts 
                SET status = 'failed', error_message = ?
                WHERE id = ?
            """, (str(e), broadcast_id))
            conn.commit()
            return {'success_count': 0, 'failed_count': 0}
        finally:
            conn.close()
    
    def _send_firebase(self, broadcast_id: int, title: str, message: str) -> Dict[str, int]:
        """Send via Firebase channel."""
        try:
            import fcm_helper
            success, failed = fcm_helper.send_broadcast_notification(title, message)
            
            # Update queue status
            conn = get_conn()
            try:
                # Mark as success
                conn.execute("""
                    UPDATE notification_queue 
                    SET status = 'success', sent_at = ?
                    WHERE broadcast_id = ? AND channel = 'firebase'
                    LIMIT ?
                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), broadcast_id, success))
                
                # Mark as failed
                conn.execute("""
                    UPDATE notification_queue 
                    SET status = 'failed', error_message = 'FCM send failed'
                    WHERE broadcast_id = ? AND channel = 'firebase' AND status = 'pending'
                    LIMIT ?
                """, (broadcast_id, failed))
                
                conn.commit()
            finally:
                conn.close()
            
            return {'success': success, 'failed': failed}
            
        except Exception as e:
            print(f"Firebase send error: {e}")
            return {'success': 0, 'failed': 0}
    

    def _send_whatsapp(self, broadcast_id: int, message: str) -> Dict[str, int]:
        """Send via WhatsApp channel using adapter."""
        try:
            from whatsapp_adapter import get_whatsapp_adapter
            from models import get_conn
            
            adapter = get_whatsapp_adapter()
            
            # Get queue items untuk WhatsApp channel
            conn = get_conn()
            try:
                cursor = conn.execute("""
                    SELECT nq.id, nq.user_id, u.phone_number
                    FROM notification_queue nq
                    JOIN users u ON nq.user_id = u.id
                    WHERE nq.broadcast_id = ? AND nq.channel = 'whatsapp' AND nq.status = 'pending'
                """, (broadcast_id,))
                
                queue_items = cursor.fetchall()
                
                success = 0
                failed = 0
                
                for item in queue_items:
                    queue_id = item['id']
                    phone_number = item['phone_number']
                    
                    if not phone_number:
                        # Skip if no phone number
                        conn.execute("""
                            UPDATE notification_queue 
                            SET status = 'failed', error_message = 'No phone number'
                            WHERE id = ?
                        """, (queue_id,))
                        failed += 1
                        continue
                    
                    # Send message via adapter
                    result = adapter.send_message(phone_number, message)
                    
                    if result.get('success'):
                        conn.execute("""
                            UPDATE notification_queue 
                            SET status = 'success', sent_at = ?
                            WHERE id = ?
                        """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), queue_id))
                        success += 1
                    else:
                        conn.execute("""
                            UPDATE notification_queue 
                            SET status = 'failed', error_message = ?
                            WHERE id = ?
                        """, (result.get('error', 'Unknown error'), queue_id))
                        failed += 1
                
                conn.commit()
                
                return {'success': success, 'failed': failed}
                
            finally:
                conn.close()
            
        except Exception as e:
            print(f"WhatsApp send error: {e}")
            return {'success': 0, 'failed': 0}

    def get_broadcast_history(self, limit: int = 50) -> List[Dict]:
        """Get broadcast history."""
        conn = get_conn()
        try:
            cursor = conn.execute("""
                SELECT id, title, message, target_type, channels, 
                       total_target, success_count, failed_count, status,
                       created_at, sent_at
                FROM notification_broadcasts
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))
            
            history = []
            for row in cursor.fetchall():
                history.append({
                    'id': row['id'],
                    'title': row['title'],
                    'message': row['message'],
                    'target_type': row['target_type'],
                    'channels': row['channels'],
                    'total_target': row['total_target'],
                    'success_count': row['success_count'],
                    'failed_count': row['failed_count'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'sent_at': row['sent_at']
                })
            
            return history
            
        except Exception as e:
            print(f"Error getting history: {e}")
            return []
        finally:
            conn.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get notification statistics."""
        conn = get_conn()
        try:
            # Total broadcasts
            total = conn.execute("SELECT COUNT(*) FROM notification_broadcasts").fetchone()[0]
            
            # Success/Failed counts
            success = conn.execute(
                "SELECT COUNT(*) FROM notification_broadcasts WHERE status = 'success'"
            ).fetchone()[0]
            
            failed = conn.execute(
                "SELECT COUNT(*) FROM notification_broadcasts WHERE status = 'failed'"
            ).fetchone()[0]
            
            # Success rate
            success_rate = (success / total * 100) if total > 0 else 0
            failed_rate = (failed / total * 100) if total > 0 else 0
            
            # Device counts (Firebase)
            import fcm_helper
            registered_devices = len(fcm_helper.get_registered_tokens())
            
            # Last broadcast
            last_broadcast = conn.execute("""
                SELECT created_at FROM notification_broadcasts 
                ORDER BY created_at DESC LIMIT 1
            """).fetchone()
            
            return {
                'total_broadcasts': total,
                'success_rate': round(success_rate, 2),
                'failed_rate': round(failed_rate, 2),
                'registered_devices': registered_devices,
                'valid_tokens': registered_devices,  # Will be updated with validation
                'invalid_tokens': 0,
                'last_broadcast': last_broadcast['created_at'] if last_broadcast else 'Never'
            }
            
        except Exception as e:
            print(f"Error getting statistics: {e}")
            return {
                'total_broadcasts': 0,
                'success_rate': 0,
                'failed_rate': 0,
                'registered_devices': 0,
                'valid_tokens': 0,
                'invalid_tokens': 0,
                'last_broadcast': 'Never'
            }
        finally:
            conn.close()


# Global instance
_notification_engine = None

def get_notification_engine() -> NotificationEngine:
    """Get global NotificationEngine instance."""
    global _notification_engine
    if _notification_engine is None:
        _notification_engine = NotificationEngine()
    return _notification_engine

