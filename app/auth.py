from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User, db, Role, Sale, Product, Category, StockLog, CartItem
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.utils.render import render_htmx
from urllib.parse import urlparse, urljoin
import logging

auth_bp = Blueprint('auth', __name__)

# Create a logger instance
logger = logging.getLogger(__name__)



def is_safe_url(target):
    """Prevent open redirects"""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    logger.info("Login route accessed.")

    if request.method == 'POST':
        # Extract JSON or form data
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        logger.info(f"Login attempt for username: {username}")
        username = username.strip().lower()

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            logger.info(f"User {username} logged in successfully.")

            # Respect 'next' parameter from query string
            next_page = request.args.get('next')
            if next_page and is_safe_url(next_page):
                redirect_url = next_page
            else:
                redirect_url = url_for('auth.admin_dashboard') if user.is_admin() else url_for('sales.sales_screen')

            if request.is_json:
                return jsonify({'success': True, 'redirect_url': redirect_url}), 200

            return redirect(redirect_url)

        logger.warning(f"Login failed for username: {username}. Invalid credentials.")
        error_field = 'username' if not user else 'password'
        if request.is_json:
            return jsonify({'success': False, 'error': error_field}), 401
        else:
            flash('Invalid username or password.', category='error')
            return redirect(url_for('auth.login'))

    # Pass along the `next` param on GET
    next_page = request.args.get('next')
    return render_template('auth/login.html', next=next_page)


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


@auth_bp.route('/logout')
@login_required
def logout():
    logger.info(f"User {current_user.username} logged out.")
    
    # Clear the session (including cart data)
    session.clear()
    
    logout_user()  # Log out the user
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home.index'))

from sqlalchemy.exc import SQLAlchemyError


def prepare_dashboard_data():
    """Helper function to prepare dashboard data (used by both routes)"""
    dashboard_data = {
        'sales_data': {
            'today': 0,
            'yesterday': 0,
            'week': 0,
            'month': 0,
            'change': 0,
            'total': 0,
            'transactions': 0,
            'chart_labels': [],
            'chart_values': []
        },
        'inventory_data': {
            'low_stock': {
                'count': 0,
                'critical': 0,
                'products': []
            },
            'total_value': 0,
            'category_count': 0,
            'product_count': 0,
            'recent_logs': 0
        },
        'system_data': {
            'users': {
                'total': 0,
                'active': 0,
                'admins': 0
            }
        },
        'transactions': {
            'recent': [],
            'payment_methods': []
        },
        'products': {
            'top_selling': [],
            'recently_added': []
        }
    }

    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    monthly_revenue = db.session.query(func.sum(Sale.total)).filter(
        func.date(Sale.date) >= month_ago
    ).scalar() or 0
    # Sales data calculations
    dashboard_data['sales_data']['today'] = db.session.query(func.sum(Sale.total)).filter(
        func.date(Sale.date) == today
    ).scalar() or 0
    
    dashboard_data['sales_data']['yesterday'] = db.session.query(func.sum(Sale.total)).filter(
        func.date(Sale.date) == yesterday
    ).scalar() or 0
    
    dashboard_data['sales_data']['week'] = db.session.query(func.sum(Sale.total)).filter(
        func.date(Sale.date) >= week_ago
    ).scalar() or 0

    dashboard_data['sales_data']['total_revenue'] = db.session.query(func.sum(Sale.total)).scalar() or 0

    
    dashboard_data['sales_data']['month'] = db.session.query(func.sum(Sale.total)).filter(
        func.date(Sale.date) >= month_ago
    ).scalar() or 0
    dashboard_data['sales_data']['transactions'] = Sale.query.count()
        
    # Calculate percentage change
    if dashboard_data['sales_data']['yesterday'] > 0:
        dashboard_data['sales_data']['change'] = (
            (dashboard_data['sales_data']['today'] - dashboard_data['sales_data']['yesterday']) / 
            dashboard_data['sales_data']['yesterday']
        ) * 100
        
    # Get sales data for chart (last 30 days)
    sales_chart_data = db.session.query(
        func.date(Sale.date).label('sale_date'),
        func.sum(Sale.total).label('daily_total')
    ).filter(
        func.date(Sale.date) >= month_ago
    ).group_by(func.date(Sale.date)).order_by(func.date(Sale.date)).all()
    
    # Format chart data - ensure we handle date objects properly
    chart_data_map = {str(row.sale_date): float(row.daily_total or 0) for row in sales_chart_data}
        
    dashboard_data['sales_data']['chart_labels'] = []
    dashboard_data['sales_data']['chart_values'] = []
        
    for n in range(30):
        day = today - timedelta(days=n)
        day_str = str(day)
        dashboard_data['sales_data']['chart_labels'].append(day.strftime('%b %d'))
        dashboard_data['sales_data']['chart_values'].append(chart_data_map.get(day_str, 0))
        
    # Reverse to show chronological order
    dashboard_data['sales_data']['chart_labels'].reverse()
    dashboard_data['sales_data']['chart_values'].reverse()
        
    # Inventory data
    low_stock_threshold = 10
    critical_stock_threshold = 5
        
    dashboard_data['inventory_data']['low_stock']['count'] = Product.query.filter(
        Product.stock <= low_stock_threshold
    ).count()
        
    dashboard_data['inventory_data']['low_stock']['critical'] = Product.query.filter(
        Product.stock <= critical_stock_threshold
    ).count()
        
    dashboard_data['inventory_data']['low_stock']['products'] = Product.query.filter(
        Product.stock <= low_stock_threshold
    ).order_by(Product.stock.asc()).limit(5).all()
        
    dashboard_data['inventory_data']['total_value'] = db.session.query(
        func.sum(Product.stock * Product.cost_price)
    ).scalar() or 0
        
    dashboard_data['inventory_data']['category_count'] = Category.query.count()
    dashboard_data['inventory_data']['product_count'] = Product.query.count()
    dashboard_data['inventory_data']['recent_logs'] = StockLog.query.filter(
        StockLog.date >= datetime.now() - timedelta(days=7)
    ).count()
        
    # System data
    dashboard_data['system_data']['users']['total'] = User.query.count()
    dashboard_data['system_data']['users']['active'] = User.query.filter(User.is_active == True).count()
    dashboard_data['system_data']['users']['admins'] = User.query.filter(User.role == Role.ADMIN).count()


        
    # Transaction data
    dashboard_data['transactions']['recent'] = Sale.query.options(
        db.joinedload(Sale.cart_items).joinedload(CartItem.product)
    ).order_by(Sale.date.desc()).limit(5).all()
        
    dashboard_data['transactions']['payment_methods'] = db.session.query(
        Sale.payment_method,
        func.count(Sale.id).label('count'),
        func.sum(Sale.total).label('total')
    ).filter(
        func.date(Sale.date) >= month_ago
    ).group_by(Sale.payment_method).all()
        
    # Product data
    dashboard_data['products']['top_selling'] = db.session.query(
        Product,
        func.sum(CartItem.quantity).label('total_quantity'),
        func.sum(CartItem.quantity * Product.selling_price).label('total_revenue')
    ).join(CartItem).join(Sale).filter(
        func.date(Sale.date) >= month_ago
    ).group_by(Product.id).order_by(
        func.sum(CartItem.quantity).desc()
    ).limit(5).all()
    dashboard_data['chart_labels'] = dashboard_data['sales_data']['chart_labels']
    dashboard_data['chart_values'] = dashboard_data['sales_data']['chart_values']

    dashboard_data['products']['recently_added'] = Product.query.order_by(
        Product.created_at.desc()).limit(3).all()
    
    return dashboard_data, monthly_revenue





