#import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

from utils import get_local_ip


class CustomHandler(BaseHTTPRequestHandler):

    @classmethod
    def configure(cls, file_mapping):
        cls.file_mapping = file_mapping
        print(f"[CONFIGURE] Handler class configured with: {list(file_mapping.keys()) if file_mapping else 'EMPTY'}")

    def do_GET(self):

        if self.path in self.file_mapping:
            filename = self.file_mapping[self.path]['filename']
            content_type = self.file_mapping[self.path]['content_type']
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'File not found')
            return

        if not os.path.exists(filename):
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'File not found')
            return

        # Отправляем файл
        self.send_response(200)
        self.send_header('Content-type', content_type)
        self.end_headers()

        with open(filename, 'rb') as f:
            self.wfile.write(f.read())


class OTAServer:
    def __init__(self, port=8001, host=None, file_mapping=None):
        self.port = port
        self.host = host if host else get_local_ip()
        self.server = None
        self.server_thread = None
        self.is_running = False
        self.file_mapping = file_mapping or {}


    def start(self):
        if self.is_running:
            print("Сервер обновлений уже запущен")
            return

        try:
            handler_class = type('CustomHandler', (CustomHandler,), {})
            handler_class.configure(self.file_mapping)
            self.server = HTTPServer((self.host, self.port), handler_class)
            self.is_running = True

            self.server_thread = threading.Thread(target=self._serve_forever, daemon=True)
            self.server_thread.start()

            print(f'Сервер обновлений запущен на http://{self.host}:{self.port}')

        except Exception as e:
            print(f"Ошибка при запуске сервера обновлений: {e}")
            self.is_running = False

    def _serve_forever(self):
        try:
            self.server.serve_forever()
        except Exception as e:
            if self.is_running:
                print(f"Ошибка сервера обновлений: {e}")

    def stop(self):
        if not self.is_running:
            print("Сервер обновлений не запущен")
            return

        self.is_running = False

        if self.server:
            self.server.shutdown()
            self.server.server_close()

        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)

        print("Сервер обновлений остановлен")

    def restart(self):
        self.stop()
        self.start()

    def get_url(self):
        return f"http://{self.host}:{self.port}"

    def add_file(self, url_path, filename, content_type='application/octet-stream'):
        self.file_mapping[url_path] = {
            'filename': filename,
            'content_type': content_type
        }
        if self.server:
            self.server.file_mapping = self.file_mapping
        print(f"Добавлен файл: {url_path} -> {filename} ({content_type})")

    def add_binary_file(self, url_path, filename):
        self.add_file(url_path, filename, 'application/octet-stream')

    def add_text_file(self, url_path, filename):
        self.add_file(url_path, filename, 'text/plain')


