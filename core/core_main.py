import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from core import Core
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

        core = Core(db, smqtt)
        core.start_processing(port=os.getenv('core_host'))

        #core.parse("serv", "40:91:51:51:97:3A/init")

