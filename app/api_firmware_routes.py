import os
import tempfile
import logging
from flask import request, jsonify, render_template
from werkzeug.utils import secure_filename
from api_utils import handle_api_errors, forward_to_core

logger = logging.getLogger(__name__)


def register_firmware_routes(app, db, core_addr):
    @app.route('/firmware-update')
    def firmware_update_page():
        return render_template('firmware_update.html')

    @app.route('/api/update-controller', methods=['POST'])
    @handle_api_errors
    def start_update():
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        topics = data.get('topics')
        if not topics:
            return jsonify({'error': 'topics field is required'}), 400

        if isinstance(topics, list):
            if len(topics) == 0:
                return jsonify({'error': 'topics list is empty'}), 400
            if "AllESP" in topics or len(topics) == 1 and topics[0] == "AllESP":
                topics_for_mqtt = "AllESP"
            else:
                topics_for_mqtt = topics
        elif isinstance(topics, str):
            topics_for_mqtt = topics
        else:
            return jsonify({'error': 'topics must be list or string'}), 400

        payload = {'topics': topics_for_mqtt}
        response = forward_to_core(core_addr, '/core_api/ota_start_update', payload, timeout=30)

        if response.status_code == 200:
            result = response.json()
            return jsonify({
                'success': True,
                'message': f'OTA update started successfully',
                'forwarded_to': core_addr,
                'topics_sent': topics_for_mqtt,
                'response': result
            }), 200
        else:
            return jsonify({
                'error': f'OTA service returned error: {response.status_code}',
                'details': response.text
            }), response.status_code

    @app.route('/api/verify-files', methods=['POST'])
    @handle_api_errors
    def verify_files():
        data = request.json
        firmware_path = data.get('firmware_path')
        version_path = data.get('version_path')

        firmware_exists = os.path.exists(firmware_path) if firmware_path else False
        version_exists = os.path.exists(version_path) if version_path else False

        return jsonify({
            'success': firmware_exists and version_exists,
            'firmware_exists': firmware_exists,
            'version_exists': version_exists
        })

    @app.route('/api/upload-firmware', methods=['POST'])
    @handle_api_errors
    def upload_firmware():
        if 'firmware' not in request.files or 'version' not in request.files:
            return jsonify({'error': 'Файлы не найдены'}), 400

        firmware = request.files['firmware']
        version = request.files['version']

        temp_dir = tempfile.mkdtemp()

        firmware_filename = secure_filename(firmware.filename)
        version_filename = secure_filename(version.filename)

        firmware_path = os.path.join(temp_dir, firmware_filename)
        version_path = os.path.join(temp_dir, version_filename)

        firmware.save(firmware_path)
        version.save(version_path)

        firmware_abs_path = os.path.abspath(firmware_path)
        version_abs_path = os.path.abspath(version_path)

        response = forward_to_core(
            core_addr,
            '/core_api/load_files_on_ota',
            {'firmware_path': firmware_path, 'version_path': version_path},
            timeout=30
        )

        return jsonify({
            'success': True,
            'firmware_absolute_path': firmware_abs_path,
            'version_absolute_path': version_abs_path
        })