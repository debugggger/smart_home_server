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

    def broadcast_bulk_update(updates):
        try:
            socketio.emit('devices_bulk_updated', {
                'updates': updates,
                'count': len(updates),
                'timestamp': time.time()
            })
            logger.info(f"Broadcasted bulk update: {len(updates)} devices")
        except Exception as e:
            logger.error(f"Error broadcasting bulk update: {e}")

    socketio.broadcast_device_update = broadcast_device_update
    socketio.broadcast_bulk_update = broadcast_bulk_update

    logger.info("✅ WebSocket routes registered")