import time

from dotenv import load_dotenv

#import db_service
from app import WebInterface
from core import Core
from servMqtt import servMqtt
from database import Database, Room, Controller, DeviceType, Device

if __name__ == '__main__':
    load_dotenv()

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
        port_core = 5001
        core = Core(db, smqtt)
        core.start_processing(port=port_core)


        web_interface = WebInterface(
            port=5000,
            port_core=port_core,
            auto_open_browser=False,
            db_instance=db
        )

        web_interface.start()


        #core.parse("serv", "40:91:51:51:97:3A/init")

        #core.parse("serv", "8C:AA:B5:59:AC:A0/init")


        #core.parse("serv", "40:91:51:51:97:3A/trig")

        #core.parse("serv", "8C:AA:B5:59:AC:A0/trig")

        #core.start_update_controllers({"ALLESP"})
