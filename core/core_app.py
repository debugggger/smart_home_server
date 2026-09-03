import json
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import requests
from flask import Flask, jsonify, request

from otaServer import OTAServer
from sh_utils import get_local_ip


@dataclass
class ControllerState:
    """Состояние контроллера в оперативной памяти"""
    mac: str
    prev_resp_time: datetime = field(default_factory=datetime.now)
    is_waiting_init: bool = False
    is_active: bool = True
    failures_count: int = 0
    last_message: str = ""


@dataclass
class DeviceState:
    """Состояние устройства в оперативной памяти"""
    device_id: int
    controller_mac: str
    is_waiting_confirm: bool = False
    prev_resp_time: datetime = field(default_factory=datetime.now)
    failures_count: int = 0
    offline_count: int = 0  # Счетчик последовательных неудач
    is_active: bool = True  # Активно ли устройство
    is_offline: bool = False  # Оффлайн ли устройство
    last_message: str = ""


class Core:
    def __init__(self, db, mqtt_client=None, ota_serv=None, kafka_handler=None):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.thread_controller = None  # Поток для контроля контроллеров
        self.stop_event = threading.Event()
        self.otaServ = ota_serv
        self.kafka_handler = kafka_handler

        # Состояния контроллеров (mac -> ControllerState)
        self.controllers_state: Dict[str, ControllerState] = {}

        # Состояния устройств (device_id -> DeviceState)
        self.devices_state: Dict[int, DeviceState] = {}

        # Очереди ожидания ответа
        self.mac_wait_request_init = []  # Список MAC контроллеров ожидающих init
        self.mac_wait_request_update = []  # Список устройств ожидающих update

        # Настройки
        self.TIMEOUT_SECONDS = 10
        self.GET_VALUES_DELAY = 60
        self.MAX_FAILURES = 3

        # Инициализируем состояния из БД
        self._init_states_from_db()

    def _init_states_from_db(self):
        """Инициализация состояний из данных БД"""
        devices = self.db.get_all_devices()

        for device in devices:
            # Создаем состояние устройства
            self.devices_state[device.id] = DeviceState(
                device_id=device.id,
                controller_mac=device.controller_mac,
                is_waiting_confirm=False,
                prev_resp_time=datetime.now(),
                failures_count=0,
                offline_count=0,
                is_active=True,
                is_offline=False,
                last_message=""
            )

            # Создаем состояние контроллера если его нет
            if device.controller_mac not in self.controllers_state:
                self.controllers_state[device.controller_mac] = ControllerState(
                    mac=device.controller_mac,
                    prev_resp_time=datetime.now(),
                    is_waiting_init=False,
                    is_active=True,
                    failures_count=0,
                    last_message=""
                )

        print(
            f"[Core] Инициализировано состояний: {len(self.devices_state)} устройств, {len(self.controllers_state)} контроллеров")

    def _get_device_state(self, device_id: int) -> Optional[DeviceState]:
        """Получить состояние устройства"""
        return self.devices_state.get(device_id)

    def _get_controller_state(self, mac: str) -> Optional[ControllerState]:
        """Получить состояние контроллера"""
        return self.controllers_state.get(mac)

    def _is_device_active(self, device_id: int) -> bool:
        """Проверить активно ли устройство"""
        state = self._get_device_state(device_id)
        return state.is_active if state else False

    def _is_controller_active(self, mac: str) -> bool:
        """Проверить активен ли контроллер"""
        state = self._get_controller_state(mac)
        return state.is_active if state else False

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client

    def parse(self, topic, payload):
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')

        if len(parts) >= 2:
            mac = parts[0]

            # Обновляем время ответа контроллера
            ctrl_state = self._get_controller_state(mac)
            if ctrl_state:
                ctrl_state.prev_resp_time = datetime.now()
                # Если контроллер был неактивен - активируем
                if not ctrl_state.is_active:
                    ctrl_state.is_active = True
                    ctrl_state.failures_count = 0
                    print(f"[Core] Контроллер {mac} восстановлен")

            if parts[1] == "init":
                if self.otaServ and self.otaServ.is_running:
                    self.otaServ.delete_running_update_controller(mac)
                self.parse_init(parts)

            elif parts[1] == "trig":
                self.parse_triggers(parts)

            elif parts[1] == "changeVal":
                self.parse_changes(parts)

            elif parts[1] == "execResp":
                self._parse_exec_response(parts)

            elif parts[1] == "initResp":
                self._parse_init_response(parts)

    def _parse_exec_response(self, parts):
        """Обработка ответа на выполнение команды"""
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)

        index = 2
        while index < len(parts) - 1:
            status = parts[index]

            if status == "ok":
                device_type = parts[index + 1]
                device_port = parts[index + 2] if index + 2 < len(parts) else None

                for device in devices:
                    if device.port == device_port and device.type == device_type:
                        dev_state = self._get_device_state(device.id)
                        if dev_state:
                            dev_state.is_waiting_confirm = False
                            dev_state.prev_resp_time = datetime.now()
                            dev_state.failures_count = 0
                            dev_state.offline_count = 0
                        break
                index += 3

            elif status == "values":
                self.parse_states(parts)
                index += 1  # Уже обработано в parse_states
            else:
                print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                break

    def _parse_init_response(self, parts):
        """Обработка ответа на инициализацию"""
        mac = parts[0]

        # Убираем из очереди ожидания
        for i, request in enumerate(self.mac_wait_request_init):
            if request["mac"] == mac:
                devices = self.db.get_devices_by_controller(mac)
                error_devices = []
                index = 2

                while index < len(parts) - 1:
                    status = parts[index]

                    if status == "ok":
                        device_type = parts[index + 1]
                        device_port = parts[index + 2] if index + 2 < len(parts) else None

                        for j, device in enumerate(devices):
                            if device.port == device_port and device.type == device_type:
                                del devices[j]
                                break
                        index += 3

                    elif status == "error":
                        device_type = parts[index + 1]
                        device_port = parts[index + 2] if index + 2 < len(parts) else None
                        error_message = parts[index + 3] if index + 3 < len(parts) else None

                        error_devices.append({
                            "type": device_type,
                            "port": device_port,
                            "message": error_message
                        })

                        if self.kafka_handler:
                            self.kafka_handler.send_notification(
                                f"Контроллер {mac} ошибка инициализации устройства {device_type}: {error_message}",
                                'error'
                            )
                        print(
                            f"[Core Error] Ошибка инициализации в контроллере {mac}: устройство {device_type}, ошибка: {error_message}")

                        if device_port and device_port.isdigit():
                            for j, device in enumerate(devices):
                                if device.port == device_port and device.type == device_type:
                                    del devices[j]
                                    break
                        index += 4
                    else:
                        print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                        break

                # Проверяем оставшиеся устройства
                if len(devices) != 0:
                    for device in devices:
                        print(
                            f"[Core Error] Ошибка инициализации в контроллере: {device.controller_mac}, устройство {device.type}, порт {device.port}")
                        if self.kafka_handler:
                            self.kafka_handler.send_notification(
                                f"Контроллер {mac} устройство {device.type} порт {device.port} не подтвердило инициализацию",
                                'warning'
                            )

                # Сбрасываем флаг ожидания init у контроллера
                ctrl_state = self._get_controller_state(mac)
                if ctrl_state:
                    ctrl_state.is_waiting_init = False

                self.mac_wait_request_init.pop(i)
                break

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

        # Поток обработки MQTT сообщений
        self.processing_thread = threading.Thread(target=self.process_messages, daemon=True)
        self.processing_thread.start()

        # Поток контроля устройств
        self.thread_controller = threading.Thread(target=self._control_devices, daemon=True)
        self.thread_controller.start()

        if self.kafka_handler:
            self.kafka_handler.set_init_callback(self.parse_init)

        # Инициализация устройств
        self.init_devices()

        print("[Core] Потоки обработки запущены")
        return True

    def stop_processing(self):
        if not self.running:
            return

        print("[Core] Остановка обработчиков...")
        self.stop_event.set()

        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=5)

        if self.thread_controller and self.thread_controller.is_alive():
            self.thread_controller.join(timeout=5)

        self.running = False
        print("[Core] Обработчики остановлены")

    def send_message(self, topic, message, qos=0, retain=False):
        if self.mqtt_client:
            return self.mqtt_client.publish(topic, message, qos, retain)
        else:
            print("[Core] Ошибка: MQTT клиент не установлен")
            return False

    def parse_init(self, parts):
        """Отправка инициализации контроллеру"""
        mac = parts[0] if isinstance(parts, list) else parts
        devices = self.db.get_devices_by_controller(mac)

        req_parts = ["connections"]
        for device in devices:
            req_parts.append(device.type)
            if device.port:
                req_parts.append(device.port)
            if device.params and isinstance(device.params, dict):

                params = '/'.join(device.params.values())
                req_parts.append(params)
            req_parts.append("next")

        req = "/".join(req_parts)
        self.mqtt_client.publish(mac, req)

        # Устанавливаем флаг ожидания для контроллера
        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_init = True
            ctrl_state.prev_resp_time = datetime.now()

        # Добавляем в очередь ожидания init
        self.mac_wait_request_init.append({"mac": mac})

    def parse_triggers(self, parts):
        """Отправка триггеров контроллеру"""
        mac = parts[0]
        req_parts = ["triggers"]
        triggers = self.db.get_triggers_by_controller(mac)

        for trigger in triggers:
            req_parts.append(trigger.trig)
            req_parts.append("next")

        req = "/".join(req_parts)
        if len(parts) > 2:
            self.mqtt_client.publish(mac, req)

    def parse_states(self, parts):
        """Обработка состояний устройств"""
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)
        dev_with_values = {}

        startValIdx = 1
        for i in range(len(parts)):
            if parts[i] == "next" and i - startValIdx == 4:
                startValIdx = i
                for device in devices:
                    if device.type == parts[i - 4] and device.port == parts[i - 3]:
                        # Обновляем значения
                        param_idx = int(parts[i - 2]) if parts[i - 2].isdigit() else parts[i - 2]
                        if isinstance(device.current_values, list):
                            if isinstance(param_idx, int) and param_idx < len(device.current_values):
                                device.current_values[param_idx] = parts[i - 1]
                            else:
                                # Если индекс не подходит, добавляем как новое значение
                                device.current_values.append(parts[i - 1])
                        else:
                            device.current_values = [parts[i - 1]]

                        dev_with_values[device.id] = device

        # Обновляем БД и отправляем уведомления
        for device_id, device in dev_with_values.items():
            self.db.update_device_current_values(device_id, device.current_values)

            if self.kafka_handler:
                self.kafka_handler.send_device_value_update(device_id, device.current_values)

            self.check_scene(device_id)

            # Сбрасываем счетчики ошибок устройства
            dev_state = self._get_device_state(device_id)
            if dev_state:
                dev_state.failures_count = 0
                dev_state.offline_count = 0
                dev_state.prev_resp_time = datetime.now()

                # Если устройство было оффлайн - восстанавливаем
                if dev_state.is_offline:
                    dev_state.is_offline = False
                    dev_state.is_active = True
                    if self.kafka_handler:
                        self.kafka_handler.send_device_status(device_id, True)

    def parse_changes(self, parts):
        """Обработка изменений от контроллера"""
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)

        for device in devices:
            if device.type == parts[2] and device.port == parts[3]:
                if len(parts) > 5 and parts[5] == 'addOne':
                    param_idx = int(parts[4]) if parts[4].isdigit() else 0
                    if isinstance(device.current_values, list) and param_idx < len(device.current_values):
                        try:
                            device.current_values[param_idx] = str(int(device.current_values[param_idx]) + 1)
                        except:
                            device.current_values[param_idx] = "0"
                    else:
                        device.current_values = ["0"]

                self.db.update_device_current_values(device.id, device.current_values)

                if self.kafka_handler:
                    self.kafka_handler.send_device_value_update(device.id, device.current_values)

                # Сбрасываем счетчики ошибок
                dev_state = self._get_device_state(device.id)
                if dev_state:
                    dev_state.failures_count = 0
                    dev_state.prev_resp_time = datetime.now()

    def _control_devices(self):
        """
        Поток контроля устройств и контроллеров

        Логика:
        1. Для контроллеров время ответа от которых более задержки - принудительно отправить запрос
        2. Для устройств у которых стоит флаг ожидания ответа - если ответа нет спустя время ожидания, пробуем еще раз
        3. При отсутствии ответа 3 раза - меняем is_active устройства
        4. Если все устройства не активны - меняем is_active контроллера
        5. Для неактивных контроллеров раз в период отправки пытаемся отправить запрос состояния
        """
        while self.running:
            try:
                current_time = datetime.now()

                # Получаем все устройства
                devices = self.db.get_all_devices()

                # Собираем активные устройства по контроллерам для проверки
                active_devices_by_controller: Dict[str, List[int]] = {}

                for device in devices:
                    device_id = device.id
                    mac = device.controller_mac

                    # Получаем состояние устройства
                    dev_state = self._get_device_state(device_id)
                    if not dev_state:
                        continue

                    # Получаем состояние контроллера
                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state:
                        continue

                    # Собираем активные устройства по контроллерам
                    if dev_state.is_active:
                        if mac not in active_devices_by_controller:
                            active_devices_by_controller[mac] = []
                        active_devices_by_controller[mac].append(device_id)

                    # === 1. Проверка устройств с истекшим временем ожидания ===
                    time_since_resp = (current_time - dev_state.prev_resp_time).total_seconds()

                    # Если устройство ожидает подтверждения и время истекло
                    if dev_state.is_waiting_confirm and time_since_resp > self.TIMEOUT_SECONDS:
                        if dev_state.failures_count < self.MAX_FAILURES:
                            # Повторная отправка
                            if dev_state.last_message:
                                self.mqtt_client.publish(mac, dev_state.last_message)
                                dev_state.prev_resp_time = datetime.now()
                                dev_state.failures_count += 1
                                print(
                                    f"[Core] Повторная отправка устройству {device_id}: {dev_state.last_message} (попытка {dev_state.failures_count})")
                        else:
                            # Превышено количество попыток - помечаем устройство как неактивное
                            if dev_state.is_active:
                                dev_state.is_active = False
                                if self.kafka_handler:
                                    self.kafka_handler.send_notification(
                                        f"Устройство {device_id} (тип: {device.type}) отключено после {self.MAX_FAILURES} неудачных попыток",
                                        'error'
                                    )
                                print(f"[Core] Устройство {device_id} отключено")

                            dev_state.is_waiting_confirm = False
                            dev_state.failures_count = 0

                    # === 2. Проверка контроллеров - принудительный запрос состояний ===
                    ctrl_time_since_resp = (current_time - ctrl_state.prev_resp_time).total_seconds()

                    if ctrl_state.is_active and ctrl_time_since_resp > self.GET_VALUES_DELAY:
                        # Отправляем запрос состояния для всех устройств контроллера
                        if not dev_state.is_waiting_confirm and dev_state.is_active:
                            message = f'exec/{device.type}/{device.port}/getValue/0'
                            self.mqtt_client.publish(mac, message)

                            dev_state.is_waiting_confirm = True
                            dev_state.prev_resp_time = datetime.now()
                            dev_state.last_message = message

                            print(f"[Core] Принудительный запрос состояния: {message} -> {mac}")

                # === 3. Проверка контроллеров на активность ===
                for mac, ctrl_state in self.controllers_state.items():
                    if ctrl_state.is_active:
                        # Проверяем есть ли активные устройства у этого контроллера
                        active_count = len(active_devices_by_controller.get(mac, []))

                        if active_count == 0:
                            # Проверяем есть ли вообще устройства у контроллера
                            controller_devices = self.db.get_devices_by_controller(mac)
                            if len(controller_devices) > 0:
                                ctrl_state.is_active = False
                                if self.kafka_handler:
                                    self.kafka_handler.send_notification(
                                        f"Контроллер {mac} деактивирован (все устройства неактивны)",
                                        'warning'
                                    )
                                print(f"[Core] Контроллер {mac} деактивирован")

                    # === 4. Восстановление неактивных контроллеров ===
                    if not ctrl_state.is_active:
                        # Пытаемся восстановить контроллер
                        ctrl_state.failures_count += 1

                        if ctrl_state.failures_count % 5 == 0:  # Каждые 5 циклов (5 секунд)
                            # Пытаемся отправить запрос инициализации
                            self.parse_init(mac)
                            print(f"[Core] Попытка восстановления контроллера {mac}")

                # === 5. Проверка очереди ожидания update ===
                current_time_ts = time.time()
                for request in self.mac_wait_request_update[:]:
                    if current_time_ts - request["timestamp"] > self.TIMEOUT_SECONDS:
                        device_id = request["device_id"]
                        self.mac_wait_request_update.remove(request)

                        dev_state = self._get_device_state(device_id)
                        if dev_state:
                            dev_state.offline_count += 1

                            if dev_state.offline_count >= self.MAX_FAILURES and not dev_state.is_offline:
                                dev_state.is_offline = True
                                dev_state.is_active = False
                                if self.kafka_handler:
                                    self.kafka_handler.send_device_status(device_id, False)
                                    self.kafka_handler.send_notification(
                                        f"Устройство {device_id} не отвечает",
                                        'error'
                                    )
                                print(f"[Core] Устройство {device_id} помечено как offline")

                time.sleep(1)  # Проверка раз в секунду

            except Exception as e:
                print(f"[Core] Ошибка в control_devices: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

    def init_devices(self):
        """Инициализация всех устройств"""
        unique_mac = set()
        devices = self.db.get_all_devices()

        for device in devices:
            if device.controller_mac not in unique_mac:
                unique_mac.add(device.controller_mac)
                self.parse_init([device.controller_mac])

    def check_scene(self, device_id: int):
        """Проверка сценариев для устройства"""
        try:
            device = self.db.get_device_by_id(device_id)
            if not device:
                return

            current_values = device.current_values
            if not current_values:
                return

            scenes = self.db.get_all_scenes()
            active_scenes = [s for s in scenes if s.is_active]

            if not active_scenes:
                return

            for scene in active_scenes:
                conditions = self._parse_scene_conditions(scene.conditions)
                if not conditions:
                    continue

                all_conditions_met = True

                for condition in conditions:
                    cond_device_id = condition.get('device_id')
                    param_num = condition.get('param_num')
                    is_execute = condition.get('is_execute', True)

                    if not is_execute:
                        continue

                    if cond_device_id == device_id:
                        if param_num is not None and param_num < len(current_values):
                            check_value = current_values[param_num]
                        else:
                            check_value = None
                    else:
                        check_value = self._get_device_parameter_value(cond_device_id, param_num)

                    if not self._check_condition_value(condition, check_value):
                        all_conditions_met = False
                        break

                if all_conditions_met:
                    if not scene.is_executed:
                        self._execute_scene_actions(scene)
                        self.db.update_scene_executed(scene.id, True)
                        print(f"[Core] Scene {scene.id} executed successfully")
                        if self.kafka_handler:
                            self.kafka_handler.send_notification(
                                'SCENE_EXECUTED',
                                f'Сценарий выполнен',
                                {'scene_id': scene.id}
                            )
                else:
                    if scene.is_executed:
                        self.db.update_scene_executed(scene.id, False)

        except Exception as e:
            print(f"[Core] Error checking scenes: {e}")
            import traceback
            traceback.print_exc()

    def _parse_scene_conditions(self, conditions_json):
        try:
            if isinstance(conditions_json, str):
                return json.loads(conditions_json)
            elif isinstance(conditions_json, list):
                return conditions_json
            return []
        except:
            return []

    def _check_condition_value(self, condition, current_value):
        compare_type = condition.get('compare_type')
        value = condition.get('value')
        is_execute = condition.get('is_execute', False)

        if not is_execute:
            return True

        if compare_type == 'changed':
            return True

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
                return current_val >= check_val
        except:
            if compare_type == 'equal':
                return str(current_value) == str(value)
            elif compare_type == 'more':
                return str(current_value) > str(value)
            elif compare_type == 'less':
                return str(current_value) < str(value)

        return False

    def _get_device_parameter_value(self, device_id: int, param_num: int):
        if device_id is None or param_num is None:
            return None

        device = self.db.get_device_by_id(device_id)
        if device and device.current_values:
            try:
                values = device.current_values
                if values and param_num < len(values):
                    return values[param_num]
            except:
                pass
        return None

    def _execute_scene_actions(self, scene):
        try:
            responses = self._parse_scene_responses(scene.responses)
            if not responses:
                return

            for response in responses:
                mac = response.get('mac')
                device_type = response.get('device_type')
                device_port = response.get('device_port')
                command = response.get('command')
                value = response.get('value')

                if mac and command:
                    cmd_parts = [device_type, device_port, command]
                    if value:
                        cmd_parts.append(value)
                    cmd_str = "/".join(cmd_parts)

                    self.mqtt_client.publish(mac, cmd_str)
                    print(f"[Core] Executed action: {cmd_str} -> {mac}")

        except Exception as e:
            print(f"[Core] Error executing scene actions: {e}")

    def _parse_scene_responses(self, responses_json):
        try:
            if isinstance(responses_json, str):
                return json.loads(responses_json)
            elif isinstance(responses_json, list):
                return responses_json
            return []
        except:
            return []