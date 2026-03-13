from flask import Flask, render_template

from beatman.logger import logger
from beatman.const import BASE_DIR
from beatman.downloads import downloads_bp
from beatman.config import config_bp
from beatman.browse import browse_bp

app = Flask(__name__)

# Register blueprints
app.register_blueprint(downloads_bp)
app.register_blueprint(config_bp)
app.register_blueprint(browse_bp)

logger.info(BASE_DIR)


@app.route('/')
def index():
    """Serve the main UI"""
    return render_template('index.html')