@auth_bp.route('/admin_dashboard/fragment')
@login_required
def admin_dashboard_fragment():
    if not current_user.is_admin():
        return "", 403
    try:
        dashboard_data, monthly_revenue = prepare_dashboard_data()
        return render_template('admin/fragments/_admin_fragment.html',
                               **dashboard_data,
                               date=date,
                               datetime=datetime,
                               monthly_revenue=monthly_revenue)
    except Exception as e:
        logger.error(f"Error in dashboard fragment: {str(e)}", exc_info=True)
        return render_template('admin/fragments/_error.html',
                               message="Failed to load dashboard content"), 500



@auth_bp.route('/admin_dashboard')
@login_required
def admin_dashboard():
    logger.info(f"Admin dashboard accessed by user {current_user.username}")
    if not current_user.is_admin():
        flash('Access denied.', 'warning')
        return redirect(url_for('home.index'))

    if request.headers.get("HX-Request"):
        return admin_dashboard_fragment()

    try:
        dashboard_data, monthly_revenue = prepare_dashboard_data()
        return render_template('auth/admin_dashboard.html',
                               fragment_template='admin/fragments/_admin_fragment.html',
                               **dashboard_data,
                               date=date,
                               datetime=datetime,
                               monthly_revenue=monthly_revenue)
    except Exception as e:
        logger.error(f"Error in full dashboard: {str(e)}", exc_info=True)
        flash("Error loading dashboard", "danger")
        return render_template('auth/admin_dashboard.html',
                               fragment_template='admin/fragments/_error.html',
                               dashboard_data={},
                               monthly_revenue=0,
                               date=date,
                               datetime=datetime)




