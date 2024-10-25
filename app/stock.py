from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import db, Product, Category, Supplier, Expense  # Include Expense model
from app import socketio

stock_bp = Blueprint('stock', __name__)

# Constants for flash messages
FLASH_ACCESS_DENIED = 'Access denied.'
FLASH_CATEGORY_EXISTS = 'Category already exists.'
FLASH_PRODUCT_EXISTS = 'Product already exists.'
FLASH_CATEGORY_CREATED = 'Category "{}" created successfully.'
FLASH_CATEGORY_UPDATED = 'Category "{}" updated successfully.'
FLASH_CATEGORY_DELETED = 'Category "{}" deleted successfully.'
FLASH_PRODUCT_ADDED = 'Product "{}" added successfully.'
FLASH_PRODUCT_UPDATED = 'Product "{}" updated successfully.'
FLASH_PRODUCT_DELETED = 'Product "{}" deleted successfully.'
FLASH_INSUFFICIENT_STOCK = 'Insufficient stock for {}.'
FLASH_STOCK_UPDATED = 'Stock for "{}" updated successfully.'

# Route to manage product categories
@stock_bp.route('/categories')
@login_required
def categories():
    categories = Category.query.all()
    return render_template('categories.html', categories=categories)

# Route to create a new category
@stock_bp.route('/categories/new', methods=['GET', 'POST'])
@login_required
def new_category():
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.categories'))

    if request.method == 'POST':
        name = request.form['name']
        if Category.query.filter_by(name=name).first():
            flash(FLASH_CATEGORY_EXISTS)
            return redirect(url_for('stock.new_category'))

        new_category = Category(name=name)
        db.session.add(new_category)
        db.session.commit()
        flash(FLASH_CATEGORY_CREATED.format(name))
        return redirect(url_for('stock.categories'))

    return render_template('new_category.html')

