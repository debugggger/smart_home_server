import json
import logging
from flask import request, jsonify

from .api_utils import handle_api_errors, get_device_with_details
from database import Device

logger = logging.getLogger(__name__)


def _parse_current_values(raw):
    """
    Приводит current_values из БД к объекту dict.
    Поддерживает:
      - None -> {}
      - dict -> как есть
      - str (JSON) -> распарсенный dict
      - list -> конвертирует в {unknown_value1: ..., unknown_value2: ...}
        (на случай старых данных)
    """
    if raw is None:
        return {}

    if isinstance(raw, dict):
        return raw

    if isinstance(raw, (list, tuple)):
        return {f"unknown_value{i + 1}": v for i, v in enumerate(raw)}

    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
        except (TypeError, ValueError):
            logger.warning("Failed to parse current_values JSON: %r", raw)
            return {}

        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, (list, tuple)):
            return {f"unknown_value{i + 1}": v for i, v in enumerate(parsed)}
        return {}

    return {}


def register_device_routes(app, db, kafkaHandler):

    @app.route('/api/devices/all', methods=['GET'])
    @handle_api_errors
    def get_all_devices_with_status():
        devices = []
        all_devices = db.get_all_devices()

        for device in all_devices:
            devices.append(get_device_with_details(db, device))

        return jsonify(devices)

    @app.route('/api/devices', methods=['GET'])
    @handle_api_errors
    def get_devices():
        devices = db.get_all_devices()
        result = []
        for d in devices:
            controller = db.get_controller_by_id(d.controller_id)
            device_type = db.get_device_type_by_id(d.type_id)
            room = None
            if controller:
                room = db.get_room_by_id(controller.room_id)

            current_values = _parse_current_values(d.current_values)

            result.append({
                'id': d.id,
                'name': d.name,
                'controller_id': d.controller_id,
                'controller_name': controller.name if controller else 'Unknown',
                'room_name': room.name if room else 'Не назначено',
                'type_id': d.type_id,
                'type_name': device_type.name if device_type else 'Unknown',
                'port': d.port,
                'params': d.params,
                'current_values': current_values,
                'is_online': d.is_online
            })
        return jsonify(result)

    @app.route('/api/devices/controller/<int:controller_id>', methods=['GET'])
    @handle_api_errors
    def get_devices_by_controller(controller_id):
        devices = db.get_devices_by_controller(controller_id)
        result = []
        for d in devices:
            device_type = db.get_device_type_by_id(d.type_id)
            result.append({
                'id': d.id,
                'name': d.name,
                'type_id': d.type_id,
                'type_name': device_type.name if device_type else 'Unknown',
                'port': d.port,
                'params': d.params,
                'is_online': d.is_online,
                'current_values': _parse_current_values(d.current_values)
            })
        return jsonify(result)

    @app.route('/api/devices/by-controller/<int:controller_id>', methods=['GET'])
    @handle_api_errors
    def get_devices_by_controller_id(controller_id):
        devices = db.get_devices_by_controller(controller_id)
        result = []
        for device in devices:
            device_type = db.get_device_type_by_id(device.type_id)
            result.append({
                'id': device.id,
                'name': device.name,
                'type_id': device.type_id,
                'type_name': device_type.name if device_type else 'Unknown',
                'port': device.port,
                'params': device.params,
                'is_online': device.is_online,
                'current_values': _parse_current_values(device.current_values)
            })
        return jsonify(result)

    @app.route('/api/devices', methods=['POST'])
    @handle_api_errors
    def add_device():

        data = request.json

        # current_values приходит с фронта как объект (dict) или не приходит вовсе.
        # Если пришёл список — конвертируем в {unknown_valueN: v}.
        raw_cv = data.get('current_values', {})
        if isinstance(raw_cv, (list, tuple)):
            raw_cv = {f"unknown_value{i + 1}": v for i, v in enumerate(raw_cv)}
        elif not isinstance(raw_cv, dict):
            raw_cv = {}

        current_values_json = json.dumps(raw_cv, ensure_ascii=False)

        device = Device(
            name=data['name'],
            controller_id=data['controller_id'],
            type_id=data['type_id'],
            port=data.get('port', ''),
            params=data.get('params', '{}'),
            current_values=current_values_json
        )
        device_id = db.add_device(device)

        if device_id:
            device.id = device_id
            data_for_core = get_device_data_for_core(device)

            if data_for_core is not None:
                success, offset = kafkaHandler.update_device_table(data_for_core)
                if success:
                    return jsonify({'success': True, 'id': device_id})
            else:
                return jsonify({'success': False}), 400

        return jsonify({'success': False}), 400

    @app.route('/api/devices/<int:device_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_device(device_id):
        db.delete_device(device_id, kafkaHandler)
        return jsonify({'success': True})

    @app.route('/api/devices/<int:device_id>/command', methods=['POST'])
    @handle_api_errors
    def send_device_command(device_id):
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        command = data.get('command')
        value = data.get('value')
        complex_data = data.get('complex_data')

        if not command:
            return jsonify({'error': 'command is required'}), 400

        device = db.get_device_by_id(device_id)
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404

        controller = db.get_controller_by_id(device.controller_id)
        if not controller:
            return jsonify({'success': False, 'error': 'Controller not found'}), 404

        if isinstance(complex_data, list) and complex_data:
            current_values = device.current_values or {}

            if isinstance(current_values, str):
                try:
                    current_values = json.loads(current_values) if current_values.strip() else {}
                except (ValueError, TypeError):
                    current_values = {}
            if not isinstance(current_values, dict):
                current_values = {}

            extra_parts = []
            for item in complex_data:
                if not isinstance(item, dict):
                    continue

                for name, meta in item.items():
                    if name in current_values:
                        extra_parts.append(str(current_values[name]))
                    else:
                        default_value = None
                        if isinstance(meta, dict):
                            default_value = meta.get('defaultValue')
                        if default_value is None:
                            extra_parts.append('None')
                        else:
                            extra_parts.append(str(default_value))

            base = '' if value is None else str(value)
            if base == '':
                value = '/'.join(extra_parts)
            else:
                value = base + '/' + '/'.join(extra_parts)


        success, offset = kafkaHandler.send_command(controller.mac, device_id, command, value)

        if success:
            return jsonify({
                'success': True,
                'message': 'Command sent via Kafka',
                'kafka_offset': offset
            }), 200
        else:
            return jsonify({'error': 'Failed to send command'}), 500

    @app.route('/api/device-commands/<int:device_type_id>', methods=['GET'])
    @handle_api_errors
    def get_device_commands(device_type_id):
        device_type = db.get_device_type_by_id(device_type_id)
        if not device_type:
            return jsonify([])

        commands = {
            'binOut': ['toggle', 'setHigh', 'setLow'],
            'led': ['turnOn', 'turnOff', 'setColor', 'setBrightness', 'setSpeed', 'setEffect',
                    'setSoundReaction', 'setSoundWeights', 'setSoundBeatColor', 'setMicro'],
            'stepper': ['setSpeed', 'setDir', 'startInf', 'startSteps', 'stop']
        }

        type_name = device_type.name.lower()
        for key in commands:
            if key.lower() in type_name:
                return jsonify(commands[key])

        return jsonify([])

    @app.route('/api/device-types', methods=['GET'])
    @handle_api_errors
    def get_device_types():
        types = db.get_all_device_types()
        return jsonify(
            [{'id': t.id, 'name': t.name, 'description': t.description, 'param_names': t.param_name} for t in types])

    def get_device_data_for_core(device):

        controller = db.get_controller_by_id(device.controller_id)
        device_type = db.get_device_type_by_id(device.type_id)

        if not controller or not device_type:
            return None

        # device.current_values — уже JSON-строка (см. add_device).
        # Для Kafka отдаём как есть — ядро само решит, что делать.
        device_data_for_core = {
            'command_type': 'ADD',
            'id': device.id,
            'controller_mac': controller.mac,
            'port': device.port,
            'params': device.params,
            'current_values': device.current_values,
            'type': device_type.name
        }
        return device_data_for_core

    @app.route('/api/device-types/<int:type_id>/params', methods=['GET'])
    def get_device_type_params(type_id):
        device_type = db.get_device_type_by_id(type_id)
        if not device_type:
            return jsonify({'error': 'Device type not found'}), 404

        # У DeviceType в БД поле param_name (см. dataclass), а не params.
        # Раньше тут было device_type.params — это всегда None.
        raw = getattr(device_type, 'param_name', None) or getattr(device_type, 'params', None)

        try:
            if raw:
                config = json.loads(raw) if isinstance(raw, str) else raw
            else:
                config = {}
        except (TypeError, ValueError):
            config = {}

        fields = config.get('input_fields', []) if isinstance(config, dict) else []

        return jsonify({
            'type_id': type_id,
            'type_name': device_type.name,
            'fields': fields
        })