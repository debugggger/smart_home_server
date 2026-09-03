# core/database.py
import json
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
import logging
import psycopg2
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class Device:
    """Только данные из БД, без состояний"""
    id: int
    controller_mac: str
    port: str
    params: dict = None
    current_values: json = None
    type: str = None


@dataclass
class Trigger:
    """Только данные из БД"""
    id: int
    controller_mac: str
    trig: str
    is_active: bool = False


@dataclass
class Scene:
    """Только данные из БД"""
    id: int
    conditions: List[dict] = field(default_factory=list)
    responses: List[dict] = field(default_factory=list)
    is_active: bool = False
    is_executed: bool = False


class Database:
    def __init__(self, host='', port=443, name='', user='', password=''):
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

        # Кеши только с данными из БД
        self._devices_cache: Dict[int, Device] = {}
        self._triggers_cache: Dict[int, Trigger] = {}
        self._scenes_cache: Dict[int, Scene] = {}

        # Индексы для быстрого поиска
        self._devices_by_controller: Dict[str, List[int]] = {}
        self._devices_by_type: Dict[str, List[int]] = {}
        self._triggers_by_controller: Dict[str, List[int]] = {}

        # Загружаем все данные в кеш
        self._load_all_cache()
        logger.info("Database cache initialized successfully")

    # ============= ЗАГРУЗКА КЕША =============

    def _load_all_cache(self):
        """Полная загрузка всех данных из БД в кеш"""
        self._load_devices_cache()
        self._load_triggers_cache()
        self._load_scenes_cache()
        logger.info("All cache loaded from database")

    def _load_devices_cache(self):
        """Загрузка устройств в кеш"""
        query = "SELECT id, controller_mac, port, params, current_values, type FROM devices"
        results = self._execute_query(query, fetch_all=True)
        self._devices_cache = {}
        self._devices_by_controller = {}
        self._devices_by_type = {}

        for r in results:
            device = Device(
                id=r[0],
                controller_mac=r[1],
                port=r[2],
                params=r[3] if r[3] else {},
                current_values=r[4] if r[4] else [],
                type=r[5]
            )
            self._devices_cache[r[0]] = device

            # Индекс по контроллеру
            if r[1] not in self._devices_by_controller:
                self._devices_by_controller[r[1]] = []
            self._devices_by_controller[r[1]].append(r[0])

            # Индекс по типу
            if r[5] not in self._devices_by_type:
                self._devices_by_type[r[5]] = []
            self._devices_by_type[r[5]].append(r[0])

    def _load_triggers_cache(self):
        """Загрузка триггеров в кеш"""
        query = "SELECT id, controller_mac, trig, is_active FROM triggers"
        results = self._execute_query(query, fetch_all=True)
        self._triggers_cache = {}
        self._triggers_by_controller = {}

        for r in results:
            trigger = Trigger(
                id=r[0],
                controller_mac=r[1],
                trig=r[2],
                is_active=r[3]
            )
            self._triggers_cache[r[0]] = trigger

            if r[1] not in self._triggers_by_controller:
                self._triggers_by_controller[r[1]] = []
            self._triggers_by_controller[r[1]].append(r[0])

    def _load_scenes_cache(self):
        """Загрузка сценариев в кеш"""
        query = "SELECT id, conditions, responses, is_active, is_executed FROM scenes"
        results = self._execute_query(query, fetch_all=True)
        self._scenes_cache = {}

        for r in results:
            scene = Scene(
                id=r[0],
                conditions=r[1] if r[1] else [],
                responses=r[2] if r[2] else [],
                is_active=r[3],
                is_executed=r[4] if len(r) > 4 else False
            )
            self._scenes_cache[r[0]] = scene

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

    def close(self):
        """Закрытие соединения с БД"""
        if self.connection:
            self.connection.close()
            print("[INFO] Close connection with DB")

    # ============= МЕТОДЫ ДЛЯ УСТРОЙСТВ =============

    def add_device(self, device: Device) -> Optional[int]:
        """Добавление устройства в БД"""
        query = """
            INSERT INTO devices (id, controller_mac, port, params, current_values, type) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (device.id, device.controller_mac, device.port,
             json.dumps(device.params) if device.params else None,
             json.dumps(device.current_values) if device.current_values else '{}',
             device.type),
            fetch_one=True
        )
        if result:
            device.id = result[0]
            self._devices_cache[device.id] = device

            # Обновляем индексы
            if device.controller_mac not in self._devices_by_controller:
                self._devices_by_controller[device.controller_mac] = []
            self._devices_by_controller[device.controller_mac].append(device.id)

            if device.type not in self._devices_by_type:
                self._devices_by_type[device.type] = []
            self._devices_by_type[device.type].append(device.id)

            return result[0]
        return None

    def get_device_by_id(self, device_id: int) -> Optional[Device]:
        return self._devices_cache.get(device_id)

    def get_devices_by_controller(self, controller_mac: str) -> List[Device]:
        result = []
        for did in self._devices_by_controller.get(controller_mac, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_devices_by_type(self, type_name: str) -> List[Device]:
        result = []
        for did in self._devices_by_type.get(type_name, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_all_devices(self) -> List[Device]:
        return list(self._devices_cache.values())

    def get_device_by_controller_and_port(self, controller_mac: str, port: str) -> Optional[Device]:
        for device in self._devices_cache.values():
            if device.controller_mac == controller_mac and device.port == port:
                return device
        return None

    def update_device_current_values(self, device_id: int, current_values: List[str]) -> bool:
        """Обновление текущих значений устройства в БД и кеше"""
        query = """
            UPDATE devices 
            SET current_values = %s 
            WHERE id = %s
        """
        self._execute_query(query, (json.dumps(current_values), device_id))

        device = self._devices_cache.get(device_id)
        if device:
            device.current_values = current_values
            return True
        return False

    def update_device_params(self, device_id: int, params: dict) -> bool:
        """Обновление параметров устройства"""
        query = """
            UPDATE devices 
            SET params = %s 
            WHERE id = %s
        """
        self._execute_query(query, (json.dumps(params), device_id))

        device = self._devices_cache.get(device_id)
        if device:
            device.params = params
            return True
        return False

    def delete_device(self, device_id: int) -> bool:
        """Удаление устройства из БД"""
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))

        device = self._devices_cache.get(device_id)
        if device:
            # Удаляем из индексов
            controller_mac = device.controller_mac
            if controller_mac in self._devices_by_controller:
                self._devices_by_controller[controller_mac] = [
                    did for did in self._devices_by_controller[controller_mac]
                    if did != device_id
                ]
                if not self._devices_by_controller[controller_mac]:
                    del self._devices_by_controller[controller_mac]

            if device.type in self._devices_by_type:
                self._devices_by_type[device.type] = [
                    did for did in self._devices_by_type[device.type]
                    if did != device_id
                ]
                if not self._devices_by_type[device.type]:
                    del self._devices_by_type[device.type]

            del self._devices_cache[device_id]
            return True
        return False

    # ============= МЕТОДЫ ДЛЯ ТРИГГЕРОВ =============

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        """Добавление триггера в БД"""
        query = """
            INSERT INTO triggers (id, controller_mac, trig, is_active) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (trigger.id, trigger.controller_mac, trigger.trig, trigger.is_active),
            fetch_one=True
        )
        if result:
            trigger.id = result[0]
            self._triggers_cache[trigger.id] = trigger

            # Обновляем индекс по контроллеру
            if trigger.controller_mac not in self._triggers_by_controller:
                self._triggers_by_controller[trigger.controller_mac] = []
            self._triggers_by_controller[trigger.controller_mac].append(trigger.id)

            return result[0]
        return None

    def get_trigger_by_id(self, trigger_id: int) -> Optional[Trigger]:
        return self._triggers_cache.get(trigger_id)

    def get_triggers_by_controller(self, controller_mac: str) -> List[Trigger]:
        result = []
        for tid in self._triggers_by_controller.get(controller_mac, []):
            trigger = self._triggers_cache.get(tid)
            if trigger:
                result.append(trigger)
        return result

    def get_all_triggers(self) -> List[Trigger]:
        return list(self._triggers_cache.values())

    def get_triggers_by_controller_and_active(self, controller_mac: str, is_active: bool = True) -> List[Trigger]:
        result = []
        for tid in self._triggers_by_controller.get(controller_mac, []):
            trigger = self._triggers_cache.get(tid)
            if trigger and trigger.is_active == is_active:
                result.append(trigger)
        return result

    def update_trig_status(self, trigger_id: int, is_active: bool) -> bool:
        """Обновление статуса триггера"""
        query = """
            UPDATE triggers 
            SET is_active = %s 
            WHERE id = %s
        """
        self._execute_query(query, (is_active, trigger_id))

        trigger = self._triggers_cache.get(trigger_id)
        if trigger:
            trigger.is_active = is_active
            return True
        return False

    def update_trigger(self, trigger: Trigger) -> bool:
        """Обновление триггера"""
        query = """
            UPDATE triggers 
            SET controller_mac = %s, trig = %s, is_active = %s 
            WHERE id = %s
        """
        self._execute_query(
            query,
            (trigger.controller_mac, trigger.trig, trigger.is_active, trigger.id)
        )

        if trigger.id in self._triggers_cache:
            self._triggers_cache[trigger.id] = trigger
            return True
        return False

    def delete_trigger(self, trigger_id: int) -> bool:
        """Удаление триггера из БД"""
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))

        trigger = self._triggers_cache.get(trigger_id)
        if trigger:
            # Удаляем из индекса
            controller_mac = trigger.controller_mac
            if controller_mac in self._triggers_by_controller:
                self._triggers_by_controller[controller_mac] = [
                    tid for tid in self._triggers_by_controller[controller_mac]
                    if tid != trigger_id
                ]
                if not self._triggers_by_controller[controller_mac]:
                    del self._triggers_by_controller[controller_mac]

            del self._triggers_cache[trigger_id]
            return True
        return False

    # ============= МЕТОДЫ ДЛЯ СЦЕНАРИЕВ =============

    def add_scene(self, scene: Scene) -> Optional[int]:
        """Добавление сценария в БД"""
        query = """
            INSERT INTO scenes (id, conditions, responses, is_active, is_executed) 
            VALUES (%s, %s, %s, %s, %s) 
            RETURNING id
        """
        conditions_json = json.dumps(scene.conditions) if scene.conditions else '[]'
        responses_json = json.dumps(scene.responses) if scene.responses else '[]'

        result = self._execute_query(
            query,
            (scene.id, conditions_json, responses_json, scene.is_active, scene.is_executed),
            fetch_one=True
        )
        if result:
            scene.id = result[0]
            self._scenes_cache[scene.id] = scene
            return result[0]
        return None

    def get_scene_by_id(self, scene_id: int) -> Optional[Scene]:
        return self._scenes_cache.get(scene_id)

    def get_all_scenes(self) -> List[Scene]:
        return list(self._scenes_cache.values())

    def get_active_scenes(self) -> List[Scene]:
        return [s for s in self._scenes_cache.values() if s.is_active]

    def update_scene(self, scene: Scene) -> bool:
        """Полное обновление сценария"""
        query = """
            UPDATE scenes 
            SET conditions = %s, responses = %s, is_active = %s, is_executed = %s 
            WHERE id = %s
        """
        conditions_json = json.dumps(scene.conditions) if scene.conditions else '[]'
        responses_json = json.dumps(scene.responses) if scene.responses else '[]'

        self._execute_query(
            query,
            (conditions_json, responses_json, scene.is_active, scene.is_executed, scene.id)
        )

        if scene.id in self._scenes_cache:
            self._scenes_cache[scene.id] = scene
            return True
        return False

    def update_scene_executed(self, scene_id: int, is_executed: bool) -> bool:
        """Обновление статуса выполнения сценария"""
        query = """
            UPDATE scenes 
            SET is_executed = %s 
            WHERE id = %s
        """
        self._execute_query(query, (is_executed, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.is_executed = is_executed
            return True
        return False

    def update_scene_status(self, scene_id: int, is_active: bool) -> bool:
        """Обновление статуса активности сценария"""
        query = """
            UPDATE scenes 
            SET is_active = %s 
            WHERE id = %s
        """
        self._execute_query(query, (is_active, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.is_active = is_active
            return True
        return False

    def update_scene_conditions(self, scene_id: int, conditions: List[dict]) -> bool:
        """Обновление условий сценария"""
        query = """
            UPDATE scenes 
            SET conditions = %s 
            WHERE id = %s
        """
        conditions_json = json.dumps(conditions) if conditions else '[]'
        self._execute_query(query, (conditions_json, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.conditions = conditions
            return True
        return False

    def update_scene_responses(self, scene_id: int, responses: List[dict]) -> bool:
        """Обновление ответов сценария"""
        query = """
            UPDATE scenes 
            SET responses = %s 
            WHERE id = %s
        """
        responses_json = json.dumps(responses) if responses else '[]'
        self._execute_query(query, (responses_json, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.responses = responses
            return True
        return False

    def delete_scene(self, scene_id: int) -> bool:
        """Удаление сценария из БД"""
        query = "DELETE FROM scenes WHERE id = %s"
        self._execute_query(query, (scene_id,))

        if scene_id in self._scenes_cache:
            del self._scenes_cache[scene_id]
            return True
        return False

    # ============= ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ =============

    def refresh_cache(self):
        """Принудительное обновление всего кеша из БД"""
        self._load_all_cache()
        logger.info("Cache refreshed from database")

    def get_cache_stats(self) -> dict:
        """Получить статистику кеша"""
        return {
            'devices': len(self._devices_cache),
            'triggers': len(self._triggers_cache),
            'scenes': len(self._scenes_cache),
            'devices_by_controller': sum(len(v) for v in self._devices_by_controller.values()),
            'devices_by_type': sum(len(v) for v in self._devices_by_type.values()),
            'triggers_by_controller': sum(len(v) for v in self._triggers_by_controller.values())
        }