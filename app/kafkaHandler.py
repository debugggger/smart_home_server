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
        self.app_api_device_value_update_callback = None
        self.app_api_device_status_update_callback = None
        self.app_api_notification_callback = None

        self.notifications = []
        self.max_notifications = 10

    def start(self):
        self.producer = create_kafka_producer(self.bootstrap_servers)

        self.consumer = create_kafka_consumer(
            topics=[TOPICS['UPD_VAL_DEVICE'],
                    TOPICS['UPD_DEVICE_STATUS'],
                    TOPICS['NOTIFICATION']
                    ],
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


    #INPUT HANDLERS
    def _consume_messages(self):
        for message in self.consumer:
            if not self.running:
                break

            event_data = message.value
            if not event_data:
                continue

            event_type = event_data.get('event_type')

            if event_type == 'UPD_VAL_DEVICE' and self.app_api_device_value_update_callback:
                self._handle_upd_value(event_data)
            elif event_type == 'UPD_DEVICE_STATUS' and self.app_api_device_status_update_callback:
                self._handle_upd_status(event_data)
            elif event_type == 'NOTIFICATION' and self.app_api_notification_callback:
                self._handle_notification(event_data)
            else:
                print(f"[Interface Kafka] Unknown or unhandled event: {event_type}")

    def _handle_upd_value(self, message):
        data = message.get('data', {})
        print(f"[App Kafka] Updating device table with data: {data}")

        try:
            id = data.get('device_id')
            value = data.get('value')
            self.db.update_device_current_values(id, value)

            if self.app_api_device_value_update_callback:
                self.app_api_device_value_update_callback(id, value)

            print(f"[App Kafka] Device table updated successfully")
        except Exception as e:
            print(f"[App Kafka] Error updating device table: {e}")

    def _handle_upd_status(self, message):
        data = message.get('data', {})
        print(f"[App Kafka] Updating device table with data: {data}")

        try:
            id = data.get('device_id')
            status = data.get('status')
            self.db.update_device_status(id, status)

            if self.app_api_device_status_update_callback:
                self.app_api_device_status_update_callback(id, status)

            print(f"[App Kafka] Device table updated successfully")
        except Exception as e:
            print(f"[App Kafka] Error updating device table: {e}")

    def send_command(self, controller_mac, device_id, command, value=None):
        command_data = {
            'controller_mac': controller_mac,
            'device_id': device_id,
            'command': command
        }
        if value is not None and value != '':
            command_data['value'] = value
        message = self._kafka_handler_create_message('SEND_COMMAND', command_data)

        return self._kafka_handler_send_message(TOPICS['SEND_COMMAND'], controller_mac, message)

    def init_controller(self, controller_mac):
        command_data = {
            'controller_mac': controller_mac,
            'command': 'init'
        }
        message = self._kafka_handler_create_message('INIT_CONTROLLER', command_data)
        return self._kafka_handler_send_message(TOPICS['INIT_CONTROLLER'], controller_mac, message)

    def load_files(self, firmware_path, version_path):
        message = self._kafka_handler_create_message('LOAD_FILE', {
            'firmware_path': firmware_path,
            'version_path': version_path
        })
        return self._kafka_handler_send_message(TOPICS['LOAD_FILE'], 'firmware_update', message)

    def start_ota_update(self, topics):
        message = self._kafka_handler_create_message('START_UPD_CONTROLLER', {
            'topics': topics
        })
        return self._kafka_handler_send_message(TOPICS['START_UPD_CONTROLLER'], 'ota_update', message)

    def update_device_table(self, device_data):
        message = self._kafka_handler_create_message('UPD_DEVICE_TABLE', device_data)
        return self._kafka_handler_send_message(TOPICS['UPD_DEVICE_TABLE'], 'device_data', message)

    def update_trig_table(self, trigger_data):
        message = self._kafka_handler_create_message('UPD_TRIG_TABLE', trigger_data)
        return self._kafka_handler_send_message(TOPICS['UPD_TRIG_TABLE'], 'trigger_data', message)

    def _handle_notification(self, message):
        data = message.get('data', {})
        notification_type = data.get('type')
        toast_message = data.get('message')

        print(f"[Interface Kafka] Notification: {notification_type} - {toast_message}")

        notification = {
            'id': len(self.notifications) + 1,
            'type': notification_type,
            'message': toast_message,
            'timestamp': datetime.now().isoformat(),
            'is_read': False
        }

        self.notifications.insert(0, notification)

        if len(self.notifications) > self.max_notifications:
            self.notifications.pop()

        if self.app_api_notification_callback:
            self.app_api_notification_callback(notification)

    def get_notifications(self, limit=10):
        """Получить последние уведомления"""
        return self.notifications[:limit]

    def mark_notification_read(self, notification_id):
        """Отметить уведомление как прочитанное"""
        for notification in self.notifications:
            if notification['id'] == notification_id:
                notification['is_read'] = True
                return True
        return False

    def clear_notifications(self):
        """Очистить все уведомления"""
        self.notifications = []
        print("[Interface Kafka] All notifications cleared")

    def _kafka_handler_create_message(self, event_type, data):
        return {
            'event_id': str(uuid.uuid4()),
            'event_type': event_type,
            'timestamp': datetime.now().isoformat(),
            'data': data,
            'source': 'interface_service'
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