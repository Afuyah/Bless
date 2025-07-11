import logging
from flask import Flask, render_template, request, g, abort, session, current_app
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from flask_migrate import Migrate
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO
from flask_caching import Cache
from flask_wtf import CSRFProtect
from logging.handlers import RotatingFileHandler
from functools import wraps
from datetime import datetime
import pytz
from config import Config

# App extensions
db = SQLAlchemy()
migrate = Migrate()
socketio = SocketIO()
login_manager = LoginManager()
cache = Cache()
csrf = CSRFProtect()

# -----------------------
# Access Control Helpers
# -----------------------
from .models import User, Shop
def role_required(*roles):
    def wrapper(view_func):
        @wraps(view_func)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view_func(*args, **kwargs)
        return decorated_view
    return wrapper

def shop_access_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        from flask import current_app

        if not current_user.is_authenticated:
            return login_manager.unauthorized()

        shop_id = kwargs.get('shop_id')
        if not shop_id:
            abort(400, "Missing shop_id in route")

        shop = Shop.query.get_or_404(shop_id)

        if current_user.is_tenant():
            if shop.business_id != current_user.business_id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Tenant {current_user.username} tried to access shop {shop_id} not in their business."
                )
                abort(403, "You don't have access to this shop.")
        elif current_user.is_admin():
            if current_user.shop_id != shop.id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Admin {current_user.username} tried to access shop {shop_id} not assigned to them."
                )
                abort(403, "Admin is not assigned to this shop.")
        elif current_user.is_cashier():
            if current_user.shop_id != shop.id:
                current_app.logger.warning(
                    f"[ACCESS DENIED] Cashier {current_user.username} tried to access shop {shop_id} not assigned to them."
                )
                abort(403, "Cashier is not assigned to this shop.")
        else:
            current_app.logger.warning(
                f"[ACCESS DENIED] Unauthorized role {current_user.role} tried to access shop {shop_id}."
            )
            abort(403, "Unauthorized role.")

        g.current_shop = shop
        return view_func(*args, **kwargs)
    return wrapped



def business_access_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        business_id = kwargs.get('business_id')
        if not business_id:
            abort(400, "Missing business_id in route")

        if not current_user.is_tenant():
            abort(403, "Only tenants can access business-level views")

        if current_user.business_id != business_id:
            abort(403, "Access denied for this business")

        return view_func(*args, **kwargs)
    return wrapped


# -----------------------
# App Factory
# -----------------------

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

   
    # -----------------------
    # Secure Config
    # -----------------------
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['TIME_ZONE'] = 'Africa/Nairobi'

    # -----------------------
    # Logging Setup
    # -----------------------
    if not app.debug:
        handler = RotatingFileHandler('app.log', maxBytes=10240, backupCount=10)
        handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.info('Application startup')

    # -----------------------
    # Initialize Extensions
    # -----------------------
    db.init_app(app)
    migrate.init_app(app, db)
    socketio.init_app(app, cors_allowed_origins=['https://yourdomain.com'])
    login_manager.init_app(app)
    cache.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'

    # -----------------------
    # Load User
    # -----------------------
    

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # -----------------------
    # Global Context Processor
    # -----------------------
    @app.before_request
    def set_tenant_context():
        g.business = None
        g.shop = None

        if current_user.is_authenticated:
            g.business = current_user.business
            g.shop = current_user.shop

            # Try to extract shop_id from URL and store it in session
            path_parts = request.path.strip('/').split('/')
            if 'shops' in path_parts:
                try:
                    shop_index = path_parts.index('shops') + 1
                    shop_id = int(path_parts[shop_index])
                    session['shop_id'] = shop_id
                except (IndexError, ValueError):
                    # Invalid or missing shop ID in URL
                    pass

  

    @app.context_processor
    def inject_now():
        tz = pytz.timezone(app.config.get('TIME_ZONE', 'Africa/Nairobi'))
        return {'now': datetime.now(tz)}


    # -----------------------
    # Template Filter
    # -----------------------
    @app.template_filter('number_format')
    def number_format(value, decimals=2):
        try:
            return f"{float(value):,.{decimals}f}"
        except (TypeError, ValueError):
            return f"{0:.{decimals}f}"

    # -----------------------
    # Error Pages
    # -----------------------
    @app.errorhandler(404)
    def not_found_error(error):
        app.logger.warning(f"404 Error at {request.url}")
        return render_template('404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"500 Internal Server Error: {error}")
        return render_template('500.html'), 500

    # -----------------------
    # Utility Route
    # -----------------------
    @app.route('/current_time')
    def current_time():
        tz = pytz.timezone(app.config['TIME_ZONE'])
        now = datetime.now(tz)
        return f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}"

    
    def format_datetime(value, format='%d %b %Y, %I:%M %p'):
        """Safely format a datetime object for Jinja2 templates."""
        if isinstance(value, str):
            try:
                # Try to parse ISO 8601 string
                value = datetime.fromisoformat(value)
            except ValueError:
                return value  # fallback to original string if parsing fails

        if isinstance(value, datetime):
            return value.strftime(format)

        return value  


    app.jinja_env.filters['format_datetime'] = format_datetime    

    @app.context_processor
    def inject_globals():
        from sqlalchemy.exc import SQLAlchemyError
        shops = []
        business = None

        try:
            if current_user.is_authenticated:
                if current_user.is_tenant():
                    shops = Shop.query.filter_by(
                        business_id=current_user.business_id,
                        is_deleted=False
                    ).all()
                    business = current_user.business
                elif current_user.is_admin() and current_user.shop:
                    shops = [current_user.shop]
                    business = current_user.shop.business
        except SQLAlchemyError as e:
            db.session.rollback()  # ✅ this is crucial
            shops = []
            business = None
            current_app.logger.error(f"inject_globals failed: {e}", exc_info=True)

        return {
            'shops': shops,
            'business': business
        }



    @app.context_processor
    def inject_current_shop():
        from flask import session
        current_shop = None

        try:
            shop_id = session.get("shop_id")
            if shop_id:
                current_shop = db.session.get(Shop, shop_id)
                if current_shop and current_shop.is_deleted:
                    current_shop = None  # Don't expose deleted shops
        except SQLAlchemyError as e:
            db.session.rollback()
            logger.error(f"inject_current_shop error: {e}", exc_info=True)

        return dict(current_shop=current_shop)

    

    @app.route('/favicon.ico')
    def favicon():
        from flask import send_from_directory
        import os
        return send_from_directory(
            os.path.join(app.root_path, 'static'),
            'imagesfavicon.ico',
            mimetype='image/vnd.microsoft.icon'
        )
        
        

    # -----------------------
    # Register Blueprints
    # -----------------------
    from .auth.routes import auth_bp
    from .inventory.routes import inventory_bp
    from app.sale import sales_bp, api_bp
    from .home.routes import home_bp
    from .expense.routes import expense_bp
    from .supplier.routes import supplier_bp
    from .reports.routes import reports_bp
    from .bhapos.routes import bhapos_bp
    from .admin.routes import admin_bp
    from .price.routes import price_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(home_bp)
    app.register_blueprint(inventory_bp, url_prefix='/inventory')
    app.register_blueprint(sales_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(expense_bp, url_prefix='/expense')
    app.register_blueprint(supplier_bp, url_prefix='/supplier')
    app.register_blueprint(reports_bp, url_prefix='/reports')
    app.register_blueprint(price_bp, url_prefix='/price')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(bhapos_bp, url_prefix='/bhapos')

    return app
