import os
from flask import request, jsonify


def register_core_api_routes(app, db, mqtt_client, ota_server):

    @app.route('/core_api/send_mqtt_command', methods=['POST'])
    def send_mqtt_command():
        try:
            data = request.json

            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400

            controller_mac = data.get('controller_mac')
            device_id = data.get('device_id')
            command = data.get('command')

            if not controller_mac:
                return jsonify({'error': 'controller_mac is required'}), 400
            if device_id is None:
                return jsonify({'error': 'device_id is required'}), 400
            if not command:
                return jsonify({'error': 'command is required'}), 400

            value = data.get('value')

            device = db.get_device_by_id(device_id)

            req_parts = []
            req_parts.append(db.get_device_type_by_id(device.type_id).name)
            if device.port:
                req_parts.append(device.port)
            if device.params:
                req_parts.append(device.params)
            req_parts.append(command)
            if value:
                req_parts.append(str(value))
            req = "/".join(req_parts)

            mqtt_client.publish(controller_mac, req)

            return jsonify({
                'success': True,
                'message': 'Command sended'
            }), 200

        except Exception as e:
            print(f"Error: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/core_api/ota_start_update', methods=['POST'])
    def start_update_controllers():
        try:
            data = request.json

            if not data:
                return jsonify({'error': 'No data provided'}), 400

            topics = data.get('topics')

            if not topics:
                return jsonify({'error': 'topics field is required'}), 400

            if isinstance(topics, str) and topics == "AllESP":
                mqtt_client.publish("AllESP", "update")
            elif isinstance(topics, list):
                for topic in topics:
                    mqtt_client.publish(topic, "update")
            else:
                mqtt_client.publish(topics, "update")

            return jsonify({
                'success': True,
                'message': 'OTA update started successfully',
                'topics_sent': topics
            }), 200

        except Exception as e:
            print(f"Error in start_update_controllers: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': str(e)}), 500

    @app.route('/core_api/load_files_on_ota', methods=['POST'])
    def upload_firmware():
        try:
            data = request.json

            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400

            firmware_path = data.get('firmware_path')
            version_path = data.get('version_path')

            if ota_server.is_running:
                ota_server.stop()

            ota_server.file_mapping.clear()
            ota_server.add_binary_file('/firmware.bin', firmware_path)
            ota_server.add_text_file('/version.txt', version_path)

            return jsonify({
                'success': True,
                'message': 'Files loaded successfully',
                'firmware_path': firmware_path,
                'version_path': version_path,
                'firmware_size': os.path.getsize(firmware_path),
                'version_size': os.path.getsize(version_path)
            }), 200

        except Exception as e:
            print(f"Error: {str(e)}")
            return jsonify({'error': str(e)}), 500

    @app.route('/core_api/update_devices_bd', methods=['POST'])
    def update_devices():
        try:
            data = request.json

            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400

            firmware_path = data.get('firmware_path')
            version_path = data.get('version_path')

            if ota_server.is_running:
                ota_server.stop()

            ota_server.file_mapping.clear()
            ota_server.add_binary_file('/firmware.bin', firmware_path)
            ota_server.add_text_file('/version.txt', version_path)

            return jsonify({
                'success': True,
                'message': 'Files loaded successfully',
                'firmware_path': firmware_path,
                'version_path': version_path,
                'firmware_size': os.path.getsize(firmware_path),
                'version_size': os.path.getsize(version_path)
            }), 200

        except Exception as e:
            print(f"Error: {str(e)}")
            return jsonify({'error': str(e)}), 500

