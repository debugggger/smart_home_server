import psycopg2
from psycopg2 import sql
from typing import Optional, List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
import os
from dataclasses import dataclass
from enum import Enum


# # ============= ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ =============
#
# class EventValueType(Enum):
#     """Типы значений событий"""
#     TEMPERATURE = "temperature"
#     HUMIDITY = "humidity"
#     MOTION = "motion"
#     SWITCH = "switch"
#     CUSTOM = "custom"


# ============= КЛАССЫ СУЩНОСТЕЙ =============

@dataclass
class Room:
    """Сущность комнаты"""
    id: Optional[int] = None
    name: str = None

    def __repr__(self):
        return f"<Room(id={self.id}, name='{self.name}')>"


@dataclass
class Controller:
    """Сущность контроллера"""
    id: Optional[int] = None
    mac: str = None
    room_id: int = None
    name: str = None

    def __repr__(self):
        return f"<Controller(id={self.id}, mac='{self.mac}', name='{self.name}')>"


@dataclass
class Device:
    """Сущность устройства"""
    id: Optional[int] = None
    name: str = None
    controller_id: int = None
    type_id: int = None
    port: str = None
    params: str = None

    def __repr__(self):
        return f"<Device(id={self.id}, name='{self.name}', type_id={self.type_id})>"


# @dataclass
# class Event:
#     """Сущность события"""
#     id: Optional[int] = None
#     value: int = None
#     device_id: int = None
#     time: datetime = None
#
#     def __post_init__(self):
#         if self.time is None:
#             self.time = datetime.now()
#
#     def __repr__(self):
#         return f"<Event(id={self.id}, device_id={self.device_id}, value={self.value}, time={self.time})>"


@dataclass
class DeviceType:
    """Сущность типа устройства"""
    id: Optional[int] = None
    name: str = None
    description: Optional[str] = None

    def __repr__(self):
        return f"<DeviceType(id={self.id}, name='{self.name}')>"


@dataclass
class TrigCondition:
    """Сущность условия триггера"""
    id: Optional[int] = None
    device_id: int = None
    condition: str = None
    trigger_id: int = None

    def __repr__(self):
        return f"<TrigCondition(id={self.id}, device_id={self.device_id}, trigger_id={self.trigger_id}, condition='{self.condition}')>"


@dataclass
class TrigResponse:
    """Сущность ответа триггера"""
    id: Optional[int] = None
    device_id: int = None
    resp: str = None
    trigger_id: int = None

    def __repr__(self):
        return f"<TrigResponse(id={self.id}, device_id={self.device_id}, trigger_id={self.trigger_id}, resp='{self.resp}')>"




@dataclass
class Trigger:
    """Сущность триггера"""
    id: Optional[int] = None
    controller_id: int = None
    controller_resp_id: int = None
    name: str = None

    def __repr__(self):
        return f"<Trigger(id={self.id}, name='{self.name}', controller_id={self.controller_id}, controller_resp_id={self.controller_resp_id})>"


# ============= КЛАСС БАЗЫ ДАННЫХ =============

