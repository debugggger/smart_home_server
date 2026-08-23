import json
import logging
from flask import request, jsonify

from database import Scene, SceneCondition, SceneResponse

logger = logging.getLogger(__name__)


def register_scene_routes(app, db, kafka_handler=None):
    """Регистрация маршрутов для управления сложными сценариями"""

    @app.route('/api/scenes', methods=['GET'])
    def get_all_scenes():
        """Получить все сложные сценарии"""
        try:
            scenes = db.get_all_scenes()
            result = []

            all_devices = db.get_all_devices()
            devices_dict = {d.id: d for d in all_devices}

            all_types = db.get_all_device_types()
            types_dict = {t.id: t for t in all_types}

            all_controllers = db.get_all_controllers()
            controllers_dict = {c.id: c for c in all_controllers}

            for scene in scenes:
                # Получаем условия
                conditions = db.get_scene_conditions_by_scene(scene.id)
                conditions_data = []
                for cond in conditions:
                    device = devices_dict.get(cond.device_id)
                    if device:
                        device_type = types_dict.get(device.type_id)

                        if '/' in cond.condition:
                            parts = cond.condition.split('/', 1)
                            command = parts[0]
                            value = parts[1] if len(parts) > 1 else None
                        else:
                            command = cond.condition
                            value = None

                        type_display_name = None
                        if device_type and device_type.param_name:
                            try:
                                config = json.loads(device_type.param_name) if isinstance(device_type.param_name,
                                                                                           str) else device_type.param_name
                                type_display_name = config.get('display_name', device_type.name)
                            except:
                                type_display_name = device_type.name

                        controller = controllers_dict.get(device.controller_id)

                        conditions_data.append({
                            'id': cond.id,
                            'device_id': device.id,
                            'device_name': device.name,
                            'device_type_id': device.type_id,
                            'device_type_name': type_display_name or device_type.name if device_type else 'Unknown',
                            'controller_name': controller.name if controller else 'Unknown',
                            'port': device.port,
                            'command': command,
                            'value': value
                        })

                # Получаем ответы
                responses = db.get_scene_responses_by_scene(scene.id)
                responses_data = []
                for resp in responses:
                    device = devices_dict.get(resp.device_id)
                    if device:
                        device_type = types_dict.get(device.type_id)

                        if '/' in resp.resp:
                            parts = resp.resp.split('/', 1)
                            command = parts[0]
                            value = parts[1] if len(parts) > 1 else None
                        else:
                            command = resp.resp
                            value = None

                        type_display_name = None
                        if device_type and device_type.param_name:
                            try:
                                config = json.loads(device_type.param_name) if isinstance(device_type.param_name,
                                                                                           str) else device_type.param_name
                                type_display_name = config.get('display_name', device_type.name)
                            except:
                                type_display_name = device_type.name

                        controller = controllers_dict.get(device.controller_id)

                        responses_data.append({
                            'id': resp.id,
                            'device_id': device.id,
                            'device_name': device.name,
                            'device_type_id': device.type_id,
                            'device_type_name': type_display_name or device_type.name if device_type else 'Unknown',
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

        except Exception as e:
            logger.error(f"Error getting scenes: {e}")
            return jsonify({'error': str(e)}), 500

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
            if kafka_handler:
                scene_data = {
                    'scene_id': scene_id,
                    'is_active': is_active
                }
                kafka_handler.update_scene_status(scene_data)

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


