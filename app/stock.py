from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import db, Product, Category, Supplier, Expense  # Include Expense model
from app import socketio
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
        name = request.form['name'].strip()
        cost_price = request.form['cost_price'].strip()
        selling_price = request.form['selling_price'].strip()
        stock = request.form['stock'].strip()
        category_id = request.form['category']
        unit_type = request.form['unit_type']
        supplier_id = request.form.get('supplier')
        combination_size = request.form.get('combination_size', '').strip()
        combination_price = request.form.get('combination_price', '').strip()

        # Check if the product already exists
        if Product.query.filter_by(name=name).first():
            flash(FLASH_PRODUCT_EXISTS)
            return redirect(url_for('stock.new_product'))

        # Validate required fields
        required_fields = [name, cost_price, selling_price, stock, category_id, unit_type]
        if any(not field for field in required_fields):
            flash("All fields must be filled out.")
            return redirect(url_for('stock.new_product'))

        # Validate numeric fields
        try:
            cost_price = float(cost_price)
            selling_price = float(selling_price)
            stock = float(stock)

            if cost_price <= 0 or selling_price <= 0 or stock < 0:
                flash("Cost price, selling price, and stock must be positive numbers.")
                return redirect(url_for('stock.new_product'))

        except ValueError:
            flash("Cost price, selling price, and stock must be valid numbers.")
            return redirect(url_for('stock.new_product'))

        # Validate combination fields if provided
        combination_unit_price = None
        if combination_size and combination_price:
            try:
                combination_size = int(combination_size)
                combination_price = float(combination_price)

                if combination_size <= 0 or combination_price <= 0:
                    flash("Combination size and price must be positive numbers.")
                    return redirect(url_for('stock.new_product'))

                combination_unit_price = combination_price / combination_size
            
            except ValueError:
                flash("Combination size and price must be valid positive numbers.")
                return redirect(url_for('stock.new_product'))

        new_product = Product(
            name=name,
            cost_price=cost_price,
            selling_price=selling_price,  # Save as entered
            stock=stock,
            category_id=category_id,
            unit_type=unit_type,
            supplier_id=supplier_id,
            combination_size=combination_size if combination_size else None,
            combination_price=combination_price if combination_price else None,
            combination_unit_price=combination_unit_price  # Save calculated combination unit price
        )
        
        db.session.add(new_product)
        db.session.commit()
        flash(FLASH_PRODUCT_ADDED.format(name))

        # Emit socket update
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
