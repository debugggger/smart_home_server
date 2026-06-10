import logging
import json
from functools import wraps
from flask import jsonify, request

logger = logging.getLogger(__name__)


def handle_api_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    return decorated_function


def get_device_with_details(db, device):
    controller = db.get_controller_by_id(device.controller_id)
    room = None
    if controller:
        room = db.get_room_by_id(controller.room_id)
    device_type = db.get_device_type_by_id(device.type_id)

    return {
        'id': device.id,
        'name': device.name,
        'type': device_type.name.lower() if device_type else 'unknown',
        'room': room.name if room else 'Без комнаты',
        'controller': controller.name if controller else 'Unknown',
        'port': device.port,
        'params': json.loads(device.params) if device.params else {},
        'status': 'online',
        'value': None
    }


def forward_to_core(core_addr, endpoint, payload, timeout=10):
    import requests

    target_url = f"{core_addr}{endpoint}"
    logger.info(f"Forwarding to {target_url}: {payload}")

    response = requests.post(target_url, json=payload, timeout=timeout)
    return response