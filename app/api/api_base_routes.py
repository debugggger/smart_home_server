from flask import render_template, jsonify
import time


def register_base_routes(app, db):

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/rooms-page')
    def rooms_page():
        return render_template('rooms.html')

    @app.route('/controllers-page')
    def controllers_page():
        return render_template('controllers.html')

    @app.route('/devices-page')
    def devices_page():
        return render_template('devices.html')

    @app.route('/triggers-page')
    def triggers_page():
        return render_template('triggers.html')

    @app.route('/dashboard')
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/api/status', methods=['GET'])
    def get_status():
        return jsonify({
            'status': 'running',
            'message': 'Web interface is active',
            'timestamp': time.time()
        })

    @app.route('/api/stats', methods=['GET'])
    def get_stats():
        return jsonify({
            'rooms': len(db.get_all_rooms()),
            'controllers': len(db.get_all_controllers()),
            'devices': len(db.get_all_devices()),
            'triggers': len(db.get_all_triggers())
        })