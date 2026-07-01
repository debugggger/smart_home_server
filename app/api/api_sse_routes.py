# api/api_sse_routes.py
import time
import json
import logging
import queue
from flask import Response, stream_with_context, jsonify

logger = logging.getLogger(__name__)

active_connections = []


def register_sse_routes(app, db, kafka_handler=None):
    @app.route('/api/sse/events')
    def sse_events():

        def event_stream():
            client_id = id(stream_with_context)
            logger.info(f"SSE клиент подключен: {client_id}")

            active_connections.append(client_id)

            try:
                yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'client_id': str(client_id)})}\n\n"

                notification_queue = queue.Queue()
                value_update_queue = queue.Queue()
                status_update_queue = queue.Queue()

                def notification_callback(notification):
                    try:
                        notification_queue.put_nowait(notification)
                    except queue.Full:
                        pass

                def value_update_callback(device_id, current_values):
                    try:
                        value_update_queue.put_nowait({
                            'device_id': device_id,
                            'current_values': current_values
                        })
                    except queue.Full:
                        pass

                def status_update_callback(device_id, status):
                    try:
                        status_update_queue.put_nowait({
                            'device_id': device_id,
                            'is_online': status
                        })
                    except queue.Full:
                        pass

                if kafka_handler:
                    # old_notification_callback = kafka_handler.app_api_notification_callback
                    # old_value_callback = kafka_handler.app_api_device_value_update_callback
                    # old_status_callback = kafka_handler.app_api_device_status_update_callback
                    #
                    # # Создаем комбинированные callback
                    # def combined_notification_callback(notification):
                    #     notification_callback(notification)
                    #     if old_notification_callback:
                    #         old_notification_callback(notification)
                    #
                    # def combined_value_callback(device_id, current_values):
                    #     value_update_callback(device_id, current_values)
                    #     if old_value_callback:
                    #         old_value_callback(device_id, current_values)
                    #
                    # def combined_status_callback(device_id, status):
                    #     status_update_callback(device_id, status)
                    #     if old_status_callback:
                    #         old_status_callback(device_id, status)

                    # kafka_handler.app_api_notification_callback = combined_notification_callback
                    # kafka_handler.app_api_device_value_update_callback = combined_value_callback
                    # kafka_handler.app_api_device_status_update_callback = combined_status_callback
                    kafka_handler.app_api_notification_callback = notification_callback
                    kafka_handler.app_api_device_value_update_callback = value_update_callback
                    kafka_handler.app_api_device_status_update_callback = status_update_callback

                while True:
                    try:
                        try:
                            notification = notification_queue.get(timeout=0.5)
                            yield f"event: notification\ndata: {json.dumps(notification)}\n\n"
                            continue
                        except queue.Empty:
                            pass

                        try:
                            value_update = value_update_queue.get(timeout=0.5)
                            yield f"event: device_updated\ndata: {json.dumps(value_update)}\n\n"
                            continue
                        except queue.Empty:
                            pass

                        try:
                            status_update = status_update_queue.get(timeout=0.5)
                            yield f"event: device_status_update\ndata: {json.dumps(status_update)}\n\n"
                            continue
                        except queue.Empty:
                            pass

                        yield f"event: ping\ndata: {json.dumps({'timestamp': time.time()})}\n\n"
                        time.sleep(1)

                    except queue.Empty:
                        yield f"event: ping\ndata: {json.dumps({'timestamp': time.time()})}\n\n"
                        time.sleep(1)

            except GeneratorExit:
                logger.info(f"SSE клиент отключен: {client_id}")
            finally:
                if client_id in active_connections:
                    active_connections.remove(client_id)

        return Response(
            stream_with_context(event_stream()),
            mimetype="text/event-stream",
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Access-Control-Allow-Origin': '*'
            }
        )

    @app.route('/api/sse/status', methods=['GET'])
    def sse_status():
        return jsonify({
            'active_connections': len(active_connections),
            'status': 'running'
        })

    logger.info("✅ SSE routes registered")