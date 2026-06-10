import os
import time
from pathlib import Path

from dotenv import load_dotenv

from core_app import Core
from core.kafkaHandler import CoreKafkaHandler

from core.otaServer import OTAServer
from servMqtt import servMqtt
from database import Database, Device

if __name__ == '__main__':

    db = Database()
    smqtt = servMqtt()
    smqtt.start()
    trying = 0
    while not smqtt.connected:
        if trying >= 10:
            print("Mqtt not connected")
            break
        time.sleep(1)

    if smqtt.connected:
        env_path = Path(__file__).parent.parent / '.env'
        load_dotenv(env_path)

        otaServ = OTAServer(os.getenv('ota_host'))

        core = Core(db, smqtt, otaServ)

        kafka_handler = CoreKafkaHandler(
            db=db,
            mqtt_client=smqtt,
            ota_server=otaServ
        )

        core.start_processing()
        kafka_handler.start()

        #core.parse("serv", "40:91:51:51:97:3A/init")

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")

