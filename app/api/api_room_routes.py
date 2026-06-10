from flask import request, jsonify
from .api_utils import handle_api_errors

def register_room_routes(app, db):
    @app.route('/api/rooms', methods=['GET'])
    @handle_api_errors
    def get_rooms():
        rooms = db.get_all_rooms()
        return jsonify([{'id': r.id, 'name': r.name} for r in rooms])

    @app.route('/api/rooms', methods=['POST'])
    @handle_api_errors
    def add_room():
        from app.database import Room

        data = request.json
        room = Room(name=data['name'])
        room_id = db.add_room(room)
        return jsonify({'success': True, 'id': room_id}) if room_id else jsonify({'success': False}), 400

    @app.route('/api/rooms/<int:room_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_room(room_id):
        db.delete_room(room_id)
        return jsonify({'success': True})

    @app.route('/api/device-types', methods=['GET'])
    @handle_api_errors
    def get_device_types():
        types = db.get_all_device_types()
        return jsonify(
            [{'id': t.id, 'name': t.name, 'description': t.description, 'param_names': t.param_name} for t in types])