from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User, db, Role, Sale, Product
from werkzeug.security import generate_password_hash
from app import admin_required

auth_bp = Blueprint('auth', __name__)

# Route for user registration (admin only)
@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
@admin_required
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('auth.register'))

        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)  # Hash the password
        db.session.add(new_user)
        db.session.commit()

        flash(f'{role.capitalize()} "{username}" registered successfully!', 'success')
        return redirect(url_for('auth.user_management'))

    return render_template('register.html')

# Route for user login
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            
            return redirect(url_for('auth.admin_dashboard' if user.is_admin() else 'sales.sales_screen'))

        flash('Invalid username or password.', 'danger')
        return redirect(url_for('auth.login'))

    return render_template('login.html')

# Route for user logout
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('home.index'))

# Admin Dashboard route
@auth_bp.route('/admin_dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_sales = db.session.query(func.sum(Sale.total)).scalar() or 0
    total_transactions = db.session.query(func.count(Sale.id)).scalar() or 0
    total_revenue = db.session.query(func.sum(Sale.total)).scalar() or 0
    recent_sales = Sale.query.order_by(Sale.date.desc()).limit(5).all()
    low_stock_threshold = 10
    low_stock_products = Product.query.filter(Product.stock <= low_stock_threshold).all()

    return render_template('admin_dashboard.html',
                           total_sales=total_sales,
                           total_transactions=total_transactions,
                           total_revenue=total_revenue,
                           recent_sales=recent_sales,
                           low_stock_products=low_stock_products)

# Route for user management (admin only)
@auth_bp.route('/user_management', methods=['GET'])
@login_required
@admin_required
def user_management():
    users = User.query.all()
    return render_template('user_management.html', users=users)

# Route to add a new user (admin only)
@auth_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('auth.add_user'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('auth.add_user'))

        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)  # Hash the password
        db.session.add(new_user)
        db.session.commit()

        flash(f'{role.capitalize()} "{username}" added successfully!', 'success')
        return redirect(url_for('auth.user_management'))

    return render_template('add_user.html')

# Route to edit an existing user (admin only)
@auth_bp.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(id: int):
    user = User.query.get_or_404(id)

    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']

        if role.upper() not in Role.__members__:
            flash('Invalid role selected.', 'danger')
            return redirect(url_for('auth.edit_user', id=id))

        if User.query.filter(User.username == username, User.id != id).first():
            flash('Username already exists.', 'danger')
            return redirect(url_for('auth.edit_user', id=id))

        user.username = username
        user.role = Role[role.upper()]
        db.session.commit()

        flash(f'User "{username}" updated successfully!', 'success')
        return redirect(url_for('auth.user_management'))

    return render_template('edit_user.html', user=user, Role=Role)

# Route to delete a user (admin only)
@auth_bp.route('/delete_user/<int:id>', methods=['POST'])
@login_required
@admin_required
def delete_user(id: int):
    user = User.query.get_or_404(id)
    db.session.delete(user)
    db.session.commit()

    flash(f'User "{user.username}" has been deleted.', 'success')
    return redirect(url_for('auth.user_management'))
