import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from kafka.errors import KafkaError

from kafka_config import TOPICS, create_kafka_producer, create_kafka_consumer


class AppKafkaHandler:

    def __init__(self, db, bootstrap_servers='localhost:9092'):
        self.db = db
        self.bootstrap_servers = bootstrap_servers

        self.producer = None
        self.consumer = None
        self.running = False
        self.consumer_thread = None

        self.value_update_callback = None

    def start(self):
        self.producer = create_kafka_producer(self.bootstrap_servers)

        self.consumer = create_kafka_consumer(
            topics=[TOPICS['UPD_VAL_DEVICE']],
            group_id='interface-service-group',
            bootstrap_servers=self.bootstrap_servers
        )

        self.running = True
        self.consumer_thread = threading.Thread(target=self._consume_messages)
        self.consumer_thread.daemon = True
        self.consumer_thread.start()

        print("[Interface Kafka] Started, listening for device value updates")

    def stop(self):
        self.running = False
        if self.consumer_thread:
            self.consumer_thread.join(timeout=5)
        if self.consumer:
            self.consumer.close()
        if self.producer:
            self.producer.flush()
            self.producer.close()
        print("[Interface Kafka] Stopped")

    def _handle_upd_value(self, callback):
        print("обновление данных текущего значения устройства")

    def _consume_messages(self):
        for message in self.consumer:
            if not self.running:
                break

            event_data = message.value
            if not event_data:
                continue

            event_type = event_data.get('event_type')

            if event_type == 'UPD_VAL_DEVICE' and self.value_update_callback:
                self._handle_upd_value(event_data.get('data', {}))
            else:
                print(f"[Interface Kafka] Unknown or unhandled event: {event_type}")

    def send_command(self, controller_mac, device_id, command, value=None):
        command_data = {
            'controller_mac': controller_mac,
            'device_id': device_id,
            'command': command
        }
        if value is not None and value != '':
            command_data['value'] = value
        message = self._create_message('SEND_COMMAND', command_data)

        return self._send_message(TOPICS['SEND_COMMAND'], controller_mac, message)

    def load_files(self, firmware_path, version_path):
        message = self._create_message('LOAD_FILE', {
            'firmware_path': firmware_path,
            'version_path': version_path
        })

        return self._send_message(TOPICS['LOAD_FILE'], 'firmware_update', message)

    def start_ota_update(self, topics):
        message = self._create_message('START_UPD_CONTROLLER', {
            'topics': topics
        })

        return self._send_message(TOPICS['START_UPD_CONTROLLER'], 'ota_update', message)

    def update_device_table(self, device_data):
        message = self._create_message('UPD_DEVICE_TABLE', device_data)

        return self._send_message(TOPICS['UPD_DEVICE_TABLE'], 'device_data', message)

    def update_trig_table(self, trigger_data):
        message = self._create_message('UPD_TRIG_TABLE', trigger_data)

        return self._send_message(TOPICS['UPD_TRIG_TABLE'], 'trigger_data', message)


    def _create_message(self, event_type, data):
        return {
            'event_id': str(uuid.uuid4()),
            'event_type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'source': 'interface_service'
        }

    def _send_message(self, topic, key, message):
        try:
            future = self.producer.send(topic, key=key, value=message)
            record_metadata = future.get(timeout=10)
            print(f"[Interface Kafka] Sent {message['event_type']} to {topic}, offset: {record_metadata.offset}")
            return True, record_metadata.offset
        except KafkaError as e:
            print(f"[Interface Kafka] Failed to send message: {e}")
            return False, None