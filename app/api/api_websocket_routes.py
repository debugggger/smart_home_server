# api/api_websocket_routes.py
import logging
import json
import time
from flask import request
from flask_socketio import SocketIO, emit

logger = logging.getLogger(__name__)


def register_websocket_routes(socketio, db, kafka_handler=None):

    @socketio.on('connect')
    def handle_connect():
        logger.info(f'Client connected: {request.sid}')

        if kafka_handler and not hasattr(socketio, 'kafka_handler'):
            socketio.kafka_handler = kafka_handler

        emit('connection_response', {
            'status': 'connected',
            'message': 'WebSocket connected',
            'timestamp': time.time()
        })

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info(f'Client disconnected: {request.sid}')

    @socketio.on('subscribe_updates')
    def handle_subscribe(data):
        client_id = request.sid
        logger.info(f'Client {client_id} subscribed to updates')

        emit('subscription_confirmed', {
            'status': 'subscribed',
            'client_id': client_id,
            'message': 'You are now subscribed to device updates'
        })

    @socketio.on('unsubscribe_updates')
    def handle_unsubscribe(data):
        client_id = request.sid
        logger.info(f'Client {client_id} unsubscribed from updates')

        emit('subscription_confirmed', {
            'status': 'unsubscribed',
            'client_id': client_id,
            'message': 'You are now unsubscribed from device updates'
        })

    @socketio.on('get_device_current_values')
    def handle_get_device_values(data):
        device_id = data.get('device_id')
        if not device_id:
            emit('error', {'message': 'device_id is required'})
            return

        device = db.get_device_by_id(device_id)
        if not device:
            emit('error', {'message': f'Device {device_id} not found'})
            return

        current_values = None
        if device.current_values:
            try:
                if isinstance(device.current_values, str):
                    current_values = json.loads(device.current_values)
                else:
                    current_values = device.current_values
            except:
                current_values = []
        else:
            current_values = []

        emit('device_values', {
            'device_id': device_id,
            'current_values': current_values,
            'timestamp': time.time()
        })

    @socketio.on('get_all_devices_values')
    def handle_get_all_devices_values(data):
        devices = db.get_all_devices()
        result = []

        for device in devices:
            current_values = None
            if device.current_values:
                try:
                    if isinstance(device.current_values, str):
                        current_values = json.loads(device.current_values)
                    else:
                        current_values = device.current_values
                except:
                    current_values = []
            else:
                current_values = []

            result.append({
                'device_id': device.id,
                'name': device.name,
                'current_values': current_values
            })

        emit('all_devices_values', {
            'devices': result,
            'count': len(result),
            'timestamp': time.time()
        })

    @socketio.on('ping')
    def handle_ping(data):
        emit('pong', {'timestamp': time.time()})

    def broadcast_device_update(device_id, current_values):
        try:
            socketio.emit('device_updated', {
                'device_id': device_id,
                'current_values': current_values,
                'timestamp': time.time()
            })
            logger.info(f"Broadcasted device update: device_id={device_id}")
        except Exception as e:
            logger.error(f"Error broadcasting device update: {e}")

    # def broadcast_bulk_update(updates):
    #     try:
    #         socketio.emit('devices_bulk_updated', {
    #             'updates': updates,
    #             'count': len(updates),
    #             'timestamp': time.time()
    #         })
    #         logger.info(f"Broadcasted bulk update: {len(updates)} devices")
    #     except Exception as e:
    #         logger.error(f"Error broadcasting bulk update: {e}")


    def broadcast_device_update_status(device_id, is_online):
        try:
            socketio.emit('device_status_update', {
                'device_id': device_id,
                'is_online': is_online,
                'timestamp': time.time()
            })
            logger.info(f"[WebSocket] Broadcasted device status update: device_id={device_id}, is_online={is_online}")
        except Exception as e:
            logger.error(f"[WebSocket] Error broadcasting device status: {e}")

    # def broadcast_device_status_bulk(updates):
    #     try:
    #         socketio.emit('devices_status_bulk_update', {
    #             'updates': updates,
    #             'count': len(updates),
    #             'timestamp': time.time()
    #         })
    #         logger.info(f"[WebSocket] Broadcasted bulk device status update: {len(updates)} devices")
    #     except Exception as e:
    #         logger.error(f"[WebSocket] Error broadcasting bulk device status: {e}")


    def broadcast_notification(notification):
        try:
            socketio.emit('notification', {
                'id': notification.get('id'),
                'type': notification.get('type'),
                'message': notification.get('message'),
                'timestamp': notification.get('timestamp'),
                'is_read': notification.get('is_read', False)
            })
            print(f"[WebSocket] Broadcasted notification: {notification.get('type')}")
        except Exception as e:
            print(f"[WebSocket] Error broadcasting notification: {e}")

    @socketio.on('get_notifications')
    def handle_get_notifications(data):
        """Клиент запрашивает историю уведомлений"""
        if kafka_handler:
            limit = data.get('limit', 10)
            notifications = kafka_handler.get_notifications(limit)
            emit('notifications_history', {
                'notifications': notifications,
                'count': len(notifications)
            })
        else:
            emit('notifications_history', {'notifications': [], 'count': 0})

    @socketio.on('mark_notification_read')
    def handle_mark_read(data):
        """Отметить уведомление как прочитанное"""
        notification_id = data.get('notification_id')
        if kafka_handler and notification_id:
            success = kafka_handler.mark_notification_read(notification_id)
            if success:
                emit('notification_marked_read', {'id': notification_id})

    @socketio.on('clear_notifications')
    def handle_clear_notifications(data):
        """Очистить все уведомления"""
        if kafka_handler:
            kafka_handler.clear_notifications()
            emit('notifications_cleared', {})

    socketio.broadcast_device_update = broadcast_device_update
    #socketio.broadcast_bulk_update = broadcast_bulk_update
    socketio.broadcast_device_update_status = broadcast_device_update_status
    socketio.broadcast_notification = broadcast_notification
    #socketio.broadcast_device_status_bulk = broadcast_device_status_bulk

    logger.info("✅ WebSocket routes registered")