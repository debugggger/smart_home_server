from fastapi import FastAPI, HTTPException, status, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import os


# Функция для получения экземпляра Database
def get_db():
    """Возвращает глобальный экземпляр Database"""
    from database import Database
    global db_instance
    if 'db_instance' not in globals():
        db_instance = Database()
    return db_instance


# Глобальная переменная для экземпляра БД
db_instance = None


def init_db(db):
    """Инициализация API с переданным экземпляром Database"""
    global db_instance
    db_instance = db


app = FastAPI(
    title="IoT Management API",
    description="API для управления комнатами, контроллерами, устройствами и триггерами",
    version="1.0.0"
)


# ============= PYDANTIC МОДЕЛИ =============

class RoomCreate(BaseModel):
    name: str


class RoomUpdate(BaseModel):
    name: str


class ControllerCreate(BaseModel):
    mac: str
    room_id: int
    name: str


class ControllerUpdate(BaseModel):
    mac: str
    room_id: int
    name: str


class DeviceTypeCreate(BaseModel):
    name: str
    description: Optional[str] = None


class DeviceTypeUpdate(BaseModel):
    name: str
    description: Optional[str] = None


class DeviceCreate(BaseModel):
    name: str
    controller_id: int
    type_id: int
    port: str
    params: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: str
    controller_id: int
    type_id: int
    port: str
    params: Optional[str] = None


class TrigConditionCreate(BaseModel):
    device_id: int
    condition: str


class TrigConditionUpdate(BaseModel):
    device_id: int
    condition: str


class TriggerCreate(BaseModel):
    controller_id: int
    condition_id: int
    response: str


class TriggerUpdate(BaseModel):
    controller_id: int
    condition_id: int
    response: str


class EventCreate(BaseModel):
    value: int
    device_id: int
    time: Optional[datetime] = None


# ============= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =============

def object_to_dict(obj):
    """Преобразует объект в словарь"""
    if obj is None:
        return None
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in obj.__dict__.items() if v is not None}
    return obj


def get_db_instance():
    """Получить экземпляр базы данных"""
    if db_instance is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return db_instance


# ============= ROOMS ENDPOINTS =============

