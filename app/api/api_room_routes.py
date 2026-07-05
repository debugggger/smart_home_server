from flask import request, jsonify
from .api_utils import handle_api_errors
from database import Room


def register_room_routes(app, db, kafkaHandler):
    @app.route('/api/rooms', methods=['GET'])
    @handle_api_errors
    def get_rooms():
        rooms = db.get_all_rooms()
        return jsonify([{'id': r.id, 'name': r.name} for r in rooms])

    @app.route('/api/rooms', methods=['POST'])
    @handle_api_errors
    def add_room():

        data = request.json
        room = Room(name=data['name'])
        room_id = db.add_room(room)
        return jsonify({'success': True, 'id': room_id}) if room_id else jsonify({'success': False}), 400

    @app.route('/api/rooms/<int:room_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_room(room_id):
        db.delete_room(room_id, kafkaHandler)
        return jsonify({'success': True})

