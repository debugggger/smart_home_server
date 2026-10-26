import json
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import requests
from flask import Flask, jsonify, request


@dataclass
class ControllerState:
    mac: str
    prev_resp_time: datetime = field(default_factory=datetime.now)
    is_waiting_init: bool = False
    is_active: bool = True
    failures_count: int = 0
    last_message: str = ""
    # Ожидание ответа на getFirmwareVersion (для OTA-контроллеров)
    is_waiting_fw_version: bool = False


@dataclass
class DeviceState:
    device_id: int
    controller_mac: str
    is_waiting_confirm: bool = False
    prev_resp_time: datetime = field(default_factory=datetime.now)
    failures_count: int = 0
    is_active: bool = True
    last_message: str = ""
    params_count: int = 0


def parse_number(value):
    try:
        f = float(value)
    except (ValueError, TypeError):
        return value
    return int(f) if f.is_integer() else f


class Core:
    def __init__(self, db, mqtt_client=None, ota_serv=None, kafka_handler=None):
        self.db = db
        self.mqtt_client = mqtt_client
        self.running = False
        self.processing_thread = None
        self.thread_controller = None
        self.stop_event = threading.Event()
        self.otaServ = ota_serv
        self.kafka_handler = kafka_handler

        self.controllers_state: Dict[str, ControllerState] = {}

        self.devices_state: Dict[int, DeviceState] = {}

        self.mac_wait_request_init = []  # Список MAC контроллеров ожидающих init
        self.mac_wait_request_update = []  # Список устройств ожидающих update

        self.TIMEOUT_SECONDS = 3
        self.GET_VALUES_DELAY = 60 * 1
        self.MAX_FAILURES = 3

        self._init_states_from_db()

    def _init_states_from_db(self):
        devices = self.db.get_all_devices()

        for device in devices:
            self.devices_state[device.id] = DeviceState(
                device_id=device.id,
                controller_mac=device.controller_mac,
                is_waiting_confirm=False,
                prev_resp_time=datetime.now(),
                failures_count=0,
                is_active=True,
                last_message="",
                params_count=0
            )

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
        return self.devices_state.get(device_id)

    def _get_controller_state(self, mac: str) -> Optional[ControllerState]:
        return self.controllers_state.get(mac)

    def _is_device_active(self, device_id: int) -> bool:
        state = self._get_device_state(device_id)
        return state.is_active if state else False

    def _is_controller_active(self, mac: str) -> bool:
        state = self._get_controller_state(mac)
        return state.is_active if state else False

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client

    def parse(self, topic, payload):
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')
        parts = [p for p in parts if p.strip()]

        if len(parts) >= 2:
            mac = parts[0]

            ctrl_state = self._get_controller_state(mac)
            if ctrl_state:
                ctrl_state.prev_resp_time = datetime.now()
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

            elif parts[1] == "trigResp":
                self._parse_trig_response(parts)

            elif parts[1] == "getFirmwareVersionResp":
                self._parse_firmware_version_response(parts)

    def _parse_exec_response(self, parts):
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)

        index = 1
        while index < len(parts) - 2:
            index += 1
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
                            dev_state.is_active = True
                            if self.kafka_handler:
                                self.kafka_handler.send_device_status(device.id, True)
                        break
                #index += 4
                while parts[index] != "next":
                    if index == len(parts):
                        print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                        break
                    index += 1

            elif status == "values":
                self.parse_states(parts)
                break
            else:
                print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                break

    def parse_error_content(self, content):

        content = content.strip()
        original = content

        patterns = [
            r'Trigger\s+[\'"]?(\d+)[\'"]?',
            r'trigger\s+[\'"]?(\d+)[\'"]?',
            r'"(\d+)"',  # "1", "5"
            r"'(\d+)'",  # '3'
            r'\[(\d+)\]',  # [5]
            r'\((\d+)\)',  # (2)
            r'\b(\d+)\b'  # Любое отдельное число (в конце, чтобы не сработать случайно)
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                trig_num = match.group(1)
                # Удаляем ВСЮ найденную подстроку (а не только число)
                start, end = match.span()
                # Убираем эту часть из текста
                cleaned_text = content[:start] + content[end:]
                # Чистим от лишних пробелов и символов
                cleaned_text = re.sub(r'[/:;,.]$', '', cleaned_text).strip()
                return trig_num, cleaned_text

        return None, original.strip()

    def _parse_trig_response(self, parts):
        mac = parts[0]

        # if request["mac"] == mac:
        triggers = self.db.get_triggers_by_controller(mac)
        index = 1

        while index < len(parts) - 2:
            index += 1
            if parts[index] == "":
                index += 1
            status = parts[index]

            index += 1

            if status == "ok":
                trig_num = parts[index]
                #print(f"[Core] Триггер: {triggers[int(trig_num)-1].id} создан")

            elif status == "error":
                num, text = self.parse_error_content(parts[index])

                if not num:
                    #print(f"[Core error] Триггер: {triggers[num - 1].id} не создан, ошибка {text}")
                    print(f"[Core error] Ошибка при создании триггера на контроллере {mac}: {text}")

            else:
                print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                break
            while parts[index] != "next":
                if index == len(parts):
                    print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                    break
                index += 1

    def _parse_init_response(self, parts):
        """Обработка ответа на инициализацию"""
        mac = parts[0]

        # Убираем из очереди ожидания
        for i, request in enumerate(self.mac_wait_request_init):
            if request["mac"] == mac:
                devices = self.db.get_devices_by_controller(mac)
                error_devices = []
                index = 1

                while index < len(parts) - 2:
                    index += 1
                    status = parts[index]

                    if status == "ok":
                        device_type = parts[index + 1]
                        device_port = parts[index + 2] if index + 2 < len(parts) else None

                        for j, device in enumerate(devices):
                            if device.port == device_port and device.type == device_type:
                                del devices[j]
                                dev_state = self._get_device_state(device.id)
                                if not dev_state:
                                    self._init_states_from_db()
                                dev_state.params_count = int(parts[index + 3])

                                break
                        # while parts[index] != "next":
                        #     if index == len(parts):
                        #         print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                        #         break
                        #     index += 1

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

                    else:
                        print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                        break

                    # index += 4
                    while parts[index] != "next":
                        if index == len(parts):
                            print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                            break
                        index += 1

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

    def _parse_firmware_version_response(self, parts):
        """
        Обработка ответа на запрос версии прошивки.
        Формат: <mac>/getFirmwareVersionResp/<version>
        """
        mac = parts[0]
        version = parts[2] if len(parts) > 2 else None

        print(f"[Core] Контроллер {mac} сообщил версию прошивки: {version}")

        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_fw_version = False
            ctrl_state.prev_resp_time = datetime.now()

        # Если контроллер есть в списке обновляемых — удаляем его
        if self.otaServ and self.otaServ.is_running:
            self.otaServ.delete_running_update_controller(mac)
            print(f"[Core] Контроллер {mac} удалён из очереди обновления после ответа о версии")

        if self.kafka_handler:
            self.kafka_handler.send_notification(
                f"Контроллер {mac} версия прошивки: {version}",
                'info'
            )

    def _handle_fw_version_timeout(self, mac: str):
        """
        Обработка ситуации, когда контроллер не ответил на getFirmwareVersion
        после MAX_FAILURES попыток. Сообщаем в интерфейс и удаляем из очереди обновления.
        """
        print(
            f"[Core] Контроллер {mac} не ответил на getFirmwareVersion "
            f"после {self.MAX_FAILURES} попыток — удаляем из очереди обновления"
        )

        # Сообщение в интерфейс (Kafka)
        if self.kafka_handler:
            try:
                self.kafka_handler.send_notification(
                    f"Контроллер {mac} не отвечает на запрос версии прошивки "
                    f"после {self.MAX_FAILURES} попыток. Удалён из очереди обновления.",
                    'error'
                )
            except Exception as e:
                print(f"[Core] Ошибка отправки уведомления в Kafka: {e}")

        # Удаляем из очереди обновления OTA-сервера
        if self.otaServ and getattr(self.otaServ, "is_running", False):
            try:
                self.otaServ.delete_running_update_controller(mac)
            except Exception as e:
                print(f"[Core] Ошибка удаления контроллера {mac} из очереди OTA: {e}")

        # Сбрасываем состояние контроллера
        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_fw_version = False
            ctrl_state.failures_count = 0
            ctrl_state.prev_resp_time = datetime.now()

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
                        #print(f"[Core] Обработка сообщения из очереди: {time_str} - {topic}: {payload}")

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

        # Поток контроля устройств
        self.thread_controller = threading.Thread(target=self._control_devices, daemon=True)
        self.thread_controller.start()

        if self.kafka_handler:
            self.kafka_handler.set_init_callback(self.parse_init)
            self.kafka_handler.set_recall_triggers(self.parse_triggers)

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
        mac = parts[0] if isinstance(parts, list) else parts
        devices = self.db.get_devices_by_controller(mac)

        req_parts = ["connections"]
        for device in devices:
            req_parts.append(device.type)
            if device.port:
                req_parts.append(device.port)
            if device.params:
                if isinstance(device.params, str):
                    device.params = json.loads(device.params)
                for key, value in device.params.items():
                    if value not in (None, "", []):
                        req_parts.append(str(value))

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
            if trigger.is_active:
                req_parts.append(trigger.trig)
                req_parts.append("next")

        devices = self.db.get_devices_by_controller(mac)

        for device in devices:
            dev_state = self._get_device_state(device.id)

            for param_num in range(dev_state.params_count):
                req_parts.append(device.type)
                req_parts.append(device.port)
                req_parts.append(f"value/{param_num}/onChange/do")
                req_parts.append(device.controller_mac)
                req_parts.append("getValue")
                req_parts.append(device.type)
                req_parts.append(device.port)
                req_parts.append(f"{param_num}/next")

        req = "/".join(req_parts)
        if len(req_parts) >= 2:
            self.mqtt_client.publish(mac, req)

    def parse_states(self, parts):
        """Обработка состояний устройств"""
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)
        dev_with_values = {}

        startValIdx = 1
        for i in range(len(parts)):
            if parts[i] == "next":
                startValIdx = i - 5
                for device in devices:
                    if device.type == parts[i - 5] and device.port == parts[i - 4]:
                        # Обновляем значения
                        param_idx = int(parts[i - 2]) if parts[i - 2].isdigit() else parts[i - 2]

                        if isinstance(device.current_values, list):
                            if isinstance(param_idx, int) and param_idx < len(device.current_values):
                                device.current_values[param_idx] = parse_number(parts[i - 1])
                            else:
                                device.current_values.append(parse_number(parts[i - 1]))
                        else:
                            device.current_values[0] = [parse_number(parts[i - 1])]

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
                dev_state.prev_resp_time = datetime.now()

                dev_state.is_active = True
                if self.kafka_handler:
                    self.kafka_handler.send_device_status(device_id, True)

    def parse_changes(self, parts):
        """Обработка изменений от контроллера"""
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)

        for device in devices:
            if device.type == parts[2] and device.port == parts[3]:
                if len(parts) > 6:
                    param_idx = int(parts[4])
                    while param_idx >= len(device.current_values):
                        device.current_values.append("0")
                    if isinstance(device.current_values, list):
                        try:
                            if parts[5] == 'plus':
                                device.current_values[param_idx] = str(int(device.current_values[param_idx]) + int(parts[6]))
                            elif parts[5] == 'minus':
                                device.current_values[param_idx] = str(
                                    int(device.current_values[param_idx]) - int(parts[5]))
                            elif parts[5] == 'setStartValue':
                                device.current_values[param_idx] = str(int(parts[6]))
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
        6. Если контроллер в очереди OTA-обновления и не отвечает — запрашиваем версию прошивки
        """
        while self.running:
            try:
                current_time = datetime.now()

                # Получаем все устройства
                devices = self.db.get_all_devices()

                # Собираем активные устройства по контроллерам для проверки
                active_devices_by_controller: Dict[str, List[int]] = {}

                all_controllers_mac: List[str] = []

                for device in devices:
                    device_id = device.id
                    mac = device.controller_mac

                    if mac not in all_controllers_mac:
                        all_controllers_mac.append(mac)

                    dev_state = self._get_device_state(device_id)
                    if not dev_state:
                        continue

                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state:
                        continue

                    if dev_state.is_active:
                        if mac not in active_devices_by_controller:
                            active_devices_by_controller[mac] = []
                        active_devices_by_controller[mac].append(device_id)

                    # === 1. Проверка устройств с истекшим временем ожидания ===
                    time_since_resp = (current_time - dev_state.prev_resp_time).total_seconds()

                    if dev_state.is_waiting_confirm and time_since_resp > self.TIMEOUT_SECONDS:
                        if dev_state.failures_count < self.MAX_FAILURES:
                            if dev_state.last_message:
                                self.mqtt_client.publish(mac, dev_state.last_message)
                                dev_state.prev_resp_time = datetime.now()
                                dev_state.failures_count += 1
                                print(
                                    f"[Core] Повторная отправка устройству {device_id}: {dev_state.last_message} (попытка {dev_state.failures_count})")
                        else:
                            if dev_state.is_active:
                                dev_state.is_active = False
                                if self.kafka_handler:
                                    self.kafka_handler.send_device_status(device_id, False)
                                    self.kafka_handler.send_notification(
                                        f"Устройство {device_id} (тип: {device.type}) отключено после {self.MAX_FAILURES} неудачных попыток",
                                        'error'
                                    )
                                print(f"[Core] Устройство {device_id} отключено")

                            dev_state.is_waiting_confirm = False
                            dev_state.failures_count = 0

                for mac in all_controllers_mac:
                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state:
                        continue
                    ctrl_time_since_resp = (current_time - ctrl_state.prev_resp_time).total_seconds()

                    # === 2.1. Проверка ожидания инициализации контроллера ===
                    if ctrl_state.is_waiting_init and ctrl_time_since_resp > self.TIMEOUT_SECONDS:
                        if ctrl_state.failures_count < self.MAX_FAILURES and ctrl_state.is_active:

                            ctrl_state.failures_count += 1
                            ctrl_state.last_message = f"Повторная инициализация (попытка {ctrl_state.failures_count})"
                            self.parse_init(mac)
                            ctrl_state.prev_resp_time = datetime.now()
                            print(
                                f"[Core] Повторная инициализация контроллера {mac} "
                                f"(попытка {ctrl_state.failures_count}/{self.MAX_FAILURES})"
                            )
                        elif ctrl_state.failures_count >= self.MAX_FAILURES and ctrl_state.is_active:
                            if self.kafka_handler and ctrl_state.is_active:
                                self.kafka_handler.send_notification(
                                    f"Контроллер {mac} деактивирован: не подтвердил инициализацию "
                                    f"после {self.MAX_FAILURES} попыток",
                                    'error'
                                )
                            print(
                                f"[Core] Контроллер {mac} деактивирован после "
                                f"{self.MAX_FAILURES} неудачных попыток инициализации"
                            )
                            ctrl_state.is_active = False
                            ctrl_state.is_waiting_init = False
                            ctrl_state.failures_count = 0

                            for device in self.db.get_devices_by_controller(mac):
                                dev_state = self._get_device_state(device.id)
                                if dev_state and dev_state.is_active:
                                    dev_state.is_active = False
                                    dev_state.is_waiting_confirm = False
                                    dev_state.failures_count = 0

                                    if self.kafka_handler:
                                        self.kafka_handler.send_device_status(device.id, False)
                                    print(f"[Core] Устройство {device.id} деактивировано (контроллер {mac} недоступен)")

                            self.mac_wait_request_init = [
                                r for r in self.mac_wait_request_init if r["mac"] != mac
                            ]
                            continue

                    # === 2.2. Проверка контроллеров в очереди OTA-обновления ===
                    is_in_ota_queue = (
                        self.otaServ is not None
                        and getattr(self.otaServ, "is_running", False)
                        and self.otaServ.is_controller_in_update_queue(mac)
                    )

                    if is_in_ota_queue:
                        if ctrl_state.is_waiting_fw_version:
                            if ctrl_time_since_resp > self.TIMEOUT_SECONDS:
                                if ctrl_state.failures_count < self.MAX_FAILURES:
                                    ctrl_state.failures_count += 1
                                    message = "getFirmwareVersion"
                                    self.mqtt_client.publish(mac, message)
                                    ctrl_state.prev_resp_time = datetime.now()
                                    print(
                                        f"[Core] Повторный запрос версии прошивки у контроллера {mac} "
                                        f"(попытка {ctrl_state.failures_count}/{self.MAX_FAILURES})"
                                    )
                                else:
                                    # Исчерпаны все попытки — сообщаем и удаляем из очереди
                                    self._handle_fw_version_timeout(mac)
                            # Пока ждём ответ на getFirmwareVersion — не шлём getAllValues
                            continue
                        else:
                            # Только что обнаружили, что контроллер в OTA-очереди и молчит
                            if ctrl_time_since_resp > self.GET_VALUES_DELAY:
                                message = "getFirmwareVersion"
                                self.mqtt_client.publish(mac, message)
                                ctrl_state.prev_resp_time = datetime.now()
                                ctrl_state.is_waiting_fw_version = True
                                ctrl_state.failures_count = 0
                                print(f"[Core] Запрос версии прошивки (OTA): {message} -> {mac}")
                                continue

                    # === 2.3. Обычный запрос состояния (вне OTA) ===
                    if ctrl_state.is_active and ctrl_time_since_resp > self.GET_VALUES_DELAY:
                        message = f'exec/getAllValues/'
                        self.mqtt_client.publish(mac, message)

                        ctrl_state.prev_resp_time = datetime.now()

                        print(f"[Core] Принудительный запрос состояния: {message} -> {mac}")

                    # === 3. Проверка контроллеров на активность ===
                    if ctrl_state.is_active:
                        active_count = len(active_devices_by_controller.get(mac, []))

                        if active_count == 0:
                            ctrl_state.is_active = False
                            if self.kafka_handler:
                                self.kafka_handler.send_notification(
                                    f"Контроллер {mac} деактивирован (все устройства неактивны)",
                                    'warning'
                                )
                            print(f"[Core] Контроллер {mac} деактивирован")

                    # === 4. Восстановление неактивных контроллеров ===
                    if not ctrl_state.is_active and ctrl_time_since_resp > self.GET_VALUES_DELAY:
                        ctrl_state.prev_resp_time = datetime.now()
                        self.parse_init(mac)
                        print(f"[Core] Попытка восстановления контроллера {mac}")

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

                executed_count = 0

                for condition in conditions:
                    cond_device_id = condition.get('device_id')
                    param_num = condition.get('param_num')
                    is_execute = condition.get('is_execute', True)

                    if cond_device_id == device_id:
                        if param_num is not None and param_num < len(current_values):
                            check_value = current_values[param_num]
                        else:
                            check_value = None

                        is_execute = self._check_condition_value(condition, check_value)
                        condition['is_execute'] = is_execute
                        if not is_execute:
                            break
                        executed_count += 1
                    else:
                        continue

                if executed_count == len(conditions):
                    if not scene.is_executed:
                        self._execute_scene_actions(scene)
                        self.db.update_scene_executed(scene.id, True)
                        print(f"[Core] Scene {scene.id} executed successfully")
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

                if mac == "serv":
                    device = self.db.get_device_by_id(response.get('target_device_id'))
                    device_param = response.get('param_num')
                    if device and device_param:
                        command = command.split("/")[-1]
                        self.parse_changes([device.controller_mac, 'changeVal', device.type, device.port, device_param, command, value])

                elif mac and command:
                    cmd_parts = ["exec", device_type, device_port, command]
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