import subprocess
import paho.mqtt.client as mqtt
import os
import queue
import time
import threading

from utils import get_local_ip


class servMqtt:
    def __init__(self):
        self.client = mqtt.Client()
        self.broker_address = "localhost"
        self.port = 1883
        self.message_queue = queue.Queue()
        self.message_callback = None
        self.connected = False
        self.mosquittoThread = None
        self.clientThread = None

    def start(self):
        self.mosquittoThread = threading.Thread(target=self.startBroker)
        self.mosquittoThread.start()
        time.sleep(0.1)
        self.clientThread = threading.Thread(target=self.startClient)
        self.clientThread.start()

    def on_connect(self, client, userdata, flags, rc):
        print("Соединение установлено с кодом результата: " + str(rc))
        if rc == 0:
            self.connected = True
            client.subscribe("serv/#")
            #client.subscribe("#")
        else:
            print(f"Ошибка подключения: {rc}")

    def on_message(self, client, userdata, message):
        try:
            print("=" * 50)
            print(f"🔔 ПОЛУЧЕНО СООБЩЕНИЕ!")
            print(f"   Топик: {message.topic}")
            print(f"   QoS: {message.qos}")
            print(f"   Retain: {message.retain}")
            print(f"   Длина payload: {len(message.payload)}")

            payload = message.payload.decode()
            print(f"   Сообщение: {payload}")
            print("=" * 50)

            self.message_queue.put({
                'topic': message.topic,
                'payload': payload,
                'timestamp': time.time()
            })
            #
            # if self.message_callback:
            #     self.message_callback(message.topic, payload)

        except Exception as e:
            print(f"Ошибка обработки сообщения: {e}")
            import traceback
            traceback.print_exc()

    def publish(self, topic, message, qos=0, retain=False):
        """Отправка сообщения в MQTT"""
        if self.connected:
            try:
                result = self.client.publish(topic, message, qos=qos, retain=retain)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    print(f"Сообщение отправлено: топик='{topic}', сообщение='{message}'")
                    return True
                else:
                    print(f"Ошибка отправки сообщения: {result.rc}")
                    return False
            except Exception as e:
                print(f"Исключение при отправке: {e}")
                return False
        else:
            print("Клиент не подключен к брокеру")
            return False

    def get_message(self, block=False, timeout=None):

        try:
            return self.message_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def set_message_callback(self, callback):
        """Установить callback функцию для обработки сообщений"""
        self.message_callback = callback

    def startBroker(self):
        current_directory = os.path.dirname(os.path.realpath(__file__))
        mosquitto_directory = os.path.join(current_directory, "mosquitto")
        os.chdir(mosquitto_directory)
        os.system('cmd /k "mosquitto -v -c conf.conf"')
        os.chdir(current_directory)
        self.broker_address = get_local_ip()

    def startClient(self):
        try:
            self.client = mqtt.Client()
            self.client.on_connect = self.on_connect
            self.client.on_message = self.on_message
            self.client.connect(self.broker_address, self.port, 60)
            self.client.loop_forever()
        except Exception as e:
            print(f"Ошибка при запуске клиента: {e}")

    def disconnect(self):
        """Отключение от брокера"""
        if self.client:
            self.client.disconnect()
            self.connected = False
            print("Отключено от брокера")