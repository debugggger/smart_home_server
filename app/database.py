# database.py - полный класс с кешированием
import json
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Room:
    id: Optional[int] = None
    name: str = None


@dataclass
class Controller:
    id: Optional[int] = None
    mac: str = None
    room_id: int = None
    name: str = None
    is_online: bool = False

@dataclass
class Device:
    id: Optional[int] = None
    name: str = None
    controller_id: int = None
    type_id: int = None
    port: str = None
    params: json = None
    current_values: Optional[List[str]] = None
    is_online: bool = False

@dataclass
class DeviceType:
    id: Optional[int] = None
    name: str = None
    param_name: json = None
    description: Optional[str] = None

@dataclass
class Trigger:
    id: Optional[int] = None
    controller_id: int = None
    controller_resp_id: int = None
    name: str = None
    is_active: bool = True

@dataclass
class TrigCondition:
    id: Optional[int] = None
    device_id: int = None
    condition: str = None
    trigger_id: int = None

@dataclass
class TrigResponse:
    id: Optional[int] = None
    device_id: int = None
    resp: str = None
    trigger_id: int = None

@dataclass
class Scene:
    id: Optional[int] = None
    name: str = None
    is_active: bool = True

@dataclass
class SceneCondition:
    id: Optional[int] = None
    device_id: int = None
    condition: str = None
    scene_id: int = None

@dataclass
class SceneResponse:
    id: Optional[int] = None
    device_id: int = None
    resp: str = None
    scene_id: int = None

