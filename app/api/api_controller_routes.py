import logging
from flask import request, jsonify
from .api_utils import handle_api_errors

logger = logging.getLogger(__name__)


def register_controller_routes(app, db):
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
        from app.database import Controller

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