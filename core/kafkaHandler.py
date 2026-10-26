import json
import threading
from datetime import datetime
import uuid
from kafka.errors import KafkaError

from database import Device, Trigger, Scene
from kafka_config import TOPICS, create_kafka_producer, create_kafka_consumer


def get_params(params):

    if not params:
        return False

    if isinstance(params, str):
        try:
            params = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            return False

    return isinstance(params, dict) and len(params) > 0


class CoreKafkaHandler:

    def __init__(self, db, mqtt_client, ota_server, bootstrap_servers='127.0.0.1:9092'):
        self.db = db
        self.mqtt_client = mqtt_client
        self.ota_server = ota_server

        self.bootstrap_servers = bootstrap_servers

        self.producer = None
        self.consumer = None
        self.running = False
        self.consumer_thread = None

        self.init_callback = None
        #self.recall_connections = None
        self.recall_triggers = None

    def start(self):
        self.producer = create_kafka_producer(self.bootstrap_servers)

        topics_to_listen = [
            TOPICS['SEND_COMMAND'],
            TOPICS['INIT_CONTROLLER'],
            TOPICS['LOAD_FILE'],
            TOPICS['START_UPD_CONTROLLER'],
            TOPICS['UPD_DEVICE_TABLE'],
            TOPICS['UPD_TRIG_TABLE'],
            TOPICS['UPD_SCENE_TABLE']
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

    def set_recall_triggers(self, callback):
        self.recall_triggers = callback
    #
    # def set_recall_connections(self, callback):
    #     self.recall_connections = callback

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
            elif topic == TOPICS['UPD_SCENE_TABLE']:
                self._handle_update_scene_table(event_data)

    def _handle_send_command(self, message):
        data = message.get('data', {})
        controller_mac = data.get('controller_mac')
        device_id = data.get('device_id')
        command = data.get('command')
        value = data.get('value')

        #TODO добавить поддержку нескольких команд для одного контроллера в одном сообщении

        print(f"[Core Kafka] Processing command: {command} for device {device_id}")

        try:
            device = self.db.get_device_by_id(device_id)
            if not device:
                print(f"[Core Kafka] Device {device_id} not found")
                return

            req_parts = []
            if controller_mac != 'serv':
                req_parts.append('exec')
            else:
                req_parts.append(device.controller_mac)
                req_parts.append('changeVal')

            req_parts.append(device.type)
            if device.port:
                req_parts.append(device.port)

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
            work_device = None
            if data.get('command_type') == 'DELETE':
                id = data.get('id')
                work_device = self.db.get_device_by_id(id)
                self.db.delete_device(id)
            else:
                device = Device(
                    id=data.get('id'),
                    controller_mac=data.get('controller_mac'),
                    port=data.get('port'),
                    params=data.get('params', '{}'),
                    type=data.get('type')
                )
                self.db.add_device(device)
                work_device = device
                self.db.update_device_current_values(device.id, [0])
                pass

            print(f"[Core Kafka] Device table updated successfully")

            if self.init_callback and work_device:
                self.init_callback([work_device.controller_mac])
        except Exception as e:
            print(f"[Core Kafka] Error updating device table: {e}")

    def _handle_update_trig_table(self, message):
        data = message.get('data', {})
        print(f"[Core Kafka] Updating trigger table with data: {data}")

        work_trig = None
        try:
            if data.get('command_type') == 'DELETE':
                id=data.get('id')
                work_trig = self.db.get_trigger_by_id(id)
                self.db.delete_trigger(id)
            elif data.get('command_type') == 'UPD_STATUS':
                work_trig = self.db.get_trigger_by_id(data.get('id'))
                self.db.update_trig_status(data.get('id'), data.get('is_active'))
            else:
                trig = Trigger(
                    id=data.get('id'),
                    controller_mac=data.get('controller_mac'),
                    trig=data.get('trig'),
                    is_active=data.get('is_active')
                )
                self.db.add_trigger(trig)
                work_trig = trig

                print(f"[Core Kafka] Trigger table updated successfully")
                pass

            if self.recall_triggers and work_trig:
                self.recall_triggers([work_trig.controller_mac])
        except Exception as e:
            print(f"[Core Kafka] Error updating trigger table: {e}")

    def _handle_update_scene_table(self, message):
        data = message.get('data', {})
        print(f"[Core Kafka] Updating scene table with data: {data}")

        try:
            if data.get('command_type') == 'DELETE':
                id=data.get('id')
                self.db.delete_scene(id)
            elif data.get('command_type') == 'UPD_STATUS':
                self.db.update_scene_status(data.get('id'), data.get('is_active'))
                scene = self.db.get_scene_by_id(data.get('id'))
                resp = scene.responses
                if isinstance(resp, str):
                    resp = json.loads(resp)
                has_change_cmd = any(
                    r.get("command") in ("changeVal/plus", "changeVal/minus")
                    for r in resp
                )
                if has_change_cmd:
                    cond = scene.conditions
                    if isinstance(cond, str):
                        cond = json.loads(cond)
                    for c in cond:
                        device_id = c.get("device_id")
                        param_num = c.get("param_num")
                        if device_id is not None and param_num is not None:
                            device = self.db.get_device_by_id(device_id)
                            if self.recall_triggers:
                                self.recall_triggers([device.controller_mac])
            else:
                scene = Scene(
                    id=data.get('id'),
                    conditions=data.get('conditions'),
                    responses=data.get('responses'),
                    is_active=data.get('is_active', True)
                )
                self.db.add_scene(scene)
                pass
            print(f"[Core Kafka] Scene table updated successfully")

        except Exception as e:
            print(f"[Core Kafka] Error updating scene table: {e}")

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
            record_metadata = future.get(timeout=35)
            print(f"[Interface Kafka] Sent {message['event_type']} to {topic}, offset: {record_metadata.offset}")
            return True, record_metadata.offset
        except KafkaError as e:
            print(f"[Interface Kafka] Failed to send message: {e}")
            return False, None