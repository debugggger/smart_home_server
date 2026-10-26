# api/api_sse_routes.py
import time
import json
import logging
import queue
import uuid
import threading
from flask import Response, stream_with_context, jsonify, request

logger = logging.getLogger(__name__)

# Реестр клиентов: client_id -> {"queue": Queue, "connected_at": float}
_clients = {}
_clients_lock = threading.Lock()


def _broadcast(event_name: str, payload: dict):
    """Разослать событие ВСЕМ подключённым клиентам."""
    message = f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
    with _clients_lock:
        dead = []
        for cid, info in _clients.items():
            try:
                info["queue"].put_nowait(message)
            except queue.Full:
                # клиент не успевает читать — отключаем его
                dead.append(cid)
        for cid in dead:
            _clients.pop(cid, None)
            logger.warning(f"SSE клиент отключён (переполнение очереди): {cid}")


def register_sse_routes(app, db, kafka_handler=None):
    # ⚠️ ВАЖНО: регистрируем ОДИН раз глобальные callback'и,
    # которые рассылают события во ВСЕ клиентские очереди.
    if kafka_handler is not None:
        kafka_handler.app_api_notification_callback = (
            lambda notification: _broadcast("notification", notification)
        )
        kafka_handler.app_api_device_value_update_callback = (
            lambda device_id, current_values: _broadcast(
                "device_updated",
                {"device_id": device_id, "current_values": current_values}
            )
        )
        kafka_handler.app_api_device_status_update_callback = (
            lambda device_id, status: _broadcast(
                "device_status_update",
                {"device_id": device_id, "is_online": status}
            )
        )

    @app.route('/api/sse/events')
    def sse_events():
        client_id = str(uuid.uuid4())
        client_queue: queue.Queue = queue.Queue(maxsize=1000)

        with _clients_lock:
            _clients[client_id] = {
                "queue": client_queue,
                "connected_at": time.time(),
            }
        logger.info(f"SSE клиент подключён: {client_id} (всего: {len(_clients)})")

        def event_stream():
            try:
                # приветственное событие
                yield (
                    f"event: connected\ndata: "
                    f"{json.dumps({'status': 'connected', 'client_id': client_id})}\n\n"
                )

                last_ping = time.time()

                while True:
                    try:
                        message = client_queue.get(timeout=1.0)
                        yield message
                    except queue.Empty:
                        # пинг раз в 15 секунд, чтобы соединение не закрывалось прокси
                        if time.time() - last_ping >= 15:
                            yield (
                                f"event: ping\ndata: "
                                f"{json.dumps({'timestamp': time.time()})}\n\n"
                            )
                            last_ping = time.time()
            except GeneratorExit:
                logger.info(f"SSE клиент отключён (GeneratorExit): {client_id}")
                raise
            except Exception as e:
                logger.error(f"SSE ошибка у клиента {client_id}: {e}")
            finally:
                with _clients_lock:
                    _clients.pop(client_id, None)
                logger.info(f"SSE клиент удалён: {client_id} (осталось: {len(_clients)})")

        return Response(
            stream_with_context(event_stream()),
            mimetype="text/event-stream",
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
                'Access-Control-Allow-Origin': '*',
            }
        )

    @app.route('/api/sse/status', methods=['GET'])
    def sse_status():
        with _clients_lock:
            ids = list(_clients.keys())
        return jsonify({
            'active_connections': len(ids),
            'clients': ids,
            'status': 'running'
        })

    logger.info("✅ SSE routes registered")