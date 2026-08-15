# ==============================================================================
# ADD THESE IMPORTS AND FUNCTIONS TO webapp.py
# ==============================================================================

import queue
import threading
import asyncio
from datetime import datetime

# ==============================================================================
# NOTIFICATION QUEUE (Thread-safe)
# ==============================================================================

notification_queue = queue.Queue()

def notification_worker():
    """Background worker to process notifications from queue."""
    while True:
        try:
            notification = notification_queue.get(timeout=1)
            if notification is None:
                break
            
            # Process notification
            try:
                from handlers import notify_brokers
                
                if bot_loop and bot_loop.is_running():
                    asyncio.run_coroutine_threadsafe(
                        notify_brokers(
                            notification.get('bot'), 
                            notification.get('text'), 
                            notification.get('req_id'), 
                            notification.get('buyer_id')
                        ),
                        bot_loop
                    )
                else:
                    # Fallback: run in current thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        notify_brokers(
                            notification.get('bot'), 
                            notification.get('text'), 
                            notification.get('req_id'), 
                            notification.get('buyer_id')
                        )
                    )
                    loop.close()
                    
            except Exception as e:
                logger.error(f"Notification worker error: {e}")
                
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Notification worker error: {e}")

# Start notification worker thread
notification_thread = threading.Thread(target=notification_worker, daemon=True, name="notify-worker")
notification_thread.start()


def _send_notification_safe(notification_text: str, req_id: int, buyer_id: int):
    """Queue notification for background processing."""
    if not bot_app:
        logger.warning("bot_app is None – cannot send notification")
        return
    
    notification_queue.put({
        'bot': bot_app.bot,
        'text': notification_text,
        'req_id': req_id,
        'buyer_id': buyer_id
    })
    logger.info(f"📬 Notification queued for #ADK-{req_id}")


# ==============================================================================
# HEALTH CHECK ENDPOINT
# ==============================================================================

@web_app.route('/health')
def health_check():
    """Health check endpoint for monitoring."""
    try:
        # Test database connection
        from models import db_connection
        with db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        
        return jsonify({
            "status": "healthy",
            "database": "connected",
            "version": "1.0.0",
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503
