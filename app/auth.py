from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func  # Import func from sqlalchemy
from app.models import User, db, Role, Sale, Product
from werkzeug.security import generate_password_hash, check_password_hash

auth_bp = Blueprint('auth', __name__)

# Route for user registration (admin only)
@auth_bp.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if not current_user.is_admin():
        flash('Access denied.')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        # Ensure role is valid
        if role.upper() not in Role.__members__:
            flash('Invalid role selected.')
            return redirect(url_for('auth.register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('auth.register'))

        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f'{role.capitalize()} "{username}" registered successfully!')
        return redirect(url_for('auth.login'))

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
            flash('Logged in successfully!')
            
            # Redirect based on user role
            if user.is_admin():
                return redirect(url_for('auth.admin_dashboard'))
            elif user.is_cashier():
                return redirect(url_for('sales.sales_screen'))

        flash('Invalid username or password.')
        return redirect(url_for('auth.login'))

    return render_template('login.html')


# Route for user logout
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.')
    return redirect(url_for('home.index'))


@auth_bp.route('/admin_dashboard')
@login_required
def admin_dashboard():
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


# Example protected route for cashier dashboard
@auth_bp.route('/cashier_dashboard')
@login_required
def cashier_dashboard():
    if not current_user.is_cashier():
        flash('Access denied.')
        return redirect(url_for('auth.login'))
    return render_template('cashier_dashboard.html')



@auth_bp.route('/user_management', methods=['GET'])
@login_required
def user_management():
    if not current_user.is_admin():
        flash('Access denied.')
        return redirect(url_for('auth.login'))

    # Fetch all users from the database
    users = User.query.all()

    return render_template('user_management.html', users=users)


@auth_bp.route('/add_user', methods=['GET', 'POST'])
@login_required
def add_user():
    if not current_user.is_admin():
        flash('Access denied.')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        # Ensure role is valid
        if role.upper() not in Role.__members__:
            flash('Invalid role selected.')
            return redirect(url_for('auth.add_user'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists.')
            return redirect(url_for('auth.add_user'))

        new_user = User(username=username, role=Role[role.upper()])
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash(f'{role.capitalize()} "{username}" added successfully!')
        return redirect(url_for('auth.user_management'))

    return render_template('add_user.html')


    
@auth_bp.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_user(id: int):
    if not current_user.is_admin():
        flash('Access denied.')
        return redirect(url_for('auth.login'))

    user = User.query.get_or_404(id)

    if request.method == 'POST':
        username = request.form['username']
        role = request.form['role']

        # Ensure role is valid
        if role.upper() not in Role.__members__:
            flash('Invalid role selected.')
            return redirect(url_for('auth.edit_user', id=id))

        # Check if the username already exists (but not for the current user)
        if User.query.filter_by(username=username).first() and username != user.username:
            flash('Username already exists.')
            return redirect(url_for('auth.edit_user', id=id))

        # Update user details
        user.username = username
        user.role = Role[role.upper()]
        
        db.session.commit()

        flash(f'User "{username}" updated successfully!')
        return redirect(url_for('auth.user_management'))

    return render_template('edit_user.html', user=user, Role=Role)  # Pass Role to the template