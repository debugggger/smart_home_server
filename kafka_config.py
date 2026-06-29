import json
from kafka import KafkaProducer, KafkaConsumer
import os

TOPICS = {
    #app -> core
    'SEND_COMMAND': 'send_command',
    'LOAD_FILE': 'load_file',
    'START_UPD_CONTROLLER': 'start_upd_controller',
    'UPD_DEVICE_TABLE': 'upd_device_table',
    'UPD_TRIG_TABLE': 'upd_trig_table',
    'INIT_CONTROLLER': 'init_controller',

    #core -> app
    'UPD_VAL_DEVICE': 'upd_val_device',
}


def create_kafka_producer(bootstrap_servers='localhost:9092'):
    return KafkaProducer(
        bootstrap_servers=[bootstrap_servers],
        value_serializer=lambda x: json.dumps(x, default=str).encode('utf-8'),
        key_serializer=lambda x: x.encode('utf-8') if x else None,
        acks='all',
        retries=3,
        max_in_flight_requests_per_connection=1
    )

def create_kafka_consumer(topics, group_id, bootstrap_servers='localhost:9092'):
    return KafkaConsumer(
        *topics,
        bootstrap_servers=[bootstrap_servers],
        value_deserializer=lambda x: json.loads(x.decode('utf-8')) if x else None,
        group_id=group_id,
        auto_offset_reset='latest',
        enable_auto_commit=True
    )