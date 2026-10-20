# api/api_trigger_routes.py
import json
import logging
from flask import request, jsonify
from .api_utils import handle_api_errors
from database import (
    Trigger, TrigCondition, TrigResponse
)

logger = logging.getLogger(__name__)
SERVER_ID = -1


def register_trigger_routes(app, db, kafkaHandler):

    # ============ ФУНКЦИИ ДЛЯ УСЛОВИЙ ТРИГГЕРОВ ============

    def get_condition_string(condition, device=None, param_number=None):
        if device:
            device_type = device.type_id
            port = device.port
        else:
            device_type = condition.get('device_type', 'unknown')
            port = condition.get('device_port', '0')

        param_num = param_number if param_number is not None else condition.get('param_num', 0)
        trigger_type = condition.get('trigger_type', 'value')

        if trigger_type == 'time':
            time_ms = int(float(condition.get('time', 0)) * 1000)
            return f"{device_type}/{port}/time/{time_ms}"
        elif trigger_type == 'changed':
            return f"{device_type}/{port}/value/{param_num}/onChange"
        else:
            compare = condition.get('compare', 'equal')
            value = condition.get('value', '')
            type_name = db.get_device_type_by_id(device_type).name
            return f"{type_name}/{port}/value/{param_num}/{compare}/{value}"

    def get_param_number(device, command_name):
        if not device:
            return None
        device_type = db.get_device_type_by_id(device.type_id)
        if not device_type or not device_type.param_name:
            return None
        try:
            config = json.loads(device_type.param_name) if isinstance(device_type.param_name, str) else device_type.param_name
            reading_commands = config.get('reading_commands', [])
            for rc in reading_commands:
                if rc.get('display_name') == command_name:
                    return rc.get('parameter_number')
        except:
            pass
        return 0

    # ============ ФУНКЦИИ ДЛЯ ОТВЕТОВ ТРИГГЕРОВ ============

    def get_response_string(response, device=None):
        if device:
            device_type = device.type_id
            port = device.port
        else:
            device_type = response.get('device_type', 'unknown')
            port = response.get('device_port', '0')

        command = response.get('command', '')
        value = response.get('value', '')
        type_name = db.get_device_type_by_id(device_type).name

        if value:
            return f"exec/{type_name}/{port}/{command}/{value}"
        else:
            return f"exec/{type_name}/{port}/{command}"

    # ============ СОХРАНЕНИЕ УСЛОВИЙ ============

    def save_conditions(trigger_id, conditions, is_scene=False):
        if is_scene:
            json_conditions = []
            for condition in conditions:
                device = db.get_device_by_id(condition['device_id'])
                cond_json = build_condition_json(condition, device)
                json_conditions.append(cond_json)
            cond_obj = TrigCondition(
                device_id=conditions[0]['device_id'] if conditions else 0,
                condition=json.dumps(json_conditions),
                trigger_id=trigger_id
            )
            db.add_trig_condition(cond_obj)
        else:
            for condition in conditions:
                device = db.get_device_by_id(condition['device_id'])
                param_number = get_param_number(device, condition.get('command'))
                condition_str = get_condition_string(condition, device, param_number)
                cond_obj = TrigCondition(
                    device_id=condition['device_id'],
                    condition=condition_str,
                    trigger_id=trigger_id
                )
                db.add_trig_condition(cond_obj)

    # ============ СОХРАНЕНИЕ ОТВЕТОВ ============

    def save_responses(trigger_id, responses, is_scene=False):
        if is_scene:
            json_responses = []
            for response in responses:
                device = None
                device_id = response.get('device_id')
                if device_id and device_id != 0:
                    device = db.get_device_by_id(device_id)

                dst_controller_id = response.get('dst_controller_id')
                if dst_controller_id == SERVER_ID:
                    response['dst_controller_mac'] = 'serv'
                else:
                    dst_controller = db.get_controller_by_id(dst_controller_id)
                    if dst_controller:
                        response['dst_controller_mac'] = dst_controller.mac

                resp_json = build_response_json(response, device)
                json_responses.append(resp_json)

            first_device_id = 0
            if responses:
                first_device_id = responses[0].get('device_id') or None

            resp_obj = TrigResponse(
                device_id=first_device_id,
                resp=json.dumps(json_responses),
                trigger_id=trigger_id
            )
            db.add_trig_response(resp_obj)
        else:
            for response in responses:
                device = None
                device_id = response.get('device_id')
                if device_id and device_id != 0:
                    device = db.get_device_by_id(device_id)
                resp_str = get_response_string(response, device)
                resp_obj = TrigResponse(
                    device_id=device_id or 0,
                    resp=resp_str,
                    trigger_id=trigger_id
                )
                db.add_trig_response(resp_obj)

    # ============ УДАЛЕНИЕ ДАННЫХ ============

    def delete_conditions(trigger_id):
        conditions = db.get_trig_conditions_by_trigger(trigger_id)
        for cond in conditions:
            db.delete_trig_condition(cond.id)

    def delete_responses(trigger_id):
        responses = db.get_trig_responses_by_trigger(trigger_id)
        for resp in responses:
            db.delete_trig_response(resp.id)

    # ============ ОТПРАВКА В KAFKA ============

    def send_to_kafka(trigger_id, data, is_scene=False):
        if is_scene:
            scene = db.get_trigger_by_id(trigger_id)
            if scene:
                scene_conditions = db.get_trig_conditions_by_trigger(trigger_id)
                scene_responses = db.get_trig_responses_by_trigger(trigger_id)

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
                    'id': trigger_id,
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
                    req_parts.append(cond.condition)
                    condCount += 1
                req_parts.append("do")
                req_parts.append(db.get_controller_by_id(trigger.controller_resp_id).mac)
                trigResps = db.get_trig_responses_by_trigger(trigger.id)
                for resp in trigResps:
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
        kafkaHandler.delete_trigger(trigger_id)

    # ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ JSON ============

    def build_response_json(response, device):
        """
        Построение JSON для ответа сценария.

        Для сервера (dst_controller_id == SERVER_ID):
            mac='serv', device_type='serv', device_port='0',
            target_device_type=<тип>, target_device_port=<порт>,
            target_device_id=<id>, param_num=<num>,
            command=<команда>, value=<значение>

        Для обычного устройства:
            mac=<mac>, device_type=<тип>, device_port=<порт>,
            command=<команда>, value=<значение>
        """
        is_server = (response.get('dst_controller_id') == SERVER_ID
                     or response.get('dst_controller_mac') == 'serv')

        command_name = response.get('command', '')
        value = response.get('value', '')

        if device:
            type_name = db.get_device_type_by_id(device.type_id).name
            device_port = device.port
        else:
            type_name = 'unknown'
            device_port = '0'

        if is_server:
            resp_json = {
                'mac': 'serv',
                'device_type': 'serv',
                'device_port': '0',
                'target_device_type': type_name,
                'target_device_port': device_port,
                'target_device_id': device.id if device else None,
                'param_num': response.get('param_num', 0),
                'command': command_name,
                'value': value
            }
        else:
            resp_json = {
                'mac': response.get('dst_controller_mac') or response.get('controller_mac') or '',
                'device_type': type_name,
                'device_port': device_port,
                'command': command_name,
                'value': value
            }

        return resp_json

    def build_condition_json(condition, device):
        if device:
            type_name = db.get_device_type_by_id(device.type_id).name
            device_port = device.port
            device_id = device.id
        else:
            type_name = 'unknown'
            device_port = '0'
            device_id = None

        cond_json = {
            'device_type': type_name,
            'device_port': device_port,
            'device_id': device_id
        }

        trigger_type = condition.get('trigger_type', 'value')

        if trigger_type == 'time':
            cond_json['value_type'] = 'time'
            cond_json['compare_type'] = 'time'
            cond_json['value'] = str(int(float(condition.get('time', 0)) * 1000))
        elif trigger_type == 'changed':
            cond_json['value_type'] = 'value'
            cond_json['compare_type'] = 'changed'
        else:
            cond_json['value_type'] = 'value'
            cond_json['compare_type'] = condition.get('compare', 'equal')
            cond_json['value'] = condition.get('value', '')

        if condition.get('param_num') is not None:
            cond_json['param_num'] = condition['param_num']

        cond_json['is_execute'] = False
        return cond_json

    # ============ ПАРСИНГ СТРОК ============

    def parse_condition_string(condition_str):
        parts = condition_str.split('/')
        result = {
            'device_type': parts[0] if len(parts) > 0 else '',
            'port': parts[1] if len(parts) > 1 else '',
            'command': '',
            'value': '',
            'compare': 'equal',
            'trigger_type': 'value',
            'time': 0,
            'param_num': 0
        }
        if len(parts) >= 4:
            if parts[2] == 'time':
                result['trigger_type'] = 'time'
                result['time'] = int(parts[3]) if parts[3].isdigit() else 0
            elif parts[2] == 'value':
                if len(parts) >= 6:
                    result['param_num'] = int(parts[3]) if parts[3].isdigit() else 0
                    if parts[4] == 'onChange':
                        result['trigger_type'] = 'changed'
                        result['value'] = 'onChange'
                    else:
                        result['trigger_type'] = 'value'
                        result['compare'] = parts[4]
                        result['value'] = parts[5]
        return result

    def parse_response_json(resp_str):
        """Пробует распарсить JSON. Возвращает (list или None)."""
        try:
            parsed = json.loads(resp_str)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    # ============ МАРШРУТЫ ============

    @app.route('/api/triggers', methods=['GET'])
    @handle_api_errors
    def get_all_triggers():
        triggers = db.get_all_triggers()
        result = []
        for trigger in triggers:
            # УСЛОВИЯ
            conditions = db.get_trig_conditions_by_trigger(trigger.id)
            conditions_data = []

            # Если сценарий — cond.condition это JSON-массив
            if trigger.is_scene and conditions:
                try:
                    parsed = json.loads(conditions[0].condition)
                    if isinstance(parsed, list):
                        for item in parsed:
                            device_id = item.get('device_id')
                            device = db.get_device_by_id(device_id) if device_id else None
                            conditions_data.append({
                                'id': None,
                                'device_id': device_id,
                                'device_name': device.name if device else 'Сервер',
                                'device_type': item.get('device_type', 'unknown'),
                                'controller_name': '',
                                'port': item.get('device_port', '0'),
                                'command': '',
                                'value': item.get('value', ''),
                                'compare': item.get('compare_type', 'equal'),
                                'trigger_type': 'time' if item.get('value_type') == 'time' else ('changed' if item.get('compare_type') == 'changed' else 'value'),
                                'time': int(item.get('value', 0)) if item.get('value_type') == 'time' else 0,
                                'param_num': item.get('param_num', 0),
                            })
                except Exception as e:
                    logger.error(f"Error parsing scene conditions for trigger {trigger.id}: {e}")
            else:
                for cond in conditions:
                    device = db.get_device_by_id(cond.device_id) if cond.device_id else None
                    condition_info = parse_condition_string(cond.condition)
                    if device:
                        controller = db.get_controller_by_id(device.controller_id)
                        device_type = db.get_device_type_by_id(device.type_id)
                        conditions_data.append({
                            'id': cond.id,
                            'device_id': device.id,
                            'device_name': device.name,
                            'device_type': device_type.name if device_type else 'Unknown',
                            'controller_name': controller.name if controller else 'Unknown',
                            'port': device.port,
                            'command': condition_info.get('command', ''),
                            'value': condition_info.get('value', ''),
                            'compare': condition_info.get('compare', 'equal'),
                            'trigger_type': condition_info.get('trigger_type', 'value'),
                            'time': condition_info.get('time', 0),
                            'param_num': condition_info.get('param_num', 0),
                        })
                    else:
                        conditions_data.append({
                            'id': cond.id,
                            'device_id': None,
                            'device_name': 'Сервер',
                            'device_type': 'serv',
                            'controller_name': 'Сервер',
                            'port': '0',
                            'command': condition_info.get('command', ''),
                            'value': condition_info.get('value', ''),
                            'compare': condition_info.get('compare', 'equal'),
                            'trigger_type': condition_info.get('trigger_type', 'value'),
                            'time': condition_info.get('time', 0),
                            'param_num': condition_info.get('param_num', 0),
                        })

            # ОТВЕТЫ
            responses = db.get_trig_responses_by_trigger(trigger.id)
            responses_data = []

            for resp in responses:
                parsed_list = parse_response_json(resp.resp)
                if parsed_list is not None:
                    # Сценарий — JSON
                    for item in parsed_list:
                        is_serv = item.get('mac') == 'serv' or item.get('device_type') == 'serv'
                        target_device_id = item.get('target_device_id') or resp.device_id
                        device = db.get_device_by_id(target_device_id) if target_device_id else None

                        if is_serv:
                            responses_data.append({
                                'id': resp.id,
                                'device_id': target_device_id,
                                'device_name': device.name if device else 'Сервер',
                                'device_type': item.get('target_device_type', 'serv'),
                                'controller_name': 'Сервер',
                                'port': item.get('target_device_port', '0'),
                                'param_num': item.get('param_num', 0),
                                'command': item.get('command', ''),
                                'value': item.get('value', ''),
                                'is_server': True
                            })
                        else:
                            responses_data.append({
                                'id': resp.id,
                                'device_id': target_device_id,
                                'device_name': device.name if device else 'Неизвестно',
                                'device_type': item.get('device_type', 'Unknown'),
                                'controller_name': '',
                                'port': item.get('device_port', '0'),
                                'command': item.get('command', ''),
                                'value': item.get('value', ''),
                                'is_server': False
                            })
                else:
                    # Обычный триггер — строка exec/type/port/command/value?
                    parts = resp.resp.split('/')
                    # exec/type/port/command/value
                    device = db.get_device_by_id(resp.device_id) if resp.device_id else None
                    command = parts[3] if len(parts) > 3 else ''
                    value = parts[4] if len(parts) > 4 else ''
                    if device:
                        controller = db.get_controller_by_id(device.controller_id)
                        device_type = db.get_device_type_by_id(device.type_id)
                        responses_data.append({
                            'id': resp.id,
                            'device_id': device.id,
                            'device_name': device.name,
                            'device_type': device_type.name if device_type else 'Unknown',
                            'controller_name': controller.name if controller else 'Unknown',
                            'port': device.port,
                            'command': command,
                            'value': value,
                            'is_server': False
                        })
                    else:
                        responses_data.append({
                            'id': resp.id,
                            'device_id': None,
                            'device_name': 'Сервер',
                            'device_type': 'serv',
                            'controller_name': 'Сервер',
                            'port': '0',
                            'command': command,
                            'value': value,
                            'is_server': True
                        })

            src_controller = db.get_controller_by_id(trigger.controller_id)
            dst_controller = db.get_controller_by_id(trigger.controller_resp_id)
            result.append({
                'id': trigger.id,
                'name': trigger.name,
                'is_active': trigger.is_active if hasattr(trigger, 'is_active') else True,
                'type': 'complex' if trigger.is_scene else 'simple',
                'src_controller_id': trigger.controller_id,
                'src_controller_name': src_controller.name if src_controller else 'Unknown',
                'dst_controller_id': trigger.controller_resp_id,
                'dst_controller_name': dst_controller.name if dst_controller else 'Unknown',
                'conditions': conditions_data,
                'responses': responses_data
            })
        return jsonify(result)

    @app.route('/api/triggers', methods=['POST'])
    @handle_api_errors
    def create_trigger():
        data = request.json
        is_scene = data.get('type') == 'complex'

        trigger = Trigger(
            controller_id=data.get('src_controller_id', None),
            controller_resp_id=data.get('dst_controller_id', None),
            name=data['name'],
            is_active=True,
            is_scene=is_scene
        )
        trigger_id = db.add_trigger(trigger)
        if not trigger_id:
            return jsonify({'success': False, 'error': 'Failed to create trigger'}), 400
        save_conditions(trigger_id, data['conditions'], is_scene=is_scene)
        save_responses(trigger_id, data['responses'], is_scene=is_scene)
        trigger.id = trigger_id
        send_to_kafka(trigger_id, data, is_scene=is_scene)
        return jsonify({'success': True, 'id': trigger_id})

    @app.route('/api/triggers/<int:trigger_id>', methods=['PUT'])
    @handle_api_errors
    def update_trigger(trigger_id):
        data = request.json
        new_is_scene = data.get('type') == 'complex'
        old_trigger = db.get_trigger_by_id(trigger_id)
        old_is_scene = old_trigger.is_scene if old_trigger else False

        db.update_trig_scene(trigger_id, new_is_scene)
        db.update_trig_name(trigger_id, data['name'])
        delete_conditions(trigger_id)
        delete_responses(trigger_id)
        save_conditions(trigger_id, data['conditions'], is_scene=new_is_scene)
        save_responses(trigger_id, data['responses'], is_scene=new_is_scene)
        send_to_kafka(trigger_id, data, is_scene=new_is_scene)

        if old_is_scene != new_is_scene:
            kafka_data = {'command_type': 'DELETE', 'id': trigger_id}
            if old_is_scene:
                kafkaHandler.update_scene_table(kafka_data)
            else:
                kafkaHandler.update_trig_table(kafka_data)

        if not new_is_scene:
            if 'src_controller_id' in data and 'dst_controller_id' in data:
                with db.connection.cursor() as cur:
                    cur.execute("""
                        UPDATE triggers 
                        SET controller_id = %s, controller_resp_id = %s 
                        WHERE id = %s
                    """, (data['src_controller_id'], data['dst_controller_id'], trigger_id))
                    db.connection.commit()

        return jsonify({'success': True, 'id': trigger_id, 'type_changed': False})

    @app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_trigger(trigger_id):
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
            db.update_trig_status(trigger_id, is_active)
            if kafkaHandler:
                trigger_data = {
                    'command_type': 'UPD_STATUS',
                    'id': trigger_id,
                    'is_active': is_active
                }
                if db.get_trigger_by_id(trigger_id).is_scene:
                    kafkaHandler.update_scene_table(trigger_data)
                else:
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
            logger.error("Server device type 'serv' not found in database")
            return jsonify({'error': 'Server type not found'}), 404
        try:
            param_data = None
            if hasattr(server_type, 'param_name') and server_type.param_name:
                param_data = server_type.param_name
            elif hasattr(server_type, 'param_names') and server_type.param_names:
                param_data = server_type.param_names
            if not param_data:
                return jsonify({'error': 'Server type has no param data'}), 500
            config = json.loads(param_data) if isinstance(param_data, str) else param_data
            if 'sending_commands' in config:
                sending_commands = config.get('sending_commands', {})
            elif 'param_names' in config:
                sending_commands = config['param_names'].get('sending_commands', {})
            else:
                sending_commands = {}
            all_commands = []
            if sending_commands.get('binary'):
                for cmd in sending_commands['binary']:
                    cmd_copy = dict(cmd)
                    cmd_copy['type'] = 'binary'
                    all_commands.append(cmd_copy)
            if sending_commands.get('numeric'):
                for cmd in sending_commands['numeric']:
                    cmd_copy = dict(cmd)
                    cmd_copy['type'] = 'numeric'
                    all_commands.append(cmd_copy)
            return jsonify(all_commands)
        except Exception as e:
            logger.error(f"Error parsing server commands: {e}", exc_info=True)
            return jsonify({'error': str(e)}), 500

    @app.route('/api/triggers/<int:trigger_id>', methods=['GET'])
    @handle_api_errors
    def get_trigger(trigger_id):
        trigger = db.get_trigger_by_id(trigger_id)
        if not trigger:
            return jsonify({'error': 'Trigger not found'}), 404

        # УСЛОВИЯ
        conditions = db.get_trig_conditions_by_trigger(trigger.id)
        conditions_data = []
        if trigger.is_scene and conditions:
            try:
                parsed = json.loads(conditions[0].condition)
                if isinstance(parsed, list):
                    for item in parsed:
                        device_id = item.get('device_id')
                        device = db.get_device_by_id(device_id) if device_id else None
                        conditions_data.append({
                            'id': None,
                            'device_id': device_id,
                            'device_name': device.name if device else 'Сервер',
                            'device_type': item.get('device_type', 'unknown'),
                            'controller_id': device.controller_id if device else None,
                            'src_controller_id': device.controller_id if device else None,
                            'port': item.get('device_port', '0'),
                            'command': '',
                            'value': item.get('value', ''),
                            'compare': item.get('compare_type', 'equal'),
                            'trigger_type': 'time' if item.get('value_type') == 'time' else ('changed' if item.get('compare_type') == 'changed' else 'value'),
                            'time': int(item.get('value', 0)) if item.get('value_type') == 'time' else 0,
                            'param_num': item.get('param_num', 0),
                        })
            except Exception as e:
                logger.error(f"Error parsing scene conditions: {e}")
        else:
            for cond in conditions:
                device = db.get_device_by_id(cond.device_id)
                if device:
                    device_type = db.get_device_type_by_id(device.type_id)
                    condition_info = parse_condition_string(cond.condition)
                    conditions_data.append({
                        'id': cond.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_id': device.controller_id,
                        'src_controller_id': device.controller_id,
                        'port': device.port,
                        'command': condition_info.get('command', ''),
                        'value': condition_info.get('value', ''),
                        'compare': condition_info.get('compare', 'equal'),
                        'trigger_type': condition_info.get('trigger_type', 'value'),
                        'time': condition_info.get('time', 0),
                        'param_num': condition_info.get('param_num', 0),
                        'condition_string': cond.condition
                    })

        # ОТВЕТЫ
        responses = db.get_trig_responses_by_trigger(trigger.id)
        responses_data = []
        for resp in responses:
            parsed_list = parse_response_json(resp.resp)
            if parsed_list is not None:
                for item in parsed_list:
                    is_serv = item.get('mac') == 'serv' or item.get('device_type') == 'serv'
                    target_device_id = item.get('target_device_id') or resp.device_id
                    device = db.get_device_by_id(target_device_id) if target_device_id else None

                    if is_serv:
                        responses_data.append({
                            'id': resp.id,
                            'device_id': target_device_id,
                            'device_name': device.name if device else 'Сервер',
                            'device_type': item.get('target_device_type', 'serv'),
                            'controller_id': SERVER_ID,
                            'dst_controller_id': SERVER_ID,
                            'port': item.get('target_device_port', '0'),
                            'param_num': item.get('param_num', 0),
                            'command': item.get('command', ''),
                            'value': item.get('value', ''),
                            'action_string': resp.resp,
                            'is_server': True
                        })
                    else:
                        responses_data.append({
                            'id': resp.id,
                            'device_id': target_device_id,
                            'device_name': device.name if device else 'Неизвестно',
                            'device_type': item.get('device_type', 'Unknown'),
                            'controller_id': device.controller_id if device else None,
                            'dst_controller_id': device.controller_id if device else None,
                            'port': item.get('device_port', '0'),
                            'command': item.get('command', ''),
                            'value': item.get('value', ''),
                            'action_string': resp.resp,
                            'is_server': False
                        })
            else:
                parts = resp.resp.split('/')
                device = db.get_device_by_id(resp.device_id)
                # exec/type/port/command/value
                command = parts[3] if len(parts) > 3 else ''
                value = parts[4] if len(parts) > 4 else ''
                if device:
                    device_type = db.get_device_type_by_id(device.type_id)
                    responses_data.append({
                        'id': resp.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_id': device.controller_id,
                        'dst_controller_id': device.controller_id,
                        'port': device.port,
                        'command': command,
                        'value': value,
                        'action_string': resp.resp,
                        'is_server': False
                    })
                else:
                    responses_data.append({
                        'id': resp.id,
                        'device_id': resp.device_id,
                        'device_name': 'Сервер',
                        'device_type': 'serv',
                        'controller_id': SERVER_ID,
                        'dst_controller_id': SERVER_ID,
                        'port': '0',
                        'command': command,
                        'value': value,
                        'action_string': resp.resp,
                        'is_server': True
                    })

        src_controller = db.get_controller_by_id(trigger.controller_id)
        dst_controller = db.get_controller_by_id(trigger.controller_resp_id)

        return jsonify({
            'id': trigger.id,
            'name': trigger.name,
            'is_active': trigger.is_active if hasattr(trigger, 'is_active') else True,
            'type': 'complex' if trigger.is_scene else 'simple',
            'src_controller_id': trigger.controller_id,
            'src_controller_name': src_controller.name if src_controller else 'Unknown',
            'dst_controller_id': trigger.controller_resp_id,
            'dst_controller_name': dst_controller.name if dst_controller else 'Unknown',
            'conditions': conditions_data,
            'responses': responses_data
        })