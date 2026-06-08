import time

from dotenv import load_dotenv

from app.app import WebInterface
from core import Core
from servMqtt import servMqtt
from database import Database

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

        # core.parse("serv", "FC:F5:C4:A3:26:17/init")
        # core.parse("serv", "FC:F5:C4:A3:26:17/trig")

        #core.parse("serv", "8C:AA:B5:59:AC:A0/init")
        #core.parse("serv", "8C:AA:B5:59:AC:A0/trig")
        #core.start_update_controllers({"ALLESP"})
