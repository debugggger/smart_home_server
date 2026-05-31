# web_interface.py
import os
import tempfile
import threading
import webbrowser


import requests

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

from database import Database, Room, Controller, Device, DeviceType, Trigger, TrigCondition, TrigResponse
import time
import logging
import json

from utils import get_local_ip

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebInterface:
    def __init__(self, host='0.0.0.0', port=5000, port_core=5001, auto_open_browser=True, db_instance=None):
        if host == '0.0.0.0':
            host = get_local_ip()
        self.host = host
        self.port = port
        self.core_addr = "http://" + str(host)+":"+str(port_core)
        self.auto_open_browser = auto_open_browser
        self.db = db_instance if db_instance else Database()
        self.app = None
        self.server_thread = None
        self.is_running = False

    def _create_app(self):
        app = Flask(__name__)

        @app.route('/')
        def index():
            return render_template('index.html')

        @app.route('/rooms-page')
        def rooms_page():
            return render_template('rooms.html')

        @app.route('/controllers-page')
        def controllers_page():
            return render_template('controllers.html')

        @app.route('/devices-page')
        def devices_page():
            return render_template('devices.html')

        @app.route('/triggers-page')
        def triggers_page():
            return render_template('triggers.html')

        @app.route('/dashboard')
        def dashboard():
            return render_template('dashboard.html')

        @app.route('/firmware-update')
        def firmware_update_page():
            """Страница обновления прошивки"""
            return render_template('firmware_update.html')

        @app.route('/api/devices/all', methods=['GET'])
        def get_all_devices_with_status():
            devices = []
            all_devices = self.db.get_all_devices()

            for device in all_devices:
                controller = self.db.get_controller_by_id(device.controller_id)
                room = None
                if controller:
                    room = self.db.get_room_by_id(controller.room_id)

                device_type = self.db.get_device_type_by_id(device.type_id)

                devices.append({
                    'id': device.id,
                    'name': device.name,
                    'type': device_type.name.lower() if device_type else 'unknown',
                    'room': room.name if room else 'Без комнаты',
                    'controller': controller.name if controller else 'Unknown',
                    'port': device.port,
                    'params': json.loads(device.params) if device.params else {},
                    'status': 'online',  # Здесь нужно получать реальный статус
                    'value': None  # Здесь нужно получать реальное значение с контроллера
                })

            return jsonify(devices)

        @app.route('/api/devices/<int:device_id>/command', methods=['POST'])
        def send_device_command(device_id):
            """
            Отправить команду на устройство
            Перенаправляет запрос на /core_api/send_mqtt_command
            """
            try:
                data = request.json

                if not data:
                    return jsonify({'error': 'No JSON data provided'}), 400

                command = data.get('command')
                value = data.get('value')

                if not command:
                    return jsonify({'error': 'command is required'}), 400

                # Получаем устройство из БД
                device = self.db.get_device_by_id(device_id)
                if not device:
                    return jsonify({'success': False, 'error': 'Device not found'}), 404

                # Получаем контроллер
                controller = self.db.get_controller_by_id(device.controller_id)
                if not controller:
                    return jsonify({'success': False, 'error': 'Controller not found'}), 404

                # Формируем payload для перенаправления на core_api
                payload = {
                    'controller_mac': controller.mac,
                    'device_id': device_id,
                    'command': command
                }

                if value is not None:
                    payload['value'] = value

                # Отправляем запрос на core_api
                target_url = f"{self.core_addr}/core_api/send_mqtt_command"

                logger.info(f"Forwarding command to {target_url}: {payload}")

                response = requests.post(
                    target_url,
                    json=payload,
                    timeout=10
                )

                if response.status_code == 200:
                    result = response.json()
                    return jsonify({
                        'success': True,
                        'message': f'Command {command} sent to device {device.name}',
                        'device_id': device_id,
                        'controller_mac': controller.mac,
                        'command': command,
                        'value': value,
                        'core_response': result
                    }), 200
                else:
                    return jsonify({
                        'success': False,
                        'error': f'Core API returned status {response.status_code}',
                        'core_response': response.text
                    }), response.status_code

            except requests.exceptions.ConnectionError:
                logger.error(f"Cannot connect to core API at {self.core_addr}")
                return jsonify({'success': False, 'error': 'Cannot connect to core service'}), 503
            except requests.exceptions.Timeout:
                logger.error(f"Timeout connecting to core API at {self.core_addr}")
                return jsonify({'success': False, 'error': 'Core service timeout'}), 504
            except Exception as e:
                logger.error(f"Error in send_device_command: {e}")
                return jsonify({'success': False, 'error': str(e)}), 500

        @app.route('/api/update-controller', methods=['POST'])
        def start_update():

            try:
                data = request.json

                if not data:
                    return jsonify({'error': 'No data provided'}), 400

                topics = data.get('topics')

                if not topics:
                    return jsonify({'error': 'topics field is required'}), 400

                if isinstance(topics, list):
                    if len(topics) == 0:
                        return jsonify({'error': 'topics list is empty'}), 400

                    if "AllESP" in topics or len(topics) == 1 and topics[0] == "AllESP":
                        topics_for_mqtt = "AllESP"
                    else:
                        topics_for_mqtt = topics

                elif isinstance(topics, str):
                    # Если передан строка
                    topics_for_mqtt = topics
                else:
                    return jsonify({'error': 'topics must be list or string'}), 400

                target_url = f"{self.core_addr}/core_api/ota_start_update"
                payload = {'topics': topics_for_mqtt}

                response = requests.post(
                    target_url,
                    json=payload,
                    timeout=30,
                    headers={'Content-Type': 'application/json'}
                )

                if response.status_code == 200:
                    result = response.json()
                    return jsonify({
                        'success': True,
                        'message': f'OTA update started successfully',
                        'forwarded_to': self.core_addr,
                        'topics_sent': topics_for_mqtt,
                        'response': result
                    }), 200
                else:
                    return jsonify({
                        'error': f'OTA service returned error: {response.status_code}',
                        'details': response.text
                    }), response.status_code

            except requests.exceptions.ConnectionError:
                return jsonify({'error': f'Cannot connect to OTA service at {self.core_addr}'}), 503
            except Exception as e:
                print(f"Error in ota_start_update: {str(e)}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': str(e)}), 500

        @app.route('/api/verify-files', methods=['POST'])
        def verify_files():
            """Проверяет существование файлов на сервере"""
            try:
                data = request.json
                firmware_path = data.get('firmware_path')
                version_path = data.get('version_path')

                firmware_exists = os.path.exists(firmware_path) if firmware_path else False
                version_exists = os.path.exists(version_path) if version_path else False

                return jsonify({
                    'success': firmware_exists and version_exists,
                    'firmware_exists': firmware_exists,
                    'version_exists': version_exists
                })
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 500


        @app.route('/api/upload-firmware', methods=['POST'])
        def upload_firmware():
            try:
                if 'firmware' not in request.files or 'version' not in request.files:
                    return jsonify({'error': 'Файлы не найдены'}), 400

                firmware = request.files['firmware']
                version = request.files['version']

                temp_dir = tempfile.mkdtemp()

                firmware_filename = secure_filename(firmware.filename)
                version_filename = secure_filename(version.filename)

                firmware_path = os.path.join(temp_dir, firmware_filename)
                version_path = os.path.join(temp_dir, version_filename)

                firmware.save(firmware_path)
                version.save(version_path)

                firmware_abs_path = os.path.abspath(firmware_path)
                version_abs_path = os.path.abspath(version_path)

                target_url = f"{self.core_addr}/core_api/load_files_on_ota"
                response = requests.post(
                    target_url,
                    json={
                        'firmware_path': firmware_path,
                        'version_path': version_path
                    },
                    timeout=30
                )

                return jsonify({
                    'success': True,
                    'firmware_absolute_path': firmware_abs_path,
                    'version_absolute_path': version_abs_path
                })

            except Exception as e:
                print(f"Error: {str(e)}")
                return jsonify({'error': str(e)}), 500



        # # Эндпоинт для отправки команд на устройство
        # @app.route('/api/devices/<int:device_id>/command', methods=['POST'])
        # def send_device_command(device_id):
        #     """Отправить команду на устройство"""
        #     data = request.json
        #     command = data.get('command')
        #     params = data.get('params', {})
        #
        #     # Здесь нужно реализовать отправку команды на соответствующий контроллер
        #     logger.info(f"Sending command {command} to device {device_id} with params {params}")
        #
        #     # Имитация отправки
        #     return jsonify({'success': True, 'message': f'Command {command} sent'})

        # ============= API ДЛЯ КОМНАТ =============

        @app.route('/api/rooms', methods=['GET'])
        def get_rooms():
            """Получить все комнаты"""
            rooms = self.db.get_all_rooms()
            return jsonify([{'id': r.id, 'name': r.name} for r in rooms])

        @app.route('/api/rooms', methods=['POST'])
        def add_room():
            """Добавить комнату"""
            data = request.json
            room = Room(name=data['name'])
            room_id = self.db.add_room(room)
            return jsonify({'success': True, 'id': room_id}) if room_id else jsonify({'success': False}), 400

        @app.route('/api/rooms/<int:room_id>', methods=['DELETE'])
        def delete_room(room_id):
            """Удалить комнату"""
            self.db.delete_room(room_id)
            return jsonify({'success': True})

        # ============= API ДЛЯ КОНТРОЛЛЕРОВ =============

        @app.route('/api/controllers', methods=['GET'])
        def get_controllers():
            """Получить все контроллеры с дополнительной информацией"""
            controllers = self.db.get_all_controllers()
            result = []
            for c in controllers:
                room = self.db.get_room_by_id(c.room_id)
                devices = self.db.get_devices_by_controller(c.id)
                result.append({
                    'id': c.id,
                    'name': c.name,
                    'mac': c.mac,
                    'room_id': c.room_id,
                    'room_name': room.name if room else 'Не назначено',
                    'devices_count': len(devices)
                })
            return jsonify(result)

        @app.route('/api/controllers', methods=['POST'])
        def add_controller():
            """Добавить контроллер"""
            data = request.json
            controller = Controller(
                name=data['name'],
                mac=data['mac'],
                room_id=data['room_id']
            )
            controller_id = self.db.add_controller(controller)
            if controller_id:
                return jsonify({'success': True, 'id': controller_id})
            return jsonify({'success': False}), 400

        @app.route('/api/controllers/<int:controller_id>', methods=['PUT'])
        def update_controller(controller_id):
            """Обновить имя контроллера"""
            data = request.json
            try:
                with self.db.connection.cursor() as cur:
                    cur.execute("UPDATE controllers SET name = %s WHERE id = %s",
                                (data['name'], controller_id))
                    self.db.connection.commit()
                return jsonify({'success': True})
            except Exception as e:
                logger.error(f"Error updating controller: {e}")
                return jsonify({'success': False}), 400


        @app.route('/api/controllers/<int:controller_id>', methods=['DELETE'])
        def delete_controller(controller_id):
            """Удалить контроллер"""
            self.db.delete_controller(controller_id)
            return jsonify({'success': True})

        # ============= API ДЛЯ ТИПОВ УСТРОЙСТВ =============

        @app.route('/api/device-types', methods=['GET'])
        def get_device_types():
            """Получить все типы устройств"""
            types = self.db.get_all_device_types()
            return jsonify([{'id': t.id, 'name': t.name, 'description': t.description, 'param_names': t.param_name} for t in types])

        # ============= API ДЛЯ УСТРОЙСТВ =============

        @app.route('/api/devices', methods=['GET'])
        def get_devices():
            """Получить все устройства"""
            devices = self.db.get_all_devices()
            result = []
            for d in devices:
                controller = self.db.get_controller_by_id(d.controller_id)
                device_type = self.db.get_device_type_by_id(d.type_id)
                room = None
                if controller:
                    room = self.db.get_room_by_id(controller.room_id)

                current_values = None

                if d.current_values:
                    try:
                        current_values = json.loads(d.current_values)
                    except:
                        current_values = []

                result.append({
                    'id': d.id,
                    'name': d.name,
                    'controller_id': d.controller_id,
                    'controller_name': controller.name if controller else 'Unknown',
                    'room_name': room.name if room else 'Не назначено',
                    'type_id': d.type_id,
                    'type_name': device_type.name if device_type else 'Unknown',
                    'port': d.port,
                    'params': d.params,
                    'current_values': current_values,
                    'status': 'online'
                })
            return jsonify(result)

        @app.route('/api/devices/controller/<int:controller_id>', methods=['GET'])
        def get_devices_by_controller(controller_id):
            """Получить устройства конкретного контроллера"""
            devices = self.db.get_devices_by_controller(controller_id)
            result = []
            for d in devices:
                device_type = self.db.get_device_type_by_id(d.type_id)
                result.append({
                    'id': d.id,
                    'name': d.name,
                    'type_id': d.type_id,
                    'type_name': device_type.name if device_type else 'Unknown',
                    'port': d.port,
                    'params': d.params,
                    'current_values': d.current_values
                })
            return jsonify(result)

        @app.route('/api/devices/by-controller/<int:controller_id>', methods=['GET'])
        def get_devices_by_controller_id(controller_id):
            """Получить устройства контроллера с их типами (для сценариев)"""
            devices = self.db.get_devices_by_controller(controller_id)
            result = []
            for device in devices:
                device_type = self.db.get_device_type_by_id(device.type_id)
                result.append({
                    'id': device.id,
                    'name': device.name,
                    'type_id': device.type_id,
                    'type_name': device_type.name if device_type else 'Unknown',
                    'port': device.port,
                    'params': device.params,
                    'current_values': device.current_values
                })
            return jsonify(result)

        @app.route('/api/devices', methods=['POST'])
        def add_device():
            """Добавить устройство"""
            data = request.json
            device = Device(
                name=data['name'],
                controller_id=data['controller_id'],
                type_id=data['type_id'],
                port=data.get('port', ''),
                params=data.get('params', '{}')
            )
            device_id = self.db.add_device(device)
            if device_id:
                return jsonify({'success': True, 'id': device_id})
            return jsonify({'success': False}), 400

        @app.route('/api/devices/<int:device_id>', methods=['DELETE'])
        def delete_device(device_id):
            """Удалить устройство"""
            self.db.delete_device(device_id)
            return jsonify({'success': True})

        # ============= API ДЛЯ КОМАНД УСТРОЙСТВ =============

        @app.route('/api/device-commands/<int:device_type_id>', methods=['GET'])
        def get_device_commands(device_type_id):
            """Получить доступные команды для типа устройства"""
            device_type = self.db.get_device_type_by_id(device_type_id)
            if not device_type:
                return jsonify([])

            # Определяем команды в зависимости от типа устройства
            commands = {
                'binOut': ['toggle', 'setHigh', 'setLow'],
                'led': ['turnOn', 'turnOff', 'setColor', 'setBrightness', 'setSpeed', 'setEffect',
                        'setSoundReaction', 'setSoundWeights', 'setSoundBeatColor', 'setMicro'],
                'stepper': ['setSpeed', 'setDir', 'startInf', 'startSteps', 'stop']
            }

            # Пытаемся определить тип по имени
            type_name = device_type.name.lower()
            for key in commands:
                if key.lower() in type_name:
                    return jsonify(commands[key])

            return jsonify([])

        # ============= API ДЛЯ ТРИГГЕРОВ (СЦЕНАРИЕВ) =============

        @app.route('/api/triggers', methods=['GET'])
        def get_all_triggers():
            """Получить все триггеры с подробной информацией"""
            triggers = self.db.get_all_triggers()
            result = []

            for trigger in triggers:
                # Получаем условия
                conditions = self.db.get_trig_conditions_by_trigger(trigger.id)
                conditions_data = []
                for cond in conditions:
                    device = self.db.get_device_by_id(cond.device_id)
                    if device:
                        controller = self.db.get_controller_by_id(device.controller_id)
                        device_type = self.db.get_device_type_by_id(device.type_id)
                        # Парсим condition
                        parts = cond.condition.split('/')
                        command = parts[0]
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

                # Получаем ответы
                responses = self.db.get_trig_responses_by_trigger(trigger.id)
                responses_data = []
                for resp in responses:
                    device = self.db.get_device_by_id(resp.device_id)
                    if device:
                        controller = self.db.get_controller_by_id(device.controller_id)
                        device_type = self.db.get_device_type_by_id(device.type_id)
                        # Парсим resp
                        parts = resp.resp.split('/')
                        command = parts[0]
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

                # Получаем контроллеры
                src_controller = self.db.get_controller_by_id(trigger.controller_id)
                dst_controller = self.db.get_controller_by_id(trigger.controller_resp_id)

                result.append({
                    'id': trigger.id,
                    'name': trigger.name,
                    'src_controller_id': trigger.controller_id,
                    'src_controller_name': src_controller.name if src_controller else 'Unknown',
                    'dst_controller_id': trigger.controller_resp_id,
                    'dst_controller_name': dst_controller.name if dst_controller else 'Unknown',
                    'conditions': conditions_data,
                    'responses': responses_data
                })

            return jsonify(result)

        @app.route('/api/triggers', methods=['POST'])
        def create_trigger():
            """Создать новый триггер со всеми условиями и ответами"""
            data = request.json

            # Создаем триггер
            trigger = Trigger(
                controller_id=data['src_controller_id'],
                controller_resp_id=data['dst_controller_id'],
                name=data['name']
            )
            trigger_id = self.db.add_trigger(trigger)

            if not trigger_id:
                return jsonify({'success': False, 'error': 'Failed to create trigger'}), 400

            # Добавляем условия
            for condition in data['conditions']:
                cond_obj = TrigCondition(
                    device_id=condition['device_id'],
                    condition=f"{condition['command']}/{condition.get('value', '')}",
                    trigger_id=trigger_id
                )
                self.db.add_trig_condition(cond_obj)

            # Добавляем ответы
            for response in data['responses']:
                resp_obj = TrigResponse(
                    device_id=response['device_id'],
                    resp=f"{response['command']}/{response.get('value', '')}",
                    trigger_id=trigger_id
                )
                self.db.add_trig_response(resp_obj)

            return jsonify({'success': True, 'id': trigger_id})

        @app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
        def delete_trigger(trigger_id):
            """Удалить триггер со всеми условиями и ответами"""
            # Сначала удаляем связанные данные
            conditions = self.db.get_trig_conditions_by_trigger(trigger_id)
            for cond in conditions:
                self.db.delete_trig_condition(cond.id)

            responses = self.db.get_trig_responses_by_trigger(trigger_id)
            for resp in responses:
                self.db.delete_trig_response(resp.id)

            # Удаляем сам триггер
            self.db.delete_trigger(trigger_id)

            return jsonify({'success': True})

        @app.route('/api/triggers/<int:trigger_id>', methods=['PUT'])
        def update_trigger(trigger_id):
            """Обновить существующий триггер"""
            data = request.json

            # Обновляем триггер
            try:
                with self.db.connection.cursor() as cur:
                    cur.execute("UPDATE triggers SET name = %s WHERE id = %s",
                                (data['name'], trigger_id))
                    self.db.connection.commit()
            except Exception as e:
                return jsonify({'success': False, 'error': str(e)}), 400

            # Удаляем старые условия и ответы
            conditions = self.db.get_trig_conditions_by_trigger(trigger_id)
            for cond in conditions:
                self.db.delete_trig_condition(cond.id)

            responses = self.db.get_trig_responses_by_trigger(trigger_id)
            for resp in responses:
                self.db.delete_trig_response(resp.id)

            # Добавляем новые
            for condition in data['conditions']:
                cond_obj = TrigCondition(
                    device_id=condition['device_id'],
                    condition=f"{condition['command']}/{condition.get('value', '')}",
                    trigger_id=trigger_id
                )
                self.db.add_trig_condition(cond_obj)

            for response in data['responses']:
                resp_obj = TrigResponse(
                    device_id=response['device_id'],
                    resp=f"{response['command']}/{response.get('value', '')}",
                    trigger_id=trigger_id
                )
                self.db.add_trig_response(resp_obj)

            return jsonify({'success': True})


        @app.route('/api/status', methods=['GET'])
        def get_status():
            """Проверка статуса сервиса"""
            return jsonify({
                'status': 'running',
                'message': 'Web interface is active',
                'timestamp': time.time()
            })

        @app.route('/api/stats', methods=['GET'])
        def get_stats():
            """Получить статистику для дашборда"""
            rooms_count = len(self.db.get_all_rooms())
            controllers_count = len(self.db.get_all_controllers())
            devices_count = len(self.db.get_all_devices())
            triggers_count = len(self.db.get_all_triggers())

            return jsonify({
                'rooms': rooms_count,
                'controllers': controllers_count,
                'devices': devices_count,
                'triggers': triggers_count
            })

        return app

    def _run_server(self):
        """Запуск сервера в отдельном потоке"""
        try:
            self.app = self._create_app()
            self.is_running = True

            # Открываем браузер, если нужно
            if self.auto_open_browser:
                def open_browser():
                    time.sleep(1.5)
                    webbrowser.open(f'http://localhost:{self.port}')

                threading.Thread(target=open_browser, daemon=True).start()

            # Запускаем Flask сервер
            logger.info(f"Starting web interface on http://{self.host}:{self.port}")
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

        except Exception as e:
            logger.error(f"Error starting web server: {e}")
            self.is_running = False
        finally:
            self.is_running = False

    def start(self):
        """
        Запуск веб-интерфейса в отдельном потоке

        Returns:
            bool: True если запуск успешен
        """
        if self.is_running:
            logger.warning("Web interface is already running")
            return False



        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        # Ждем немного чтобы сервер успел запуститься
        time.sleep(0.5)

        if self.server_thread.is_alive():
            logger.info(f"✅ Web interface started successfully at http://{self.host}:{self.port}")
            return True
        else:
            logger.error("❌ Failed to start web interface")
            return False

    def stop(self):
        """
        Остановка веб-интерфейса

        Returns:
            bool: True если остановка успешна
        """
        if not self.is_running:
            logger.warning("Web interface is not running")
            return False

        logger.info("Stopping web interface...")
        self.is_running = False

        # Ждем завершения потока
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)

        logger.info("✅ Web interface stopped")
        return True

    def is_alive(self):
        """Проверка, запущен ли веб-интерфейс"""
        return self.is_running and self.server_thread and self.server_thread.is_alive()

    def get_url(self):
        """Получить URL интерфейса"""
        return f"http://localhost:{self.port}"

    def set_database(self, db_instance):
        """
        Установка нового экземпляра БД (только если интерфейс не запущен)

        Args:
            db_instance: экземпляр Database
        """
        if self.is_running:
            logger.warning("Cannot change database while interface is running")
            return False

        self.db = db_instance
        logger.info("Database instance updated")
        return True

    def restart(self):
        """
        Перезапуск веб-интерфейса

        Returns:
            bool: True если перезапуск успешен
        """
        logger.info("Restarting web interface...")
        self.stop()
        time.sleep(1)
        return self.start()