import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from kafkaHandler import AppKafkaHandler
from sh_utils import get_env_value, get_parsed_addr
from web_app import WebInterface
from database import Database

if __name__ == '__main__':

    env_file = Path(__file__).parent.parent / '.env'
    if '--docker' in sys.argv:
        env_file = Path(__file__).parent.parent / '.envDocker'

    db = Database(host=get_env_value('APP_DB_HOST', env_file), port=get_env_value('APP_DB_PORT', env_file),
                  name=get_env_value('APP_DB_NAME', env_file), user=get_env_value('APP_DB_USER', env_file),
                  password=get_env_value('APP_DB_PASSWORD', env_file))

    kafka_handler = AppKafkaHandler(db=db, bootstrap_servers=get_env_value('ADDR_KAFKA', env_file))

    host, port = get_parsed_addr('ADDR_WEB', env_file)
    web_interface = WebInterface(
                kafka_handler=kafka_handler,
                auto_open_browser=False,
                db_instance=db,
                host=host,
                port=port
            )

    web_interface.start()
    kafka_handler.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
