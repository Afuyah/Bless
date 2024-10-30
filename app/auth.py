from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User, db, Role, Sale, Product
from werkzeug.security import generate_password_hash, check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Extract JSON or form data
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
        else:
            username = request.form.get('username')
            password = request.form.get('password')

        # Convert username to lowercase for case-insensitive matching
        username = username.strip().lower()

        # Query user from database
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)
            # Redirect based on user role
            redirect_url = url_for('auth.admin_dashboard') if user.is_admin() else url_for('sales.sales_screen')
            
            # For AJAX requests
            if request.is_json:
                return jsonify({'success': True, 'redirect_url': redirect_url}), 200
            return redirect(redirect_url)

        # Handle failed login (username or password error)
        error_field = 'username' if not user else 'password'
        if request.is_json:
            return jsonify({'success': False, 'error': error_field}), 401
        else:
            flash('Invalid username or password.', category='error')
            return redirect(url_for('auth.login'))

    return render_template('login.html')



@auth_bp.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        if not current_user.check_password(current_password):
            flash('Current password is incorrect.', category='error')
            return redirect(url_for('auth.change_password'))

        if new_password != confirm_password:
            flash('New passwords do not match.', category='error')
            return redirect(url_for('auth.change_password'))

        # Optional: Add password strength validation here

        current_user.set_password(new_password)
        db.session.commit()
        flash('Your password has been updated successfully!', category='success')
        return redirect(url_for('auth.admin_dashboard' if current_user.is_admin() else 'auth.cashier_dashboard'))

    return render_template('change_password.html')



# Route for user logout
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('home.index'))


@auth_bp.route('/admin_dashboard')
@login_required
def admin_dashboard():
    # Check if the current user is an admin
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        return redirect(url_for('home.index'))  # Redirect to an appropriate page

    # Total sales and revenue
    total_sales = db.session.query(func.sum(Sale.total)).scalar() or 0
    total_transactions = db.session.query(func.count(Sale.id)).scalar() or 0
    total_revenue = db.session.query(func.sum(Sale.total)).scalar() or 0

    # Recent sales (last 5 sales)
    recent_sales = Sale.query.order_by(Sale.date.desc()).limit(5).all()

    # Low stock products (where stock is less than or equal to a threshold, e.g., 10)
    low_stock_threshold = 10
    low_stock_products = Product.query.filter(Product.stock <= low_stock_threshold).all()

    return render_template(
        'admin_dashboard.html',
        total_sales=total_sales,
        total_transactions=total_transactions,
        total_revenue=total_revenue,
        recent_sales=recent_sales,
        low_stock_products=low_stock_products
    )


@auth_bp.route('/cashier_dashboard')
@login_required
def cashier_dashboard():
    # Check if the current user is a cashier
    if not current_user.is_cashier():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        return redirect(url_for('home.index'))  # Redirect to an appropriate page

    return render_template('sales.html')


@auth_bp.route('/user_management', methods=['GET'])
@login_required
def user_management():
    # Check if the current user is an admin
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        return redirect(url_for('home.index'))  # Redirect to an appropriate page

    # Fetch all users from the database
    users = User.query.all()

    return render_template('user_management.html', users=users)



@auth_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        return redirect(url_for('home.index'))

    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        password = request.form['password']
        role = request.form['role']

        # Check if username is only numbers
        if username.isdigit():
            flash('Username cannot contain only numbers.', 'danger')
            return render_template('add_user.html')

        # Ensure role is valid
        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            return render_template('add_user.html')

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return render_template('add_user.html')

        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f'{role.capitalize()} "{username}" added successfully!', 'success')
        return redirect(url_for('auth.user_management'))

    return render_template('add_user.html')


@auth_bp.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_user(id: int):
    if not current_user.is_admin():
        flash('Access denied. You do not have permission to access this page.', 'warning')
        return redirect(url_for('home.index'))

    user = User.query.get_or_404(id)

    if request.method == 'POST':
        username = request.form['username'].strip().lower()
        role = request.form['role']

        # Check if username is only numbers
        if username.isdigit():
            flash('Username cannot contain only numbers.', 'danger')
            return render_template('edit_user.html', user=user, Role=Role)

        # Ensure role is valid
        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            return render_template('edit_user.html', user=user, Role=Role)

        # Check if the username already exists (but not for the current user)
        if User.query.filter_by(username=username).first() and username != user.username:
            flash('Username already exists.', 'danger')
            return render_template('edit_user.html', user=user, Role=Role)

        # Update user details
        user.username = username
        user.role = Role[role.upper()]
        
        db.session.commit()

        flash(f'User "{username}" updated successfully!', 'success')
        return redirect(url_for('auth.user_management'))

    return render_template('edit_user.html', user=user, Role=Role)

