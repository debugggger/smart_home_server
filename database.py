import psycopg2
from psycopg2 import sql
from typing import Optional, List, Dict, Any
from datetime import datetime
from dotenv import load_dotenv
import os
from dataclasses import dataclass
from enum import Enum


# ============= ВСПОМОГАТЕЛЬНЫЕ КЛАССЫ =============

class EventValueType(Enum):
    """Типы значений событий"""
    TEMPERATURE = "temperature"
    HUMIDITY = "humidity"
    MOTION = "motion"
    SWITCH = "switch"
    CUSTOM = "custom"


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
    params: str = None  # JSON строка с параметрами

    def __repr__(self):
        return f"<Device(id={self.id}, name='{self.name}', type_id={self.type_id})>"


@dataclass
class Event:
    """Сущность события"""
    id: Optional[int] = None
    value: int = None
    device_id: int = None
    time: datetime = None

    def __post_init__(self):
        if self.time is None:
            self.time = datetime.now()

    def __repr__(self):
        return f"<Event(id={self.id}, device_id={self.device_id}, value={self.value}, time={self.time})>"

@dataclass
class DeviceType:
    """Сущность типа устройства"""
    id: Optional[int] = None
    name: str = None

    def __repr__(self):
        return f"<DeviceType(id={self.id}, name='{self.name}')>"


@dataclass
class TrigCondition:
    """Сущность условия триггера"""
    id: Optional[int] = None
    device_id: int = None
    condition: str = None

    def __repr__(self):
        return f"<TrigCondition(id={self.id}, device_id={self.device_id}, condition='{self.condition}')>"


@dataclass
class Trigger:
    """Сущность триггера"""
    id: Optional[int] = None
    controller_id: int = None
    condition_id: int = None
    response: str = None

    def __repr__(self):
        return f"<Trigger(id={self.id}, controller_id={self.controller_id}, condition_id={self.condition_id})>"

