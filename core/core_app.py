import json
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

        self.mac_wait_request_update = []
        self.mac_wait_request_init = []

        self.device_failure_counters = {}
        self.device_offline_status = {}

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
                # self.device_offline_status[device_id] = True
                # self.kafka_handler.send_device_status(device_id, False)
                self.kafka_handler.send_notification(f"Контроллер {parts[0]} ошибка {parts[1]}", 'error')
                print(f"[Core Error] Ошибка в контроллере: {parts}")
            if parts[1] == "ok":
                if parts[2] == "init":
                    for i, request in enumerate(self.mac_wait_request_init):
                        if request["mac"] == parts[0]:
                            devices = self.db.get_devices_by_controller(request["mac"])
                            matched_indices = []
                            for j in range(len(parts)):
                                for k, device in enumerate(devices):
                                    if device.port == parts[j] and device.type == parts[j - 1] if j > 0 else False:
                                        matched_indices.append(k)
                                        break
                            for k in sorted(matched_indices, reverse=True):
                                del devices[k]
                            if len(devices) != 0:
                                for device in devices:
                                    print(f"[Core Error] Ошибка инициализации в контроллере: {device.controller_mac}, устройство {device.type}, порт {device.port}")

                            self.mac_wait_request_init.pop(i)

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

        self.kafka_handler.set_init_callback(self.parse_init)

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
                params = '/'.join(device.params.values())
                req_parts.append(params)
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
        if len(parts) > 1:
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
            self.check_scene(device.id)

            if device.id in self.device_failure_counters:
                self.device_failure_counters[device.id] = 0
                print(f"[CORE] Устройство {device.id} ответило, счетчик ошибок сброшен")

            if self.device_offline_status.get(device.id, False):
                self.device_offline_status[device.id] = False
                self.kafka_handler.send_device_status(device.id, True)


                # self._send_single_device_status_update(device.id, mac, True)
                #
                # # Отправляем уведомление о восстановлении
                # self._send_device_online_notification(device.id, mac)

    def parse_changes(self, parts):
        devices = self.db.get_devices_by_controller(parts[0])
        for device in devices:
            if device.type == parts[2] and device.port == parts[3]:
                if parts[5] == 'addOne':
                    device.current_values[parts[4]] = str(int(device.current_values[parts[4]])+1)

            self.db.update_device_current_values(device.id, device.current_values)
            self.kafka_handler.send_device_value_update(device.id, device.current_values)


    def request_states(self):
        timeout_seconds = 1 #время ожидания ответа от контроллера
        get_controller_values_delay = 2 #частота отпарвки запроса
        MAX_FAILURES = 5

        while self.running:
            start_time = time.time()

            try:
                devices = self.db.get_all_devices()

                for device in devices:
                    mac = device.controller_mac
                    device_id = device.id

                    if not self._is_device_waiting(device_id):
                        request_data = {
                            "device_id": device_id,
                            "mac": mac,
                            "sending_time": datetime.now().isoformat(),
                            "timestamp": time.time()
                        }
                        self.mac_wait_request_update.append(request_data)
                        self.mqtt_client.publish(mac, f'{device.type}/{device.port}/getValue')

                        if device_id not in self.device_failure_counters:
                            self.device_failure_counters[device_id] = 0
                            self.device_offline_status[device_id] = False

            except Exception as e:
                print(f"[CORE] Ошибка при отправке MQTT: {e}")

            elapsed = time.time() - start_time
            sleep_time = max(0, get_controller_values_delay - elapsed)

            for _ in range(int(sleep_time)):
                if not self.running:
                    break

                current_time = time.time()

                for request in self.mac_wait_request_update[:]:
                    if current_time - request["timestamp"] > timeout_seconds:
                        device_id = request["device_id"]
                        mac = request["mac"]
                        self.mac_wait_request_update.remove(request)

                        if device_id not in self.device_failure_counters:
                            self.device_failure_counters[device_id] = 0

                        if self.device_failure_counters[device_id] < MAX_FAILURES:
                            self.device_failure_counters[device_id] += 1
                            # print(
                            #     f"[CORE] Устройство {device_id} на {mac} нет ответа")

                        if self.device_failure_counters[device_id] >= MAX_FAILURES:
                            if not self.device_offline_status.get(device_id, False):
                                self.device_offline_status[device_id] = True
                                self.kafka_handler.send_device_status(device_id, False)
                                self.kafka_handler.send_notification(f"Устройство {device_id} на {mac} нет ответа", 'error')

                time.sleep(1)

    def _is_device_waiting(self, device_id):
        for request in self.mac_wait_request_update:
            if request["device_id"] == device_id:
                return True
        return False

    def init_devices(self):
        unique_mac = []
        devices = self.db.get_all_devices()
        for device in devices:
            if device.controller_mac not in unique_mac:
                unique_mac.append(device.controller_mac)
                self.parse_init([device.controller_mac])
                #self.parse_triggers([device.controller_mac])

    # core/core_app.py

    def check_scene(self, device_id: int):
        """
        Проверка всех сценариев при обновлении устройства

        Args:
            device_id: ID устройства, которое обновилось
        """
        try:
            # Получаем устройство со всеми его значениями
            device = self.db.get_device_by_id(device_id)
            if not device:
                return

            # Получаем все параметры устройства
            current_values = device.current_values
            if not current_values:
                return

            # Получаем все активные сценарии
            scenes = self.db.get_all_scenes()
            active_scenes = [s for s in scenes if s.is_active]

            if not active_scenes:
                return

            # Для каждого активного сценария проверяем условия
            for scene in active_scenes:
                # Парсим условия из JSON
                conditions = self._parse_scene_conditions(scene.conditions)
                if not conditions:
                    continue

                # Проверяем все ли условия выполнены
                all_conditions_met = True

                for condition in conditions:
                    cond_device_id = condition.get('device_id')
                    param_num = condition.get('param_num')
                    is_execute = condition.get('is_execute', True)

                    # Если is_execute = False, пропускаем это условие
                    if not is_execute:
                        continue

                    # Получаем значение для проверки
                    check_value = None

                    # Если условие относится к текущему устройству
                    if cond_device_id == device_id:
                        if param_num is not None and param_num < len(current_values):
                            check_value = current_values[param_num]
                    else:
                        # Получаем значение из БД для другого устройства
                        check_value = self._get_device_parameter_value(cond_device_id, param_num)

                    # Проверяем условие
                    if not self._check_condition_value(condition, check_value):
                        all_conditions_met = False
                        break

                # Если все условия выполнены
                if all_conditions_met:
                    if not scene.executed:
                        # Выполняем действия сценария
                        self._execute_scene_actions(scene)
                        # Отмечаем сценарий как выполненный
                        self.db.update_scene_executed(scene.id, True)
                        print(f"[Core] Scene {scene.id} executed successfully")
                        # Отправляем уведомление о выполнении
                        self.kafka_handler.send_notification(
                            'SCENE_EXECUTED',
                            f'Сценарий "{scene.name}" выполнен',
                            {'scene_id': scene.id}
                        )
                else:
                    # Если условия не выполнены, сбрасываем флаг выполнения
                    if scene.executed:
                        self.db.update_scene_executed(scene.id, False)

        except Exception as e:
            print(f"[Core] Error checking scenes: {e}")
            import traceback
            traceback.print_exc()

    def _parse_scene_conditions(self, conditions_json):
        """Парсинг условий сценария из JSON"""
        try:
            if isinstance(conditions_json, str):
                return json.loads(conditions_json)
            elif isinstance(conditions_json, list):
                return conditions_json
            return []
        except:
            return []

    def _check_condition_value(self, condition, current_value):
        """
        Проверка значения по условию

        Args:
            condition: словарь с условием
            current_value: текущее значение для проверки

        Returns:
            bool: True если условие выполнено
        """
        compare_type = condition.get('compare_type')
        value = condition.get('value')
        is_execute = condition.get('is_execute', False)

        # Если is_execute = True, то это условие должно быть выполнено для активации сценария
        # Если is_execute = False, то это условие игнорируется при проверке

        if not is_execute:
            # Если is_execute = False, условие не проверяется
            return True

        if compare_type == 'changed':
            # Для changed проверяем, изменилось ли значение
            return True  # Значение уже изменилось, так как мы получили новое

        if current_value is None:
            return False

        try:
            current_val = float(current_value)
            check_val = float(value) if value else 0

            if compare_type == 'equal':
                return current_val == check_val
            elif compare_type == 'more':
                return current_val > check_val
            elif compare_type == 'less':
                return current_val < check_val
            elif compare_type == 'time':
                # Для времени проверяем, прошло ли заданное время
                return current_val >= check_val
        except:
            # Если не число - сравниваем как строки
            if compare_type == 'equal':
                return str(current_value) == str(value)
            elif compare_type == 'more':
                return str(current_value) > str(value)
            elif compare_type == 'less':
                return str(current_value) < str(value)

        return False

    def _get_device_current_value(self, device_id):
        """Получение текущего значения устройства из БД"""
        if device_id is None:
            return None

        device = self.db.get_device_by_id(device_id)
        if device and device.current_values:
            try:
                values = json.loads(device.current_values)
                if values and len(values) > 0:
                    return values[0]  # Берем первое значение
            except:
                pass
        return None

    def _get_device_parameter_value(self, device_id: int, param_num: int):
        """
        Получение значения конкретного параметра устройства из БД

        Args:
            device_id: ID устройства
            param_num: номер параметра (parameter_number)

        Returns:
            значение параметра или None
        """
        if device_id is None or param_num is None:
            return None

        device = self.db.get_device_by_id(device_id)
        if device and device.current_values:
            try:
                if isinstance(device.current_values, str):
                    values = json.loads(device.current_values)
                else:
                    values = device.current_values

                if values and param_num < len(values):
                    return values[param_num]
            except:
                pass
        return None

    def _execute_scene_actions(self, scene):
        """Выполнение действий сценария"""
        try:
            # Парсим ответы из JSON
            responses = self._parse_scene_responses(scene.responses)
            if not responses:
                return

            for response in responses:
                mac = response.get('mac')
                device_type = response.get('device_type')
                device_port = response.get('device_port')
                command = response.get('command')
                value = response.get('value')

                # Формируем команду для отправки через MQTT
                if mac and command:
                    # Формируем сообщение: device_type/port/command/value
                    cmd_parts = [device_type, device_port, command]
                    if value:
                        cmd_parts.append(value)
                    cmd_str = "/".join(cmd_parts)

                    # Отправляем через MQTT
                    self.mqtt_client.publish(mac, cmd_str)
                    print(f"[Core] Executed action: {cmd_str} -> {mac}")

        except Exception as e:
            print(f"[Core] Error executing scene actions: {e}")

    def _parse_scene_responses(self, responses_json):
        """Парсинг ответов сценария из JSON"""
        try:
            if isinstance(responses_json, str):
                return json.loads(responses_json)
            elif isinstance(responses_json, list):
                return responses_json
            return []
        except:
            return []

