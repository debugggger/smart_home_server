import json
import logging
from flask import request, jsonify

from .api_utils import handle_api_errors, get_device_with_details
from database import Device

logger = logging.getLogger(__name__)

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

            current_values = None
            if d.current_values:
                try:
                    current_values = json.loads(d.current_values)
                except:
                    current_values = []

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
                'status': 'online'
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
                'current_values': d.current_values
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
                'current_values': device.current_values
            })
        return jsonify(result)

    @app.route('/api/devices', methods=['POST'])
    @handle_api_errors
    def add_device():

        data = request.json
        device = Device(
            name=data['name'],
            controller_id=data['controller_id'],
            type_id=data['type_id'],
            port=data.get('port', ''),
            params=data.get('params', '{}')
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
        db.delete_device(device_id)
        return jsonify({'success': True})

    @app.route('/api/devices/<int:device_id>/command', methods=['POST'])
    @handle_api_errors
    def send_device_command(device_id):
        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        command = data.get('command')
        value = data.get('value')

        if not command:
            return jsonify({'error': 'command is required'}), 400

        device = db.get_device_by_id(device_id)
        if not device:
            return jsonify({'success': False, 'error': 'Device not found'}), 404

        controller = db.get_controller_by_id(device.controller_id)
        if not controller:
            return jsonify({'success': False, 'error': 'Controller not found'}), 404

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


    def get_device_data_for_core(device):

        controller_mac = db.get_controller_by_id(device.controller_id).mac
        device_type = db.get_device_type_by_id(device.type_id).name

        device_data_for_core = {
            'id': device.id,
            'controller_mac': controller_mac,
            'port': device.port,
            'params': device.params,
            'current_values': device.current_values,
            'type': device_type
        }
        return device_data_for_core