@auth_bp.route('/sales_chart_data')
@login_required
def sales_chart_data():
    range = request.args.get('range', 'month')
    today = date.today()

    # Date range configuration
    range_config = {
        'week': {'days': 6, 'format': '%a %d'},
        'year': {'days': 365, 'format': '%b %Y'},
        'month': {'days': 30, 'format': '%b %d'}
    }
    
    # Default to month if invalid range provided
    config = range_config.get(range, range_config['month'])
    start_date = today - timedelta(days=config['days'])
    label_format = config['format']

    try:
        # Query sales data - ensure we get date objects
        sales_data = db.session.query(
            func.date(Sale.date).label('sale_date'),
            func.sum(Sale.total).label('daily_total')
        ).filter(
            func.date(Sale.date) >= start_date
        ).group_by(
            func.date(Sale.date)
        ).order_by(
            func.date(Sale.date)
        ).all()

        # Process data with proper date handling
        chart_labels = []
        chart_values = []
        
        for row in sales_data:
            try:
                # Handle date conversion safely
                if isinstance(row.sale_date, str):
                    date_obj = datetime.strptime(row.sale_date, '%Y-%m-%d').date()
                else:
                    date_obj = row.sale_date
                
                chart_labels.append(date_obj.strftime(label_format))
                chart_values.append(float(row.daily_total or 0))
            except (ValueError, AttributeError) as e:
                current_app.logger.error(f"Error processing row: {e}")
                continue

        return render_template(
            'reports/fragments/sales_chart.html',
            chart_labels=chart_labels,
            chart_values=chart_values
        )

    except Exception as e:
        current_app.logger.error(f"Error generating sales chart data: {e}")
        # Return empty data on error
        return render_template(
            'reports/fragments/sales_chart.html',
            chart_labels=[],
            chart_values=[]
        )



@auth_bp.route('/cashier_dashboard')
@login_required
def cashier_dashboard():
    logger.info(f"Cashier dashboard accessed by user {current_user.username}.")
    if not current_user.is_cashier():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        logger.warning(f"User {current_user.username} attempted to access cashier dashboard without permissions.")
        return redirect(url_for('home.index'))

    return render_template('sales.html')

@auth_bp.route('/user_management', methods=['GET'])
@login_required
def user_management():
    logger.info(f"User management accessed by user {current_user.username}.")
    
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        logger.warning(f"User {current_user.username} attempted to access user management without permissions.")
        return redirect(url_for('home.index'))

    users = User.query.all()

    if request.headers.get('HX-Request'):
        logger.info(f"[HTMX] Fragment request for user management by {current_user.username}")
        return render_template('auth/fragments/_user_management_fragment.html', users=users)

    return render_template(
        'auth/admin_dashboard.html',  # assuming this wraps dynamic fragments
        fragment_template='auth/fragments/_user_management_fragment.html',
        users=users
    )


@auth_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    logger.info(f"Add user route accessed by user {current_user.username}.")
    
    if not current_user.is_admin():
        logger.warning(f"Unauthorized access by {current_user.username}")
        return render_template('shared/unauthorized_fragment.html'), 403

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password')
        role = request.form.get('role')

        # Validations
        if username.isdigit():
            return render_template('auth/fragments/add_user_fragment.html', error="Username cannot be only numbers.")

        if role.upper() not in Role.__members__:
            return render_template('auth/fragments/add_user_fragment.html', error="Invalid role selected.")

        if User.query.filter_by(username=username).first():
            return render_template('auth/fragments/add_user_fragment.html', error="Username already exists.")

        # Create and save user
        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()
        logger.info(f"User {username} created successfully.")

        # Trigger a frontend redirect or refresh with HX-Redirect
        return Response(headers={"HX-Redirect": url_for('auth.user_management_fragment')})

    # GET request → return form fragment
    return render_template('auth/fragments/add_user_fragment.html')



@auth_bp.route('/add_user_fragment')
@login_required
def add_user_fragment():
    if not current_user.is_admin():
        return render_template('shared/unauthorized_fragment.html'), 403
    return render_template('auth/fragments/add_user_fragment.html')


@auth_bp.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_user(id: int):
    logger.info(f"Edit user route accessed by user {current_user.username}.")
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        logger.warning(f"User {current_user.username} attempted to access edit user without permissions.")
        return redirect(url_for('home.index'))

    user = User.query.get_or_404(id)

    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        role = request.form['role']

        if username.isdigit():
            flash('Username cannot contain only numbers.', 'danger')
            logger.warning("Invalid username attempt during edit: only numbers.")
            return render_template('auth/edit_user.html', user=user, Role=Role)

        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            logger.warning("Invalid role selected during user edit.")
            return render_template('auth/edit_user.html', user=user, Role=Role)

        if User.query.filter_by(username=username).first() and username != user.username:
            flash('Username already exists.', 'danger')
            logger.warning("Username already exists during user edit.")
            return render_template('auth/edit_user.html', user=user, Role=Role)

        user.username = username
        user.role = Role[role.upper()]
        
        db.session.commit()

        flash(f'User "{username}" updated successfully!', 'success')
        logger.info(f"User updated: {username}.")
        return redirect(url_for('auth.user_management'))

    return render_template('auth/edit_user.html', user=user, Role=Role)
