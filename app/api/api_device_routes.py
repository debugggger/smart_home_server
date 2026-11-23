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


def _device_to_dict(db, d, *, with_controller=False):
    """Общая сериализация устройства (is_controlled включён, is_active — нет)."""
    controller = db.get_controller_by_id(d.controller_id)
    device_type = db.get_device_type_by_id(d.type_id)

    result = {
        'id': d.id,
        'name': d.name,
        'controller_id': d.controller_id,
        'type_id': d.type_id,
        'type_name': device_type.name if device_type else 'Unknown',
        'port': d.port,
        'params': d.params,
        'current_values': _parse_current_values(d.current_values),
        'is_online': d.is_online,
        'is_controlled': bool(getattr(d, 'is_controlled', True)),
    }
    if with_controller:
        result['controller_name'] = controller.name if controller else 'Unknown'
        room = db.get_room_by_id(controller.room_id) if controller else None
        result['room_name'] = room.name if room else 'Не назначено'
    return result


def register_device_routes(app, db, kafkaHandler):

    @app.route('/api/devices/all', methods=['GET'])
    @handle_api_errors
    def get_all_devices_with_status():
        devices = [get_device_with_details(db, d) for d in db.get_all_devices()]
        return jsonify(devices)

    @app.route('/api/devices', methods=['GET'])
    @handle_api_errors
    def get_devices():
        return jsonify([_device_to_dict(db, d, with_controller=True)
                        for d in db.get_all_devices()])

    @app.route('/api/devices/controller/<int:controller_id>', methods=['GET'])
    @handle_api_errors
    def get_devices_by_controller(controller_id):
        return jsonify([_device_to_dict(db, d)
                        for d in db.get_devices_by_controller(controller_id)])

    @app.route('/api/devices/by-controller/<int:controller_id>', methods=['GET'])
    @handle_api_errors
    def get_devices_by_controller_id(controller_id):
        return jsonify([_device_to_dict(db, d)
                        for d in db.get_devices_by_controller(controller_id)])

    @app.route('/api/devices', methods=['POST'])
    @handle_api_errors
    def add_device():
        data = request.json

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
            current_values=current_values_json,
            # is_controlled по умолчанию True — управление разрешено
            is_controlled=True,
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

    # ============ ПЕРЕКЛЮЧАТЕЛЬ is_controlled ============

    @app.route('/api/devices/<int:device_id>/toggle-controlled', methods=['PATCH'])
    @handle_api_errors
    def toggle_device_controlled(device_id):
        """Переключение is_controlled.
        Если тело с is_controlled не передано — инвертирует текущее значение.
        Кеш в Database.update_device_is_controlled обновляется автоматически."""
        device = db.get_device_by_id(device_id)
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404

        data = request.get_json(silent=True) or {}
        if 'is_controlled' in data:
            new_value = bool(data['is_controlled'])
        else:
            new_value = not bool(getattr(device, 'is_controlled', True))

        db.update_device_is_controlled(device_id, new_value)
        return jsonify({'success': True, 'is_controlled': new_value})

    # ============ ОТПРАВКА КОМАНДЫ ============

    @app.route('/api/devices/<int:device_id>/command', methods=['POST'])
    @handle_api_errors
    def send_device_command(device_id):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'No JSON data provided'}), 400

        command = data.get('command')
        value = data.get('value')
        complex_data = data.get('complex_data')

        if not command:
            return jsonify({'error': 'command is required'}), 400

        device = db.get_device_by_id(device_id)
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404

        # Блокировка управления
        if not getattr(device, 'is_controlled', True):
            return jsonify({
                'success': False,
                'error': 'Device control is blocked (is_controlled = false)'
            }), 409

        controller = db.get_controller_by_id(device.controller_id)
        if not controller:
            return jsonify({'success': False, 'error': 'Controller not found'}), 404

        device_type = db.get_device_type_by_id(device.type_id)
        if not device_type:
            return jsonify({'success': False, 'error': 'Device type not found'}), 404

        # ---------- complex_data -> value ----------
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
                        extra_parts.append('None' if default_value is None else str(default_value))

            base = '' if value is None else str(value)
            if base == '':
                value = '/'.join(extra_parts)
            else:
                value = base + '/' + '/'.join(extra_parts)

        # ---------- ищем команду в обоих источниках ----------
        param_name = device_type.param_name
        if isinstance(param_name, str):
            try:
                param_name = json.loads(param_name)
            except (ValueError, TypeError):
                param_name = {}
        if not isinstance(param_name, dict):
            param_name = {}

        sending_reading = param_name.get('sending_reading_commands') or {}
        sending_plain = param_name.get('sending_commands') or {}

        all_commands = []
        for src in (sending_reading, sending_plain):
            if not isinstance(src, dict):
                continue
            for group in ('binary', 'numeric'):
                group_cmds = src.get(group)
                if isinstance(group_cmds, list):
                    all_commands.extend([c for c in group_cmds if isinstance(c, dict)])

        sending_mac = getattr(controller, 'mac', None) or ''
        matched = None
        for com in all_commands:
            if com.get('sending_name') == command:
                matched = com
                break

        if matched is not None:
            if matched.get('is_on_serv') is True:
                sending_mac = 'serv'
                pn = matched.get('parameter_number')
                if pn is not None:
                    command = str(pn) + '/' + command

        if not sending_mac:
            return jsonify({'success': False, 'error': 'Controller has no MAC/address'}), 500

        success, offset = kafkaHandler.send_command(sending_mac, device_id, command, value)

        if success:
            return jsonify({
                'success': True,
                'message': 'Command sent via Kafka',
                'kafka_offset': offset
            }), 200
        return jsonify({'error': 'Failed to send command'}), 500

    # ============ ТИПЫ УСТРОЙСТВ ============

    @app.route('/api/device-types', methods=['GET'])
    @handle_api_errors
    def get_device_types():
        types = db.get_all_device_types()
        return jsonify(
            [{'id': t.id, 'name': t.name, 'description': t.description, 'param_names': t.param_name} for t in types])

    def get_device_data_for_core(device):
        controller = db.get_controller_by_id(device.controller_id)
        device_type = db.get_device_type_by_id(device.type_id)

        send_type_name = device_type.name

        if not controller or not device_type:
            return None

        if device_type.param_name.get("parent_name") is not None:
            send_type_name = device_type.param_name.get("parent_name")

        device_data_for_core = {
            'command_type': 'ADD',
            'id': device.id,
            'controller_mac': controller.mac,
            'port': device.port,
            'params': device.params,
            'current_values': device.current_values,
            'type': send_type_name
        }
        return device_data_for_core

    @app.route('/api/device-types/<int:type_id>/params', methods=['GET'])
    def get_device_type_params(type_id):
        device_type = db.get_device_type_by_id(type_id)
        if not device_type:
            return jsonify({'error': 'Device type not found'}), 404

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