import os
import threading
import time
import queue
from datetime import datetime


import requests
from flask import Flask, jsonify, request

from otaServer import OTAServer
from database import Database, Room, Controller, Device, DeviceType, Trigger, TrigCondition, TrigResponse
from utils import get_local_ip


class Core:
    def __init__(self, db, mqtt_client=None, host='0.0.0.0'):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.otaServ = OTAServer()
        self._create_app()
        if host == '0.0.0.0':
            host = get_local_ip()
        self.host = host

    def _create_app(self):
        self.app = Flask(__name__)

        @self.app.route('/core_api/ota_start_update', methods=['POST'])
        def start_update_controllers():
            try:
                data = request.json

                if not data:
                    return jsonify({'error': 'No data provided'}), 400

                topics = data.get('topics')

                if not topics:
                    return jsonify({'error': 'topics field is required'}), 400

                #self.otaServ.start()

                if isinstance(topics, str) and topics == "AllESP":
                    self.mqtt_client.publish("AllESP", "update")
                elif isinstance(topics, list):
                    for topic in topics:
                        self.mqtt_client.publish(topic, "update")
                else:
                    self.mqtt_client.publish(topics, "update")

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
            # TODO Добавить проверку загрузки контроллера с новой версией и после подтверждения от всех остановить сервер

        @self.app.route('/core_api/load_files_on_ota', methods=['POST'])
        def upload_firmware():

            try:
                data = request.json

                if not data:
                    return jsonify({'error': 'No JSON data provided'}), 400

                firmware_path = data.get('firmware_path')
                version_path = data.get('version_path')

                if self.otaServ.is_running:
                    self.otaServ.stop()

                self.otaServ.file_mapping.clear()
                self.otaServ.add_binary_file('/firmware.bin', 'firmware.bin')
                self.otaServ.add_text_file('/version.txt', 'version.txt')

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

        @self.app.route('/core_api/send_mqtt_command', methods=['POST'])
        def send_mqtt_command():

            try:
                data = request.json

                if not data:
                    return jsonify({'error': 'No JSON data provided'}), 400

                # Получаем обязательные параметры
                controller_mac = data.get('controller_mac')
                device_id = data.get('device_id')
                command = data.get('command')

                # Валидация обязательных полей
                if not controller_mac:
                    return jsonify({'error': 'controller_mac is required'}), 400
                if device_id is None:
                    return jsonify({'error': 'device_id is required'}), 400
                if not command:
                    return jsonify({'error': 'command is required'}), 400

                value = data.get('value')

                device = self.db.get_device_by_id(device_id)

                req_parts = []
                req_parts.append(self.db.get_device_type_by_id(device.type_id).name)
                if device.port:
                    req_parts.append(device.port)
                if device.params:
                    req_parts.append(device.params)
                req_parts.append(command)
                if value:
                    req_parts.append(value)
                req = "/".join(req_parts)


                self.mqtt_client.publish(controller_mac, req)

                return jsonify({
                    'success': True,
                    'message': 'Command sended'
                }), 200

            except Exception as e:
                print(f"Error: {str(e)}")
                return jsonify({'error': str(e)}), 500


    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client



    def parse(self, topic, payload):

        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')
        controllers = self.db.get_all_controllers()

        if len(parts) >= 2:
            if parts[1] == "init":
                self.parse_init(controllers, parts)
            if parts[1] == "trig":
                self.parse_triggers(controllers, parts)
            if parts[1] == "states":
                self.parse_states(controllers, parts)


        # if payload == "40:91:51:51:97:3A/init":
        #     #self.mqtt_client.publish("40:91:51:51:97:3A", "update")
        #     self.mqtt_client.publish("40:91:51:51:97:3A", "connections/btn/15/relay/2")
        # if payload == "40:91:51:51:97:3A/trig":
        #     self.mqtt_client.publish("40:91:51:51:97:3A", "triggers/btn/15/value/equal/1/do/40:91:51:51:97:3A/relay/2/toggle/next")


    def process_messages(self):

        while not self.stop_event.is_set():
            try:
                if self.mqtt_client:
                    message = self.mqtt_client.get_message(block=False)

                    if message:
                        topic = message['topic']
                        payload = message['payload']
                        timestamp = message.get('timestamp', time.time())

                        time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S.%f')[:-3]
                        print(f"[Core] Обработка сообщения из очереди: {time_str} - {topic}: {payload}")

                        self.parse(topic, payload)

                    else:
                        time.sleep(0.01)
                else:
                    print("[Core] Ожидание установки MQTT клиента...")
                    time.sleep(1)

            except Exception as e:
                print(f"[Core] Ошибка при обработке сообщения: {e}")
                time.sleep(0.1)


    def start_processing(self, port):
        if self.running:
            print("[Core] Обработчик уже запущен")
            return False

        def run_flask():
            self.app.run(host=self.host, port=port, debug=False, use_reloader=False)
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()

        self.running = True
        self.stop_event.clear()
        self.processing_thread = threading.Thread(target=self.process_messages, daemon=True)
        self.processing_thread.start()
        print("[Core] Поток обработки сообщений запущен")
        return True

    def stop_processing(self):
        if not self.running:
            return

        print("[Core] Остановка обработчика сообщений...")
        self.stop_event.set()
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=5)
        self.running = False
        print("[Core] Обработчик сообщений остановлен")

    def send_message(self, topic, message, qos=0, retain=False):
        if self.mqtt_client:
            return self.mqtt_client.publish(topic, message, qos, retain)
        else:
            print("[Core] Ошибка: MQTT клиент не установлен")
            return False

    def get_stats(self):
        if self.mqtt_client and hasattr(self.mqtt_client, 'message_queue'):
            return {
                'queue_size': self.mqtt_client.message_queue.qsize(),
                'running': self.running,
                'mqtt_connected': self.mqtt_client.connected if hasattr(self.mqtt_client, 'connected') else False
            }
        return {'queue_size': 0, 'running': self.running, 'mqtt_connected': False}

    def parse_init(self, controllers, parts):
        print("init for ", parts[0])
        for controller in controllers:
            if parts[0] == controller.mac:
                devices = self.db.get_devices_by_controller(controller.id)
                req_parts = ["connections"]
                for device in devices:
                    req_parts.append(self.db.get_device_type_by_id(device.type_id).name)
                    if device.port:
                        req_parts.append(device.port)
                    if device.params:
                        req_parts.append(device.params)
                req = "/".join(req_parts)
                self.mqtt_client.publish(controller.mac, req)

    def parse_triggers(self, controllers, parts):
        for controller in controllers:
            if parts[0] == controller.mac:
                triggers = self.db.get_triggers_by_controller(controller.id)
                if len(triggers) > 0:
                    req_parts = ["triggers"]
                    condCount = 0
                    for trig in triggers:
                        trigConditions = self.db.get_trig_conditions_by_trigger(trig.id)
                        for cond in trigConditions:
                            if condCount > 0:
                                req_parts.append("and")
                            device = self.db.get_device_by_id(cond.device_id)
                            req_parts.append(self.db.get_device_type_by_id(device.type_id).name)
                            if device.port:
                                req_parts.append(device.port)
                            req_parts.append(cond.condition)
                            condCount += 1

                        req_parts.append("do")
                        req_parts.append(self.db.get_controller_by_id(trig.controller_resp_id).mac)
                        trigResps = self.db.get_trig_responses_by_trigger(trig.id)

                        for resp in trigResps:
                            device = self.db.get_device_by_id(resp.device_id)
                            req_parts.append(self.db.get_device_type_by_id(device.type_id).name)
                            if device.port:
                                req_parts.append(device.port)
                            req_parts.append(resp.resp)
                        req_parts.append("next")

                    req = "/".join(req_parts)
                    self.mqtt_client.publish(controller.mac, req)

    def parse_states(self, controllers, parts):
        for controller in controllers:
            if parts[0] == controller.mac:
                devices = self.db.get_devices_by_controller(controller.id)
                for device in devices:
                    for i in range(len(parts)):
                        if parts[i] == self.db.get_device_type_by_id(device.type_id).name:
                            print(parts[i+1])