class Database:
    def __init__(self, host=None, port=None, name=None, user=None, password=None):

        import psycopg2
        self.connection = psycopg2.connect(
            host=host,
            user=user,
            password=password,
            database=name,
            port=port
        )
        self.connection.autocommit = True

        self._rooms_cache = {}  # id -> Room
        self._controllers_cache = {}  # id -> Controller
        self._devices_cache = {}  # id -> Device
        self._device_types_cache = {}  # id -> DeviceType
        self._triggers_cache = {}  # id -> Trigger
        self._trigger_conditions_cache = {}  # id -> TrigCondition
        self._trigger_responses_cache = {}  # id -> TrigResponse
        self._scenes_cache = {}  # id -> Scene
        self._scene_conditions_cache = {}  # id -> SceneCondition
        self._scene_responses_cache = {}  # id -> SceneResponse

        self._controllers_by_room = {}  # room_id -> [controller_ids]
        self._devices_by_controller = {}  # controller_id -> [device_ids]
        self._devices_by_type = {}  # type_id -> [device_ids]
        self._triggers_by_controller = {}  # controller_id -> [trigger_ids]
        self._triggers_by_resp_controller = {}  # controller_resp_id -> [trigger_ids]
        self._conditions_by_trigger = {}  # trigger_id -> [condition_ids]
        self._responses_by_trigger = {}  # trigger_id -> [response_ids]
        self._conditions_by_scene = {}  # scene_id -> [condition_ids]
        self._responses_by_scene = {}  # scene_id -> [response_ids]

        self._load_all_cache()


    def _load_all_cache(self):
        self._load_rooms_cache()
        self._load_controllers_cache()
        self._load_device_types_cache()
        self._load_devices_cache()
        self._load_triggers_cache()
        self._load_scenes_cache()

    def _load_rooms_cache(self):
        query = "SELECT id, name FROM rooms"
        results = self._execute_query(query, fetch_all=True)
        self._rooms_cache = {}
        for r in results:
            self._rooms_cache[r[0]] = Room(id=r[0], name=r[1])

    def _load_controllers_cache(self):
        query = "SELECT id, mac, room_id, name, is_online FROM controllers"
        results = self._execute_query(query, fetch_all=True)
        self._controllers_cache = {}
        self._controllers_by_room = {}

        for r in results:
            controller = Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3], is_online=r[4])
            self._controllers_cache[r[0]] = controller

            if r[2] not in self._controllers_by_room:
                self._controllers_by_room[r[2]] = []
            self._controllers_by_room[r[2]].append(r[0])

    def _load_device_types_cache(self):
        query = "SELECT id, name, param_names, description FROM device_types"
        results = self._execute_query(query, fetch_all=True)
        self._device_types_cache = {}
        for r in results:
            self._device_types_cache[r[0]] = DeviceType(
                id=r[0], name=r[1], param_name=r[2], description=r[3]
            )

    def _load_devices_cache(self):
        query = "SELECT id, name, controller_id, type_id, port, params, current_values, is_online FROM devices"
        results = self._execute_query(query, fetch_all=True)
        self._devices_cache = {}
        self._devices_by_controller = {}
        self._devices_by_type = {}

        for r in results:
            device = Device(
                id=r[0], name=r[1], controller_id=r[2], type_id=r[3],
                port=r[4], params=r[5], current_values=r[6], is_online=r[7]
            )
            self._devices_cache[r[0]] = device

            if r[2] not in self._devices_by_controller:
                self._devices_by_controller[r[2]] = []
            self._devices_by_controller[r[2]].append(r[0])

            if r[3] not in self._devices_by_type:
                self._devices_by_type[r[3]] = []
            self._devices_by_type[r[3]].append(r[0])

    def _load_triggers_cache(self):
        query = "SELECT id, controller_id, controller_resp_id, name, is_active FROM triggers"
        results = self._execute_query(query, fetch_all=True)
        self._triggers_cache = {}
        self._triggers_by_controller = {}
        self._triggers_by_resp_controller = {}

        for r in results:
            trigger = Trigger(
                id=r[0], controller_id=r[1], controller_resp_id=r[2],
                name=r[3], is_active=r[4]
            )
            self._triggers_cache[r[0]] = trigger

            if r[1] not in self._triggers_by_controller:
                self._triggers_by_controller[r[1]] = []
            self._triggers_by_controller[r[1]].append(r[0])

            if r[2] not in self._triggers_by_resp_controller:
                self._triggers_by_resp_controller[r[2]] = []
            self._triggers_by_resp_controller[r[2]].append(r[0])

        query = "SELECT id, device_id, condition, trigger_id FROM trig_conditions"
        results = self._execute_query(query, fetch_all=True)
        self._trigger_conditions_cache = {}
        self._conditions_by_trigger = {}

        for r in results:
            condition = TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
            self._trigger_conditions_cache[r[0]] = condition

            if r[3] not in self._conditions_by_trigger:
                self._conditions_by_trigger[r[3]] = []
            self._conditions_by_trigger[r[3]].append(r[0])

        query = "SELECT id, device_id, resp, trigger_id FROM trig_responses"
        results = self._execute_query(query, fetch_all=True)
        self._trigger_responses_cache = {}
        self._responses_by_trigger = {}

        for r in results:
            response = TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
            self._trigger_responses_cache[r[0]] = response

            if r[3] not in self._responses_by_trigger:
                self._responses_by_trigger[r[3]] = []
            self._responses_by_trigger[r[3]].append(r[0])

    def _load_scenes_cache(self):
        query = "SELECT id, name, is_active FROM scenes"
        results = self._execute_query(query, fetch_all=True)
        self._scenes_cache = {}

        for r in results:
            self._scenes_cache[r[0]] = Scene(id=r[0], name=r[1], is_active=r[2])

        query = "SELECT id, device_id, condition, scene_id FROM scene_conditions"
        results = self._execute_query(query, fetch_all=True)
        self._scene_conditions_cache = {}
        self._conditions_by_scene = {}

        for r in results:
            condition = SceneCondition(id=r[0], device_id=r[1], condition=r[2], scene_id=r[3])
            self._scene_conditions_cache[r[0]] = condition

            if r[3] not in self._conditions_by_scene:
                self._conditions_by_scene[r[3]] = []
            self._conditions_by_scene[r[3]].append(r[0])

        query = "SELECT id, device_id, resp, scene_id FROM scene_responses"
        results = self._execute_query(query, fetch_all=True)
        self._scene_responses_cache = {}
        self._responses_by_scene = {}

        for r in results:
            response = SceneResponse(id=r[0], device_id=r[1], resp=r[2], scene_id=r[3])
            self._scene_responses_cache[r[0]] = response

            if r[3] not in self._responses_by_scene:
                self._responses_by_scene[r[3]] = []
            self._responses_by_scene[r[3]].append(r[0])

    def _execute_query(self, query: str, params: tuple = None,
                       fetch_one: bool = False, fetch_all: bool = False):
        with self.connection.cursor() as cur:
            cur.execute(query, params)
            if fetch_one:
                return cur.fetchone()
            elif fetch_all:
                return cur.fetchall()
            return None

    def add_room(self, room: Room) -> Optional[int]:
        query = "INSERT INTO rooms (name) VALUES (%s) RETURNING id"
        result = self._execute_query(query, (room.name,), fetch_one=True)
        if result:
            room.id = result[0]
            self._rooms_cache[room.id] = room
            return result[0]
        return None

    def get_room_by_id(self, room_id: int) -> Optional[Room]:
        """Получение комнаты по ID из кеша"""
        return self._rooms_cache.get(room_id)

    def get_rooms_by_name(self, name: str) -> List[Room]:
        """Получение комнат по имени из кеша"""
        return [r for r in self._rooms_cache.values() if r.name == name]

    def get_all_rooms(self) -> List[Room]:
        """Получение всех комнат из кеша"""
        return list(self._rooms_cache.values())

    def delete_room(self, room_id: int) -> bool:
        """Удаление комнаты по ID"""
        query = "DELETE FROM rooms WHERE id = %s"
        self._execute_query(query, (room_id,))
        if room_id in self._rooms_cache:
            del self._rooms_cache[room_id]
        return True

    # ============= МЕТОДЫ ДЛЯ CONTROLLERS (кешированные) =============

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
            self._controllers_cache[controller.id] = controller

            # Обновляем индекс по комнате
            if controller.room_id not in self._controllers_by_room:
                self._controllers_by_room[controller.room_id] = []
            self._controllers_by_room[controller.room_id].append(controller.id)

            return result[0]
        return None

    def get_controller_by_id(self, controller_id: int) -> Optional[Controller]:
        """Получение контроллера по ID из кеша"""
        return self._controllers_cache.get(controller_id)

    def get_controllers_by_room(self, room_id: int) -> List[Controller]:
        """Получение всех контроллеров в комнате из кеша"""
        result = []
        for cid in self._controllers_by_room.get(room_id, []):
            controller = self._controllers_cache.get(cid)
            if controller:
                result.append(controller)
        return result

    def get_controllers_by_mac(self, mac: str) -> List[Controller]:
        """Получение контроллеров по MAC адресу из кеша"""
        return [c for c in self._controllers_cache.values() if c.mac == mac]

    def get_all_controllers(self) -> List[Controller]:
        """Получение всех контроллеров из кеша"""
        return list(self._controllers_cache.values())

    def update_controller_status(self, mac: str, is_online: bool) -> bool:
        """Обновление статуса контроллера"""
        query = "UPDATE controllers SET is_online = %s WHERE mac = %s"
        self._execute_query(query, (is_online, mac))

        for controller in self._controllers_cache.values():
            if controller.mac == mac:
                controller.is_online = is_online
                return True
        return False

    def delete_controller(self, controller_id: int) -> bool:
        """Удаление контроллера по ID"""
        query = "DELETE FROM controllers WHERE id = %s"
        self._execute_query(query, (controller_id,))
        if controller_id in self._controllers_cache:
            del self._controllers_cache[controller_id]
        return True

    # ============= МЕТОДЫ ДЛЯ DEVICE_TYPES (кешированные) =============

    def add_device_type(self, device_type: DeviceType) -> Optional[int]:
        """Добавление типа устройства"""
        query = """
            INSERT INTO device_types (name, param_names, description) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (device_type.name, device_type.param_name, device_type.description),
            fetch_one=True
        )
        if result:
            device_type.id = result[0]
            self._device_types_cache[device_type.id] = device_type
            return result[0]
        return None

    def get_device_type_by_id(self, type_id: int) -> Optional[DeviceType]:
        """Получение типа устройства по ID из кеша"""
        return self._device_types_cache.get(type_id)

    def get_device_type_by_name(self, name: str) -> Optional[DeviceType]:
        """Получение типа устройства по имени из кеша"""
        for dt in self._device_types_cache.values():
            if dt.name == name:
                return dt
        return None

    def get_all_device_types(self) -> List[DeviceType]:
        """Получение всех типов устройств из кеша"""
        return list(self._device_types_cache.values())

    def delete_device_type(self, type_id: int) -> bool:
        """Удаление типа устройства по ID"""
        query = "DELETE FROM device_types WHERE id = %s"
        self._execute_query(query, (type_id,))
        if type_id in self._device_types_cache:
            del self._device_types_cache[type_id]
        return True

    # ============= МЕТОДЫ ДЛЯ DEVICES (кешированные) =============

    def add_device(self, device: Device) -> Optional[int]:
        """Добавление устройства"""
        query = """
            INSERT INTO devices (name, controller_id, type_id, port, params, current_values) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (device.name, device.controller_id, device.type_id,
             device.port, device.params, device.current_values),
            fetch_one=True
        )
        if result:
            device.id = result[0]
            self._devices_cache[device.id] = device

            # Обновляем индексы
            if device.controller_id not in self._devices_by_controller:
                self._devices_by_controller[device.controller_id] = []
            self._devices_by_controller[device.controller_id].append(device.id)

            if device.type_id not in self._devices_by_type:
                self._devices_by_type[device.type_id] = []
            self._devices_by_type[device.type_id].append(device.id)

            return result[0]
        return None

    def get_device_by_id(self, device_id: int) -> Optional[Device]:
        """Получение устройства по ID из кеша"""
        return self._devices_cache.get(device_id)

    def get_devices_by_controller(self, controller_id: int) -> List[Device]:
        """Получение всех устройств контроллера из кеша"""
        result = []
        for did in self._devices_by_controller.get(controller_id, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_devices_by_type(self, type_id: int) -> List[Device]:
        """Получение устройств по типу из кеша"""
        result = []
        for did in self._devices_by_type.get(type_id, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_devices_by_name(self, name: str) -> List[Device]:
        """Получение устройств по имени из кеша"""
        return [d for d in self._devices_cache.values() if d.name == name]

    def get_all_devices(self) -> List[Device]:
        """Получение всех устройств из кеша"""
        return list(self._devices_cache.values())

    def update_device_status(self, device_id: int, is_online: bool) -> bool:
        """Обновление статуса устройства"""
        query = "UPDATE devices SET is_online = %s WHERE id = %s"
        self._execute_query(query, (is_online, device_id))

        device = self._devices_cache.get(device_id)
        if device:
            device.is_online = is_online
            return True
        return False

    def update_device_current_values(self, device_id: int, current_values: str) -> bool:
        """Обновление текущих значений устройства"""
        query = "UPDATE devices SET current_values = %s WHERE id = %s"
        self._execute_query(query, (current_values, device_id))

        device = self._devices_cache.get(device_id)
        if device:
            device.current_values = current_values
            return True
        return False

    def delete_device(self, device_id: int) -> bool:
        """Удаление устройства по ID"""
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))
        if device_id in self._devices_cache:
            del self._devices_cache[device_id]
        return True

    # ============= МЕТОДЫ ДЛЯ TRIGGERS (кешированные) =============

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        """Добавление триггера"""
        query = """
            INSERT INTO triggers (controller_id, controller_resp_id, name, is_active) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (trigger.controller_id, trigger.controller_resp_id, trigger.name, trigger.is_active),
            fetch_one=True
        )
        if result:
            trigger.id = result[0]
            self._triggers_cache[trigger.id] = trigger

            # Обновляем индексы
            if trigger.controller_id not in self._triggers_by_controller:
                self._triggers_by_controller[trigger.controller_id] = []
            self._triggers_by_controller[trigger.controller_id].append(trigger.id)

            if trigger.controller_resp_id not in self._triggers_by_resp_controller:
                self._triggers_by_resp_controller[trigger.controller_resp_id] = []
            self._triggers_by_resp_controller[trigger.controller_resp_id].append(trigger.id)

            return result[0]
        return None

    def get_trigger_by_id(self, trigger_id: int) -> Optional[Trigger]:
        """Получение триггера по ID из кеша"""
        return self._triggers_cache.get(trigger_id)

    def get_triggers_by_controller(self, controller_id: int) -> List[Trigger]:
        """Получение триггеров по контроллеру-источнику из кеша"""
        result = []
        for tid in self._triggers_by_controller.get(controller_id, []):
            trigger = self._triggers_cache.get(tid)
            if trigger:
                result.append(trigger)
        return result

    def get_triggers_by_resp_controller(self, controller_resp_id: int) -> List[Trigger]:
        """Получение триггеров по контроллеру-приемнику из кеша"""
        result = []
        for tid in self._triggers_by_resp_controller.get(controller_resp_id, []):
            trigger = self._triggers_cache.get(tid)
            if trigger:
                result.append(trigger)
        return result

    def get_triggers_by_name(self, name: str) -> List[Trigger]:
        """Получение триггеров по имени из кеша"""
        return [t for t in self._triggers_cache.values() if t.name == name]

    def get_all_triggers(self) -> List[Trigger]:
        """Получение всех триггеров из кеша"""
        return list(self._triggers_cache.values())

    def update_trig_status(self, trigger_id: int, is_active: bool) -> bool:
        """Обновление статуса триггера"""
        query = "UPDATE triggers SET is_active = %s WHERE id = %s"
        self._execute_query(query, (is_active, trigger_id))

        trigger = self._triggers_cache.get(trigger_id)
        if trigger:
            trigger.is_active = is_active
            return True
        return False

    def delete_trigger(self, trigger_id: int) -> bool:
        """Удаление триггера по ID"""
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))
        if trigger_id in self._triggers_cache:
            del self._triggers_cache[trigger_id]
        return True

    # ============= МЕТОДЫ ДЛЯ TRIG_CONDITIONS (кешированные) =============

    def add_trig_condition(self, condition: TrigCondition) -> Optional[int]:
        """Добавление условия триггера"""
        query = """
            INSERT INTO trig_conditions (device_id, condition, trigger_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (condition.device_id, condition.condition, condition.trigger_id),
            fetch_one=True
        )
        if result:
            condition.id = result[0]
            self._trigger_conditions_cache[condition.id] = condition

            if condition.trigger_id not in self._conditions_by_trigger:
                self._conditions_by_trigger[condition.trigger_id] = []
            self._conditions_by_trigger[condition.trigger_id].append(condition.id)

            return result[0]
        return None

    def get_trig_condition_by_id(self, condition_id: int) -> Optional[TrigCondition]:
        """Получение условия триггера по ID из кеша"""
        return self._trigger_conditions_cache.get(condition_id)

    def get_trig_conditions_by_device(self, device_id: int) -> List[TrigCondition]:
        """Получение условий по устройству из кеша"""
        return [c for c in self._trigger_conditions_cache.values() if c.device_id == device_id]

    def get_trig_conditions_by_trigger(self, trigger_id: int) -> List[TrigCondition]:
        """Получение условий по триггеру из кеша"""
        result = []
        for cid in self._conditions_by_trigger.get(trigger_id, []):
            condition = self._trigger_conditions_cache.get(cid)
            if condition:
                result.append(condition)
        return result

    def get_all_trig_conditions(self) -> List[TrigCondition]:
        """Получение всех условий триггеров из кеша"""
        return list(self._trigger_conditions_cache.values())

    def delete_trig_condition(self, condition_id: int) -> bool:
        """Удаление условия триггера по ID"""
        query = "DELETE FROM trig_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        if condition_id in self._trigger_conditions_cache:
            del self._trigger_conditions_cache[condition_id]
        return True

    # ============= МЕТОДЫ ДЛЯ TRIG_RESPONSES (кешированные) =============

    def add_trig_response(self, response: TrigResponse) -> Optional[int]:
        """Добавление ответа триггера"""
        query = """
            INSERT INTO trig_responses (device_id, resp, trigger_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (response.device_id, response.resp, response.trigger_id),
            fetch_one=True
        )
        if result:
            response.id = result[0]
            self._trigger_responses_cache[response.id] = response

            if response.trigger_id not in self._responses_by_trigger:
                self._responses_by_trigger[response.trigger_id] = []
            self._responses_by_trigger[response.trigger_id].append(response.id)

            return result[0]
        return None

    def get_trig_response_by_id(self, response_id: int) -> Optional[TrigResponse]:
        """Получение ответа триггера по ID из кеша"""
        return self._trigger_responses_cache.get(response_id)

    def get_trig_responses_by_device(self, device_id: int) -> List[TrigResponse]:
        """Получение ответов по устройству из кеша"""
        return [r for r in self._trigger_responses_cache.values() if r.device_id == device_id]

    def get_trig_responses_by_trigger(self, trigger_id: int) -> List[TrigResponse]:
        """Получение ответов по триггеру из кеша"""
        result = []
        for rid in self._responses_by_trigger.get(trigger_id, []):
            response = self._trigger_responses_cache.get(rid)
            if response:
                result.append(response)
        return result

    def get_all_trig_responses(self) -> List[TrigResponse]:
        """Получение всех ответов триггеров из кеша"""
        return list(self._trigger_responses_cache.values())

    def delete_trig_response(self, response_id: int) -> bool:
        """Удаление ответа триггера по ID"""
        query = "DELETE FROM trig_responses WHERE id = %s"
        self._execute_query(query, (response_id,))
        if response_id in self._trigger_responses_cache:
            del self._trigger_responses_cache[response_id]
        return True

    # ============= МЕТОДЫ ДЛЯ SCENES (кешированные) =============

    def add_scene(self, scene: Scene) -> Optional[int]:
        """Добавление сценария"""
        query = "INSERT INTO scenes (name, is_active) VALUES (%s, %s) RETURNING id"
        result = self._execute_query(query, (scene.name, scene.is_active), fetch_one=True)
        if result:
            scene.id = result[0]
            self._scenes_cache[scene.id] = scene
            return result[0]
        return None

    def get_scene_by_id(self, scene_id: int) -> Optional[Scene]:
        """Получение сценария по ID из кеша"""
        return self._scenes_cache.get(scene_id)

    def get_scenes_by_name(self, name: str) -> List[Scene]:
        """Получение сценариев по имени из кеша"""
        return [s for s in self._scenes_cache.values() if s.name == name]

    def get_all_scenes(self) -> List[Scene]:
        """Получение всех сценариев из кеша"""
        return list(self._scenes_cache.values())

    def update_scene_status(self, scene_id: int, is_active: bool) -> bool:
        """Обновление статуса сценария"""
        query = "UPDATE scenes SET is_active = %s WHERE id = %s"
        self._execute_query(query, (is_active, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.is_active = is_active
            return True
        return False

    def update_scene_name(self, scene_id: int, name: str) -> bool:
        """Обновление имени сценария"""
        query = "UPDATE scenes SET name = %s WHERE id = %s"
        self._execute_query(query, (name, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.name = name
            return True
        return False

    def delete_scene(self, scene_id: int) -> bool:
        """Удаление сценария по ID"""
        query = "DELETE FROM scenes WHERE id = %s"
        self._execute_query(query, (scene_id,))
        if scene_id in self._scenes_cache:
            del self._scenes_cache[scene_id]
        return True

    # ============= МЕТОДЫ ДЛЯ SCENE_CONDITIONS (кешированные) =============

    def add_scene_condition(self, condition: SceneCondition) -> Optional[int]:
        """Добавление условия сценария"""
        query = """
            INSERT INTO scene_conditions (device_id, condition, scene_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (condition.device_id, condition.condition, condition.scene_id),
            fetch_one=True
        )
        if result:
            condition.id = result[0]
            self._scene_conditions_cache[condition.id] = condition

            if condition.scene_id not in self._conditions_by_scene:
                self._conditions_by_scene[condition.scene_id] = []
            self._conditions_by_scene[condition.scene_id].append(condition.id)

            return result[0]
        return None

    def get_scene_condition_by_id(self, condition_id: int) -> Optional[SceneCondition]:
        """Получение условия сценария по ID из кеша"""
        return self._scene_conditions_cache.get(condition_id)

    def get_scene_conditions_by_device(self, device_id: int) -> List[SceneCondition]:
        """Получение условий по устройству из кеша"""
        return [c for c in self._scene_conditions_cache.values() if c.device_id == device_id]

    def get_scene_conditions_by_scene(self, scene_id: int) -> List[SceneCondition]:
        """Получение условий по сценарию из кеша"""
        result = []
        for cid in self._conditions_by_scene.get(scene_id, []):
            condition = self._scene_conditions_cache.get(cid)
            if condition:
                result.append(condition)
        return result

    def get_all_scene_conditions(self) -> List[SceneCondition]:
        """Получение всех условий сценариев из кеша"""
        return list(self._scene_conditions_cache.values())

    def delete_scene_condition(self, condition_id: int) -> bool:
        """Удаление условия сценария по ID"""
        query = "DELETE FROM scene_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        if condition_id in self._scene_conditions_cache:
            del self._scene_conditions_cache[condition_id]
        return True

    # ============= МЕТОДЫ ДЛЯ SCENE_RESPONSES (кешированные) =============

    def add_scene_response(self, response: SceneResponse) -> Optional[int]:
        """Добавление ответа сценария"""
        query = """
            INSERT INTO scene_responses (device_id, resp, scene_id) 
            VALUES (%s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (response.device_id, response.resp, response.scene_id),
            fetch_one=True
        )
        if result:
            response.id = result[0]
            self._scene_responses_cache[response.id] = response

            if response.scene_id not in self._responses_by_scene:
                self._responses_by_scene[response.scene_id] = []
            self._responses_by_scene[response.scene_id].append(response.id)

            return result[0]
        return None

    def get_scene_response_by_id(self, response_id: int) -> Optional[SceneResponse]:
        """Получение ответа сценария по ID из кеша"""
        return self._scene_responses_cache.get(response_id)

    def get_scene_responses_by_device(self, device_id: int) -> List[SceneResponse]:
        """Получение ответов по устройству из кеша"""
        return [r for r in self._scene_responses_cache.values() if r.device_id == device_id]

    def get_scene_responses_by_scene(self, scene_id: int) -> List[SceneResponse]:
        """Получение ответов по сценарию из кеша"""
        result = []
        for rid in self._responses_by_scene.get(scene_id, []):
            response = self._scene_responses_cache.get(rid)
            if response:
                result.append(response)
        return result

    def get_all_scene_responses(self) -> List[SceneResponse]:
        """Получение всех ответов сценариев из кеша"""
        return list(self._scene_responses_cache.values())

    def delete_scene_response(self, response_id: int) -> bool:
        """Удаление ответа сценария по ID"""
        query = "DELETE FROM scene_responses WHERE id = %s"
        self._execute_query(query, (response_id,))
        if response_id in self._scene_responses_cache:
            del self._scene_responses_cache[response_id]
        return True

    # ============= ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ ДЛЯ ОБНОВЛЕНИЯ КЕША =============

    def refresh_cache(self):
        """Принудительное обновление всего кеша из БД"""
        self._load_all_cache()
        logger.info("Cache refreshed from database")

    def get_cache_stats(self) -> dict:
        """Получить статистику кеша"""
        return {
            'rooms': len(self._rooms_cache),
            'controllers': len(self._controllers_cache),
            'devices': len(self._devices_cache),
            'device_types': len(self._device_types_cache),
            'triggers': len(self._triggers_cache),
            'trigger_conditions': len(self._trigger_conditions_cache),
            'trigger_responses': len(self._trigger_responses_cache),
            'scenes': len(self._scenes_cache),
            'scene_conditions': len(self._scene_conditions_cache),
            'scene_responses': len(self._scene_responses_cache)
        }

    def close(self):
        """Закрытие соединения с БД"""
        if self.connection:
            self.connection.close()
            logger.info("Database connection closed")