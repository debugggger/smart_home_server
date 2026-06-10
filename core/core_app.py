import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, request

from otaServer import OTAServer
from utils import get_local_ip

class Core:
    def __init__(self, db, mqtt_client=None, host='0.0.0.0', ota_serv=None):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.otaServ = ota_serv

        if host == '0.0.0.0':
            host = get_local_ip()
        self.host = host

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client

    def parse(self, topic, payload):
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')


        if len(parts) >= 2:
            if parts[1] == "init":
                self.parse_init(parts)
            if parts[1] == "trig":
                self.parse_triggers(parts)
            if parts[1] == "states":
                self.parse_states(parts)

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

    def start_processing(self):
        if self.running:
            print("[Core] Обработчик уже запущен")
            return False

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

    def parse_init(self, parts):

        print("init for ", parts[0])

        devices = self.db.get_all_devices()
        req_parts = ["connections"]
        for device in devices:
            if parts[0] == device.controller_mac:
                req_parts.append(device.type)
                if device.port:
                    req_parts.append(device.port)
                if device.params:
                    req_parts.append(device.params)
                    #req_parts.append("next")
                    #TODO как для триггеров добавить разделитель next

        req = "/".join(req_parts)
        self.mqtt_client.publish(parts[0], req)

    def parse_triggers(self, parts):

        req_parts = ["triggers"]
        triggers = self.db.get_all_triggers()
        for trigger in triggers:
            if parts[0] == trigger.controller_mac:
                req_parts.append(trigger.trig)
                req_parts.append("next")

        req = "/".join(req_parts)
        self.mqtt_client.publish(parts[0], req)

    def parse_states(self, parts):

        devices = self.db.get_all_devices()
        for device in devices:
            if parts[0] == device.controller_mac:
                for i in range(len(parts)):
                    if parts[i] == self.db.get_device_type_by_id(device.type_id).name:
                        print(parts[i + 1])