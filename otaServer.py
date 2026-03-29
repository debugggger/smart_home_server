#!/usr/bin/env python3
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import os


class CustomHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Определяем путь к файлу
        if self.path == '/firmware.bin':
            filename = 'firmware.bin'
            content_type = 'application/octet-stream'
        elif self.path == '/version.txt':
            filename = 'version.txt'
            content_type = 'text/plain'
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'File not found')
            return

        # Проверяем существование файла
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

    def log_message(self, format, *args):
        # Опционально: кастомизация логов
        print(f"{self.address_string()} - {format % args}")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return 'localhost'

def run_server():
    server_address = ('0.0.0.0', 8001)
    httpd = HTTPServer(server_address, CustomHandler)
    print(f'Сервер запущен на http://'+get_local_ip()+':8001')
    print('Доступные файлы: firmware.bin, ver.txt')
    httpd.serve_forever()


if __name__ == '__main__':
    run_server()