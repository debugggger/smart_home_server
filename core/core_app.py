import threading
import time
from datetime import datetime

import requests
from flask import Flask, jsonify, request

from otaServer import OTAServer
from sh_utils import get_local_ip

class Core:
    def __init__(self, db, mqtt_client=None, ota_serv=None, kafka_handler=None):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.thread_request = None
        self.stop_event = threading.Event()
        self.otaServ = ota_serv
        self.kafka_handler = kafka_handler
        self.get_controller_values_delay = 30
        self.mac_wait_request_update = []
        self.mac_wait_request_init = []

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client

    def parse(self, topic, payload):
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')

        if len(parts) >= 2:
            if parts[1] == "init":
                if self.otaServ.is_running:
                    self.otaServ.delete_running_update_controller(parts[0])
                self.parse_init(parts)
            if parts[1] == "trig":
                self.parse_triggers(parts)
            if parts[1] == "value":
                self.parse_states(parts)
                for i, request in enumerate(self.mac_wait_request_update):
                    if request["mac"] == parts[0]:
                        self.mac_wait_request_update.pop(i)
            if parts[1] == "changeVal":
                self.parse_changes(parts)
            if parts[1] == "error":
                print(f"[Core Error] Ошибка в контроллере: {parts}")
            if parts[1] == "ok":
                if parts[2] == "init":
                    for i, request in enumerate(self.mac_wait_request_init):
                        if request["mac"] == parts[0]:
                            self.mac_wait_request_init.pop(i)
                            #TODO распарсить ответ и проверить что все устройства проинициализированы

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

        self.thread_request = threading.Thread(target=self.request_states, daemon=True)
        self.thread_request.start()

        self.init_devices()

        print("[Core] Поток обработки сообщений запущен")
        return True

    def stop_processing(self):
        if not self.running:
            return

        print("[Core] Остановка обработчика сообщений...")
        self.stop_event.set()
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=5)

        if self.thread_request and self.thread_request.is_alive():
            self.thread_request.join(timeout=5)

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

        devices = self.db.get_devices_by_controller(parts[0])
        req_parts = ["connections"]
        for device in devices:
            req_parts.append(device.type)
            if device.port:
                req_parts.append(device.port)
            if device.params:
                req_parts.append(device.params)
                req_parts.append("next")

        req = "/".join(req_parts)
        self.mqtt_client.publish(parts[0], req)

    def parse_triggers(self, parts):

        req_parts = ["triggers"]
        triggers = self.db.get_triggers_by_controller(parts[0])
        for trigger in triggers:
            req_parts.append(trigger.trig)
            req_parts.append("next")

        req = "/".join(req_parts)
        self.mqtt_client.publish(parts[0], req)

    def parse_states(self, parts):
        #mac/type1/port/val_type1/val/next/type1/port/val_type2/val/next
        devices = self.db.get_devices_by_controller(parts[0])
        dev_with_values = {}
        startValIdx = 1
        for i in range(len(parts)):
            if parts[i] == "next" and i - startValIdx == 4:
                startValIdx = i
                for device in devices:
                    if device.type == parts[i-4] and device.port == parts[i-3]:
                        device.current_values.insert(parts[i-2], parts[i-1])
                        dev_with_values[device.id] = device

        for device in dev_with_values.values():
            self.db.update_device_current_values(device.id, device.current_values)
            self.kafka_handler.send_device_value_update(device.id, device.current_values)

    def parse_changes(self, parts):
        devices = self.db.get_devices_by_controller(parts[0])
        for device in devices:
            if device.type == parts[2] and device.port == parts[3]:
                if parts[5] == 'addOne':
                    device.current_values[parts[4]] = str(int(device.current_values[parts[4]])+1)

            self.db.update_device_current_values(device.id, device.current_values)
            self.kafka_handler.send_device_value_update(device.id, device.current_values)

    def request_states(self):

        timeout_seconds = 60
        while self.running:
            start_time = time.time()

            try:

                devices = self.db.get_all_devices()
                for device in devices:
                    if device.controller_mac not in self.mac_wait_request_update:
                        request_data = {
                            "mac": device.controller_mac,
                            "sending_time": datetime.now().isoformat(),
                            "timestamp": time.time()
                        }
                        self.mac_wait_request_update.append(request_data)
                        self.mqtt_client.publish(device.controller_mac, 'getAllValues')

            except Exception as e:
                print(f"Ошибка при отправке MQTT: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0, self.get_controller_values_delay - elapsed)

            for _ in range(int(sleep_time)):
                if not self.running:
                    break

                current_time = time.time()

                for request in self.mac_wait_request_update[:]:
                    if current_time - request["timestamp"] > timeout_seconds:
                        self.mac_wait_request_update.remove(request)
                        print(f"[CORE] {request['mac']} нет ответа состояния устройства")

                time.sleep(1)

    def init_devices(self):
        unique_mac = []
        devices = self.db.get_all_devices()
        for device in devices:
            if device.controller_mac not in unique_mac:
                unique_mac.append(device.controller_mac)
                self.parse_init([device.controller_mac])
                self.parse_triggers([device.controller_mac])