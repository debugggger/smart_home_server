
import threading
import time
import queue
from datetime import datetime

from otaServer import OTAServer


class Core:
    def __init__(self, db, mqtt_client=None):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.stop_event = threading.Event()
        self.otaServ = OTAServer()

    def start_update_controllers(self, topics):
        if self.otaServ.is_running:
            self.otaServ.stop()

        # Очищаем старые файлы и добавляем новые
        self.otaServ.file_mapping.clear()  # Очищаем старые маппинги
        self.otaServ.add_binary_file('/firmware.bin', 'firmware.bin')
        self.otaServ.add_text_file('/version.txt', 'version.txt')
        self.otaServ.start()
        # self.otaServ.add_binary_file('/firmware.bin', 'firmware.bin')
        # self.otaServ.add_text_file('/version.txt', 'version.txt')
        # self.otaServ.start()
        for topic in topics:
            self.mqtt_client.publish(topic, "update")

        #TODO Добавить проверку загрузки контроллера с новой версией и после подтверждения от всех остановить сервер

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client



    def parse(self, topic, payload):

        # TODO: Добавить логику обработки сообщений
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")

        parts = payload.split('/')

        controllers = self.db.get_all_controllers()

        if len(parts) >= 2:
            if parts[1] == "init":
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
            if parts[1] == "trig":
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