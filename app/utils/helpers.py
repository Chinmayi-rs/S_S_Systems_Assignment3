from flask import jsonify


def json_error(message, status):
    return jsonify({'error': message}), status


def validate_required_fields(data, required_fields):
    if not isinstance(data, dict):
        return False, 'Request body must be a JSON object'
    missing = [field for field in required_fields if data.get(field) in (None, '')]
    if missing:
        return False, 'Missing required fields: ' + ', '.join(missing)
    return True, None