# Route to edit an existing category
@stock_bp.route('/categories/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_category(id: int):
    category = Category.query.get_or_404(id)

    if request.method == 'POST':
        category.name = request.form['name']
        db.session.commit()
        flash(FLASH_CATEGORY_UPDATED.format(category.name))
        return redirect(url_for('stock.categories'))

    return render_template('edit_category.html', category=category)

# Route to delete a category
@stock_bp.route('/categories/<int:id>/delete', methods=['POST'])
@login_required
def delete_category(id: int):
    category = Category.query.get_or_404(id)
    db.session.delete(category)
    db.session.commit()
    flash(FLASH_CATEGORY_DELETED.format(category.name))
    return redirect(url_for('stock.categories'))

# Route to manage products
@stock_bp.route('/products')
@login_required
def products():
    products = Product.query.all()
    return render_template('products.html', products=products)

# Route to add a new product
@stock_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
def new_product():
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    categories = Category.query.all()
    suppliers = Supplier.query.all()

    if request.method == 'POST':
        name = request.form['name']
        cost_price = request.form['cost_price']
        selling_price = request.form['selling_price']
        stock = request.form['stock']
        category_id = request.form['category']
       

        if Product.query.filter_by(name=name).first():
            flash(FLASH_PRODUCT_EXISTS)
            return redirect(url_for('stock.new_product'))

        new_product = Product(
            name=name,
            cost_price=float(cost_price),
            selling_price=float(selling_price),
            stock=int(stock),
            category_id=category_id,
          
        )
        db.session.add(new_product)
        db.session.commit()
        flash(FLASH_PRODUCT_ADDED.format(name))

        # Emit real-time stock update
        socketio.emit('stock_updated', {
            'id': new_product.id,
            'name': new_product.name,
            'stock': new_product.stock
        }, broadcast=True)

        return redirect(url_for('stock.products'))

    return render_template('new_product.html', categories=categories, suppliers=suppliers)

@stock_bp.route('/products/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_product(id: int):
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    product = Product.query.get_or_404(id)
    categories = Category.query.all()
  
    if request.method == 'POST':
        try:
            # Validate input
            name = request.form['name']
            cost_price = float(request.form['cost_price'])
            selling_price = float(request.form['selling_price'])
            stock = int(request.form['stock'])

            if selling_price < cost_price:
                flash("Selling price cannot be lower than cost price.", 'danger')
                return redirect(url_for('stock.edit_product', id=id))

            # Update product data
            product.name = name
            product.cost_price = cost_price
            product.selling_price = selling_price
            product.stock = stock
            product.category_id = request.form['category']
            

            db.session.commit()

            flash(FLASH_PRODUCT_UPDATED.format(product.name), 'success')

            # Emit real-time stock update
            socketio.emit('stock_updated', {
                'id': product.id,
                'name': product.name,
                'stock': product.stock
            }, broadcast=True)

            return redirect(url_for('stock.products'))

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred: {str(e)}", 'danger')
            return redirect(url_for('stock.edit_product', id=id))

    return render_template('edit_product.html', product=product, categories=categories, suppliers=suppliers)

@stock_bp.route('/products/<int:id>/delete', methods=['POST'])
@login_required
def delete_product(id: int):
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    product = Product.query.get_or_404(id)

    try:
        db.session.delete(product)
        db.session.commit()
        flash(FLASH_PRODUCT_DELETED.format(product.name), 'success')

        # Emit real-time stock update (stock set to 0)
        socketio.emit('stock_updated', {
            'id': product.id,
            'name': product.name,
            'stock': 0
        }, broadcast=True)

    except Exception as e:
        db.session.rollback()
        flash('An error occurred while deleting the product. Please try again.', 'danger')

    return redirect(url_for('stock.products'))



# Route for displaying the stock update page and handling updates
@stock_bp.route('/admin_update_stock', methods=['GET', 'POST'])
@login_required
def update_stock():
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    if request.method == 'POST':
        product_id = request.form['product_id']
        quantity_to_add = int(request.form['quantity'])
        total_amount = float(request.form['total_amount'])  # Total amount for stock

        product = Product.query.get_or_404(product_id)

        # Update stock
        product.stock += quantity_to_add

        # Calculate the new cost price per unit
        if quantity_to_add > 0:
            new_cost_price = total_amount / quantity_to_add
            product.cost_price = new_cost_price

        # Commit changes
        db.session.commit()

        # Log the stock addition as an expense
        new_expense = Expense(
            description=f"Stock added for {product.name}",
            amount=total_amount,  # Log total amount as expense
            category="Stock Update"
        )
        db.session.add(new_expense)
        db.session.commit()

        flash(FLASH_STOCK_UPDATED.format(product.name))

        # Emit real-time stock update
        socketio.emit('stock_updated', {
            'id': product.id,
            'name': product.name,
            'stock': product.stock,
            'cost_price': product.cost_price  # Include the updated cost price
        }, broadcast=True)

        return redirect(url_for('stock.update_stock'))

    products = Product.query.all()
    return render_template('update_stock.html', products=products)

# Route to display the update stock modal for a specific product
@stock_bp.route('/products/<int:product_id>/update_stock_modal', methods=['GET'])
@login_required
def update_stock_modal(product_id: int):
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    product = Product.query.get_or_404(product_id)
    return render_template('update_stock_modal.html', product=product)

# Route to handle stock updates from the modal form
@stock_bp.route('/products/<int:product_id>/update_stock', methods=['POST'])
@login_required
def update_stock_product(product_id: int):
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    product = Product.query.get_or_404(product_id)
    quantity_to_add = int(request.form['quantity'])
    total_amount = float(request.form['total_amount'])  # Total amount for stock

    # Update stock
    product.stock += quantity_to_add

    # Calculate the new cost price per unit
    if quantity_to_add > 0:
        new_cost_price = total_amount / quantity_to_add
        product.cost_price = new_cost_price

    # Commit changes
    db.session.commit()

    # Log the stock addition as an expense
    new_expense = Expense(
        description=f"Stock added for {product.name}",
        amount=total_amount,
        category="Stock Update"
    )
    db.session.add(new_expense)
    db.session.commit()

    flash(FLASH_PRODUCT_UPDATED.format(product.name))

    # Emit real-time stock update
    socketio.emit('stock_updated', {
        'id': product.id,
        'name': product.name,
        'stock': product.stock,
        'cost_price': product.cost_price  # Include updated cost price
    }, broadcast=True)

    return redirect(url_for('stock.update_stock'))
