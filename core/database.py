# core/database.py
import json
import psycopg2
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Device:
    id: Optional[int] = None
    controller_mac: str = None
    port: str = None
    params: json = None
    current_values: Optional[List[str]] = None
    type: str = None

@dataclass
class Trigger:
    id: Optional[int] = None
    controller_mac: str = None
    trig: str = None
    is_active: bool = False


@dataclass
class Scene:
    id: Optional[int] = None
    conditions: List[str] = None
    responses: List[str] = None
    is_active: bool = False
    is_executed: bool = False


class Database:
    def __init__(self, host='', port=443, name='', user='', password=''):
        # Подключение к БД
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

        # Инициализация кешей
        self._devices_cache = {}  # id -> Device
        self._triggers_cache = {}  # id -> Trigger
        self._scenes_cache = {}  # id -> Scene

        # Индексы для быстрого поиска
        self._devices_by_controller = {}  # controller_mac -> [device_ids]
        self._devices_by_type = {}  # type -> [device_ids]
        self._triggers_by_controller = {}  # controller_mac -> [trigger_ids]

        # Загружаем все данные в кеш при инициализации
        self._load_all_cache()
        logger.info("Core Database cache initialized successfully")

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
                params=r[3],
                current_values=r[4],
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

            # Индекс по контроллеру
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
                is_executed = r[4]


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

    # ============= МЕТОДЫ ДЛЯ УСТРОЙСТВ (кешированные) =============

    def add_device(self, device: Device) -> Optional[int]:
        """Добавление устройства"""
        query = """
            INSERT INTO devices (id, controller_mac, port, params, current_values, type) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(
            query,
            (device.id, device.controller_mac, device.port, device.params, device.current_values, device.type),
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
        """Получение устройства по ID из кеша"""
        return self._devices_cache.get(device_id)

    def get_devices_by_controller(self, controller_mac: str) -> List[Device]:
        """Получение устройств по MAC контроллера из кеша"""
        result = []
        for did in self._devices_by_controller.get(controller_mac, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_devices_by_type(self, type_name: str) -> List[Device]:
        """Получение устройств по типу из кеша"""
        result = []
        for did in self._devices_by_type.get(type_name, []):
            device = self._devices_cache.get(did)
            if device:
                result.append(device)
        return result

    def get_all_devices(self) -> List[Device]:
        """Получение всех устройств из кеша"""
        return list(self._devices_cache.values())

    def update_device_current_values(self, device_id: int, current_values: str) -> bool:
        """Обновление текущих значений устройства"""
        query = """
            UPDATE devices 
            SET current_values = %s 
            WHERE id = %s
        """
        result = self._execute_query(query, (current_values, device_id))

        device = self._devices_cache.get(device_id)
        if device:
            device.current_values = current_values
            return True
        return result is not None

    def delete_device(self, device_id: int) -> bool:
        """Удаление устройства по ID"""
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))
        if device_id in self._devices_cache:
            del self._devices_cache[device_id]
        return True

    # ============= МЕТОДЫ ДЛЯ ТРИГГЕРОВ (кешированные) =============

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        """Добавление или обновление триггера"""
        # Если триггер с таким ID уже существует - удаляем старый
        if trigger.id and self.get_trigger_by_id(trigger.id):
            self.delete_trigger(trigger.id)

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
        """Получение триггера по ID из кеша"""
        return self._triggers_cache.get(trigger_id)

    def get_triggers_by_controller(self, controller_mac: str) -> List[Trigger]:
        """Получение триггеров по MAC контроллера из кеша"""
        result = []
        for tid in self._triggers_by_controller.get(controller_mac, []):
            trigger = self._triggers_cache.get(tid)
            if trigger:
                result.append(trigger)
        return result

    def get_all_triggers(self) -> List[Trigger]:
        """Получение всех триггеров из кеша"""
        return list(self._triggers_cache.values())

    def update_trig_status(self, trigger_id: int, is_active: bool) -> bool:
        """Обновление статуса триггера"""
        query = """
            UPDATE triggers 
            SET is_active = %s 
            WHERE id = %s
        """
        result = self._execute_query(query, (is_active, trigger_id))

        trigger = self._triggers_cache.get(trigger_id)
        if trigger:
            trigger.is_active = is_active
            return True
        return result is not None

    def delete_trigger(self, trigger_id: int) -> bool:
        """Удаление триггера по ID"""
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))
        if trigger_id in self._triggers_cache:
            del self._triggers_cache[trigger_id]
        return True

    # ============= МЕТОДЫ ДЛЯ СЦЕНАРИЕВ (кешированные) =============

    def add_scene(self, scene: Scene) -> Optional[int]:
        """Добавление сценария"""
        query = """
            INSERT INTO scenes (id, conditions, responses, is_active, is_executed) 
            VALUES (%s, %s, %s, %s, %s) 
            RETURNING id
        """
        # Преобразуем списки в JSON строки для хранения в БД
        conditions_json = json.dumps(scene.conditions) if scene.conditions else '[]'
        responses_json = json.dumps(scene.responses) if scene.responses else '[]'

        result = self._execute_query(
            query,
            (scene.id, conditions_json, responses_json, scene.is_active, False),
            fetch_one=True
        )
        if result:
            scene.id = result[0]
            self._scenes_cache[scene.id] = scene
            return result[0]
        return None

    def get_scene_by_id(self, scene_id: int) -> Optional[Scene]:
        """Получение сценария по ID из кеша"""
        return self._scenes_cache.get(scene_id)

    def get_all_scenes(self) -> List[Scene]:
        """Получение всех сценариев из кеша"""
        return list(self._scenes_cache.values())

    def update_scene(self, scene: Scene) -> bool:
        """Обновление сценария"""
        query = """
            UPDATE scenes 
            SET conditions = %s, responses = %s, is_active = %s , is_executed = %s
            WHERE id = %s
        """
        conditions_json = json.dumps(scene.conditions) if scene.conditions else '[]'
        responses_json = json.dumps(scene.responses) if scene.responses else '[]'

        result = self._execute_query(
            query,
            (conditions_json, responses_json, scene.is_active, scene.is_executed, scene.id)
        )

        if scene.id in self._scenes_cache:
            self._scenes_cache[scene.id] = scene
            return True
        return result is not None

    def update_scene_status(self, scene_id: int, is_active: bool) -> bool:
        """Обновление статуса сценария"""
        query = """
            UPDATE scenes 
            SET is_active = %s 
            WHERE id = %s
        """
        result = self._execute_query(query, (is_active, scene_id))

        scene = self._scenes_cache.get(scene_id)
        if scene:
            scene.is_active = is_active
            return True
        return result is not None

    def delete_scene(self, scene_id: int) -> bool:
        """Удаление сценария по ID"""
        query = "DELETE FROM scenes WHERE id = %s"
        self._execute_query(query, (scene_id,))
        if scene_id in self._scenes_cache:
            del self._scenes_cache[scene_id]
        return True

    # ============= ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ =============

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

    def get_device_by_controller_and_port(self, controller_mac: str, port: str) -> Optional[Device]:
        """Получение устройства по MAC контроллера и порту"""
        for device in self._devices_cache.values():
            if device.controller_mac == controller_mac and device.port == port:
                return device
        return None

    def get_triggers_by_controller_and_active(self, controller_mac: str, is_active: bool = True) -> List[Trigger]:
        """Получение активных триггеров по MAC контроллера"""
        result = []
        for tid in self._triggers_by_controller.get(controller_mac, []):
            trigger = self._triggers_cache.get(tid)
            if trigger and trigger.is_active == is_active:
                result.append(trigger)
        return result

    def get_active_scenes(self) -> List[Scene]:
        """Получение всех активных сценариев"""
        return [s for s in self._scenes_cache.values() if s.is_active]