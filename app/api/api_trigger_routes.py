# api/api_trigger_routes.py
import json
import logging
from flask import request, jsonify
from .api_utils import handle_api_errors
from database import (
    Trigger, TrigCondition, TrigResponse,
    Scene, SceneCondition, SceneResponse
)

logger = logging.getLogger(__name__)


def register_trigger_routes(app, db, kafkaHandler):
    # ============ ФУНКЦИИ ДЛЯ УСЛОВИЙ ТРИГГЕРОВ ============

    def get_condition_string(condition, device=None, param_number=None):
        """
        Формирование строки условия для триггера

        Правильный формат для условия:
        - По значению: device_type/port/value/{param_number}/{compare}/{value}
        - По времени: device_type/port/time/{time_ms}
        - По изменению: device_type/port/value/{param_number}/onChange
        """
        # Получаем тип и порт устройства
        if device:
            device_type = device.type_id
            port = device.port
        else:
            device_type = condition.get('device_type', 'unknown')
            port = condition.get('device_port', '0')

        # Получаем номер параметра
        param_num = param_number if param_number is not None else condition.get('param_num', 0)

        # Определяем тип триггера
        trigger_type = condition.get('trigger_type', 'value')

        if trigger_type == 'time':
            # Формат: device_type/port/time/time_ms
            time_ms = int(float(condition.get('time', 0)) * 1000)
            return f"{device_type}/{port}/time/{time_ms}"

        elif trigger_type == 'changed':
            # Формат: device_type/port/value/{param_num}/onChange
            return f"{device_type}/{port}/value/{param_num}/onChange"

        else:
            # По значению: device_type/port/value/{param_num}/{compare}/{value}
            compare = condition.get('compare', 'equal')
            value = condition.get('value', '')
            type_name = db.get_device_type_by_id(device_type).name

            return f"{type_name}/{port}/value/{param_num}/{compare}/{value}"

    def get_param_number(device, command_name):
        """
        Получение parameter_number из reading_commands устройства
        """
        if not device:
            return None

        device_type = db.get_device_type_by_id(device.type_id)
        if not device_type or not device_type.param_name:
            return None

        try:
            config = json.loads(device_type.param_name) if isinstance(device_type.param_name,
                                                                      str) else device_type.param_name
            reading_commands = config.get('reading_commands', [])
            for rc in reading_commands:
                if rc.get('display_name') == command_name:
                    return rc.get('parameter_number')
        except:
            pass

        return 0

    # ============ ФУНКЦИИ ДЛЯ ОТВЕТОВ ТРИГГЕРОВ ============

    def get_response_string(response, device=None):
        """
        Формирование строки ответа для триггера

        Правильный формат:
        - Команда без значения: device_type/port/command
        - Команда со значением: device_type/port/command/value
        """
        if device:
            device_type = device.type_id
            port = device.port
        else:
            device_type = response.get('device_type', 'unknown')
            port = response.get('device_port', '0')

        command = response.get('command', '')
        value = response.get('value', '')
        type_name = db.get_device_type_by_id(device_type).name

        # Если есть значение - добавляем его
        if value:
            return f"{type_name}/{port}/{command}/{value}"
        else:
            return f"{type_name}/{port}/{command}"

    # ============ СОХРАНЕНИЕ УСЛОВИЙ ============

    def save_conditions(trigger_id, conditions, is_scene=False, src_controller_id=None):
        """Сохранение условий для триггера или сценария"""
        if is_scene:
            # Для сценариев сохраняем как JSON
            json_conditions = []
            for condition in conditions:
                device = db.get_device_by_id(condition['device_id'])
                cond_json = build_condition_json(condition, device)
                json_conditions.append(cond_json)

            # Сохраняем как JSON строку
            cond_obj = SceneCondition(
                device_id=conditions[0]['device_id'] if conditions else 0,
                condition=json.dumps(json_conditions),
                scene_id=trigger_id
            )
            db.add_scene_condition(cond_obj)
        else:
            # Для триггеров сохраняем как строку
            for condition in conditions:
                device = db.get_device_by_id(condition['device_id'])
                # Получаем parameter_number из команды чтения
                param_number = get_param_number(device, condition.get('command'))

                # Формируем строку условия
                condition_str = get_condition_string(condition, device, param_number)
                cond_obj = TrigCondition(
                    device_id=condition['device_id'],
                    condition=condition_str,
                    trigger_id=trigger_id
                )
                db.add_trig_condition(cond_obj)

    # ============ СОХРАНЕНИЕ ОТВЕТОВ ============

    def save_responses(trigger_id, responses, is_scene=False):
        """Сохранение ответов для триггера или сценария"""
        if is_scene:
            # Для сценариев сохраняем как JSON
            json_responses = []
            for response in responses:
                device = db.get_device_by_id(response['device_id'])
                # Получаем MAC контроллера-приемника
                dst_controller = db.get_controller_by_id(response.get('dst_controller_id'))
                if dst_controller:
                    response['dst_controller_mac'] = dst_controller.mac
                resp_json = build_response_json(response, device)
                json_responses.append(resp_json)

            # Сохраняем как JSON строку
            resp_obj = SceneResponse(
                device_id=responses[0]['device_id'] if responses else 0,
                resp=json.dumps(json_responses),
                scene_id=trigger_id
            )
            db.add_scene_response(resp_obj)
        else:
            # Для триггеров сохраняем как строку
            for response in responses:
                device = db.get_device_by_id(response['device_id'])
                resp_str = get_response_string(response, device)
                resp_obj = TrigResponse(
                    device_id=response['device_id'],
                    resp=resp_str,
                    trigger_id=trigger_id
                )
                db.add_trig_response(resp_obj)

    # ============ УДАЛЕНИЕ ДАННЫХ ============

    def delete_conditions(trigger_id, is_scene=False):
        if is_scene:
            conditions = db.get_scene_conditions_by_scene(trigger_id)
            for cond in conditions:
                db.delete_scene_condition(cond.id)
        else:
            conditions = db.get_trig_conditions_by_trigger(trigger_id)
            for cond in conditions:
                db.delete_trig_condition(cond.id)

    def delete_responses(trigger_id, is_scene=False):
        if is_scene:
            responses = db.get_scene_responses_by_scene(trigger_id)
            for resp in responses:
                db.delete_scene_response(resp.id)
        else:
            responses = db.get_trig_responses_by_trigger(trigger_id)
            for resp in responses:
                db.delete_trig_response(resp.id)

    # ============ ОТПРАВКА В KAFKA ============

    def send_to_kafka(trigger_id, data, is_scene=False):
        """Отправка данных в Kafka"""
        if is_scene:
            scene = db.get_scene_by_id(trigger_id)
            if scene:
                scene_conditions = db.get_scene_conditions_by_scene(trigger_id)
                scene_responses = db.get_scene_responses_by_scene(trigger_id)

                conditions_json = []
                responses_json = []

                for cond in scene_conditions:
                    try:
                        cond_data = json.loads(cond.condition)
                        if isinstance(cond_data, list):
                            conditions_json.extend(cond_data)
                        else:
                            conditions_json.append(cond_data)
                    except:
                        pass

                for resp in scene_responses:
                    try:
                        resp_data = json.loads(resp.resp)
                        if isinstance(resp_data, list):
                            responses_json.extend(resp_data)
                        else:
                            responses_json.append(resp_data)
                    except:
                        pass

                scene_data = {
                    'scene_id': trigger_id,
                    'conditions': conditions_json,
                    'responses': responses_json,
                    'is_active': scene.is_active
                }
                kafkaHandler.update_scene_table(scene_data)
        else:
            trigger = db.get_trigger_by_id(trigger_id)
            if trigger:
                req_parts = []
                condCount = 0
                trigConditions = db.get_trig_conditions_by_trigger(trigger.id)
                for cond in trigConditions:
                    if condCount > 0:
                        req_parts.append("and")
                    # device = db.get_device_by_id(cond.device_id)
                    # req_parts.append(db.get_device_type_by_id(device.type_id).name)
                    # if device.port:
                    #     req_parts.append(device.port)
                    req_parts.append(cond.condition)
                    condCount += 1
                req_parts.append("do")
                req_parts.append(db.get_controller_by_id(trigger.controller_resp_id).mac)
                trigResps = db.get_trig_responses_by_trigger(trigger.id)
                for resp in trigResps:
                    # device = db.get_device_by_id(resp.device_id)
                    # req_parts.append(db.get_device_type_by_id(device.type_id).name)
                    # if device.port:
                    #     req_parts.append(device.port)
                    req_parts.append(resp.resp)
                req = "/".join(req_parts)
                trig_data_for_core = {
                    'id': trigger.id,
                    'controller_mac': db.get_controller_by_id(trigger.controller_id).mac,
                    'trig': req,
                    'is_active': trigger.is_active
                }
                kafkaHandler.update_trig_table(trig_data_for_core)

    def delete_from_kafka(trigger_id, is_scene=False):
        if is_scene:
            kafkaHandler.delete_scene(trigger_id)
        else:
            kafkaHandler.delete_trigger(trigger_id)

    # ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ JSON ============

    def build_response_json(response, device):
        """
        Построение JSON для ответа сценария
        Формат: {'mac': '...', 'device_type': '...', 'device_port': '...', 'command': '...'}
        """
        command_parts = response.get('command', '').split('/')
        command_name = command_parts[0]
        command_value = command_parts[1] if len(command_parts) > 1 else None

        resp_json = {
            'mac': response.get('dst_controller_mac') or response.get('controller_mac'),
            'device_type': device.type if device else 'unknown',
            'device_port': device.port if device else '0',
            'command': command_name
        }

        if command_value:
            resp_json['value'] = command_value

        return resp_json

    def build_condition_json(condition, device):
        """
        Построение JSON для условия сценария
        Формат: {'device_type': '...', 'device_port': '...', 'value_type': '...', ...}
        """
        cond_json = {
            'device_type': device.type if device else 'unknown',
            'device_port': device.port if device else '0'
        }

        trigger_type = condition.get('trigger_type', 'value')

        if trigger_type == 'time':
            cond_json['value_type'] = 'Time'
            cond_json['compare_type'] = 'time'
            cond_json['value'] = str(int(float(condition.get('time', 0)) * 1000))
        elif trigger_type == 'changed':
            cond_json['value_type'] = 'Value'
            cond_json['compare_type'] = 'changed'
        else:
            cond_json['value_type'] = 'Value'
            cond_json['compare_type'] = condition.get('compare', 'equal')
            cond_json['value'] = condition.get('value', '')

        if condition.get('param_num') is not None:
            cond_json['param_num'] = condition['param_num']

        cond_json['is_execute'] = False

        return cond_json

    # ============ МАРШРУТЫ ============

    @app.route('/api/triggers', methods=['GET'])
    @handle_api_errors
    def get_all_triggers():
        triggers = db.get_all_triggers()
        result = []
        for trigger in triggers:
            conditions = db.get_trig_conditions_by_trigger(trigger.id)
            conditions_data = []
            for cond in conditions:
                device = db.get_device_by_id(cond.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = cond.condition.split('/')
                    command = parts[0] if parts else ''
                    value = parts[1] if len(parts) > 1 else None
                    conditions_data.append({
                        'id': cond.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })
            responses = db.get_trig_responses_by_trigger(trigger.id)
            responses_data = []
            for resp in responses:
                device = db.get_device_by_id(resp.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = resp.resp.split('/')
                    command = parts[0] if parts else ''
                    value = parts[1] if len(parts) > 1 else None
                    responses_data.append({
                        'id': resp.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })
            src_controller = db.get_controller_by_id(trigger.controller_id)
            dst_controller = db.get_controller_by_id(trigger.controller_resp_id)
            result.append({
                'id': trigger.id,
                'name': trigger.name,
                'is_active': trigger.is_active if hasattr(trigger, 'is_active') else True,
                'src_controller_id': trigger.controller_id,
                'src_controller_name': src_controller.name if src_controller else 'Unknown',
                'dst_controller_id': trigger.controller_resp_id,
                'dst_controller_name': dst_controller.name if dst_controller else 'Unknown',
                'conditions': conditions_data,
                'responses': responses_data
            })
        return jsonify(result)

    @app.route('/api/scenes', methods=['GET'])
    @handle_api_errors
    def get_all_scenes():
        scenes = db.get_all_scenes()
        result = []
        for scene in scenes:
            conditions = db.get_scene_conditions_by_scene(scene.id)
            conditions_data = []
            for cond in conditions:
                device = db.get_device_by_id(cond.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = cond.condition.split('/')
                    command = parts[0] if parts else ''
                    value = parts[1] if len(parts) > 1 else None
                    conditions_data.append({
                        'id': cond.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })
            responses = db.get_scene_responses_by_scene(scene.id)
            responses_data = []
            for resp in responses:
                device = db.get_device_by_id(resp.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = resp.resp.split('/')
                    command = parts[0] if parts else ''
                    value = parts[1] if len(parts) > 1 else None
                    responses_data.append({
                        'id': resp.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })
            result.append({
                'id': scene.id,
                'name': scene.name,
                'is_active': scene.is_active if hasattr(scene, 'is_active') else True,
                'conditions': conditions_data,
                'responses': responses_data
            })
        return jsonify(result)

    @app.route('/api/triggers', methods=['POST'])
    @handle_api_errors
    def create_trigger():
        data = request.json
        is_scene = data.get('type') == 'complex'

        if is_scene:
            scene = Scene(
                name=data['name'],
                is_active=True
            )
            scene_id = db.add_scene(scene)
            if not scene_id:
                return jsonify({'success': False, 'error': 'Failed to create scene'}), 400
            save_conditions(scene_id, data['conditions'], is_scene=True)
            save_responses(scene_id, data['responses'], is_scene=True)
            send_to_kafka(scene_id, data, is_scene=True)
            return jsonify({'success': True, 'id': scene_id})
        else:
            trigger = Trigger(
                controller_id=data['src_controller_id'],
                controller_resp_id=data['dst_controller_id'],
                name=data['name'],
                is_active=True
            )
            trigger_id = db.add_trigger(trigger)
            if not trigger_id:
                return jsonify({'success': False, 'error': 'Failed to create trigger'}), 400
            save_conditions(trigger_id, data['conditions'], is_scene=False)
            save_responses(trigger_id, data['responses'], is_scene=False)
            trigger.id = trigger_id
            send_to_kafka(trigger_id, data, is_scene=False)
            return jsonify({'success': True, 'id': trigger_id})

    @app.route('/api/triggers/<int:trigger_id>', methods=['PUT'])
    @handle_api_errors
    def update_trigger(trigger_id):
        data = request.json
        new_is_scene = data.get('type') == 'complex'

        existing_scene = db.get_scene_by_id(trigger_id)
        existing_trigger = db.get_trigger_by_id(trigger_id) if not existing_scene else None

        old_is_scene = existing_scene is not None

        if old_is_scene == new_is_scene:
            if new_is_scene:
                db.update_scene_name(trigger_id, data['name'])
                delete_conditions(trigger_id, is_scene=True)
                delete_responses(trigger_id, is_scene=True)
                save_conditions(trigger_id, data['conditions'], is_scene=True)
                save_responses(trigger_id, data['responses'], is_scene=True)
                send_to_kafka(trigger_id, data, is_scene=True)
            else:
                with db.connection.cursor() as cur:
                    cur.execute("UPDATE triggers SET name = %s WHERE id = %s",
                                (data['name'], trigger_id))
                    db.connection.commit()
                delete_conditions(trigger_id, is_scene=False)
                delete_responses(trigger_id, is_scene=False)
                save_conditions(trigger_id, data['conditions'], is_scene=False)
                save_responses(trigger_id, data['responses'], is_scene=False)
                if 'src_controller_id' in data and 'dst_controller_id' in data:
                    with db.connection.cursor() as cur:
                        cur.execute("""
                            UPDATE triggers 
                            SET controller_id = %s, controller_resp_id = %s 
                            WHERE id = %s
                        """, (data['src_controller_id'], data['dst_controller_id'], trigger_id))
                        db.connection.commit()
                send_to_kafka(trigger_id, data, is_scene=False)

            return jsonify({'success': True, 'id': trigger_id, 'type_changed': False})

        if old_is_scene:
            delete_conditions(trigger_id, is_scene=True)
            delete_responses(trigger_id, is_scene=True)
            db.delete_scene(trigger_id)
            delete_from_kafka(trigger_id, is_scene=True)
            logger.info(f"Deleted old scene {trigger_id} before type change")
        else:
            conditions = db.get_trig_conditions_by_trigger(trigger_id)
            for cond in conditions:
                db.delete_trig_condition(cond.id)
            responses = db.get_trig_responses_by_trigger(trigger_id)
            for resp in responses:
                db.delete_trig_response(resp.id)
            db.delete_trigger(trigger_id)
            delete_from_kafka(trigger_id, is_scene=False)
            logger.info(f"Deleted old trigger {trigger_id} before type change")

        new_id = None
        if new_is_scene:
            scene = Scene(
                name=data['name'],
                is_active=True
            )
            new_id = db.add_scene(scene)
            if not new_id:
                return jsonify({'success': False, 'error': 'Failed to create scene during type change'}), 400
            save_conditions(new_id, data['conditions'], is_scene=True)
            save_responses(new_id, data['responses'], is_scene=True)
            send_to_kafka(new_id, data, is_scene=True)
            logger.info(f"Created new scene {new_id} after type change from trigger {trigger_id}")
        else:
            trigger = Trigger(
                controller_id=data['src_controller_id'],
                controller_resp_id=data['dst_controller_id'],
                name=data['name'],
                is_active=True
            )
            new_id = db.add_trigger(trigger)
            if not new_id:
                return jsonify({'success': False, 'error': 'Failed to create trigger during type change'}), 400
            save_conditions(new_id, data['conditions'], is_scene=False)
            save_responses(new_id, data['responses'], is_scene=False)
            trigger.id = new_id
            send_to_kafka(new_id, data, is_scene=False)
            logger.info(f"Created new trigger {new_id} after type change from scene {trigger_id}")

        return jsonify({'success': True, 'id': new_id, 'type_changed': True})

    @app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_trigger(trigger_id):
        scene = db.get_scene_by_id(trigger_id) #TODO проверять так не корректно, может быть и триггер и сценарий с одним id
        if scene:
            delete_conditions(trigger_id, is_scene=True)
            delete_responses(trigger_id, is_scene=True)
            db.delete_scene(trigger_id)
            delete_from_kafka(trigger_id, is_scene=True)
            return jsonify({'success': True})

        conditions = db.get_trig_conditions_by_trigger(trigger_id)
        for cond in conditions:
            db.delete_trig_condition(cond.id)
        responses = db.get_trig_responses_by_trigger(trigger_id)
        for resp in responses:
            db.delete_trig_response(resp.id)
        db.delete_trigger(trigger_id, kafkaHandler)
        return jsonify({'success': True})

    @app.route('/api/triggers/<int:trigger_id>/toggle', methods=['PUT'])
    def toggle_trigger(trigger_id):
        try:
            data = request.json
            is_active = data.get('is_active', True)

            scene = db.get_scene_by_id(trigger_id)
            if scene:
                db.update_scene_status(trigger_id, is_active)
                if kafkaHandler:
                    scene_data = {
                        'command_type': 'UPD_STATUS',
                        'scene_id': trigger_id,
                        'is_active': is_active
                    }
                    kafkaHandler.update_scene_status(scene_data)
                return jsonify({'success': True})

            db.update_trig_status(trigger_id, is_active)
            if kafkaHandler:
                trigger_data = {
                    'command_type': 'UPD_STATUS',
                    'trigger_id': trigger_id,
                    'is_active': is_active
                }
                kafkaHandler.update_trig_table(trigger_data)

            return jsonify({'success': True})

        except Exception as e:
            logger.error(f"Error toggling trigger/scene: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/device-types/server-commands', methods=['GET'])
    @handle_api_errors
    def get_server_commands():
        server_type = db.get_device_type_by_name('serv')
        if not server_type:
            return jsonify({'error': 'Server type not found'}), 404

        try:
            config = json.loads(server_type.param_name) if server_type.param_name else {}
            sending_commands = config.get('sending_commands', {})
            all_commands = []
            if sending_commands.get('binary'):
                for cmd in sending_commands['binary']:
                    cmd['type'] = 'binary'
                    all_commands.append(cmd)
            if sending_commands.get('numeric'):
                for cmd in sending_commands['numeric']:
                    cmd['type'] = 'numeric'
                    all_commands.append(cmd)
            return jsonify(all_commands)
        except Exception as e:
            logger.error(f"Error parsing server commands: {e}")
            return jsonify({'error': str(e)}), 500

    # @app.route('/api/scenes', methods=['GET'])
    # def get_all_scenes():
    #     """Получить все сложные сценарии"""
    #     try:
    #         scenes = db.get_all_scenes()
    #         result = []
    #
    #         all_devices = db.get_all_devices()
    #         devices_dict = {d.id: d for d in all_devices}
    #
    #         all_types = db.get_all_device_types()
    #         types_dict = {t.id: t for t in all_types}
    #
    #         all_controllers = db.get_all_controllers()
    #         controllers_dict = {c.id: c for c in all_controllers}
    #
    #         for scene in scenes:
    #             # Получаем условия
    #             conditions = db.get_scene_conditions_by_scene(scene.id)
    #             conditions_data = []
    #             for cond in conditions:
    #                 device = devices_dict.get(cond.device_id)
    #                 if device:
    #                     device_type = types_dict.get(device.type_id)
    #
    #                     if '/' in cond.condition:
    #                         parts = cond.condition.split('/', 1)
    #                         command = parts[0]
    #                         value = parts[1] if len(parts) > 1 else None
    #                     else:
    #                         command = cond.condition
    #                         value = None
    #
    #                     type_display_name = None
    #                     if device_type and device_type.param_name:
    #                         try:
    #                             config = json.loads(device_type.param_name) if isinstance(device_type.param_name,
    #                                                                                       str) else device_type.param_name
    #                             type_display_name = config.get('display_name', device_type.name)
    #                         except:
    #                             type_display_name = device_type.name
    #
    #                     controller = controllers_dict.get(device.controller_id)
    #
    #                     conditions_data.append({
    #                         'id': cond.id,
    #                         'device_id': device.id,
    #                         'device_name': device.name,
    #                         'device_type_id': device.type_id,
    #                         'device_type_name': type_display_name or device_type.name if device_type else 'Unknown',
    #                         'controller_name': controller.name if controller else 'Unknown',
    #                         'port': device.port,
    #                         'command': command,
    #                         'value': value
    #                     })
    #
    #             # Получаем ответы
    #             responses = db.get_scene_responses_by_scene(scene.id)
    #             responses_data = []
    #             for resp in responses:
    #                 device = devices_dict.get(resp.device_id)
    #                 if device:
    #                     device_type = types_dict.get(device.type_id)
    #
    #                     if '/' in resp.resp:
    #                         parts = resp.resp.split('/', 1)
    #                         command = parts[0]
    #                         value = parts[1] if len(parts) > 1 else None
    #                     else:
    #                         command = resp.resp
    #                         value = None
    #
    #                     type_display_name = None
    #                     if device_type and device_type.param_name:
    #                         try:
    #                             config = json.loads(device_type.param_name) if isinstance(device_type.param_name,
    #                                                                                       str) else device_type.param_name
    #                             type_display_name = config.get('display_name', device_type.name)
    #                         except:
    #                             type_display_name = device_type.name
    #
    #                     controller = controllers_dict.get(device.controller_id)
    #
    #                     responses_data.append({
    #                         'id': resp.id,
    #                         'device_id': device.id,
    #                         'device_name': device.name,
    #                         'device_type_id': device.type_id,
    #                         'device_type_name': type_display_name or device_type.name if device_type else 'Unknown',
    #                         'controller_name': controller.name if controller else 'Unknown',
    #                         'port': device.port,
    #                         'command': command,
    #                         'value': value
    #                     })
    #
    #             result.append({
    #                 'id': scene.id,
    #                 'name': scene.name,
    #                 'is_active': scene.is_active if hasattr(scene, 'is_active') else True,
    #                 'conditions': conditions_data,
    #                 'responses': responses_data
    #             })
    #
    #         return jsonify(result)
    #
    #     except Exception as e:
    #         logger.error(f"Error getting scenes: {e}")
    #         return jsonify({'error': str(e)}), 500

    @app.route('/api/scenes', methods=['POST'])
    def create_scene():
        """Создать сложный сценарий"""
        try:
            data = request.json

            scene = Scene(
                name=data['name'],
                is_active=True
            )
            scene_id = db.add_scene(scene)

            if not scene_id:
                return jsonify({'success': False, 'error': 'Failed to create scene'}), 400

            # Добавляем условия
            for condition in data['conditions']:
                if condition.get('value') and condition['value'] != '':
                    condition_str = f"{condition['command']}/{condition['value']}"
                else:
                    condition_str = condition['command']

                cond_obj = SceneCondition(
                    device_id=condition['device_id'],
                    condition=condition_str,
                    scene_id=scene_id
                )
                db.add_scene_condition(cond_obj)

            # Добавляем ответы
            for response in data['responses']:
                if response.get('value') and response['value'] != '':
                    resp_str = f"{response['command']}/{response['value']}"
                else:
                    resp_str = response['command']

                resp_obj = SceneResponse(
                    device_id=response['device_id'],
                    resp=resp_str,
                    scene_id=scene_id
                )
                db.add_scene_response(resp_obj)

            # Отправляем через Kafka для синхронизации с ядром

            # if kafka_handler:
            #     scene_data = {
            #         'scene_id': scene_id,
            #         'name': data['name'],
            #         'conditions': data['conditions'],
            #         'responses': data['responses'],
            #         'type': 'complex'
            #     }
            #     kafka_handler.update_scene_table(scene_data)

            return jsonify({'success': True, 'id': scene_id})

        except Exception as e:
            logger.error(f"Error creating scene: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/scenes/<int:scene_id>/toggle', methods=['PUT'])
    def toggle_scene(scene_id):
        """Переключение статуса сценария"""
        try:
            data = request.json
            is_active = data.get('is_active', True)

            db.update_scene_status(scene_id, is_active)

            # Отправляем через Kafka для синхронизации
            if kafkaHandler:
                scene_data = {
                    'scene_id': scene_id,
                    'is_active': is_active
                }
                kafkaHandler.update_scene_status(scene_data)

            return jsonify({'success': True})

        except Exception as e:
            logger.error(f"Error toggling scene: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/scenes/<int:scene_id>', methods=['DELETE'])
    def delete_scene(scene_id):
        """Удалить сложный сценарий"""
        try:
            # Удаляем связанные данные
            conditions = db.get_scene_conditions_by_scene(scene_id)
            for cond in conditions:
                db.delete_scene_condition(cond.id)

            responses = db.get_scene_responses_by_scene(scene_id)
            for resp in responses:
                db.delete_scene_response(resp.id)

            db.delete_scene(scene_id)
            return jsonify({'success': True})

        except Exception as e:
            logger.error(f"Error deleting scene: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500