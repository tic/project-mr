from flask import Blueprint, request, jsonify

from beatman.utils import load_json, save_json
from beatman.const import CONFIG_FILE

config_bp = Blueprint('config', __name__)


@config_bp.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration"""
    return jsonify(load_json(CONFIG_FILE, {}))


@config_bp.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration"""
    data = request.json
    config = load_json(CONFIG_FILE, {})
    config.update(data)
    save_json(CONFIG_FILE, config)
    return jsonify({'success': True})
