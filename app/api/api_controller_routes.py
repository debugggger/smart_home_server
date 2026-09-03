import logging
from flask import request, jsonify
from .api_utils import handle_api_errors

from database import Controller

logger = logging.getLogger(__name__)


def register_controller_routes(app, db, kafkaHandler):
    @app.route('/api/controllers', methods=['GET'])
    @handle_api_errors
    def get_controllers():
        controllers = db.get_all_controllers()
        result = []
        for c in controllers:
            room = db.get_room_by_id(c.room_id)
            devices = db.get_devices_by_controller(c.id)
            result.append({
                'id': c.id,
                'name': c.name,
                'mac': c.mac,
                'room_id': c.room_id,
                'room_name': room.name if room else 'Не назначено',
                'devices_count': len(devices)
            })
        return jsonify(result)

    @app.route('/api/controllers', methods=['POST'])
    @handle_api_errors
    def add_controller():

        data = request.json
        controller = Controller(
            name=data['name'],
            mac=data['mac'],
            room_id=data['room_id']
        )
        controller_id = db.add_controller(controller)
        if controller_id:
            return jsonify({'success': True, 'id': controller_id})
        return jsonify({'success': False}), 400

    @app.route('/api/controllers/<int:controller_id>', methods=['PUT'])
    @handle_api_errors
    def update_controller(controller_id):
        data = request.json
        with db.connection.cursor() as cur:
            cur.execute("UPDATE controllers SET name = %s WHERE id = %s",
                        (data['name'], controller_id))
            db.connection.commit()
        return jsonify({'success': True})

    @app.route('/api/controllers/<int:controller_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_controller(controller_id):
        db.delete_controller(controller_id)
        return jsonify({'success': True})

    @app.route('/api/controllers/init', methods=['POST'])
    def init_controller():
        """Отправить команду инициализации на контроллер"""
        data = request.json
        mac = data.get('mac')

        if not mac:
            return jsonify({'error': 'MAC address required'}), 400

        if kafkaHandler:
            success, offset = kafkaHandler.init_controller(
                controller_mac=mac
            )

            if success:
                return jsonify({'success': True, 'message': f'Init command sent to {mac}'})
            else:
                return jsonify({'success': False, 'error': 'Failed to send command'}), 500

        return jsonify({'success': False, 'error': 'Kafka handler not available'}), 503