class Database:
    def __init__(self):
        load_dotenv()
        self.connection = psycopg2.connect(
            host=os.getenv('host'),
            user=os.getenv('user'),
            password=os.getenv('password'),
            database=os.getenv('db_name'),
            port=os.getenv('port')
        )
        self.connection.autocommit = True
        with self.connection.cursor() as cur:
            cur.execute("select version();")
            print(f"server vers:  {cur.fetchone()}")

    def close(self):
        self.connection.close()
        print("[INFO] Close connection with DB")

        # ============= ВНУТРЕННИЕ МЕТОДЫ =============

    def _execute_query(self, query: str, params: tuple = None,
                       fetch_one: bool = False, fetch_all: bool = False):
        """Внутренний метод для выполнения запросов"""
        with self.connection.cursor() as cur:
            cur.execute(query, params)
            if fetch_one:
                return cur.fetchone()
            elif fetch_all:
                return cur.fetchall()
            return None

    # ============= МЕТОДЫ ДЛЯ ROOMS =============

    def add_room(self, room: Room) -> Optional[int]:
        """Добавление комнаты"""
        query = "INSERT INTO rooms (name) VALUES (%s) RETURNING id"
        result = self._execute_query(query, (room.name,), fetch_one=True)
        if result:
            room.id = result[0]
            return result[0]
        return None

    def get_room_by_id(self, room_id: int) -> Optional[Room]:
        """Получение комнаты по ID"""
        query = "SELECT id, name FROM rooms WHERE id = %s"
        result = self._execute_query(query, (room_id,), fetch_one=True)
        if result:
            return Room(id=result[0], name=result[1])
        return None

    def get_rooms_by_name(self, name: str) -> List[Room]:
        """Получение комнат по имени"""
        query = "SELECT id, name FROM rooms WHERE name = %s"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Room(id=r[0], name=r[1]) for r in results] if results else []

    def get_all_rooms(self) -> List[Room]:
        """Получение всех комнат"""
        query = "SELECT id, name FROM rooms ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        print(results)
        return [Room(id=r[0], name=r[1]) for r in results] if results else []

    def delete_room(self, room_id: int) -> bool:
        """Удаление комнаты по ID"""
        query = "DELETE FROM rooms WHERE id = %s"
        self._execute_query(query, (room_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ CONTROLLERS =============

    def add_controller(self, controller: Controller) -> Optional[int]:
        """Добавление контроллера"""
        query = """
            INSERT INTO controllers (mac, room_id, name) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (controller.mac, controller.room_id, controller.name), fetch_one=True)
        if result:
            controller.id = result[0]
            return result[0]
        return None

    def get_controller_by_id(self, controller_id: int) -> Optional[Controller]:
        """Получение контроллера по ID"""
        query = "SELECT id, mac, room_id, name FROM controllers WHERE id = %s"
        result = self._execute_query(query, (controller_id,), fetch_one=True)
        if result:
            return Controller(id=result[0], mac=result[1], room_id=result[2], name=result[3])
        return None

    def get_controllers_by_room(self, room_id: int) -> List[Controller]:
        """Получение всех контроллеров в комнате"""
        query = "SELECT id, mac, room_id, name FROM controllers WHERE room_id = %s ORDER BY id"
        results = self._execute_query(query, (room_id,), fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3]) for r in results] if results else []

    def get_controllers_by_mac(self, mac: str) -> List[Controller]:
        """Получение контроллеров по MAC адресу"""
        query = "SELECT id, mac, room_id, name FROM controllers WHERE mac = %s"
        results = self._execute_query(query, (mac,), fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3]) for r in results] if results else []

    def get_all_controllers(self) -> List[Controller]:
        """Получение всех контроллеров"""
        query = "SELECT id, mac, room_id, name FROM controllers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3]) for r in results] if results else []

    def delete_controller(self, controller_id: int) -> bool:
        """Удаление контроллера по ID"""
        query = "DELETE FROM controllers WHERE id = %s"
        self._execute_query(query, (controller_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ DEVICE_TYPES =============

    def add_device_type(self, device_type: DeviceType) -> Optional[int]:
        """Добавление типа устройства"""
        query = """
            INSERT INTO device_types (name, description) 
            VALUES (%s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (device_type.name, device_type.description), fetch_one=True)
        if result:
            device_type.id = result[0]
            return result[0]
        return None

    def get_device_type_by_id(self, type_id: int) -> Optional[DeviceType]:
        """Получение типа устройства по ID"""
        query = "SELECT id, name, description FROM device_types WHERE id = %s"
        result = self._execute_query(query, (type_id,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1], description=result[2])
        return None

    def get_device_type_by_name(self, name: str) -> Optional[DeviceType]:
        """Получение типа устройства по имени"""
        query = "SELECT id, name, description FROM device_types WHERE name = %s"
        result = self._execute_query(query, (name,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1], description=result[2])
        return None

    def get_all_device_types(self) -> List[DeviceType]:
        """Получение всех типов устройств"""
        query = "SELECT id, name, description FROM device_types ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [DeviceType(id=r[0], name=r[1], description=r[2]) for r in results] if results else []

    def delete_device_type(self, type_id: int) -> bool:
        """Удаление типа устройства по ID"""
        query = "DELETE FROM device_types WHERE id = %s"
        self._execute_query(query, (type_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ DEVICES =============

    def add_device(self, device: Device) -> Optional[int]:
        """Добавление устройства"""
        query = """
            INSERT INTO devices (name, controller_id, type_id, port, params) 
            VALUES (%s, %s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (device.name, device.controller_id,
                                             device.type_id, device.port, device.params), fetch_one=True)
        if result:
            device.id = result[0]
            return result[0]
        return None

    def get_device_by_id(self, device_id: int) -> Optional[Device]:
        """Получение устройства по ID"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices WHERE id = %s"
        result = self._execute_query(query, (device_id,), fetch_one=True)
        if result:
            return Device(id=result[0], name=result[1], controller_id=result[2],
                          type_id=result[3], port=result[4], params=result[5])
        return None

    def get_devices_by_controller(self, controller_id: int) -> List[Device]:
        """Получение всех устройств контроллера"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices WHERE controller_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_id,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5])
                for r in results] if results else []

    def get_devices_by_type(self, type_id: int) -> List[Device]:
        """Получение устройств по типу"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices WHERE type_id = %s"
        results = self._execute_query(query, (type_id,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5])
                for r in results] if results else []

    def get_devices_by_name(self, name: str) -> List[Device]:
        """Получение устройств по имени"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices WHERE name = %s"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5])
                for r in results] if results else []

    def get_all_devices(self) -> List[Device]:
        """Получение всех устройств"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5])
                for r in results] if results else []

    def delete_device(self, device_id: int) -> bool:
        """Удаление устройства по ID"""
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))
        return True

    # # ============= МЕТОДЫ ДЛЯ EVENTS =============
    #
    # def add_event(self, event: Event) -> Optional[int]:
    #     """Добавление события"""
    #     query = """
    #         INSERT INTO events (value, device_id, time)
    #         VALUES (%s, %s, %s)
    #         RETURNING id
    #     """
    #     result = self._execute_query(query, (event.value, event.device_id, event.time), fetch_one=True)
    #     if result:
    #         event.id = result[0]
    #         return result[0]
    #     return None
    #
    # def get_event_by_id(self, event_id: int) -> Optional[Event]:
    #     """Получение события по ID"""
    #     query = "SELECT id, value, device_id, time FROM events WHERE id = %s"
    #     result = self._execute_query(query, (event_id,), fetch_one=True)
    #     if result:
    #         return Event(id=result[0], value=result[1], device_id=result[2], time=result[3])
    #     return None
    #
    # def get_events_by_device(self, device_id: int, limit: int = 100) -> List[Event]:
    #     """Получение событий устройства"""
    #     query = """
    #         SELECT id, value, device_id, time
    #         FROM events
    #         WHERE device_id = %s
    #         ORDER BY time DESC
    #         LIMIT %s
    #     """
    #     results = self._execute_query(query, (device_id, limit), fetch_all=True)
    #     return [Event(id=r[0], value=r[1], device_id=r[2], time=r[3])
    #             for r in results] if results else []
    #
    # def get_events_by_time_range(self, device_id: int, start_time: datetime, end_time: datetime) -> List[Event]:
    #     """Получение событий устройства за временной промежуток"""
    #     query = """
    #         SELECT id, value, device_id, time
    #         FROM events
    #         WHERE device_id = %s AND time BETWEEN %s AND %s
    #         ORDER BY time DESC
    #     """
    #     results = self._execute_query(query, (device_id, start_time, end_time), fetch_all=True)
    #     return [Event(id=r[0], value=r[1], device_id=r[2], time=r[3])
    #             for r in results] if results else []
    #
    # def get_all_events(self, limit: int = 1000) -> List[Event]:
    #     """Получение всех событий"""
    #     query = "SELECT id, value, device_id, time FROM events ORDER BY time DESC LIMIT %s"
    #     results = self._execute_query(query, (limit,), fetch_all=True)
    #     return [Event(id=r[0], value=r[1], device_id=r[2], time=r[3])
    #             for r in results] if results else []
    #
    # def delete_event(self, event_id: int) -> bool:
    #     """Удаление события по ID"""
    #     query = "DELETE FROM events WHERE id = %s"
    #     self._execute_query(query, (event_id,))
    #     return True
    #
    # def delete_old_events(self, days: int = 30) -> int:
    #     """Удаление старых событий"""
    #     query = "DELETE FROM events WHERE time < NOW() - INTERVAL '%s days'"
    #     self._execute_query(query, (days,))
    #     return True

    # ============= МЕТОДЫ ДЛЯ TRIGGERS =============

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        """Добавление триггера"""
        query = """
            INSERT INTO triggers (controller_id, controller_resp_id, name) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (trigger.controller_id, trigger.controller_resp_id, trigger.name),
                                     fetch_one=True)
        if result:
            trigger.id = result[0]
            return result[0]
        return None

    def get_trigger_by_id(self, trigger_id: int) -> Optional[Trigger]:
        """Получение триггера по ID"""
        query = "SELECT id, controller_id, controller_resp_id, name FROM triggers WHERE id = %s"
        result = self._execute_query(query, (trigger_id,), fetch_one=True)
        if result:
            return Trigger(id=result[0], controller_id=result[1], controller_resp_id=result[2], name=result[3])
        return None

    def get_triggers_by_controller(self, controller_id: int) -> List[Trigger]:
        """Получение триггеров по контроллеру (источнику)"""
        query = "SELECT id, controller_id, controller_resp_id, name FROM triggers WHERE controller_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3]) for r in
                results] if results else []

    def get_triggers_by_resp_controller(self, controller_resp_id: int) -> List[Trigger]:
        """Получение триггеров по контроллеру ответа"""
        query = "SELECT id, controller_id, controller_resp_id, name FROM triggers WHERE controller_resp_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_resp_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3]) for r in
                results] if results else []

    def get_triggers_by_name(self, name: str) -> List[Trigger]:
        """Получение триггеров по имени"""
        query = "SELECT id, controller_id, controller_resp_id, name FROM triggers WHERE name = %s ORDER BY id"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3]) for r in
                results] if results else []

    def get_all_triggers(self) -> List[Trigger]:
        """Получение всех триггеров"""
        query = "SELECT id, controller_id, controller_resp_id, name FROM triggers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3]) for r in
                results] if results else []

    def delete_trigger(self, trigger_id: int) -> bool:
        """Удаление триггера по ID"""
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ TRIG_CONDITIONS =============

    def add_trig_condition(self, condition: TrigCondition) -> Optional[int]:
        """Добавление условия триггера"""
        query = """
            INSERT INTO trig_conditions (device_id, condition, trigger_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (condition.device_id, condition.condition, condition.trigger_id),
                                     fetch_one=True)
        if result:
            condition.id = result[0]
            return result[0]
        return None

    def get_trig_condition_by_id(self, condition_id: int) -> Optional[TrigCondition]:
        """Получение условия триггера по ID"""
        query = "SELECT id, device_id, condition, trigger_id FROM trig_conditions WHERE id = %s"
        result = self._execute_query(query, (condition_id,), fetch_one=True)
        if result:
            return TrigCondition(id=result[0], device_id=result[1], condition=result[2], trigger_id=result[3])
        return None

    def get_trig_conditions_by_device(self, device_id: int) -> List[TrigCondition]:
        """Получение условий по устройству"""
        query = "SELECT id, device_id, condition, trigger_id FROM trig_conditions WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_trig_conditions_by_trigger(self, trigger_id: int) -> List[TrigCondition]:
        """Получение условий по триггеру"""
        query = "SELECT id, device_id, condition, trigger_id FROM trig_conditions WHERE trigger_id = %s ORDER BY id"
        results = self._execute_query(query, (trigger_id,), fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_all_trig_conditions(self) -> List[TrigCondition]:
        """Получение всех условий триггеров"""
        query = "SELECT id, device_id, condition, trigger_id FROM trig_conditions ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def delete_trig_condition(self, condition_id: int) -> bool:
        """Удаление условия триггера по ID"""
        query = "DELETE FROM trig_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ TRIG_RESPONSES =============

    def add_trig_response(self, response: TrigResponse) -> Optional[int]:
        """Добавление ответа триггера"""
        query = """
            INSERT INTO trig_responses (device_id, resp, trigger_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (response.device_id, response.resp, response.trigger_id), fetch_one=True)
        if result:
            response.id = result[0]
            return result[0]
        return None

    def get_trig_response_by_id(self, response_id: int) -> Optional[TrigResponse]:
        """Получение ответа триггера по ID"""
        query = "SELECT id, device_id, resp, trigger_id FROM trig_responses WHERE id = %s"
        result = self._execute_query(query, (response_id,), fetch_one=True)
        if result:
            return TrigResponse(id=result[0], device_id=result[1], resp=result[2], trigger_id=result[3])
        return None

    def get_trig_responses_by_device(self, device_id: int) -> List[TrigResponse]:
        """Получение ответов по устройству"""
        query = "SELECT id, device_id, resp, trigger_id FROM trig_responses WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_trig_responses_by_trigger(self, trigger_id: int) -> List[TrigResponse]:
        """Получение ответов по триггеру"""
        query = "SELECT id, device_id, resp, trigger_id FROM trig_responses WHERE trigger_id = %s ORDER BY id"
        results = self._execute_query(query, (trigger_id,), fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_all_trig_responses(self) -> List[TrigResponse]:
        """Получение всех ответов триггеров"""
        query = "SELECT id, device_id, resp, trigger_id FROM trig_responses ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def delete_trig_response(self, response_id: int) -> bool:
        """Удаление ответа триггера по ID"""
        query = "DELETE FROM trig_responses WHERE id = %s"
        self._execute_query(query, (response_id,))
        return True