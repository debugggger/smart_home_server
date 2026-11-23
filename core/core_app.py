import json
import re
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from flask import Flask, jsonify, request


@dataclass
class ControllerState:
    mac: str
    prev_resp_time: datetime = field(default_factory=datetime.now)
    is_waiting_init: bool = False
    is_active: bool = True
    failures_count: int = 0
    last_message: str = ""
    fw_version: str = ""
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

        self.mac_wait_request_init = []       # MAC контроллеров, ожидающих init
        self.mac_wait_request_update = []     # Устройства, ожидающих update

        self.TIMEOUT_SECONDS = 3
        self.GET_VALUES_DELAY = 60 * 1
        self.MAX_FAILURES = 3
        # Устройство считается «молчащим», если от него не было данных дольше этого времени.
        # Должно быть заметно больше периода опроса getAllValues, чтобы не ложно срабатывать.
        self.DEVICE_SILENCE_TIMEOUT = self.GET_VALUES_DELAY * 3

        self._init_states_from_db()

    # ------------------------------------------------------------------ #
    # Инициализация состояний
    # ------------------------------------------------------------------ #
    def _init_states_from_db(self):
        devices = self.db.get_all_devices()

        for device in devices:
            if device.id not in self.devices_state:
                self.devices_state[device.id] = DeviceState(
                    device_id=device.id,
                    controller_mac=device.controller_mac,
                    is_waiting_confirm=False,
                    prev_resp_time=datetime.now(),
                    failures_count=0,
                    is_active=True,
                    last_message="",
                    params_count=0,
                )

            if device.controller_mac not in self.controllers_state:
                self.controllers_state[device.controller_mac] = ControllerState(
                    mac=device.controller_mac,
                    prev_resp_time=datetime.now(),
                    is_waiting_init=False,
                    is_active=True,
                    failures_count=0,
                    fw_version="",
                    last_message="",
                )
        # print(
        #     f"[Core] Инициализировано состояний: {len(self.devices_state)} устройств, "
        #     f"{len(self.controllers_state)} контроллеров"
        # )

    # ------------------------------------------------------------------ #
    # Утилиты доступа к состояниям
    # ------------------------------------------------------------------ #
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

    def _mark_device_alive(self, device_id: int):
        """Обновить состояние устройства как «живого» (получен любой ответ)."""
        dev_state = self._get_device_state(device_id)
        if not dev_state:
            return
        was_inactive = not dev_state.is_active
        dev_state.prev_resp_time = datetime.now()
        dev_state.failures_count = 0
        dev_state.is_waiting_confirm = False
        dev_state.is_active = True
        if was_inactive:
            print(f"[Core] Устройство {device_id} восстановлено")
            if self.kafka_handler:
                try:
                    self.kafka_handler.send_device_status(device_id, True)
                except Exception as e:
                    print(f"[Core] Kafka error (device status): {e}")

    def _mark_controller_alive(self, mac: str):
        ctrl_state = self._get_controller_state(mac)
        if not ctrl_state:
            return
        was_inactive = not ctrl_state.is_active
        ctrl_state.prev_resp_time = datetime.now()
        ctrl_state.failures_count = 0
        ctrl_state.is_active = True
        if was_inactive:
            print(f"[Core] Контроллер {mac} восстановлен")

    def _deactivate_device(self, device_id: int, reason: str):
        dev_state = self._get_device_state(device_id)
        if not dev_state or not dev_state.is_active:
            return
        dev_state.is_active = False
        dev_state.is_waiting_confirm = False
        dev_state.failures_count = 0

        device = self.db.get_device_by_id(device_id)
        dev_type = device.type if device else "?"
        print(f"[Core] Устройство {device_id} (тип {dev_type}) деактивировано: {reason}")
        if self.kafka_handler:
            try:
                self.kafka_handler.send_device_status(device_id, False)
                self.kafka_handler.send_notification(
                    f"Устройство {device_id} (тип: {dev_type}) деактивировано: {reason}",
                    'error',
                )
            except Exception as e:
                print(f"[Core] Kafka error (device deactivate): {e}")

    def _deactivate_controller(self, mac: str, reason: str):
        ctrl_state = self._get_controller_state(mac)
        if not ctrl_state or not ctrl_state.is_active:
            return
        ctrl_state.is_active = False
        ctrl_state.is_waiting_init = False
        ctrl_state.failures_count = 0

        print(f"[Core] Контроллер {mac} деактивирован: {reason}")
        if self.kafka_handler:
            try:
                self.kafka_handler.send_notification(
                    f"Контроллер {mac} деактивирован: {reason}", 'warning'
                )
            except Exception as e:
                print(f"[Core] Kafka error (controller deactivate): {e}")

        # Деактивируем все устройства этого контроллера
        for device in self.db.get_devices_by_controller(mac):
            self._deactivate_device(device.id, f"контроллер {mac} недоступен")

        # Убираем из очереди ожидания init
        self.mac_wait_request_init = [
            r for r in self.mac_wait_request_init if r["mac"] != mac
        ]

    def set_mqtt_client(self, mqtt_client):
        self.mqtt_client = mqtt_client

    # ------------------------------------------------------------------ #
    # Отправка команд устройству через контроллер
    # ------------------------------------------------------------------ #
    def _send_device_state_to_controller(self, device_id: int):
        device = self.db.get_device_by_id(device_id)
        if not device:
            return
        req_parts = ["exec", str(device.type), str(device.port), "setValues"]
        for val in device.current_values:
            req_parts.append(str(val))
        req_parts.append("next")
        req = "/".join(req_parts)

        if not self.mqtt_client:
            print("[Core] MQTT клиент не установлен, отправка отменена")
            return

        self.mqtt_client.publish(device.controller_mac, req)

        dev_state = self._get_device_state(device_id)
        if dev_state:
            dev_state.is_waiting_confirm = True
            dev_state.last_message = req
            # prev_resp_time НЕ трогаем: таймаут считается от последнего ответа,
            # а не от последней отправки. Но для повторной отправки нам важен момент
            # отправки — храним его в last_message + отдельный дедлайн через prev_resp_time
            # не подходит, поэтому используем поле last_message и таймаут от него
            # через failures_count. Проще: храним отдельно момент отправки.
            dev_state.prev_resp_time = datetime.now()  # старт окна ожидания ответа

    # ------------------------------------------------------------------ #
    # Парсинг входящих сообщений
    # ------------------------------------------------------------------ #
    def parse(self, topic, payload):
        print(f"[PARSE] Обработка сообщения: топик={topic}, данные={payload}")
        parts = payload.split('/')
        parts = [p for p in parts if p.strip()]

        if len(parts) >= 2:
            mac = parts[0]

            # Любое сообщение от контроллера — признак жизни
            if self._get_controller_state(mac):
                self._mark_controller_alive(mac)

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
                device_type = parts[index + 1] if index + 1 < len(parts) else None
                device_port = parts[index + 2] if index + 2 < len(parts) else None

                for device in devices:
                    if device.port == device_port and device.type == device_type:
                        self._mark_device_alive(device.id)
                        if self.kafka_handler:
                            try:
                                self.kafka_handler.send_device_status(device.id, True)
                            except Exception as e:
                                print(f"[Core] Kafka error (exec ok): {e}")
                        break

                # Пропускаем до next
                while index < len(parts) and parts[index] != "next":
                    index += 1
                if index >= len(parts):
                    break

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
            r'"(\d+)"',
            r"'(\d+)'",
            r'\[(\d+)\]',
            r'\((\d+)\)',
            r'\b(\d+)\b',
        ]

        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                trig_num = match.group(1)
                start, end = match.span()
                cleaned_text = content[:start] + content[end:]
                cleaned_text = re.sub(r'[/:;,.]$', '', cleaned_text).strip()
                return trig_num, cleaned_text

        return None, original.strip()

    def _parse_trig_response(self, parts):
        mac = parts[0]
        triggers = self.db.get_triggers_by_controller(mac)
        index = 1

        while index < len(parts) - 2:
            index += 1
            if parts[index] == "":
                index += 1
            status = parts[index]
            index += 1

            if status == "ok":
                trig_num = parts[index] if index < len(parts) else None
                print(f"[Core] Триггер создан на {mac}: {trig_num}")

            elif status == "error":
                num, text = self.parse_error_content(parts[index] if index < len(parts) else "")
                print(f"[Core error] Ошибка триггера на {mac}: {text}")

            else:
                print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                break

            while index < len(parts) and parts[index] != "next":
                index += 1
            if index >= len(parts):
                break

    def _parse_init_response(self, parts):
        mac = parts[0]

        for i, req in enumerate(self.mac_wait_request_init):
            if req["mac"] != mac:
                continue

            devices = self.db.get_devices_by_controller(mac)
            index = 1

            while index < len(parts) - 2:
                index += 1
                status = parts[index]

                if status == "ok":
                    device_type = parts[index + 1] if index + 1 < len(parts) else None
                    device_port = parts[index + 2] if index + 2 < len(parts) else None
                    params_count_str = parts[index + 3] if index + 3 < len(parts) else "0"

                    for j, device in enumerate(devices):
                        if device.port == device_port and device.type == device_type:
                            del devices[j]
                            dev_state = self._get_device_state(device.id)
                            if not dev_state:
                                self._init_states_from_db()
                                dev_state = self._get_device_state(device.id)
                            if dev_state:
                                try:
                                    dev_state.params_count = int(params_count_str)
                                except (ValueError, TypeError):
                                    dev_state.params_count = 0
                                dev_state.is_active = True
                                dev_state.prev_resp_time = datetime.now()
                                dev_state.failures_count = 0
                                if self.kafka_handler:
                                    try:
                                        self.kafka_handler.send_device_status(device.id, True)
                                    except Exception as e:
                                        print(f"[Core] Kafka error (init ok): {e}")
                            self._send_device_state_to_controller(device.id)
                            break

                elif status == "error":
                    device_type = parts[index + 1] if index + 1 < len(parts) else None
                    device_port = parts[index + 2] if index + 2 < len(parts) else None
                    error_message = parts[index + 3] if index + 3 < len(parts) else None

                    if self.kafka_handler:
                        try:
                            self.kafka_handler.send_notification(
                                f"Контроллер {mac} ошибка инициализации устройства "
                                f"{device_type}: {error_message}",
                                'error',
                            )
                        except Exception as e:
                            print(f"[Core] Kafka error (init err): {e}")
                    print(
                        f"[Core Error] Ошибка инициализации в контроллере {mac}: "
                        f"устройство {device_type}, ошибка: {error_message}"
                    )

                    if device_port and str(device_port).isdigit():
                        for j, device in enumerate(devices):
                            if device.port == device_port and device.type == device_type:
                                del devices[j]
                                # Помечаем устройство как неактивное
                                dev_state = self._get_device_state(device.id)
                                if dev_state and dev_state.is_active:
                                    dev_state.is_active = False
                                    if self.kafka_handler:
                                        try:
                                            self.kafka_handler.send_device_status(device.id, False)
                                        except Exception as e:
                                            print(f"[Core] Kafka error (init err dev): {e}")
                                break
                else:
                    print(f"[Core Warning] Неожиданный формат ответа: {parts[index:]}")
                    break

                while index < len(parts) and parts[index] != "next":
                    index += 1
                if index >= len(parts):
                    break

            # Оставшиеся устройства не подтвердили инициализацию
            for device in devices:
                dev_state = self._get_device_state(device.id)
                if dev_state and dev_state.is_active:
                    dev_state.failures_count += 1
                    print(
                        f"[Core Error] Устройство {device.id} (тип {device.type}, "
                        f"порт {device.port}) не подтвердило инициализацию "
                        f"(попытка {dev_state.failures_count}/{self.MAX_FAILURES})"
                    )
                    if dev_state.failures_count >= self.MAX_FAILURES:
                        self._deactivate_device(
                            device.id, "не подтвердило инициализацию"
                        )

            ctrl_state = self._get_controller_state(mac)
            if ctrl_state:
                ctrl_state.is_waiting_init = False

            self.mac_wait_request_init.pop(i)
            break

    def _parse_firmware_version_response(self, parts):
        mac = parts[0]
        version = parts[2] if len(parts) > 2 else None

        print(f"[Core] Контроллер {mac} сообщил версию прошивки: {version}")

        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_fw_version = False
            ctrl_state.prev_resp_time = datetime.now()
            ctrl_state.fw_version = version

        if self.otaServ and self.otaServ.is_running:
            try:
                self.otaServ.delete_running_update_controller(mac)
            except Exception as e:
                print(f"[Core] OTA delete error: {e}")
            print(f"[Core] Контроллер {mac} удалён из очереди обновления после ответа о версии")

        if self.kafka_handler:
            try:
                self.kafka_handler.send_notification(
                    f"Контроллер {mac} версия прошивки: {version}", 'info'
                )
            except Exception as e:
                print(f"[Core] Kafka error (fw ver): {e}")

    def _handle_fw_version_timeout(self, mac: str):
        print(
            f"[Core] Контроллер {mac} не ответил на getFirmwareVersion "
            f"после {self.MAX_FAILURES} попыток — удаляем из очереди обновления"
        )
        if self.kafka_handler:
            try:
                self.kafka_handler.send_notification(
                    f"Контроллер {mac} не отвечает на запрос версии прошивки "
                    f"после {self.MAX_FAILURES} попыток. Удалён из очереди обновления.",
                    'error',
                )
            except Exception as e:
                print(f"[Core] Ошибка отправки уведомления в Kafka: {e}")

        if self.otaServ and getattr(self.otaServ, "is_running", False):
            try:
                self.otaServ.delete_running_update_controller(mac)
            except Exception as e:
                print(f"[Core] Ошибка удаления контроллера {mac} из очереди OTA: {e}")

        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_fw_version = False
            ctrl_state.failures_count = 0
            ctrl_state.prev_resp_time = datetime.now()

    # ------------------------------------------------------------------ #
    # Поток обработки сообщений
    # ------------------------------------------------------------------ #
    def process_messages(self):
        while not self.stop_event.is_set():
            try:
                if self.mqtt_client:
                    message = self.mqtt_client.get_message(block=False)
                    if message:
                        topic = message['topic']
                        payload = message['payload']
                        self.parse(topic, payload)
                    else:
                        time.sleep(0.01)
                else:
                    print("[Core] Ожидание установки MQTT клиента...")
                    time.sleep(1)
            except Exception as e:
                print(f"[Core] Ошибка при обработке сообщения: {e}")
                time.sleep(0.1)

    # ------------------------------------------------------------------ #
    # Запуск/остановка
    # ------------------------------------------------------------------ #
    def start_processing(self):
        if self.running:
            print("[Core] Обработчик уже запущен")
            return False

        self.running = True
        self.stop_event.clear()

        self.processing_thread = threading.Thread(target=self.process_messages, daemon=True)
        self.processing_thread.start()

        self.thread_controller = threading.Thread(target=self._control_devices, daemon=True)
        self.thread_controller.start()

        if self.kafka_handler:
            self.kafka_handler.set_init_callback(self.parse_init)
            self.kafka_handler.set_recall_triggers(self.parse_triggers)

        self.init_devices()
        self.get_firmware_versions()
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
        print("[Core] Ошибка: MQTT клиент не установлен")
        return False

    # ------------------------------------------------------------------ #
    # Init / triggers / states / changes
    # ------------------------------------------------------------------ #
    def parse_init(self, parts):
        mac = parts[0] if isinstance(parts, list) else parts
        devices = self.db.get_devices_by_controller(mac)

        req_parts = ["connections"]
        for device in devices:
            req_parts.append(device.type)
            if device.port:
                req_parts.append(str(device.port))
            if device.params:
                if isinstance(device.params, str):
                    try:
                        device.params = json.loads(device.params)
                    except Exception:
                        device.params = {}
                for key, value in device.params.items():
                    if value not in (None, "", []):
                        req_parts.append(str(value))
            req_parts.append("next")

        req = "/".join(req_parts)

        if not self.mqtt_client:
            print("[Core] MQTT клиент не установлен, init отменён")
            return

        self.mqtt_client.publish(mac, req)

        ctrl_state = self._get_controller_state(mac)
        if ctrl_state:
            ctrl_state.is_waiting_init = True
            ctrl_state.prev_resp_time = datetime.now()

        self.mac_wait_request_init.append({"mac": mac})

    def parse_triggers(self, parts):
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
            if not dev_state:
                continue
            for param_num in range(dev_state.params_count):
                req_parts.append(device.type)
                req_parts.append(str(device.port))
                req_parts.append(f"value/{param_num}/onChange/do")
                req_parts.append(device.controller_mac)
                req_parts.append("getValue")
                req_parts.append(device.type)
                req_parts.append(str(device.port))
                req_parts.append(f"{param_num}/next")

        req = "/".join(req_parts)
        if len(req_parts) >= 2 and self.mqtt_client:
            self.mqtt_client.publish(mac, req)

    def parse_states(self, parts):
        """
        Обработка ответа values от контроллера.

        Поддерживаем формат:
          ... values / <type> / <port> / value / <param_idx> / <value> / ... / next
        (то есть после port идут поля value, param_idx, val, затем следующий блок или next)

        Дополнительно: любое упоминание типа+порта устройства в ответе обновляет
        prev_resp_time этого устройства — это ключ к корректной проверке «молчания».
        """
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)
        dev_with_values = {}

        # Найдём все "окна" между next и обновим значения
        i = 0
        while i < len(parts):
            if parts[i] != "next":
                i += 1
                continue

            # Парсим блок, заканчивающийся на next: ... <type> <port> value <param> <val>
            # Ищем с конца блока (наиболее вероятная раскладка)
            if i >= 5:
                dev_type = parts[i - 5]
                dev_port = parts[i - 4]
                # parts[i-3] == "value"
                param_str = parts[i - 2]
                val_str = parts[i - 1]

                for device in devices:
                    if device.type == dev_type and str(device.port) == str(dev_port):
                        if param_str.isdigit():
                            param_idx = int(param_str)
                        else:
                            param_idx = None

                        if param_idx is not None:
                            if not isinstance(device.current_values, list):
                                device.current_values = []
                            while param_idx >= len(device.current_values):
                                device.current_values.append("0")
                            device.current_values[param_idx] = parse_number(val_str)

                        dev_with_values[device.id] = device
                        # Обновляем «живость» устройства
                        self._mark_device_alive(device.id)
                        break
            i += 1

        for device_id, device in dev_with_values.items():
            try:
                self.db.update_device_current_values(device_id, device.current_values)
            except Exception as e:
                print(f"[Core] DB error update_device_current_values: {e}")

            if self.kafka_handler:
                try:
                    self.kafka_handler.send_device_value_update(device_id, device.current_values)
                except Exception as e:
                    print(f"[Core] Kafka error (value update): {e}")

            self.check_scene(device_id)

    def parse_changes(self, parts):
        mac = parts[0]
        devices = self.db.get_devices_by_controller(mac)

        for device in devices:
            if device.type == parts[2] and str(device.port) == str(parts[3]):
                if len(parts) > 6:
                    try:
                        param_idx = int(parts[4])
                    except (ValueError, IndexError):
                        param_idx = None

                    if param_idx is not None:
                        if not isinstance(device.current_values, list):
                            device.current_values = []
                        while param_idx >= len(device.current_values):
                            device.current_values.append("0")
                        try:
                            if parts[5] == 'plus':
                                device.current_values[param_idx] = str(
                                    int(float(device.current_values[param_idx])) + int(float(parts[6]))
                                )
                            elif parts[5] == 'minus':
                                device.current_values[param_idx] = str(
                                    int(float(device.current_values[param_idx])) - int(float(parts[6]))
                                )
                            elif parts[5] == 'setStartValue':
                                device.current_values[param_idx] = str(int(float(parts[6])))
                        except Exception:
                            device.current_values[param_idx] = "0"

                self._mark_device_alive(device.id)

                try:
                    self.db.update_device_current_values(device.id, device.current_values)
                except Exception as e:
                    print(f"[Core] DB error update_device_current_values: {e}")

                if self.kafka_handler:
                    try:
                        self.kafka_handler.send_device_value_update(device.id, device.current_values)
                    except Exception as e:
                        print(f"[Core] Kafka error (value update): {e}")

    # ------------------------------------------------------------------ #
    # Поток контроля устройств и контроллеров
    # ------------------------------------------------------------------ #
    def _control_devices(self):
        """
        1. Повторная отправка команд устройству при is_waiting_confirm и таймауте.
        2. Деактивация устройства по «молчанию» (DEVICE_SILENCE_TIMEOUT) — независимо от is_waiting_confirm.
        3. Деактивация контроллера, если все его устройства неактивны (в том же проходе).
        4. Восстановление неактивного контроллера через parse_init.
        5. OTA: если контроллер в очереди обновления и молчит — getFirmwareVersion.
        """
        while self.running:
            try:
                current_time = datetime.now()
                devices = self.db.get_all_devices()

                # Итерация 1: проверка устройств (повторная отправка и таймаут молчания)
                for device in devices:
                    device_id = device.id
                    mac = device.controller_mac

                    dev_state = self._get_device_state(device_id)
                    ctrl_state = self._get_controller_state(mac)
                    if not dev_state or not ctrl_state:
                        continue

                    time_since_resp = (current_time - dev_state.prev_resp_time).total_seconds()

                    # 1. Повторная отправка, если ждём подтверждения
                    if dev_state.is_waiting_confirm and time_since_resp > self.TIMEOUT_SECONDS:
                        if dev_state.failures_count < self.MAX_FAILURES:
                            if dev_state.last_message and self.mqtt_client:
                                self.mqtt_client.publish(mac, dev_state.last_message)
                                dev_state.prev_resp_time = datetime.now()
                                dev_state.failures_count += 1
                                print(
                                    f"[Core] Повторная отправка устройству {device_id}: "
                                    f"{dev_state.last_message} (попытка {dev_state.failures_count})"
                                )
                            else:
                                # Нечего повторять — просто снимаем ожидание
                                dev_state.is_waiting_confirm = False
                        else:
                            # Исчерпаны попытки повторной отправки команды
                            self._deactivate_device(
                                device_id,
                                f"нет подтверждения после {self.MAX_FAILURES} повторных отправок",
                            )

                    # 2. Деактивация по «молчанию» — независимо от is_waiting_confirm
                    elif dev_state.is_active and time_since_resp > self.DEVICE_SILENCE_TIMEOUT:
                        dev_state.failures_count += 1
                        print(
                            f"[Core] Устройство {device_id} молчит "
                            f"{time_since_resp:.0f}с "
                            f"(попытка {dev_state.failures_count}/{self.MAX_FAILURES})"
                        )
                        if dev_state.failures_count >= self.MAX_FAILURES:
                            self._deactivate_device(
                                device_id,
                                f"молчит более {self.DEVICE_SILENCE_TIMEOUT}с",
                            )

                # Итерация 2: проверка контроллеров
                all_macs = {d.controller_mac for d in devices}
                for mac in all_macs:
                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state:
                        continue

                    ctrl_time_since_resp = (current_time - ctrl_state.prev_resp_time).total_seconds()

                    # 2.1 Инициализация
                    if ctrl_state.is_waiting_init and ctrl_time_since_resp > self.TIMEOUT_SECONDS:
                        if ctrl_state.failures_count < self.MAX_FAILURES and ctrl_state.is_active:
                            ctrl_state.failures_count += 1
                            print(
                                f"[Core] Повторная инициализация контроллера {mac} "
                                f"(попытка {ctrl_state.failures_count}/{self.MAX_FAILURES})"
                            )
                            self.parse_init(mac)
                        elif ctrl_state.failures_count >= self.MAX_FAILURES:
                            self._deactivate_controller(
                                mac, "не подтвердил инициализацию"
                            )
                            continue

                    # 2.2 OTA
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
                                    if self.mqtt_client:
                                        self.mqtt_client.publish(mac, "getFirmwareVersion")
                                    ctrl_state.prev_resp_time = datetime.now()
                                    print(
                                        f"[Core] Повторный запрос версии прошивки у {mac} "
                                        f"(попытка {ctrl_state.failures_count}/{self.MAX_FAILURES})"
                                    )
                                else:
                                    self._handle_fw_version_timeout(mac)
                            continue
                        else:
                            if ctrl_time_since_resp > self.GET_VALUES_DELAY:
                                if self.mqtt_client:
                                    self.mqtt_client.publish(mac, "getFirmwareVersion")
                                ctrl_state.prev_resp_time = datetime.now()
                                ctrl_state.is_waiting_fw_version = True
                                ctrl_state.failures_count = 0
                                print(f"[Core] Запрос версии прошивки (OTA): getFirmwareVersion -> {mac}")
                                continue

                    # 2.3 Обычный запрос состояния (вне OTA)
                    if ctrl_state.is_active and ctrl_time_since_resp > self.GET_VALUES_DELAY:
                        if self.mqtt_client:
                            self.mqtt_client.publish(mac, "exec/getAllValues/")
                        ctrl_state.prev_resp_time = datetime.now()
                        print(f"[Core] Принудительный запрос состояния: exec/getAllValues/ -> {mac}")

                # Итерация 3: деактивация контроллера, если все его устройства неактивны.
                # Пересчитываем уже ПОСЛЕ итерации 1, чтобы изменения применились в этом же проходе.
                for mac in all_macs:
                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state or not ctrl_state.is_active:
                        continue

                    ctrl_devices = self.db.get_devices_by_controller(mac)
                    if not ctrl_devices:
                        continue
                    any_active = any(
                        (self._get_device_state(d.id) or DeviceState(0, mac)).is_active
                        for d in ctrl_devices
                    )
                    if not any_active:
                        self._deactivate_controller(mac, "все устройства неактивны")

                # Итерация 4: восстановление неактивных контроллеров
                for mac in all_macs:
                    ctrl_state = self._get_controller_state(mac)
                    if not ctrl_state or ctrl_state.is_active:
                        continue
                    ctrl_time_since_resp = (current_time - ctrl_state.prev_resp_time).total_seconds()
                    if ctrl_time_since_resp > self.GET_VALUES_DELAY:
                        ctrl_state.prev_resp_time = datetime.now()
                        print(f"[Core] Попытка восстановления контроллера {mac}")
                        self.parse_init(mac)

                time.sleep(1)

            except Exception as e:
                print(f"[Core] Ошибка в control_devices: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(1)

    # ------------------------------------------------------------------ #
    # Инициализация устройств при старте
    # ------------------------------------------------------------------ #
    def init_devices(self):
        unique_mac = set()
        devices = self.db.get_all_devices()
        for device in devices:
            if device.controller_mac not in unique_mac:
                unique_mac.add(device.controller_mac)
                self.parse_init([device.controller_mac])

    def get_firmware_versions(self):
        unique_mac = set()
        devices = self.db.get_all_devices()
        for device in devices:
            if device.controller_mac not in unique_mac:
                unique_mac.add(device.controller_mac)
        for mac in unique_mac:
            if self.mqtt_client:
                self.mqtt_client.publish(mac, "getFirmwareVersion")

    # ------------------------------------------------------------------ #
    # Сцены
    # ------------------------------------------------------------------ #
    def check_scene(self, device_id: int):
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
                    if cond_device_id != device_id:
                        continue
                    if param_num is not None and param_num < len(current_values):
                        check_value = current_values[param_num]
                    else:
                        check_value = None
                    is_execute = self._check_condition_value(condition, check_value)
                    condition['is_execute'] = is_execute
                    if not is_execute:
                        break
                    executed_count += 1

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
        except Exception:
            return []

    def _check_condition_value(self, condition, current_value):
        compare_type = condition.get('compare_type')
        value = condition.get('value')
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
        except Exception:
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
            except Exception:
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
                    if device and device_param is not None:
                        command = command.split("/")[-1]
                        self.parse_changes([
                            device.controller_mac, 'changeVal', device.type,
                            device.port, device_param, command, value
                        ])
                        self._mark_device_alive(device.id)

                elif mac and command:
                    cmd_parts = ["exec", device_type, device_port, command]
                    if value:
                        cmd_parts.append(value)
                    cmd_str = "/".join(str(p) for p in cmd_parts)

                    if self.mqtt_client:
                        self.mqtt_client.publish(mac, cmd_str)
                    print(f"[Core] Executed action: {cmd_str} -> {mac}")

                    # Помечаем устройство как ожидающее подтверждения
                    for d in self.db.get_devices_by_controller(mac):
                        if d.type == device_type and str(d.port) == str(device_port):
                            st = self._get_device_state(d.id)
                            if st:
                                st.is_waiting_confirm = True
                                st.last_message = cmd_str
                                st.prev_resp_time = datetime.now()
                            break

        except Exception as e:
            print(f"[Core] Error executing scene actions: {e}")

    def _parse_scene_responses(self, responses_json):
        try:
            if isinstance(responses_json, str):
                return json.loads(responses_json)
            elif isinstance(responses_json, list):
                return responses_json
            return []
        except Exception:
            return []