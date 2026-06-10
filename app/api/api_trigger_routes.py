import logging
from flask import request, jsonify

from .api_utils import handle_api_errors
from app.database import TrigResponse

logger = logging.getLogger(__name__)


def register_trigger_routes(app, db, kafkaHandler):
    @app.route('/api/triggers', methods=['GET'])
    @handle_api_errors
    def get_all_triggers():
        triggers = db.get_all_triggers()
        result = []

        for trigger in triggers:
            conditions = db.get_trig_conditions_by_trigger(trigger.id)
            conditions_data = []
            for cond in conditions:
                device = db.get_device_by_id(cond.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = cond.condition.split('/')
                    command = parts[0]
                    value = parts[1] if len(parts) > 1 else None

                    conditions_data.append({
                        'id': cond.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })

            responses = db.get_trig_responses_by_trigger(trigger.id)
            responses_data = []
            for resp in responses:
                device = db.get_device_by_id(resp.device_id)
                if device:
                    controller = db.get_controller_by_id(device.controller_id)
                    device_type = db.get_device_type_by_id(device.type_id)
                    parts = resp.resp.split('/')
                    command = parts[0]
                    value = parts[1] if len(parts) > 1 else None

                    responses_data.append({
                        'id': resp.id,
                        'device_id': device.id,
                        'device_name': device.name,
                        'device_type': device_type.name if device_type else 'Unknown',
                        'controller_name': controller.name if controller else 'Unknown',
                        'port': device.port,
                        'command': command,
                        'value': value
                    })

            src_controller = db.get_controller_by_id(trigger.controller_id)
            dst_controller = db.get_controller_by_id(trigger.controller_resp_id)

            result.append({
                'id': trigger.id,
                'name': trigger.name,
                'src_controller_id': trigger.controller_id,
                'src_controller_name': src_controller.name if src_controller else 'Unknown',
                'dst_controller_id': trigger.controller_resp_id,
                'dst_controller_name': dst_controller.name if dst_controller else 'Unknown',
                'conditions': conditions_data,
                'responses': responses_data
            })

        return jsonify(result)


    @app.route('/api/triggers', methods=['POST'])
    @handle_api_errors
    def create_trigger():
        from app.database import Trigger, TrigCondition, TrigResponse

        data = request.json

        trigger = Trigger(
            controller_id=data['src_controller_id'],
            controller_resp_id=data['dst_controller_id'],
            name=data['name']
        )
        trigger_id = db.add_trigger(trigger)
        trigger.id = trigger_id

        if not trigger_id:
            return jsonify({'success': False, 'error': 'Failed to create trigger'}), 400


        for condition in data['conditions']:
            cond_obj = TrigCondition(
                device_id=condition['device_id'],
                condition=f"{condition['command']}/{condition.get('value', '')}",
                trigger_id=trigger_id
            )
            db.add_trig_condition(cond_obj)

        for response in data['responses']:
            if response.get('value') and response['value'] != '':
                resp_str = f"{response['command']}/{response['value']}"
            else:
                resp_str = response['command']

            resp_obj = TrigResponse(
                device_id=response['device_id'],
                resp=resp_str,
                trigger_id=trigger_id
            )
            db.add_trig_response(resp_obj)


        data_for_trig = get_trig_data_for_core(trigger)

        if data_for_trig is not None:
            success, offset = kafkaHandler.update_device_table(data_for_trig)
            if success:
                return jsonify({'success': True, 'id': trigger_id})
        else:
            return jsonify({'success': False}), 400



        # for response in data['responses']:
        #     resp_obj = TrigResponse(
        #         device_id=response['device_id'],
        #         resp=f"{response['command']}/{response.get('value', '')}",
        #         trigger_id=trigger_id
        #     )
        #     db.add_trig_response(resp_obj)

        return jsonify({'success': True, 'id': trigger_id})

    @app.route('/api/triggers/<int:trigger_id>', methods=['DELETE'])
    @handle_api_errors
    def delete_trigger(trigger_id):
        conditions = db.get_trig_conditions_by_trigger(trigger_id)
        for cond in conditions:
            db.delete_trig_condition(cond.id)

        responses = db.get_trig_responses_by_trigger(trigger_id)
        for resp in responses:
            db.delete_trig_response(resp.id)

        db.delete_trigger(trigger_id)
        return jsonify({'success': True})

    @app.route('/api/triggers/<int:trigger_id>', methods=['PUT'])
    @handle_api_errors
    def update_trigger(trigger_id):
        data = request.json

        with db.connection.cursor() as cur:
            cur.execute("UPDATE triggers SET name = %s WHERE id = %s",
                        (data['name'], trigger_id))
            db.connection.commit()

        conditions = db.get_trig_conditions_by_trigger(trigger_id)
        for cond in conditions:
            db.delete_trig_condition(cond.id)

        responses = db.get_trig_responses_by_trigger(trigger_id)
        for resp in responses:
            db.delete_trig_response(resp.id)

        for condition in data['conditions']:
            from app.database import TrigCondition
            cond_obj = TrigCondition(
                device_id=condition['device_id'],
                condition=f"{condition['command']}/{condition.get('value', '')}",
                trigger_id=trigger_id
            )
            db.add_trig_condition(cond_obj)

        for response in data['responses']:
            if response.get('value') and response['value'] != '':
                resp_str = f"{response['command']}/{response['value']}"
            else:
                resp_str = response['command']

            resp_obj = TrigResponse(
                device_id=response['device_id'],
                resp=resp_str,
                trigger_id=trigger_id
            )
            db.add_trig_response(resp_obj)

        trigger = db.get_trigger_by_id(trigger_id)

        data_for_trig = get_trig_data_for_core(trigger)

        if data_for_trig is not None:
            success, offset = kafkaHandler.update_device_table(data_for_trig)
            if success:
                return jsonify({'success': True, 'id': trigger_id})
        else:
            return jsonify({'success': False}), 400

        # for response in data['responses']:
        #     from database import TrigResponse
        #     resp_obj = TrigResponse(
        #         device_id=response['device_id'],
        #         resp=f"{response['command']}/{response.get('value', '')}",
        #         trigger_id=trigger_id
        #     )
        #     db.add_trig_response(resp_obj)

        return jsonify({'success': True})


    def get_trig_data_for_core(trigger):

        req_parts = []
        condCount = 0

        trigConditions = db.get_trig_conditions_by_trigger(trigger.id)
        for cond in trigConditions:
            if condCount > 0:
                req_parts.append("and")
            device = db.get_device_by_id(cond.device_id)
            req_parts.append(db.get_device_type_by_id(device.type_id).name)
            if device.port:
                req_parts.append(device.port)
            req_parts.append(cond.condition)
            condCount += 1

        req_parts.append("do")
        req_parts.append(db.get_controller_by_id(trigger.controller_resp_id).mac)
        trigResps = db.get_trig_responses_by_trigger(trigger.id)

        for resp in trigResps:
            device = db.get_device_by_id(resp.device_id)
            req_parts.append(db.get_device_type_by_id(device.type_id).name)
            if device.port:
                req_parts.append(device.port)
            req_parts.append(resp.resp)

        req = "/".join(req_parts)


        trig_data_for_core = {
            'id': trigger.id,
            'controller_mac': "",
            'trig': req
        }
        return trig_data_for_core