from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app, g, Response, abort
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User,  Role, Sale, Product, Category, StockLog, CartItem, Shop, Business
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.utils.render import render_htmx
from urllib.parse import urlparse, urljoin
import logging
from app import db, csrf, role_required, shop_access_required, business_access_required

auth_bp = Blueprint('auth', __name__)

# Create a logger instance
logger = logging.getLogger(__name__)



def is_safe_url(target):
    """Prevent open redirects"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc

def _handle_login_error(message, is_json, field=None):
    if is_json:
        response = {'success': False, 'message': message}
        if field:
            response['field'] = field
        return jsonify(response), 401
    flash(message, 'error')
    return redirect(url_for('auth.login'))

def _handle_login_success(redirect_url, user, is_json):
    if is_json:
        return jsonify({
            'success': True,
            'redirect_url': redirect_url,
            'user': {
                'id': user.id,
                'username': user.username,
                'role': user.role.value
            }
        }), 200
    return redirect(redirect_url)

def _determine_redirect_url(user, next_param):
    from flask import session

    # 1. Safe "next" param
    if next_param and is_safe_url(next_param):
        return next_param

    # 2. Superadmin → Full platform
    if user.is_superadmin():
        return url_for('bhapos.superadmin_dashboard')

    # 3. Tenant → Must own a business
    elif user.is_tenant():
        business = Business.query.filter_by(id=user.business_id, is_deleted=False).first()
        if business:
            session['active_business_id'] = business.id
            return url_for('bhapos.tenant_dashboard')  # ✅ Redirect here
        abort(400, "Tenant does not own a valid business")

    # 4. Admin → Must be assigned to a shop
    elif user.is_admin():
        if user.shop_id:
            session['active_shop_id'] = user.shop_id
            return url_for('admin.admin_dashboard', shop_id=user.shop_id)
        abort(400, "Admin has no assigned shop")

    # 5. Cashier → Shop sales screen
    elif user.is_cashier():
        if user.shop_id:
            return url_for('sales.sales_screen', shop_id=user.shop_id)
        abort(400, "Cashier is not assigned to a shop")

    # 6. Fallback
    return url_for('main.home')



@csrf.exempt
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    logger.info("Login route accessed.")

    if request.method == 'POST':
        # Extract credentials
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        # Validate input
        if not username or not password:
            logger.warning("Missing username or password")
            return _handle_login_error("Username and password are required", request.is_json, field='username')

        username = username.strip().lower()
        user = User.query.filter_by(username=username).first()

        # Authentication check
        if not user or not user.check_password(password):
            logger.warning(f"Failed login attempt for {username}")
            field = 'username' if not user else 'password'
            return _handle_login_error("Invalid credentials", request.is_json, field=field)

        # Account status check
        if user.is_deleted:
            logger.warning(f"Login attempt for deleted user: {username}")
            return _handle_login_error("Account is disabled", request.is_json)

        # Log in user
        login_user(user)
        logger.info(f"User {username} logged in successfully.")

        # Determine redirect and store active_shop_id
        redirect_url = _determine_redirect_url(user, request.args.get('next'))

        return _handle_login_success(redirect_url, user, request.is_json)

    # GET login form
    next_page = request.args.get('next')
    return render_template('auth/login.html', next=next_page)


@csrf.exempt
@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    logger.info("Change password route accessed.")
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        # Validate current password
        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', category='error')
            logger.warning(f"User {current_user.username} provided incorrect current password.")
            return render_template('auth/fragments/_admin_change_password.html')

        if new_password != confirm_password:
            flash('New passwords do not match.', category='error')
            logger.warning("New password confirmation did not match.")
            return render_template('auth/fragments/_admin_change_password.html')

        if len(new_password) < 5:
            flash('New password must be at least 5 characters long.', category='error')
            logger.warning("New password length is insufficient.")
            return render_template('auth/fragments/_admin_change_password.html')

        current_user.set_password(new_password)
        db.session.commit()
        flash('Your password has been updated successfully!', category='success')
        logger.info(f"User {current_user.username} updated their password.")

        # After successful password update, redirect or return a success partial
        return render_template('auth/fragments/_admin_change_password.html')

    # For GET request, render the form fragment
    template_name = 'auth/fragments/_admin_change_password.html'
    return render_template(template_name)


@auth_bp.route('/user_management/<int:shop_id>', methods=['GET'])
@login_required
@shop_access_required 
@role_required(Role.ADMIN, Role.TENANT) 
def user_management(shop_id):
    logger.info(f"User management accessed by user {current_user.username}.")

    # Get the current shop from g (set by shop_access_required)
    shop = g.current_shop

    # Fetch users belonging only to this shop
    users = User.query.filter_by(shop_id=shop.id, is_deleted=False).all()

    if request.headers.get('HX-Request'):
        logger.info(f"[HTMX] Fragment request for user management by {current_user.username}")
        return render_template('auth/fragments/_user_management_fragment.html', users=users,)

    return render_template(
        'auth/admin_dashboard.html',
        fragment_template='auth/fragments/_user_management_fragment.html',
        users=users
    )

@csrf.exempt
@auth_bp.route('/shops/<int:shop_id>/add_user', methods=['GET', 'POST'])
@login_required
@role_required(Role.ADMIN, Role.TENANT)
@shop_access_required  # Ensures the shop belongs to the current admin or tenant
def add_user(shop_id):
    shop = g.current_shop
    logger.info(f"Add user route accessed by user {current_user.username} for shop {shop.id}.")

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password')
        role = request.form.get('role')

        # --- Validations ---
        if username.isdigit():
            return render_template('auth/fragments/add_user_fragment.html', error="Username cannot be only numbers.", shop=shop)

        if role.upper() not in Role.__members__:
            return render_template('auth/fragments/add_user_fragment.html', error="Invalid role selected.", shop=shop)

        if User.query.filter_by(username=username).first():
            return render_template('auth/fragments/add_user_fragment.html', error="Username already exists.", shop=shop)

        # --- Create new user ---
        new_user = User(
            username=username,
            role=Role[role.upper()],
            shop_id=shop.id,
            business_id=shop.business_id  # ensure scoped correctly
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"User {username} created for shop {shop.name}.")

        return Response(headers={"HX-Redirect": url_for('auth.user_management', shop_id=shop.id)})

    return render_template('auth/fragments/add_user_fragment.html', shop=shop)



@auth_bp.route('/logout')
@login_required
def logout():
    logger.info(f"User {current_user.username} logged out.")
    
    # Clear the session (including cart data)
    session.clear()
    
    logout_user()  # Log out the user
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home.index'))


@auth_bp.route('/api/auth/current-user')
@login_required
def current_user_info():
    return jsonify({
        'id': current_user.id,
        'name': current_user.username,
        
        'role': current_user.role.value
    })
