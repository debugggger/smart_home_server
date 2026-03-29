import threading
import time

from dotenv import load_dotenv

from core import Core
from servMqtt import servMqtt
from db import Database

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
        core = Core(db, smqtt)
        core.start_processing()

