from flask import Flask, redirect, url_for, flash, session, render_template, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_socketio import SocketIO
from flask_login import LoginManager
from config import Config
import logging
from logging.handlers import RotatingFileHandler
from functools import wraps

# Initialize extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
login_manager = LoginManager()

# Custom decorator to enforce login requirement
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):  # Check if user is logged in
            flash('You must be logged in to view this page.', 'warning')  # Flash message
            return redirect(url_for('auth.login'))  # Redirect to login page
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Assuming you have a way to check if the user is admin
        if not session.get('is_admin', False):  # Replace with your admin check logic
            flash('Access denied. Admins only.', 'danger')  # Flash message for access denial
            return redirect(url_for('home.index'))  # Redirect to a safe page
        return f(*args, **kwargs)
    return decorated_function

    

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

    # Security configurations
    app.secret_key = 'your_secret_key'  # Set a strong secret key
    app.config['SESSION_COOKIE_SECURE'] = True  # Only send cookies over HTTPS

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins="*")  # Modify as needed
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'  # Redirect to login if not authenticated

    # Register Blueprints
    from .auth import auth_bp
    from .stock import stock_bp
    from .sales import sales_bp
    from .home import home_bp
    from .expense import expense_bp
    from .supplier import supplier_bp

    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(stock_bp, url_prefix='/stock')
    app.register_blueprint(sales_bp, url_prefix='/sales')
    app.register_blueprint(expense_bp, url_prefix='/expense')
    app.register_blueprint(supplier_bp, url_prefix='/supplier')

    # User loader for Flask-Login
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Error handling
    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Server Error: {error}")
        return render_template('500.html'), 500  # Render a custom 500 error page

    @app.errorhandler(404)
    def not_found_error(error):
        app.logger.warning(f"404 Error: {error}, attempted URL: {request.url}")
        return render_template('404.html'), 404  # Render a custom 404 error page

    @app.template_filter('number_format')
    def number_format(value, decimals=2):
        """Format numbers to a specified number of decimal places."""
        return f"{value:,.{decimals}f}"

    return app
