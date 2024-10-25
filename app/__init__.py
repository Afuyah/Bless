from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager
from config import Config
import logging
from logging.handlers import RotatingFileHandler

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
login_manager = LoginManager()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize logging
    if not app.debug:
        handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.info('Application startup')

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*")  # Modify as needed
    login_manager.init_app(app)

    # Register Blueprints
    from .auth import auth_bp
    from .stock import stock_bp
    from .sales import sales_bp
    from .home import home_bp
    from .expense import expense_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(stock_bp, url_prefix='/stock')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(expense_bp, url_prefix='/expense')

    # User loader for Flask-Login
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Error handling
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Server Error: {error}")
        return "Internal Server Error", 500

    @app.errorhandler(404)
    def not_found_error(error):
        return "Page Not Found", 404

    @app.template_filter('number_format')
    def number_format(value, decimals=2):
        return f"{value:,.{decimals}f}"

    return app
