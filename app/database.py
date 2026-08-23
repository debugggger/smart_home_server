import json
import psycopg2
from typing import Optional, List
from dataclasses import dataclass

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


# @dataclass
# class Event:
#     id: Optional[int] = None
#     value: int = None
#     device_id: int = None
#     time: datetime = None


@dataclass
class DeviceType:
    id: Optional[int] = None
    name: str = None
    param_name: json = None
    description: Optional[str] = None

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
class Trigger:
    id: Optional[int] = None
    controller_id: int = None
    controller_resp_id: int = None
    name: str = None
    is_active: bool = False

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

@dataclass
class Scene:
    id: Optional[int] = None
    name: str = None
    is_active: bool = False

class Database:
    def __init__(self, host='127.0.0.1', port=443, name='sh', user='postgres', password=''):
        self.connection = psycopg2.connect(
            host=host,
            user=user,
            password=password,
            database=name,
            port=port
        )
        self.connection.autocommit = True
        with self.connection.cursor() as cur:
            cur.execute("select version();")
            print(f"server vers:  {cur.fetchone()}")

    def close(self):
        self.connection.close()
        print("[INFO] Close connection with DB")

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
            return result[0]
        return None

    def get_room_by_id(self, room_id: int) -> Optional[Room]:
        query = "SELECT * FROM rooms WHERE id = %s"
        result = self._execute_query(query, (room_id,), fetch_one=True)
        if result:
            return Room(id=result[0], name=result[1])
        return None

    def get_rooms_by_name(self, name: str) -> List[Room]:
        query = "SELECT * FROM rooms WHERE name = %s"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Room(id=r[0], name=r[1]) for r in results] if results else []

    def get_all_rooms(self) -> List[Room]:
        query = "SELECT * FROM rooms ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Room(id=r[0], name=r[1]) for r in results] if results else []

    def delete_room(self, room_id: int, kafkaHandler) -> bool:

        conntollers = self.get_controllers_by_room(room_id)
        for controller in conntollers:
            self.delete_controller(controller.id, kafkaHandler)

        query = "DELETE FROM rooms WHERE id = %s"
        self._execute_query(query, (room_id,))
        return True

    def add_controller(self, controller: Controller) -> Optional[int]:
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
        query = "SELECT * FROM controllers WHERE id = %s"
        result = self._execute_query(query, (controller_id,), fetch_one=True)
        if result:
            return Controller(id=result[0], mac=result[1], room_id=result[2], name=result[3], is_online=result[4])
        return None

    def get_controllers_by_room(self, room_id: int) -> List[Controller]:
        query = "SELECT * FROM controllers WHERE room_id = %s ORDER BY id"
        results = self._execute_query(query, (room_id,), fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3], is_online=r[4]) for r in results] if results else []

    def get_controllers_by_mac(self, mac: str) -> List[Controller]:
        query = "SELECT * FROM controllers WHERE mac = %s"
        results = self._execute_query(query, (mac,), fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3], is_online=r[4]) for r in results] if results else []

    def get_all_controllers(self) -> List[Controller]:
        query = "SELECT * FROM controllers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Controller(id=r[0], mac=r[1], room_id=r[2], name=r[3], is_online=r[4]) for r in results] if results else []

    def delete_controller(self, controller_id: int, kafkaHandler) -> bool:

        triggers = {}
        for t in self.get_triggers_by_controller(controller_id):
            triggers[t.id] = t

        for t in self.get_triggers_by_resp_controller(controller_id):
            if t.id not in triggers:
                triggers[t.id] = t

        unique_triggers = list(triggers.values())
        for trig in unique_triggers:
            if not self.delete_trigger(trig.id, kafkaHandler):
                return False

        devices = self.get_devices_by_controller(controller_id)
        for device in devices:
            if not self.delete_device(device.id, kafkaHandler):
                return False

        query = "DELETE FROM controllers WHERE id = %s"
        self._execute_query(query, (controller_id,))
        return True

    def update_controller_status(self, mac: str, status: bool):
        query = """
            UPDATE controllers 
            SET is_online = %s 
            WHERE mac = %s
        """
        result = self._execute_query(query, (status, mac))
        return result is not None


    def get_device_type_by_id(self, type_id: int) -> Optional[DeviceType]:
        query = "SELECT * FROM device_types WHERE id = %s"
        result = self._execute_query(query, (type_id,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1], description=result[2], param_name=result[3])
        return None

    def get_device_type_by_name(self, name: str) -> Optional[DeviceType]:
        query = "SELECT * FROM device_types WHERE name = %s"
        result = self._execute_query(query, (name,), fetch_one=True)
        if result:
            return DeviceType(id=result[0], name=result[1], description=result[2], param_name=result[3])
        return None

    def get_all_device_types(self) -> List[DeviceType]:
        query = "SELECT * FROM device_types ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [DeviceType(id=r[0], name=r[1], description=r[2], param_name = r[3]) for r in results] if results else []


    def add_device(self, device: Device) -> Optional[int]:
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
        query = "SELECT * FROM devices WHERE id = %s"
        result = self._execute_query(query, (device_id,), fetch_one=True)
        if result:
            return Device(id=result[0], name=result[1], controller_id=result[2],
                          type_id=result[3], port=result[4], params=result[5], current_values=result[6], is_online=result[7])
        return None

    def get_devices_by_controller(self, controller_id: int) -> List[Device]:
        query = "SELECT * FROM devices WHERE controller_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_id,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5], current_values=r[6], is_online=r[7])
                for r in results] if results else []

    def get_devices_by_type(self, type_id: int) -> List[Device]:
        query = "SELECT * FROM devices WHERE type_id = %s"
        results = self._execute_query(query, (type_id,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5], current_values=r[6], is_online=r[7])
                for r in results] if results else []

    def get_devices_by_name(self, name: str) -> List[Device]:
        query = "SELECT * FROM devices WHERE name = %s"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5], current_values=r[6], is_online=r[7])
                for r in results] if results else []

    def get_all_devices(self) -> List[Device]:
        query = "SELECT * FROM devices ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5], current_values=r[6], is_online=r[7])
                for r in results] if results else []

    def delete_device(self, device_id: int, kafkaHandler) -> bool:

        device = self.get_device_by_id(device_id)
        if not device:
            return False

        affected_triggers = set()
        all_conditions = self.get_all_trig_conditions()
        for condition in all_conditions:
            if condition.device_id == device_id:
                affected_triggers.add(condition.trigger_id)
        all_responses = self.get_all_trig_responses()
        for response in all_responses:
            if response.device_id == device_id:
                affected_triggers.add(response.trigger_id)
        for trigger_id in affected_triggers:
            success = self.delete_trigger(trigger_id, kafkaHandler)
            if not success:
                return False

        kafka_data = {
            'command_type': 'DELETE',
            'id': device_id
        }
        success = kafkaHandler.update_device_table(kafka_data)
        if success:
            query = "DELETE FROM devices WHERE id = %s"
            self._execute_query(query, (device_id,))
            return True
        return False

    def update_device_status(self, device_id: int, status: bool):
        query = """
            UPDATE devices 
            SET is_online = %s 
            WHERE id = %s
        """
        result = self._execute_query(query, (status, device_id))
        return result is not None

    def update_device_current_values(self, device_id: int, current_values: str):
        query = """
            UPDATE devices 
            SET current_values = %s 
            WHERE id = %s
        """
        result = self._execute_query(query, (current_values, device_id))
        return result is not None

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        query = """
            INSERT INTO triggers (controller_id, controller_resp_id, name, is_active) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (trigger.controller_id, trigger.controller_resp_id, trigger.name, trigger.is_active),
                                     fetch_one=True)
        if result:
            trigger.id = result[0]
            return result[0]
        return None

    def get_trigger_by_id(self, trigger_id: int) -> Optional[Trigger]:
        query = "SELECT * FROM triggers WHERE id = %s"
        result = self._execute_query(query, (trigger_id,), fetch_one=True)
        if result:
            return Trigger(id=result[0], controller_id=result[1], controller_resp_id=result[2], name=result[3], is_active=result[4])
        return None

    def get_triggers_by_controller(self, controller_id: int) -> List[Trigger]:
        query = "SELECT * FROM triggers WHERE controller_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3], is_active=r[4]) for r in
                results] if results else []

    def get_triggers_by_resp_controller(self, controller_resp_id: int) -> List[Trigger]:
        query = "SELECT * FROM triggers WHERE controller_resp_id = %s ORDER BY id"
        results = self._execute_query(query, (controller_resp_id,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3], is_active=r[4]) for r in
                results] if results else []

    def get_triggers_by_name(self, name: str) -> List[Trigger]:
        query = "SELECT * FROM triggers WHERE name = %s ORDER BY id"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3], is_active=r[4]) for r in
                results] if results else []

    def get_all_triggers(self) -> List[Trigger]:
        query = "SELECT * FROM triggers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Trigger(id=r[0], controller_id=r[1], controller_resp_id=r[2], name=r[3], is_active=r[4]) for r in
                results] if results else []

    def update_trig_status(self, trigger_id: int, is_active: bool):
        query = """
            UPDATE triggers 
            SET is_active = %s 
            WHERE trigger_id = %s
        """
        result = self._execute_query(query, (is_active, trigger_id))
        return result is not None

    def delete_trigger(self, trigger_id: int, kafkaHandler) -> bool:

        kafka_data = {
            'command_type': 'DELETE',
            'id': trigger_id
        }
        if kafkaHandler.update_trig_table(kafka_data):
            trig_conditions = self.get_trig_conditions_by_trigger(trigger_id)
            for trig_cond in trig_conditions:
                self.delete_trig_condition(trig_cond.id)
            trig_responses = self.get_trig_responses_by_trigger(trigger_id)
            for trig_resp in trig_responses:
                self.delete_trig_response(trig_resp.id)
            #TODO откат транзации если что-то не выполнилось
            query = "DELETE FROM triggers WHERE id = %s"
            self._execute_query(query, (trigger_id,))
            return True
        return False

    def add_trig_condition(self, condition: TrigCondition) -> Optional[int]:
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
        query = "SELECT * FROM trig_conditions WHERE id = %s"
        result = self._execute_query(query, (condition_id,), fetch_one=True)
        if result:
            return TrigCondition(id=result[0], device_id=result[1], condition=result[2], trigger_id=result[3])
        return None

    def get_trig_conditions_by_device(self, device_id: int) -> List[TrigCondition]:
        query = "SELECT * FROM trig_conditions WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_trig_conditions_by_trigger(self, trigger_id: int) -> List[TrigCondition]:
        query = "SELECT * FROM trig_conditions WHERE trigger_id = %s ORDER BY id"
        results = self._execute_query(query, (trigger_id,), fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_all_trig_conditions(self) -> List[TrigCondition]:
        query = "SELECT * FROM trig_conditions ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [TrigCondition(id=r[0], device_id=r[1], condition=r[2], trigger_id=r[3])
                for r in results] if results else []

    def delete_trig_condition(self, condition_id: int) -> bool:
        query = "DELETE FROM trig_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        return True

    def add_trig_response(self, response: TrigResponse) -> Optional[int]:
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
        query = "SELECT * FROM trig_responses WHERE id = %s"
        result = self._execute_query(query, (response_id,), fetch_one=True)
        if result:
            return TrigResponse(id=result[0], device_id=result[1], resp=result[2], trigger_id=result[3])
        return None

    def get_trig_responses_by_device(self, device_id: int) -> List[TrigResponse]:
        query = "SELECT * WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_trig_responses_by_trigger(self, trigger_id: int) -> List[TrigResponse]:
        query = "SELECT * FROM trig_responses WHERE trigger_id = %s ORDER BY id"
        results = self._execute_query(query, (trigger_id,), fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def get_all_trig_responses(self) -> List[TrigResponse]:
        query = "SELECT * FROM trig_responses ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [TrigResponse(id=r[0], device_id=r[1], resp=r[2], trigger_id=r[3])
                for r in results] if results else []

    def delete_trig_response(self, response_id: int) -> bool:
        query = "DELETE FROM trig_responses WHERE id = %s"
        self._execute_query(query, (response_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ SCENES =============

    def add_scene(self, scene: Scene) -> Optional[int]:
        """Добавление сценария"""
        query = """
            INSERT INTO scenes (name, is_active) 
            VALUES (%s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (scene.name, scene.is_active), fetch_one=True)
        if result:
            scene.id = result[0]
            return result[0]
        return None

    def get_scene_by_id(self, scene_id: int) -> Optional[Scene]:
        """Получение сценария по ID"""
        query = "SELECT id, name, is_active FROM scenes WHERE id = %s"
        result = self._execute_query(query, (scene_id,), fetch_one=True)
        if result:
            return Scene(id=result[0], name=result[1], is_active=result[2])
        return None

    def get_scenes_by_name(self, name: str) -> List[Scene]:
        """Получение сценариев по имени"""
        query = "SELECT id, name, is_active FROM scenes WHERE name = %s ORDER BY id"
        results = self._execute_query(query, (name,), fetch_all=True)
        return [Scene(id=r[0], name=r[1], is_active=r[2]) for r in results] if results else []

    def get_all_scenes(self) -> List[Scene]:
        """Получение всех сценариев"""
        query = "SELECT id, name, is_active FROM scenes ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Scene(id=r[0], name=r[1], is_active=r[2]) for r in results] if results else []

    def update_scene_status(self, scene_id: int, is_active: bool) -> bool:
        """Обновление статуса сценария"""
        query = """
            UPDATE scenes 
            SET is_active = %s 
            WHERE id = %s
        """
        self._execute_query(query, (is_active, scene_id))
        return True

    def update_scene_name(self, scene_id: int, name: str) -> bool:
        """Обновление имени сценария"""
        query = """
            UPDATE scenes 
            SET name = %s 
            WHERE id = %s
        """
        self._execute_query(query, (name, scene_id))
        return True

    def delete_scene(self, scene_id: int) -> bool:
        """Удаление сценария по ID"""
        query = "DELETE FROM scenes WHERE id = %s"
        self._execute_query(query, (scene_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ SCENE_CONDITIONS =============

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
            return result[0]
        return None

    def get_scene_condition_by_id(self, condition_id: int) -> Optional[SceneCondition]:
        """Получение условия сценария по ID"""
        query = "SELECT id, device_id, condition, scene_id FROM scene_conditions WHERE id = %s"
        result = self._execute_query(query, (condition_id,), fetch_one=True)
        if result:
            return SceneCondition(
                id=result[0],
                device_id=result[1],
                condition=result[2],
                scene_id=result[3]
            )
        return None

    def get_scene_conditions_by_device(self, device_id: int) -> List[SceneCondition]:
        """Получение условий по устройству"""
        query = "SELECT id, device_id, condition, scene_id FROM scene_conditions WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [
            SceneCondition(id=r[0], device_id=r[1], condition=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def get_scene_conditions_by_scene(self, scene_id: int) -> List[SceneCondition]:
        """Получение условий по сценарию"""
        query = "SELECT id, device_id, condition, scene_id FROM scene_conditions WHERE scene_id = %s ORDER BY id"
        results = self._execute_query(query, (scene_id,), fetch_all=True)
        return [
            SceneCondition(id=r[0], device_id=r[1], condition=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def get_all_scene_conditions(self) -> List[SceneCondition]:
        """Получение всех условий сценариев"""
        query = "SELECT id, device_id, condition, scene_id FROM scene_conditions ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [
            SceneCondition(id=r[0], device_id=r[1], condition=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def delete_scene_condition(self, condition_id: int) -> bool:
        """Удаление условия сценария по ID"""
        query = "DELETE FROM scene_conditions WHERE id = %s"
        self._execute_query(query, (condition_id,))
        return True

    def delete_scene_conditions_by_scene(self, scene_id: int) -> bool:
        """Удаление всех условий сценария"""
        query = "DELETE FROM scene_conditions WHERE scene_id = %s"
        self._execute_query(query, (scene_id,))
        return True

    # ============= МЕТОДЫ ДЛЯ SCENE_RESPONSES =============

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
            return result[0]
        return None

    def get_scene_response_by_id(self, response_id: int) -> Optional[SceneResponse]:
        """Получение ответа сценария по ID"""
        query = "SELECT id, device_id, resp, scene_id FROM scene_responses WHERE id = %s"
        result = self._execute_query(query, (response_id,), fetch_one=True)
        if result:
            return SceneResponse(
                id=result[0],
                device_id=result[1],
                resp=result[2],
                scene_id=result[3]
            )
        return None

    def get_scene_responses_by_device(self, device_id: int) -> List[SceneResponse]:
        """Получение ответов по устройству"""
        query = "SELECT id, device_id, resp, scene_id FROM scene_responses WHERE device_id = %s ORDER BY id"
        results = self._execute_query(query, (device_id,), fetch_all=True)
        return [
            SceneResponse(id=r[0], device_id=r[1], resp=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def get_scene_responses_by_scene(self, scene_id: int) -> List[SceneResponse]:
        """Получение ответов по сценарию"""
        query = "SELECT id, device_id, resp, scene_id FROM scene_responses WHERE scene_id = %s ORDER BY id"
        results = self._execute_query(query, (scene_id,), fetch_all=True)
        return [
            SceneResponse(id=r[0], device_id=r[1], resp=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def get_all_scene_responses(self) -> List[SceneResponse]:
        """Получение всех ответов сценариев"""
        query = "SELECT id, device_id, resp, scene_id FROM scene_responses ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [
            SceneResponse(id=r[0], device_id=r[1], resp=r[2], scene_id=r[3])
            for r in results
        ] if results else []

    def delete_scene_response(self, response_id: int) -> bool:
        """Удаление ответа сценария по ID"""
        query = "DELETE FROM scene_responses WHERE id = %s"
        self._execute_query(query, (response_id,))
        return True

    def delete_scene_responses_by_scene(self, scene_id: int) -> bool:
        """Удаление всех ответов сценария"""
        query = "DELETE FROM scene_responses WHERE scene_id = %s"
        self._execute_query(query, (scene_id,))
        return True

    # ============= ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =============

    def get_scene_with_details(self, scene_id: int) -> Optional[dict]:
        """Получение сценария со всеми условиями и ответами"""
        scene = self.get_scene_by_id(scene_id)
        if not scene:
            return None

        conditions = self.get_scene_conditions_by_scene(scene_id)
        responses = self.get_scene_responses_by_scene(scene_id)

        return {
            'id': scene.id,
            'name': scene.name,
            'is_active': scene.is_active,
            'conditions': [
                {'id': c.id, 'device_id': c.device_id, 'condition': c.condition}
                for c in conditions
            ],
            'responses': [
                {'id': r.id, 'device_id': r.device_id, 'resp': r.resp}
                for r in responses
            ]
        }

    def delete_scene_with_all_relations(self, scene_id: int) -> bool:
        """
        Удаление сценария со всеми связанными данными
        (условия и ответы)
        """
        # Удаляем условия
        conditions = self.get_scene_conditions_by_scene(scene_id)
        for cond in conditions:
            self.delete_scene_condition(cond.id)

        # Удаляем ответы
        responses = self.get_scene_responses_by_scene(scene_id)
        for resp in responses:
            self.delete_scene_response(resp.id)

        # Удаляем сам сценарий
        return self.delete_scene(scene_id)

