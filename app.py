# web_interface.py
import threading
import webbrowser
from flask import Flask, render_template, request, jsonify
from database import Database, Room, Controller, Device, DeviceType, Trigger, TrigCondition, TrigResponse
import time
import logging
import json

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebInterface:
    """Класс для управления веб-интерфейсом умного дома в отдельном потоке"""

    def __init__(self, host='0.0.0.0', port=5000, auto_open_browser=True, db_instance=None):
        """
        Инициализация веб-интерфейса

        Args:
            host: хост для запуска (по умолчанию '0.0.0.0')
            port: порт для запуска (по умолчанию 5000)
            auto_open_browser: автоматически открывать браузер (по умолчанию True)
            db_instance: экземпляр Database (если None - создаст новый)
        """
        self.host = host
        self.port = port
        self.auto_open_browser = auto_open_browser
        self.db = db_instance if db_instance else Database()
        self.app = None
        self.server_thread = None
        self.is_running = False

    def _create_app(self):
        """Создание Flask приложения со всеми маршрутами"""
        app = Flask(__name__)

        # ============= ОСНОВНЫЕ МАРШРУТЫ =============

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
            return jsonify([{'id': t.id, 'name': t.name, 'description': t.description} for t in types])

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
                    'params': d.params
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
                    'params': device.params
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

        # ============= СТАТУС И ДОПОЛНИТЕЛЬНЫЕ ЭНДПОИНТЫ =============

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