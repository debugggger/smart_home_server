import time

from dotenv import load_dotenv

import db_service
from core import Core
from servMqtt import servMqtt
from database import Database, Room, Controller, DeviceType, Device

if __name__ == '__main__':
    load_dotenv()

    db = Database()
    db_service.init_db(db)


    smqtt = servMqtt()
    smqtt.start()
    trying = 0
    while not smqtt.connected:
        if trying >= 10:
            print("Mqtt not connected")
            break
        time.sleep(1)

    if smqtt.connected:
        core = Core(db, smqtt)
        core.start_processing()

        #core.parse("serv", "40:91:51:51:97:3A/init")
        core.parse("serv", "8C:AA:B5:59:AC:A0/init")

        #core.start_update_controllers({"ALLESP"})
