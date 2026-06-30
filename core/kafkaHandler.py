import os
import threading
from datetime import datetime
import uuid
from pathlib import Path

from dotenv import load_dotenv
from kafka.errors import KafkaError

from kafka_config import TOPICS, create_kafka_producer, create_kafka_consumer


class CoreKafkaHandler:

    def __init__(self, db, mqtt_client, ota_server, bootstrap_servers='localhost:9092'):
        self.db = db
        self.mqtt_client = mqtt_client
        self.ota_server = ota_server

        self.bootstrap_servers = bootstrap_servers

        self.producer = None
        self.consumer = None
        self.running = False
        self.consumer_thread = None

        self.init_callback = None

    def start(self):
        self.producer = create_kafka_producer(self.bootstrap_servers)

        topics_to_listen = [
            TOPICS['SEND_COMMAND'],
            TOPICS['INIT_CONTROLLER'],
            TOPICS['LOAD_FILE'],
            TOPICS['START_UPD_CONTROLLER'],
            TOPICS['UPD_DEVICE_TABLE'],
            TOPICS['UPD_TRIG_TABLE']
        ]

        self.consumer = create_kafka_consumer(
            topics=topics_to_listen,
            group_id='core-service-group',
            bootstrap_servers=self.bootstrap_servers
        )

        self.running = True
        self.consumer_thread = threading.Thread(target=self._consume_messages)
        self.consumer_thread.daemon = True
        self.consumer_thread.start()

        print("[Core Kafka] Started, listening for messages from interface")

    def stop(self):
        self.running = False
        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)
        if self.consumer:
            self.consumer.close()
        if self.producer:
            self.producer.flush()
            self.producer.close()
        print("[Core Kafka] Stopped")

    def set_init_callback(self, callback):
        self.init_callback = callback

    def _consume_messages(self):
        for message in self.consumer:
            if not self.running:
                break

            event_data = message.value
            if not event_data:
                continue

            event_type = event_data.get('event_type')
            topic = message.topic

            print(f"[Core Kafka] Received event: {event_type} from topic: {topic}")

            if topic == TOPICS['SEND_COMMAND']:
                self._handle_send_command(event_data)
            elif topic == TOPICS['LOAD_FILE']:
                self._handle_load_file(event_data)
            elif topic == TOPICS['INIT_CONTROLLER']:
                self._handle_init_controller(event_data)
            elif topic == TOPICS['START_UPD_CONTROLLER']:
                self._handle_start_ota_update(event_data)
            elif topic == TOPICS['UPD_DEVICE_TABLE']:
                self._handle_update_device_table(event_data)
            elif topic == TOPICS['UPD_TRIG_TABLE']:
                self._handle_update_trig_table(event_data)


    def _handle_send_command(self, message):
        data = message.get('data', {})
        controller_mac = data.get('controller_mac')
        device_id = data.get('device_id')
        command = data.get('command')
        value = data.get('value')

        print(f"[Core Kafka] Processing command: {command} for device {device_id}")

        try:
            device = self.db.get_device_by_id(device_id)
            if not device:
                print(f"[Core Kafka] Device {device_id} not found")
                return

            req_parts = []
            req_parts.append(device.type)
            if device.port:
                req_parts.append(device.port)
            if device.params:
                req_parts.append(device.params)
            req_parts.append(command)
            if value:
                req_parts.append(str(value))
            req = "/".join(req_parts)

            self.mqtt_client.publish(controller_mac, req)
            print(f"[Core Kafka] MQTT command sent to {controller_mac}: {req}")

        except Exception as e:
            print(f"[Core Kafka] Error processing command: {e}")

    def _handle_init_controller(self, message):
        data = message.get('data', {})
        controller_mac = data.get('controller_mac')
        command = data.get('command')
        try:
            if self.init_callback:
                self.init_callback([controller_mac])
                print(f"[Core Kafka] Start init controller")


        except Exception as e:
            print(f"[Core Kafka] Error start init: {e}")


    def _handle_load_file(self, message):
        data = message.get('data', {})
        firmware_path = data.get('firmware_path')
        version_path = data.get('version_path')

        print(f"[Core Kafka] Loading firmware files: {firmware_path}, {version_path}")

        try:
            if self.ota_server.is_running:
                self.ota_server.stop()

            self.ota_server.file_mapping.clear()
            self.ota_server.add_binary_file('/firmware.bin', firmware_path)
            self.ota_server.add_text_file('/version.txt', version_path)

            print(f"[Core Kafka] Files loaded successfully")

        except Exception as e:
            print(f"[Core Kafka] Error loading files: {e}")

    def _handle_start_ota_update(self, message):
        data = message.get('data', {})
        topics = data.get('topics')

        print(f"[Core Kafka] Starting OTA update for topics: {topics}")

        # if self.ota_server.is_running:
        #     self.ota_server.stop()
        self.ota_server.start()

        try:
            if isinstance(topics, str) and topics == "AllESP":
                self.mqtt_client.publish("AllESP", "update")
                devices = self.db.get_all_devices()
                uniqueMac = []
                for device in devices:
                    if device.controller_mac not in uniqueMac:
                        uniqueMac.append(device.controller_mac)
                        self.ota_server.add_running_update_controller(device.controller_mac)

            elif isinstance(topics, list):
                for topic in topics:
                    self.mqtt_client.publish(topic, "update")
                    self.ota_server.add_running_update_controller(topic)
            # else:
            #     self.mqtt_client.publish(topics, "update")

            print(f"[Core Kafka] OTA update started")

        except Exception as e:
            print(f"[Core Kafka] Error starting OTA update: {e}")

    def _handle_update_device_table(self, message):
        data = message.get('data', {})
        print(f"[Core Kafka] Updating device table with data: {data}")

        try:
            devices = data.get('devices', [])
            for device_data in devices:
                self.db.add_device(device_data)
                pass

            print(f"[Core Kafka] Device table updated successfully")
        except Exception as e:
            print(f"[Core Kafka] Error updating device table: {e}")

    def _handle_update_trig_table(self, message):
        data = message.get('data', {})
        print(f"[Core Kafka] Updating trigger table with data: {data}")

        try:
            triggers = data.get('triggers', [])
            for trigger_data in triggers:
                self.db.add_trigger(trigger_data)
                pass

            print(f"[Core Kafka] Trigger table updated successfully")
        except Exception as e:
            print(f"[Core Kafka] Error updating trigger table: {e}")

    def send_device_value_update(self, device_id, value, metadata=None):
        data = {
            'device_id': device_id,
            'value': value,
            'source': 'core_service'
        }
        message = self._kafka_handler_create_message('UPD_VAL_DEVICE', data)
        return self._kafka_handler_send_message(TOPICS['UPD_VAL_DEVICE'], 'upd_device_value', message)

    def send_device_status(self, device_id, status):
        data = {
            'device_id': device_id,
            'status': status,
            'source': 'core_service'
        }
        message = self._kafka_handler_create_message('UPD_DEVICE_STATUS', data)
        return self._kafka_handler_send_message(TOPICS['UPD_DEVICE_STATUS'], 'upd_device_status', message)

    def send_notification(self, message, type):
        data = {
            'message': message,
            'type': type,
            'source': 'core_service'
        }
        message = self._kafka_handler_create_message('NOTIFICATION', data)
        return self._kafka_handler_send_message(TOPICS['NOTIFICATION'], 'send_notification', message)

    def _kafka_handler_create_message(self, event_type, data):
        return {
            'event_id': str(uuid.uuid4()),
            'event_type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'source': 'core_service'
        }

    def _kafka_handler_send_message(self, topic, key, message):
        try:
            future = self.producer.send(topic, key=key, value=message)
            record_metadata = future.get(timeout=10)
            print(f"[Interface Kafka] Sent {message['event_type']} to {topic}, offset: {record_metadata.offset}")
            return True, record_metadata.offset
        except KafkaError as e:
            print(f"[Interface Kafka] Failed to send message: {e}")
            return False, None