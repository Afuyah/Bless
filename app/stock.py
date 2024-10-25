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
        flash("Access denied.", "danger")
        return redirect(url_for('stock.products'))

    product = Product.query.get_or_404(id)
    categories = Category.query.all()

    if request.method == 'POST':
        try:
            # Retrieve and validate input fields
            name = request.form['name']
            selling_price = float(request.form['selling_price'])

            # Update product data
            product.name = name
            product.selling_price = selling_price
            product.category_id = request.form['category']

            db.session.commit()
            flash(f"Product '{product.name}' updated successfully.", "success")

            # Emit real-time update for product change
            socketio.emit('product_updated', {
                'id': product.id,
                'name': product.name,
                'selling_price': product.selling_price
            }, broadcast=True)

            return redirect(url_for('stock.products'))

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while updating the product: {str(e)}", "danger")
            return redirect(url_for('stock.edit_product', id=id))

    return render_template('edit_product.html', product=product, categories=categories)


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



def update_product_stock(product, quantity_to_add, total_amount):
    """Helper function to update product stock and log expenses."""
    # Update the stock with the quantity being added
    product.stock += quantity_to_add

    # Update cost price if quantity added is greater than 0
    if quantity_to_add > 0:
        new_cost_price = total_amount / quantity_to_add
        product.cost_price = new_cost_price  # Update cost price in the product

    # Log the stock addition as an expense
    new_expense = Expense(
        description=f"Stock added for {product.name}",
        amount=total_amount,
        category="Stock Update",
        quantity=quantity_to_add  # Optional: Include quantity in the expense
    )
    db.session.add(new_expense)

@stock_bp.route('/admin_update_stock', methods=['GET', 'POST'])
@login_required
def update_stock():
    if request.method == 'POST':
        product_id = request.form['productId']
        quantity_to_add = int(request.form['newStock'])
        total_amount = float(request.form['totalAmount'])

        # Validate form inputs
        if quantity_to_add <= 0:
            flash("Quantity must be a positive integer.", "error")
            return redirect(url_for('stock.update_stock'))
        if total_amount < 0:
            flash("Total amount cannot be negative.", "error")
            return redirect(url_for('stock.update_stock'))

        product = Product.query.get_or_404(product_id)

        try:
            update_product_stock(product, quantity_to_add, total_amount)
            db.session.commit()
            flash(f"Stock updated successfully for {product.name}.", "success")
            
            # Emit real-time stock update
            socketio.emit('stock_updated', {
                'id': product.id,
                'name': product.name,
                'stock': product.stock,
                'cost_price': product.cost_price
            }, broadcast=True)

        except Exception as e:
            db.session.rollback()
            flash('An error occurred while updating stock. Please try again.', "error")
            return redirect(url_for('stock.update_stock'))

        return redirect(url_for('stock.update_stock'))

    products = Product.query.all()
    return render_template('update_stock.html', products=products)

@stock_bp.route('/products/<int:product_id>/update_stock_modal', methods=['GET'])
@login_required
def update_stock_modal(product_id: int):
    product = Product.query.get_or_404(product_id)
    return render_template('update_stock_modal.html', product=product)

from sqlalchemy.exc import SQLAlchemyError

@stock_bp.route('/products/<int:product_id>/update_stock', methods=['POST'])
@login_required
def update_stock_product(product_id: int):
    product = Product.query.get_or_404(product_id)
    quantity_to_add = int(request.form['quantity'])
    total_amount = float(request.form['total_amount'])

    if quantity_to_add <= 0:
        return jsonify({'message': "Quantity must be a positive integer."}), 400
    if total_amount < 0:
        return jsonify({'message': "Total amount cannot be negative."}), 400

    try:
        update_product_stock(product, quantity_to_add, total_amount)
        db.session.commit()
        socketio.emit('stock_updated', {
            'id': product.id,
            'name': product.name,
            'stock': product.stock,
            'cost_price': product.cost_price
        }, broadcast=True)
        return jsonify({'message': f"Stock updated successfully for {product.name}."}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'message': 'Database error. Please try again.'}), 500
    except Exception as e:
        return jsonify({'message': str(e)}), 500
