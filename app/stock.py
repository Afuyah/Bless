from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import db, Product, Category, Supplier, Expense  # Include Expense model
from app import socketio
from decimal import Decimal, InvalidOperation

import logging
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
    if not categories:
        flash('No categories found.', 'info')
    return render_template('categories.html', categories=categories)


# Route to create a new category
@stock_bp.route('/categories/new', methods=['GET', 'POST'])
@login_required
def new_category():
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.categories'))

    if request.method == 'POST':
        name = request.form.get('name').strip()
        if not name:
            flash("Category name cannot be empty.", "danger")
            return redirect(url_for('stock.new_category'))

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
        new_name = request.form['name'].strip()
        if not new_name:
            flash("Category name cannot be empty.", "danger")
            return redirect(url_for('stock.edit_category', id=id))

        if Category.query.filter_by(name=new_name).first():
            flash("Category with this name already exists.", "danger")
            return redirect(url_for('stock.edit_category', id=id))

        category.name = new_name
        db.session.commit()
        flash(FLASH_CATEGORY_UPDATED.format(category.name))
        return redirect(url_for('stock.categories'))

    return render_template('edit_category.html', category=category)


# Route to delete a category
@stock_bp.route('/categories/<int:id>/delete', methods=['POST'])
@login_required
def delete_category(id: int):
    category = Category.query.get_or_404(id)
    try:
        db.session.delete(category)
        db.session.commit()
        flash(FLASH_CATEGORY_DELETED.format(category.name))
    except Exception as e:
        db.session.rollback()
        flash(f"An error occurred while deleting the category: {str(e)}", "danger")
    return redirect(url_for('stock.categories'))


# Route to manage products
@stock_bp.route('/products', methods=['GET'])
@login_required
def products():
    search_query = request.args.get('search', '')
    products = Product.query.filter(Product.name.contains(search_query)).all()
    return render_template('products.html', products=products, search_query=search_query)


@stock_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
def new_product():
    if not current_user.is_admin():
        flash(FLASH_ACCESS_DENIED)
        return redirect(url_for('stock.products'))

    categories = Category.query.all()
    suppliers = Supplier.query.all()

    if request.method == 'POST':
        product_data = {
            'name': request.form['name'].strip(),
            'cost_price': request.form['cost_price'].strip(),
            'selling_price': request.form['selling_price'].strip(),
            'stock': request.form['stock'].strip(),
            'category_id': request.form['category'],
            'supplier_id': request.form.get('supplier'),
            'combination_size': request.form.get('combination_size', '').strip(),
            'combination_price': request.form.get('combination_price', '').strip()
        }

        # Validate and create the product
        validation_error = validate_product_data(product_data)
        if validation_error:
            flash(validation_error)
            return redirect(url_for('stock.new_product'))

        new_product = create_product(product_data)
        db.session.add(new_product)
        db.session.commit()
        flash(FLASH_PRODUCT_ADDED.format(new_product.name))

        # Emit socket update
        socketio.emit('stock_updated', {
            'id': new_product.id,
            'name': new_product.name,
            'stock': new_product.stock
        }, broadcast=True)

        return redirect(url_for('stock.products'))

    return render_template('new_product.html', categories=categories, suppliers=suppliers)

def validate_product_data(data):
    # Check if the product already exists
    if Product.query.filter_by(name=data['name']).first():
        return FLASH_PRODUCT_EXISTS

    # Check required fields
    required_fields = [data['name'], data['cost_price'], data['selling_price'], data['stock'], data['category_id']]
    for field, value in zip(['Name', 'Cost Price', 'Selling Price', 'Stock', 'Category'], required_fields):
        if not value:
            return f"{field} is required."

    # Validate numeric fields
    try:
        data['cost_price'] = Decimal(data['cost_price'])
        data['selling_price'] = Decimal(data['selling_price'])
        data['stock'] = int(data['stock'])
        if data['cost_price'] <= 0 or data['selling_price'] <= 0 or data['stock'] < 0:
            return "Cost price, selling price, and stock must be positive numbers."
    except (ValueError, InvalidOperation):
        return "Cost price, selling price, and stock must be valid numbers."

    # Validate combination fields if provided
    if data['combination_size'] and data['combination_price']:
        try:
            data['combination_size'] = int(data['combination_size'])
            data['combination_price'] = Decimal(data['combination_price'])
            if data['combination_size'] <= 0 or data['combination_price'] <= 0:
                return "Combination size and price must be positive numbers."
        except (ValueError, InvalidOperation):
            return "Combination size and price must be valid positive numbers."

    return None  # No errors


def create_product(data):
    combination_unit_price = None
    if data['combination_size'] and data['combination_price']:
        combination_unit_price = float(data['combination_price']) / int(data['combination_size'])

    return Product(
        name=data['name'],
        cost_price=float(data['cost_price']),
        selling_price=float(data['selling_price']),
        stock=float(data['stock']),
        category_id=data['category_id'],
        supplier_id=data['supplier_id'],
        combination_size=int(data['combination_size']) if data['combination_size'] else None,
        combination_price=float(data['combination_price']) if data['combination_price'] else None,
        combination_unit_price=combination_unit_price
    )




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
    # Ensure quantity_to_add is valid
    if quantity_to_add <= 0:
        raise ValueError("Quantity to add must be positive.")

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

        except ValueError as ve:
            db.session.rollback()
            flash(str(ve), "error")  # Display specific validation error
            return redirect(url_for('stock.update_stock'))
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

    # Validate input
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

    except ValueError as ve:
        db.session.rollback()
        return jsonify({'message': str(ve)}), 400  # Return specific validation error
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify({'message': 'Database error. Please try again.'}), 500
    except Exception as e:
        return jsonify({'message': str(e)}), 500


@stock_bp.route('/api/low-stock-products', methods=['GET'])
def get_low_stock_products():
    low_stock_products = Product.query.filter(Product.stock < 5).all()  # Fetch products with stock less than 5
    low_stock_count = len(low_stock_products)

    # Construct a list of product details to return
    products_data = [
        {
            'id': product.id,
            'name': product.name,
            'stock': product.stock,
            'cost_price': product.cost_price,  # Include cost price
            'selling_price': product.selling_price  # Include selling price
        }
        for product in low_stock_products
    ]

    return jsonify({
        'low_stock_count': low_stock_count,
        'products': products_data  # Return detailed product data
    })