# ============= КЛАСС БАЗЫ ДАННЫХ С ПОЛНЫМ ИНТЕРФЕЙСОМ =============

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

    def get_room(self, room_id: int) -> Optional[Room]:
        """Получение комнаты по ID"""
        query = "SELECT id, name FROM rooms WHERE id = %s"
        result = self._execute_query(query, (room_id,), fetch_one=True)
        if result:
            return Room(id=result[0], name=result[1])
        return None

    def get_all_rooms(self) -> List[Room]:
        """Получение всех комнат"""
        query = "SELECT id, name FROM rooms ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Room(id=r[0], name=r[1]) for r in results] if results else []

    def update_room(self, room: Room) -> bool:
        """Обновление комнаты"""
        query = "UPDATE rooms SET name = %s WHERE id = %s"
        self._execute_query(query, (room.name, room.id))
        return True

    def delete_room(self, room_id: int) -> bool:
        """Удаление комнаты"""
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

    def get_controller(self, controller_id: int) -> Optional[Controller]:
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

    def get_all_controllers(self) -> List[Controller]:
        """Получение всех контроллеров"""
        query = "SELECT id, mac, room_id, name FROM controllers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3]) for r in results] if results else []

    def update_controller(self, controller: Controller) -> bool:
        """Обновление контроллера"""
        query = "UPDATE controllers SET mac = %s, room_id = %s, name = %s WHERE id = %s"
        self._execute_query(query, (controller.mac, controller.room_id, controller.name, controller.id))
        return True

    def delete_controller(self, controller_id: int) -> bool:
        """Удаление контроллера"""
        query = "DELETE FROM controllers WHERE id = %s"
        self._execute_query(query, (controller_id,))
        return True

        # ============= МЕТОДЫ ДЛЯ DEVICE_TYPES =============

    def add_device_type(self, device_type: DeviceType) -> Optional[int]:
        """Добавление типа устройства"""
        query = """
               INSERT INTO device_types (type) 
               VALUES (%s, %s) 
               RETURNING id
           """
        result = self._execute_query(query, (device_type.name), fetch_one=True)
        if result:
            device_type.id = result[0]
            return result[0]
        return None

    def get_device_type(self, type_id: int) -> Optional[DeviceType]:
        """Получение типа устройства по ID"""
        query = "SELECT id, type FROM device_types WHERE id = %s"
        result = self._execute_query(query, (type_id,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1])
        return None

    def get_device_type_by_name(self, name: str) -> Optional[DeviceType]:
        """Получение типа устройства по имени"""
        query = "SELECT id, type FROM device_types WHERE name = %s"
        result = self._execute_query(query, (name,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1])
        return None

    def get_all_device_types(self) -> List[DeviceType]:
        """Получение всех типов устройств"""
        query = "SELECT id, type FROM device_types ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [DeviceType(id=r[0], name=r[1]) for r in results] if results else []

    def update_device_type(self, device_type: DeviceType) -> bool:
        """Обновление типа устройства"""
        query = "UPDATE device_types SET name = %s, description = %s WHERE id = %s"
        self._execute_query(query, (device_type.name, device_type.id))
        return True

    def delete_device_type(self, type_id: int) -> bool:
        """Удаление типа устройства (только если нет устройств этого типа)"""
        # Проверяем, есть ли устройства с таким типом
        check_query = "SELECT COUNT(*) FROM devices WHERE type_id = %s"
        result = self._execute_query(check_query, (type_id,), fetch_one=True)

        if result and result[0] > 0:
            raise ValueError(
                f"Cannot delete device type with id {type_id} because it has {result[0]} associated devices")

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

    def get_device(self, device_id: int) -> Optional[Device]:
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

    def get_all_devices(self) -> List[Device]:
        """Получение всех устройств"""
        query = "SELECT id, name, controller_id, type_id, port, params FROM devices ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5])
                for r in results] if results else []

    def update_device(self, device: Device) -> bool:
        """Обновление устройства"""
        query = """
            UPDATE devices 
            SET name = %s, controller_id = %s, type_id = %s, port = %s, params = %s 
            WHERE id = %s
        """
        self._execute_query(query, (device.name, device.controller_id, device.type_id,
                                    device.port, device.params, device.id))
        return True

    def delete_device(self, device_id: int) -> bool:
        """Удаление устройства"""
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ EVENTS =============

    def add_event(self, event: Event) -> Optional[int]:
        """Добавление события"""
        query = """
            INSERT INTO events (value, device_id, time) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (event.value, event.device_id, event.time), fetch_one=True)
        if result:
            event.id = result[0]
            return result[0]
        return None

    def get_event(self, event_id: int) -> Optional[Event]:
        """Получение события по ID"""
        query = "SELECT id, value, device_id, time FROM events WHERE id = %s"
        result = self._execute_query(query, (event_id,), fetch_one=True)
        if result:
            return Event(id=result[0], value=result[1], device_id=result[2], time=result[3])
        return None

    def get_events_by_device(self, device_id: int, limit: int = 100) -> List[Event]:
        """Получение событий устройства с ограничением по количеству"""
        query = """
            SELECT id, value, device_id, time 
            FROM events 
            WHERE device_id = %s 
            ORDER BY time DESC 
            LIMIT %s
        """
        results = self._execute_query(query, (device_id, limit), fetch_all=True)
        return [Event(id=r[0], value=r[1], device_id=r[2], time=r[3])
                for r in results] if results else []

    def get_events_by_time_range(self, device_id: int, start_time: datetime, end_time: datetime) -> List[Event]:
        """Получение событий устройства за временной промежуток"""
        query = """
            SELECT id, value, device_id, time 
            FROM events 
            WHERE device_id = %s AND time BETWEEN %s AND %s
            ORDER BY time DESC
        """
        results = self._execute_query(query, (device_id, start_time, end_time), fetch_all=True)
        return [Event(id=r[0], value=r[1], device_id=r[2], time=r[3])
                for r in results] if results else []

    def get_latest_event(self, device_id: int) -> Optional[Event]:
        """Получение последнего события устройства"""
        query = """
            SELECT id, value, device_id, time 
            FROM events 
            WHERE device_id = %s 
            ORDER BY time DESC 
            LIMIT 1
        """
        result = self._execute_query(query, (device_id,), fetch_one=True)
        if result:
            return Event(id=result[0], value=result[1], device_id=result[2], time=result[3])
        return None

    def delete_old_events(self, days: int = 30) -> int:
        """Удаление старых событий (старше указанного количества дней)"""
        query = "DELETE FROM events WHERE time < NOW() - INTERVAL '%s days'"
        self._execute_query(query, (days,))
        return True

        # ============= МЕТОДЫ ДЛЯ TRIG_CONDITIONS =============

    def add_trig_condition(self, condition: TrigCondition) -> Optional[int]:
        """Добавление условия триггера"""
        query = """
               INSERT INTO trig_conditions (device_id, condition) 
               VALUES (%s, %s) 
               RETURNING id
           """
        result = self._execute_query(query, (condition.device_id, condition.condition), fetch_one=True)
        if result:
            condition.id = result[0]
            return result[0]
        return None

    def get_trig_condition(self, condition_id: int) -> Optional[TrigCondition]:
        """Получение условия триггера по ID"""
        query = "SELECT id, device_id, condition FROM trig_conditions WHERE id = %s"
        result = self._execute_query(query, (condition_id,), fetch_one=True)
        if result:
            return TrigCondition(id=result[0], device_id=result[1], condition=result[2])
        return None

    def get_conditions_by_device(self, device_id: int) -> List[TrigCondition]:
        """Получение всех условий для устройства"""
        query = "SELECT id, device_id, condition FROM trig_conditions WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2]) for r in results] if results else []

    def get_all_trig_conditions(self) -> List[TrigCondition]:
        """Получение всех условий триггеров"""
        query = "SELECT id, device_id, condition FROM trig_conditions ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2]) for r in results] if results else []

    def update_trig_condition(self, condition: TrigCondition) -> bool:
        """Обновление условия триггера"""
        query = "UPDATE trig_conditions SET device_id = %s, condition = %s WHERE id = %s"
        self._execute_query(query, (condition.device_id, condition.condition, condition.id))
        return True

    def delete_trig_condition(self, condition_id: int) -> bool:
        """Удаление условия триггера (только если нет триггеров, использующих это условие)"""
        check_query = "SELECT COUNT(*) FROM triggers WHERE condition_id = %s"
        result = self._execute_query(check_query, (condition_id,), fetch_one=True)

        if result and result[0] > 0:
            raise ValueError(
                f"Cannot delete condition with id {condition_id} because it has {result[0]} associated triggers")

        query = "DELETE FROM trig_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        return True

        # ============= МЕТОДЫ ДЛЯ TRIGGERS =============

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        """Добавление триггера"""
        query = """
               INSERT INTO triggers (controller_id, condition_id, response) 
               VALUES (%s, %s, %s) 
               RETURNING id
           """
        result = self._execute_query(query, (trigger.controller_id, trigger.condition_id, trigger.response),
                                     fetch_one=True)
        if result:
            trigger.id = result[0]
            return result[0]
        return None

    def get_trigger(self, trigger_id: int) -> Optional[Trigger]:
        """Получение триггера по ID"""
        query = "SELECT id, controller_id, condition_id, response FROM triggers WHERE id = %s"
        result = self._execute_query(query, (trigger_id,), fetch_one=True)
        if result:
            return Trigger(id=result[0], controller_id=result[1], condition_id=result[2], response=result[3])
        return None

    def get_triggers_by_controller(self, controller_id: int) -> List[Trigger]:
        """Получение всех триггеров для контроллера"""
        query = "SELECT id, controller_id, condition_id, response FROM triggers WHERE controller_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], condition_id=r[2], response=r[3]) for r in
                results] if results else []

    def get_triggers_by_condition(self, condition_id: int) -> List[Trigger]:
        """Получение всех триггеров для условия"""
        query = "SELECT id, controller_id, condition_id, response FROM triggers WHERE condition_id = %s"
        results = self._execute_query(query, (condition_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], condition_id=r[2], response=r[3]) for r in
                results] if results else []

    def get_all_triggers(self) -> List[Trigger]:
        """Получение всех триггеров"""
        query = "SELECT id, controller_id, condition_id, response FROM triggers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], condition_id=r[2], response=r[3]) for r in
                results] if results else []

    def update_trigger(self, trigger: Trigger) -> bool:
        """Обновление триггера"""
        query = "UPDATE triggers SET controller_id = %s, condition_id = %s, response = %s WHERE id = %s"
        self._execute_query(query, (trigger.controller_id, trigger.condition_id, trigger.response, trigger.id))
        return True

    def delete_trigger(self, trigger_id: int) -> bool:
        """Удаление триггера"""
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))
        return True

    # ============= СЛОЖНЫЕ ЗАПРОСЫ =============

    def get_full_room_info(self, room_id: int) -> Dict[str, Any]:
        """Получение полной информации о комнате (контроллеры, устройства, последние события)"""
        room = self.get_room(room_id)
        if not room:
            return {}

        controllers = self.get_controllers_by_room(room_id)
        result = {
            'room': room,
            'controllers': []
        }

        for controller in controllers:
            devices = self.get_devices_by_controller(controller.id)
            controller_data = {
                'controller': controller,
                'devices': []
            }

            for device in devices:
                latest_event = self.get_latest_event(device.id)
                controller_data['devices'].append({
                    'device': device,
                    'latest_event': latest_event
                })

            result['controllers'].append(controller_data)

        return result

    def get_device_statistics(self, device_id: int, hours: int = 24) -> Dict[str, Any]:
        """Получение статистики по устройству за последние N часов"""
        query = """
            SELECT 
                COUNT(*) as event_count,
                AVG(value) as avg_value,
                MIN(value) as min_value,
                MAX(value) as max_value
            FROM events 
            WHERE device_id = %s AND time > NOW() - INTERVAL '%s hours'
        """
        result = self._execute_query(query, (device_id, hours), fetch_one=True)

        if result:
            return {
                'device_id': device_id,
                'hours': hours,
                'event_count': result[0],
                'avg_value': float(result[1]) if result[1] else None,
                'min_value': result[2],
                'max_value': result[3]
            }
        return {}