@app.get("/api/rooms")
async def get_rooms():
    """Получить все комнаты"""
    try:
        db = get_db_instance()
        rooms = db.get_all_rooms()
        return {
            "success": True,
            "data": [object_to_dict(room) for room in rooms],
            "count": len(rooms)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rooms/{room_id}")
async def get_room(room_id: int):
    """Получить комнату по ID"""
    try:
        db = get_db_instance()
        room = db.get_room(room_id)
        if room:
            return {"success": True, "data": object_to_dict(room)}
        raise HTTPException(status_code=404, detail="Room not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/rooms/{room_id}/full-info")
async def get_room_full_info(room_id: int):
    """Получить полную информацию о комнате (с контроллерами, устройствами, событиями)"""
    try:
        db = get_db_instance()
        info = db.get_full_room_info(room_id)
        if info:
            # Преобразуем объекты в словари для JSON сериализации
            info_serializable = {
                'room': object_to_dict(info['room']),
                'controllers': []
            }
            for controller_data in info['controllers']:
                controller_dict = {
                    'controller': object_to_dict(controller_data['controller']),
                    'devices': []
                }
                for device_data in controller_data['devices']:
                    device_dict = {
                        'device': object_to_dict(device_data['device']),
                        'latest_event': object_to_dict(device_data['latest_event'])
                    }
                    controller_dict['devices'].append(device_dict)
                info_serializable['controllers'].append(controller_dict)

            return {"success": True, "data": info_serializable}
        raise HTTPException(status_code=404, detail="Room not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(room: RoomCreate):
    """Создать новую комнату"""
    try:
        from database import Room
        db = get_db_instance()
        room_obj = Room(name=room.name)
        room_id = db.add_room(room_obj)
        return {"success": True, "id": room_id, "message": "Room created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/rooms/{room_id}")
async def update_room(room_id: int, room: RoomUpdate):
    """Обновить комнату"""
    try:
        from database import Room
        db = get_db_instance()
        room_obj = Room(id=room_id, name=room.name)
        db.update_room(room_obj)
        return {"success": True, "message": "Room updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/rooms/{room_id}")
async def delete_room(room_id: int):
    """Удалить комнату"""
    try:
        db = get_db_instance()
        db.delete_room(room_id)
        return {"success": True, "message": "Room deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= CONTROLLERS ENDPOINTS =============

@app.get("/api/controllers")
async def get_controllers():
    """Получить все контроллеры"""
    try:
        db = get_db_instance()
        controllers = db.get_all_controllers()
        return {
            "success": True,
            "data": [object_to_dict(c) for c in controllers],
            "count": len(controllers)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/controllers/{controller_id}")
async def get_controller(controller_id: int):
    """Получить контроллер по ID"""
    try:
        db = get_db_instance()
        controller = db.get_controller(controller_id)
        if controller:
            return {"success": True, "data": object_to_dict(controller)}
        raise HTTPException(status_code=404, detail="Controller not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/controllers/by-room/{room_id}")
async def get_controllers_by_room(room_id: int):
    """Получить контроллеры по комнате"""
    try:
        db = get_db_instance()
        controllers = db.get_controllers_by_room(room_id)
        return {
            "success": True,
            "data": [object_to_dict(c) for c in controllers],
            "count": len(controllers)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/controllers", status_code=status.HTTP_201_CREATED)
async def create_controller(controller: ControllerCreate):
    """Создать новый контроллер"""
    try:
        from database import Controller
        db = get_db_instance()
        controller_obj = Controller(
            mac=controller.mac,
            room_id=controller.room_id,
            name=controller.name
        )
        controller_id = db.add_controller(controller_obj)
        return {"success": True, "id": controller_id, "message": "Controller created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/controllers/{controller_id}")
async def update_controller(controller_id: int, controller: ControllerUpdate):
    """Обновить контроллер"""
    try:
        from database import Controller
        db = get_db_instance()
        controller_obj = Controller(
            id=controller_id,
            mac=controller.mac,
            room_id=controller.room_id,
            name=controller.name
        )
        db.update_controller(controller_obj)
        return {"success": True, "message": "Controller updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/controllers/{controller_id}")
async def delete_controller(controller_id: int):
    """Удалить контроллер"""
    try:
        db = get_db_instance()
        db.delete_controller(controller_id)
        return {"success": True, "message": "Controller deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= DEVICE TYPES ENDPOINTS =============

@app.get("/api/device-types")
async def get_device_types():
    """Получить все типы устройств"""
    try:
        db = get_db_instance()
        types = db.get_all_device_types()
        return {
            "success": True,
            "data": [object_to_dict(t) for t in types],
            "count": len(types)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/device-types/{type_id}")
async def get_device_type(type_id: int):
    """Получить тип устройства по ID"""
    try:
        db = get_db_instance()
        device_type = db.get_device_type(type_id)
        if device_type:
            return {"success": True, "data": object_to_dict(device_type)}
        raise HTTPException(status_code=404, detail="Device type not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/device-types", status_code=status.HTTP_201_CREATED)
async def create_device_type(device_type: DeviceTypeCreate):
    """Создать новый тип устройства"""
    try:
        from database import DeviceType
        db = get_db_instance()
        type_obj = DeviceType(name=device_type.name, description=device_type.description)
        type_id = db.add_device_type(type_obj)
        return {"success": True, "id": type_id, "message": "Device type created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/device-types/{type_id}")
async def update_device_type(type_id: int, device_type: DeviceTypeUpdate):
    """Обновить тип устройства"""
    try:
        from database import DeviceType
        db = get_db_instance()
        type_obj = DeviceType(id=type_id, name=device_type.name, description=device_type.description)
        db.update_device_type(type_obj)
        return {"success": True, "message": "Device type updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/device-types/{type_id}")
async def delete_device_type(type_id: int):
    """Удалить тип устройства"""
    try:
        db = get_db_instance()
        db.delete_device_type(type_id)
        return {"success": True, "message": "Device type deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= DEVICES ENDPOINTS =============

@app.get("/api/devices")
async def get_devices():
    """Получить все устройства"""
    try:
        db = get_db_instance()
        devices = db.get_all_devices()
        return {
            "success": True,
            "data": [object_to_dict(d) for d in devices],
            "count": len(devices)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/devices/{device_id}")
async def get_device(device_id: int):
    """Получить устройство по ID"""
    try:
        db = get_db_instance()
        device = db.get_device(device_id)
        if device:
            return {"success": True, "data": object_to_dict(device)}
        raise HTTPException(status_code=404, detail="Device not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/devices/by-controller/{controller_id}")
async def get_devices_by_controller(controller_id: int):
    """Получить устройства по контроллеру"""
    try:
        db = get_db_instance()
        devices = db.get_devices_by_controller(controller_id)
        return {
            "success": True,
            "data": [object_to_dict(d) for d in devices],
            "count": len(devices)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/devices/by-type/{type_id}")
async def get_devices_by_type(type_id: int):
    """Получить устройства по типу"""
    try:
        db = get_db_instance()
        devices = db.get_devices_by_type(type_id)
        return {
            "success": True,
            "data": [object_to_dict(d) for d in devices],
            "count": len(devices)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/devices", status_code=status.HTTP_201_CREATED)
async def create_device(device: DeviceCreate):
    """Создать новое устройство"""
    try:
        from database import Device
        db = get_db_instance()
        device_obj = Device(
            name=device.name,
            controller_id=device.controller_id,
            type_id=device.type_id,
            port=device.port,
            params=device.params
        )
        device_id = db.add_device(device_obj)
        return {"success": True, "id": device_id, "message": "Device created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/devices/{device_id}")
async def update_device(device_id: int, device: DeviceUpdate):
    """Обновить устройство"""
    try:
        from database import Device
        db = get_db_instance()
        device_obj = Device(
            id=device_id,
            name=device.name,
            controller_id=device.controller_id,
            type_id=device.type_id,
            port=device.port,
            params=device.params
        )
        db.update_device(device_obj)
        return {"success": True, "message": "Device updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/devices/{device_id}")
async def delete_device(device_id: int):
    """Удалить устройство"""
    try:
        db = get_db_instance()
        db.delete_device(device_id)
        return {"success": True, "message": "Device deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= TRIGGER CONDITIONS ENDPOINTS =============

@app.get("/api/trig-conditions")
async def get_trig_conditions():
    """Получить все условия триггеров"""
    try:
        db = get_db_instance()
        conditions = db.get_all_trig_conditions()
        return {
            "success": True,
            "data": [object_to_dict(c) for c in conditions],
            "count": len(conditions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trig-conditions/{condition_id}")
async def get_trig_condition(condition_id: int):
    """Получить условие триггера по ID"""
    try:
        db = get_db_instance()
        condition = db.get_trig_condition(condition_id)
        if condition:
            return {"success": True, "data": object_to_dict(condition)}
        raise HTTPException(status_code=404, detail="Condition not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/trig-conditions/by-device/{device_id}")
async def get_conditions_by_device(device_id: int):
    """Получить условия по устройству"""
    try:
        db = get_db_instance()
        conditions = db.get_conditions_by_device(device_id)
        return {
            "success": True,
            "data": [object_to_dict(c) for c in conditions],
            "count": len(conditions)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/trig-conditions", status_code=status.HTTP_201_CREATED)
async def create_trig_condition(condition: TrigConditionCreate):
    """Создать новое условие триггера"""
    try:
        from database import TrigCondition
        db = get_db_instance()
        condition_obj = TrigCondition(
            device_id=condition.device_id,
            condition=condition.condition
        )
        condition_id = db.add_trig_condition(condition_obj)
        return {"success": True, "id": condition_id, "message": "Trigger condition created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/trig-conditions/{condition_id}")
async def update_trig_condition(condition_id: int, condition: TrigConditionUpdate):
    """Обновить условие триггера"""
    try:
        from database import TrigCondition
        db = get_db_instance()
        condition_obj = TrigCondition(
            id=condition_id,
            device_id=condition.device_id,
            condition=condition.condition
        )
        db.update_trig_condition(condition_obj)
        return {"success": True, "message": "Trigger condition updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/trig-conditions/{condition_id}")
async def delete_trig_condition(condition_id: int):
    """Удалить условие триггера"""
    try:
        db = get_db_instance()
        db.delete_trig_condition(condition_id)
        return {"success": True, "message": "Trigger condition deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= TRIGGERS ENDPOINTS =============

@app.get("/api/triggers")
async def get_triggers():
    """Получить все триггеры"""
    try:
        db = get_db_instance()
        triggers = db.get_all_triggers()
        return {
            "success": True,
            "data": [object_to_dict(t) for t in triggers],
            "count": len(triggers)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/triggers/{trigger_id}")
async def get_trigger(trigger_id: int):
    """Получить триггер по ID"""
    try:
        db = get_db_instance()
        trigger = db.get_trigger(trigger_id)
        if trigger:
            return {"success": True, "data": object_to_dict(trigger)}
        raise HTTPException(status_code=404, detail="Trigger not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/triggers/by-controller/{controller_id}")
async def get_triggers_by_controller(controller_id: int):
    """Получить триггеры по контроллеру"""
    try:
        db = get_db_instance()
        triggers = db.get_triggers_by_controller(controller_id)
        return {
            "success": True,
            "data": [object_to_dict(t) for t in triggers],
            "count": len(triggers)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/triggers", status_code=status.HTTP_201_CREATED)
async def create_trigger(trigger: TriggerCreate):
    """Создать новый триггер"""
    try:
        from database import Trigger
        db = get_db_instance()
        trigger_obj = Trigger(
            controller_id=trigger.controller_id,
            condition_id=trigger.condition_id,
            response=trigger.response
        )
        trigger_id = db.add_trigger(trigger_obj)
        return {"success": True, "id": trigger_id, "message": "Trigger created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/triggers/{trigger_id}")
async def update_trigger(trigger_id: int, trigger: TriggerUpdate):
    """Обновить триггер"""
    try:
        from database import Trigger
        db = get_db_instance()
        trigger_obj = Trigger(
            id=trigger_id,
            controller_id=trigger.controller_id,
            condition_id=trigger.condition_id,
            response=trigger.response
        )
        db.update_trigger(trigger_obj)
        return {"success": True, "message": "Trigger updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/triggers/{trigger_id}")
async def delete_trigger(trigger_id: int):
    """Удалить триггер"""
    try:
        db = get_db_instance()
        db.delete_trigger(trigger_id)
        return {"success": True, "message": "Trigger deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= EVENTS ENDPOINTS =============

@app.get("/api/events/by-device/{device_id}")
async def get_events_by_device(device_id: int, limit: int = Query(100, ge=1, le=1000)):
    """Получить события устройства"""
    try:
        db = get_db_instance()
        events = db.get_events_by_device(device_id, limit)
        return {
            "success": True,
            "data": [object_to_dict(e) for e in events],
            "count": len(events)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/latest/{device_id}")
async def get_latest_event(device_id: int):
    """Получить последнее событие устройства"""
    try:
        db = get_db_instance()
        event = db.get_latest_event(device_id)
        return {"success": True, "data": object_to_dict(event)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/events/statistics/{device_id}")
async def get_device_statistics(device_id: int, hours: int = Query(24, ge=1, le=168)):
    """Получить статистику устройства за последние N часов"""
    try:
        db = get_db_instance()
        stats = db.get_device_statistics(device_id, hours)
        return {"success": True, "data": stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/events", status_code=status.HTTP_201_CREATED)
async def create_event(event: EventCreate):
    """Создать новое событие"""
    try:
        from database import Event
        db = get_db_instance()
        event_obj = Event(
            value=event.value,
            device_id=event.device_id,
            time=event.time if event.time else datetime.now()
        )
        event_id = db.add_event(event_obj)
        return {"success": True, "id": event_id, "message": "Event created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============= HEALTH CHECK =============

@app.get("/api/health")
async def health_check():
    """Проверка работоспособности API"""
    try:
        db = get_db_instance()
        return {"status": "healthy", "service": "IoT Management API", "db_connected": True}
    except:
        return {"status": "unhealthy", "service": "IoT Management API", "db_connected": False}


# ============= ЗАКРЫТИЕ СОЕДИНЕНИЯ =============

@app.on_event("shutdown")
async def shutdown_event():
    """Закрытие соединения с БД при остановке приложения"""
    global db_instance
    if db_instance:
        db_instance.close()