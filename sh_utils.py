import os
import socket
from pathlib import Path

from dotenv import load_dotenv


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return 'localhost'

def get_parsed_addr(name: str, file):
    #env_path = Path(__file__).parent.parent / '.env'
    # env_path = '.env'
    # load_dotenv(env_path)

    bind_str = get_env_value(name, file)
    host, port_str = bind_str.rsplit(':', 1)
    return host, int(port_str)

def get_env_value(name: str, file):
    load_dotenv(file)
    return os.getenv(name)