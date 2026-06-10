
import threading
import webbrowser
import time
import logging

from flask import Flask
from utils import get_local_ip
from database import Database

from api.api_base_routes import register_base_routes
from api.api_device_routes import register_device_routes
from api.api_controller_routes import register_controller_routes
from api.api_room_routes import register_room_routes
from api.api_trigger_routes import register_trigger_routes
from api.api_firmware_routes import register_firmware_routes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WebInterface:
    def __init__(self, host='0.0.0.0', port=5000, kafka_handler = None, auto_open_browser=True, db_instance=None):
        if host == '0.0.0.0':
            host = get_local_ip()
        self.host = host
        self.port = port
        self.auto_open_browser = auto_open_browser
        self.db = db_instance if db_instance else Database()
        self.app = None
        self.server_thread = None
        self.is_running = False
        self.kafkaHandler = kafka_handler

    def _create_app(self):
        app = Flask(__name__)
        register_base_routes(app, self.db)
        register_device_routes(app, self.db, self.kafkaHandler)
        register_controller_routes(app, self.db)
        register_room_routes(app, self.db)
        register_trigger_routes(app, self.db, self.kafkaHandler)
        register_firmware_routes(app, self.db, self.kafkaHandler)

        return app

    def _run_server(self):
        try:
            self.app = self._create_app()
            self.is_running = True
            if self.auto_open_browser:
                def open_browser():
                    time.sleep(1.5)
                    webbrowser.open(f'http://localhost:{self.port}')

                threading.Thread(target=open_browser, daemon=True).start()

            logger.info(f"Starting web interface on http://{self.host}:{self.port}")
            self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False)

        except Exception as e:
            logger.error(f"Error starting web server: {e}")
            self.is_running = False
        finally:
            self.is_running = False

    def start(self):
        if self.is_running:
            logger.warning("Web interface is already running")
            return False

        self.server_thread = threading.Thread(target=self._run_server, daemon=True)
        self.server_thread.start()

        time.sleep(0.5)

        if self.server_thread.is_alive():
            logger.info(f"✅ Web interface started successfully at http://{self.host}:{self.port}")
            return True
        else:
            logger.error("❌ Failed to start web interface")
            return False

    def stop(self):
        if not self.is_running:
            logger.warning("Web interface is not running")
            return False
        logger.info("Stopping web interface...")
        self.is_running = False
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)

        logger.info("✅ Web interface stopped")
        return True

    def is_alive(self):
        return self.is_running and self.server_thread and self.server_thread.is_alive()

    def get_url(self):
        return f"http://localhost:{self.port}"

    def set_database(self, db_instance):
        if self.is_running:
            logger.warning("Cannot change database while interface is running")
            return False

        self.db = db_instance
        logger.info("Database instance updated")
        return True

    def restart(self):
        logger.info("Restarting web interface...")
        self.stop()
        time.sleep(1)
        return self.start()