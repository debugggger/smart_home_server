import socket
import sys
import time
from pathlib import Path

from core_app import Core
from kafkaHandler import CoreKafkaHandler

from otaServer import OTAServer
from servMqtt import servMqtt
from database import Database
from sh_utils import get_parsed_addr, get_env_value

if __name__ == '__main__':
    env_file = Path(__file__).parent.parent / '.env'
    if '--docker' in sys.argv:
        env_file = Path(__file__).parent.parent / '.envDocker'

    db = Database(host=get_env_value('CORE_DB_HOST', env_file), port=get_env_value('CORE_DB_PORT', env_file),
                  name=get_env_value('CORE_DB_NAME', env_file), user=get_env_value('CORE_DB_USER', env_file),
                  password=get_env_value('CORE_DB_PASSWORD', env_file))

    host, port = get_parsed_addr('ADDR_MQTT', env_file)
    if host == 'localhost':
        host = socket.gethostbyname(socket.gethostname())
    smqtt = servMqtt(host=host, port=port)

    smqtt.start()
    trying = 0
    while not smqtt.connected:
        if trying >= 10:
            print("Mqtt not connected")
            break
        time.sleep(1)

    if smqtt.connected:

        host, port = get_parsed_addr('ADDR_OTA', env_file)
        otaServ = OTAServer(host=host, port=port)

        kafka_handler = CoreKafkaHandler(
            db=db,
            mqtt_client=smqtt,
            ota_server=otaServ,
            bootstrap_servers=get_env_value('ADDR_KAFKA', env_file)
        )

        core = Core(db, smqtt, otaServ, kafka_handler)

        kafka_handler.start()
        core.start_processing()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")

