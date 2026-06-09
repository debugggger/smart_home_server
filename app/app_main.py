import os
import time
from pathlib import Path

from dotenv import load_dotenv

from app import WebInterface
from database import Database

if __name__ == '__main__':
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)

    db = Database()

    web_interface = WebInterface(
                port=os.getenv('app_host'),
                port_core=os.getenv('core_host'),
                auto_open_browser=False,
                db_instance=db
            )
    web_interface.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
