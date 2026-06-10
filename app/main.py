import os
import time
from pathlib import Path

from dotenv import load_dotenv

from app.kafkaHandler import AppKafkaHandler
from web_app import WebInterface
from database import Database

if __name__ == '__main__':
    env_path = Path(__file__).parent.parent / '.env'
    load_dotenv(env_path)

    db = Database()
    kafka_handler = AppKafkaHandler(db=db)

    web_interface = WebInterface(
                port=os.getenv('app_host'),
                kafka_handler = kafka_handler,
                auto_open_browser=False,
                db_instance=db
            )


    web_interface.start()
    kafka_handler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
