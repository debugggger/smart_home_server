import json
from pathlib import Path

import psycopg2
from typing import Optional, List
from dotenv import load_dotenv
import os
from dataclasses import dataclass

@dataclass
class Device:
    id: Optional[int] = None
    controller_mac: str = None
    port: str = None
    params: json = None
    current_values: Optional[str] = None
    type: str = None

@dataclass
class Trigger:
    id: Optional[int] = None
    controller_mac: str = None
    trig: str = None

class Database:
    def __init__(self):
        env_path = Path(__file__).parent.parent / '.env'
        load_dotenv(env_path)
        self.connection = psycopg2.connect(
            host=os.getenv('core_db_host'),
            user=os.getenv('core_db_user'),
            password=os.getenv('core_db_password'),
            database=os.getenv('core_db_name'),
            port=os.getenv('core_db_port')
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

    def add_device(self, device: Device) -> Optional[int]:
        query = """
            INSERT INTO devices (id, controller_mac, port, params, type) 
            VALUES (%s, %s, %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (device.id, device.controller_mac, device.port, device.params,
                                             device.type), fetch_one=True)
        if result:
            device.id = result[0]
            return result[0]
        return None

    def get_device_by_id(self, device_id: int) -> Optional[Device]:
        query = "SELECT * FROM devices WHERE id = %s"
        result = self._execute_query(query, (device_id,), fetch_one=True)
        if result:
            return Device(id=result[0], controller_mac=result[1],
                          port=result[2], params=result[3], current_values=result[4], type=result[5])
        return None

    def get_devices_by_controller(self, controller_mac: int) -> List[Device]:
        query = "SELECT * FROM devices WHERE controller_mac = %s ORDER BY id"
        results = self._execute_query(query, (controller_mac,), fetch_all=True)
        return [Device(id=r[0], controller_mac=r[1],
                          port=r[2], params=r[3], current_values=r[4], type=r[5])
                for r in results] if results else []

    # def get_devices_by_type(self, type_name: int) -> List[Device]:
    #     """Получение устройств по типу"""
    #     query = "SELECT id, name, controller_id, type_id, port, params, current_values FROM devices WHERE type_id = %s"
    #     results = self._execute_query(query, (type_name,), fetch_all=True)
    #     return [Device(id=r[0], name=r[1], controller_id=r[2], type_id=r[3], port=r[4], params=r[5], current_values=r[6])
    #             for r in results] if results else []


    def get_all_devices(self) -> List[Device]:
        query = "SELECT * FROM devices ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Device(id=r[0], controller_mac=r[1],
                          port=r[2], params=r[3], current_values=r[4], type=r[5])
                for r in results] if results else []

    def delete_device(self, device_id: int) -> bool:
        query = "DELETE FROM devices WHERE id = %s"
        self._execute_query(query, (device_id,))
        return True

    def add_trigger(self, trigger: Trigger) -> Optional[int]:
        query = """
            INSERT INTO triggers (id, controller_mac, trig) 
            VALUES ( %s, %s) 
            RETURNING id
        """
        result = self._execute_query(query, (trigger.id, trigger.controller_mac, trigger.trig),
                                     fetch_one=True)
        if result:
            trigger.id = result[0]
            return result[0]
        return None

    def get_trigger_by_id(self, trigger_id: int) -> Optional[Trigger]:
        query = "SELECT * FROM triggers WHERE id = %s"
        result = self._execute_query(query, (trigger_id,), fetch_one=True)
        if result:
            return Trigger(id=result[0], controller_mac=result[1], trig=result[2])
        return None

    def get_triggers_by_controller(self, controller_mac: int) -> List[Trigger]:
        query = "SELECT * FROM triggers WHERE controller_mac = %s ORDER BY id"
        results = self._execute_query(query, (controller_mac,), fetch_all=True)
        return [Trigger(id=r[0], controller_mac=r[1], trig=r[2]) for r in
                results] if results else []

    def get_all_triggers(self) -> List[Trigger]:
        query = "SELECT * FROM triggers ORDER BY id"
        results = self._execute_query(query, fetch_all=True)
        return [Trigger(id=r[0], controller_mac=r[1], trig=r[2]) for r in
                results] if results else []

    def delete_trigger(self, trigger_id: int) -> bool:
        query = "DELETE FROM triggers WHERE id = %s"
        self._execute_query(query, (trigger_id,))
        return True
