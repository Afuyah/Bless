from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app.models import db, Product, Category, Supplier, Expense ,AdjustmentType, StockLog, User, PriceChange 
from app import socketio
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, date
import logging
from werkzeug.exceptions import BadRequest
from app.utils.render import render_htmx
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
stock_bp = Blueprint('stock', __name__)

MAX_STOCK_LIMIT = 1000

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
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        categories = Category.query.order_by(Category.name).paginate(
            page=page, per_page=per_page, error_out=False
        )

        if not categories.items:
            flash('No categories found. Create your first category to get started.', 'info')

        # Shared rendering logic
        return render_htmx(
            'admin/fragments/_categories_fragment.html',
            categories=categories,
            page=page,
            per_page=per_page,
            total_pages=categories.pages,
            total_items=categories.total,
            active_page='categories'
        )

    except Exception as e:
        current_app.logger.error(f"Error fetching categories: {str(e)}")
        flash('An error occurred while loading categories. Please try again.', 'danger')
        return redirect(url_for('auth.admin_dashboard'))




@stock_bp.route('/categories/new', methods=['POST'])
@login_required
def create_category():
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    name = request.form.get('name', '').strip()

    if not name:
        return render_htmx(
            'admin/fragments/_new_category_form.html',
            error="Category name cannot be empty."
        )

    if Category.query.filter_by(name=name).first():
        return render_htmx(
            'admin/fragments/_new_category_form.html',
            error="A category with this name already exists."
        )

    # Add the new category
    new_category = Category(name=name)
    db.session.add(new_category)
    db.session.commit()

    # Re-fetch using pagination to match what the fragment expects
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total
    )


@stock_bp.route('/categories/new-fragment', methods=['GET'])
@login_required
def new_category_form_fragment():
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    return render_htmx('admin/fragments/_new_category_form.html')




@stock_bp.route('/categories/<int:id>/edit', methods=['POST'])
@login_required
def update_category(id):
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    category = Category.query.get_or_404(id)
    name = request.form.get('name', '').strip()

    if not name:
        return render_htmx(
            'admin/fragments/_edit_category_form.html',
            category=category,
            error="Category name cannot be empty."
        )

    existing = Category.query.filter_by(name=name).first()
    if existing and existing.id != id:
        return render_htmx(
            'admin/fragments/_edit_category_form.html',
            category=category,
            error="A category with this name already exists."
        )

    # Update and commit
    category.name = name
    db.session.commit()

    # Re-query using pagination (consistent with categories view)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total
    )


@stock_bp.route('/categories/<int:id>/edit-fragment', methods=['GET'])
@login_required
def edit_category_fragment(id):
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    category = Category.query.get_or_404(id)
    return render_htmx('admin/fragments/_edit_category_form.html', category=category)



@stock_bp.route('/categories/<int:id>', methods=['DELETE'])
@login_required
def delete_category(id):
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    category = Category.query.get_or_404(id)
    db.session.delete(category)
    db.session.commit()

    # Ensure we preserve pagination context
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total
    )



@stock_bp.route('/products', methods=['GET'])
@login_required
def products():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    products_query = Product.query.filter(Product.name.contains(search_query))
    pagination = products_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    if not (current_user.is_admin() or current_user.is_cashier()):
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('home.index'))

    fragment_template = (
        'admin/fragments/_product_inventory.html'
        if current_user.is_admin() else
        'admin/fragments/_cashier_products_view.html'
    )

    # HTMX request = return only fragment
    if request.headers.get('HX-Request'):
        return render_htmx(
            fragment_template,
            products=products,
            pagination=pagination,
            page=page,
            per_page=per_page,
            total_pages=pagination.pages,
            total_items=pagination.total,
            search_query=search_query
        )

    # Normal full-page request = render layout + include fragment
    return render_template(
        'auth/admin_dashboard.html',
        fragment_template=fragment_template,
        products=products,
        pagination=pagination,
        page=page,
        per_page=per_page,
        total_pages=pagination.pages,
        total_items=pagination.total,
        search_query=search_query,
        active_page='products'
    )



@stock_bp.route('/products/fragment', methods=['GET'])
@login_required
def products_fragment():
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    products_query = Product.query.filter(Product.name.contains(search_query))
    pagination = products_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    if current_user.is_admin():
        return render_htmx(
            'admin/fragments/_product_inventory.html',
            products=products,
            pagination=pagination,
            search_query=search_query
        )
    elif current_user.is_cashier():
        return render_htmx(
            'admin/fragments/_cashier_products_view.html',
            products=products,
            pagination=pagination,
            search_query=search_query
        )
    else:
        return '', 403




       

@stock_bp.route('/products/new', methods=['GET', 'POST'])
@login_required
def new_product():
    if not current_user.is_admin():
        return render_template("fragments/error.html", message=FLASH_ACCESS_DENIED)

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

        validation_error = validate_product_data(product_data)
        if validation_error:
            return render_template('fragments/product_form.html',
                                   categories=categories,
                                   suppliers=suppliers,
                                   error=validation_error)

        new_product = create_product(product_data)
        db.session.add(new_product)
        db.session.commit()

        socketio.emit('stock_updated', {
            'id': new_product.id,
            'name': new_product.name,
            'stock': new_product.stock
        }, broadcast=True)

        # Return updated product list fragment directly
        products = Product.query.all()
        return render_htmx('fragments/products_list.html', products=products)

    return render_htmx('fragments/product_form.html', categories=categories, suppliers=suppliers)




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



@stock_bp.route('/products/new-fragment', methods=['GET'])
@login_required
def new_product_form_fragment():
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    categories = Category.query.all()
    suppliers = Supplier.query.all()

    return render_htmx('admin/fragments/_new_product.html', categories=categories, suppliers=suppliers)



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



# Route to display the product management page
@stock_bp.route('/admin_update_stock', methods=['GET'])
@login_required
def update_stock_page():
    if not current_user.is_admin():
        flash("Access denied.", "danger")
        return redirect(url_for("home.index"))

    products = Product.query.all()

    return render_template(
        'auth/admin_dashboard.html',
        fragment_template='admin/fragments/_update_stock_fragment.html',  # your main stock list
        products=products,
        active_page='update_stock',
        sales_data={"change": 0},  # prevent sidebar errors
        monthly_revenue=0,
        date=date,
        datetime=datetime
    )

@stock_bp.route('/products/<int:product_id>/update_stock_form')
@login_required
def update_stock_form_fragment(product_id):
    if not current_user.is_admin():
        return "<div class='text-red-600 p-4'>Access Denied</div>", 403

    product = Product.query.get_or_404(product_id)
    allowed_types = ['addition', 'reduction', 'inventory_adjustment', 'damage', 'returned']

    return render_htmx(
        'admin/fragments/_update_stock_form.html',
        product=product,
        allowed_types=allowed_types
    )




@stock_bp.route('/products/<int:product_id>/update_stock', methods=['POST'])
@login_required
def update_stock(product_id):
    product = Product.query.get_or_404(product_id)
    quantity = request.form.get('quantity')

    if not quantity:
        return render_template('admin/fragments/_stock_feedback.html', message="Quantity is required", success=False), 400

    try:
        quantity = int(quantity)
    except ValueError:
        return render_template('admin/fragments/_stock_feedback.html', message="Quantity must be a number", success=False), 400

    if quantity < 0:
        return render_template('admin/fragments/_stock_feedback.html', message="Quantity cannot be negative", success=False), 400

    try:
        product.stock += quantity

        if product.stock > MAX_STOCK_LIMIT:
            return render_template('admin/fragments/_stock_feedback.html', message="Stock exceeds max limit", success=False), 400

        db.session.commit()

        logger.info(f'User {current_user.id} updated stock for product {product_id} by {quantity}. New stock: {product.stock}')

        return render_template(
            'admin/fragments/_stock_feedback.html',
            product=product,
            quantity=quantity,
            success=True,
            message="Stock updated successfully."
        )

    except IntegrityError:
        db.session.rollback()
        return render_template('admin/fragments/_stock_feedback.html', message="Integrity error occurred", success=False), 500
    except Exception as e:
        db.session.rollback()
        return render_template('admin/fragments/_stock_feedback.html', message=f"Unexpected error: {str(e)}", success=False), 500





@stock_bp.route('/products/<int:product_id>/update_stock_modal', methods=['GET'])
@login_required
def update_stock_modal(product_id: int):
    """Render stock update modal with product data"""
    product = Product.query.get_or_404(product_id)
    
    if not current_user.can_manage_inventory():
        abort(403, description="You don't have permission to manage inventory")
    
    return render_template(
        'update_stock_modal.html', 
        product=product,
        current_quantity=product.current_stock,
        form_action=url_for('stock.update_stock', product_id=product_id)
    )


# Helper functions
def parse_decimal(value):
    """Safely parse decimal values with validation"""
    if value is None or value == '':
        return None
    try:
        return Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise InvalidOperation("Invalid decimal value")

def parse_int(value):
    """Safely parse integer values with validation"""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise InvalidOperation("Invalid integer value")

def format_currency(value):
    """Format decimal values as currency strings"""
    if value is None:
        return None
    return f"{float(value):.2f}"

def record_price_change(product_id, user_id, change_type, old_price, new_price, 
                       old_combo=None, new_combo=None):
    """Record price changes in the audit log"""
    change = PriceChange(
        product_id=product_id,
        user_id=user_id,
        change_type=change_type,
        old_price=old_price,
        new_price=new_price,
        old_combo_size=old_combo[0] if old_combo else None,
        old_combo_price=old_combo[1] if old_combo else None,
        new_combo_size=new_combo[0] if new_combo else None,
        new_combo_price=new_combo[1] if new_combo else None
    )
    db.session.add(change)






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
            'cost_price': product.cost_price,  
            'selling_price': product.selling_price  # Include selling price
        }
        for product in low_stock_products
    ]

    return jsonify({
        'low_stock_count': low_stock_count,
        'products': products_data  # Return detailed product data
    })


@stock_bp.route('/adjust-stock/<int:product_id>', methods=['GET', 'POST'])
@login_required
def adjust_stock(product_id):
    product = Product.query.get_or_404(product_id)
    
    # Check user roles
    is_admin = current_user.is_admin()
    is_cashier = current_user.is_cashier()

    if request.method == 'POST':
        try:
            # Retrieve data from form
            adjustment_quantity = int(request.form['adjustment_quantity'])
            change_reason = request.form.get('change_reason', '').strip()  # Change reason is optional
            adjustment_type = request.form.get('adjustment_type')

            # Validate adjustment quantity
            if adjustment_quantity < 1:
                flash('Adjustment quantity must be greater than zero.', 'danger')
                logger.warning(f'Invalid quantity {adjustment_quantity} attempted by user {current_user.id} on product {product.id}')
                return redirect(url_for('stock.product_detail', product_id=product.id))

            # Validate change reason if provided
            if change_reason and len(change_reason) < 5:
                flash('If provided, change reason must be at least 5 characters long.', 'danger')
                logger.warning(f'Insufficient reason length by user {current_user.id} on product {product.id}')
                return redirect(url_for('stock.product_detail', product_id=product.id))

            # Determine allowed adjustment types based on user role
            allowed_types = ['addition', 'reduction', 'returned'] if is_cashier else [e.value for e in AdjustmentType]
            
            # Validate the adjustment type
            if adjustment_type not in allowed_types:
                flash('Unauthorized adjustment type for your role.', 'danger')
                logger.warning(f'Unauthorized adjustment attempt by user {current_user.id} on product {product.id}: {adjustment_type}')
                return redirect(url_for('stock.product_detail', product_id=product.id))

            # Calculate the new stock level based on the adjustment type
            if adjustment_type == 'addition':
                new_stock = product.stock + adjustment_quantity
            elif adjustment_type == 'reduction':
                new_stock = max(product.stock - adjustment_quantity, 0)  # Ensures stock can't go negative
            elif adjustment_type == 'returned':
                new_stock = product.stock + adjustment_quantity  # Increase stock for returned items
            elif adjustment_type in ['spoilage', 'damage', 'theft']:
                new_stock = max(product.stock - adjustment_quantity, 0)  # Decrease stock for spoilage, damage, or theft
            elif adjustment_type == 'inventory_adjustment':
                new_stock = adjustment_quantity  # Set stock to the provided amount
            else:
                flash('Invalid adjustment type.', 'danger')
                logger.warning(f'Invalid adjustment type {adjustment_type} attempted by user {current_user.id} on product {product.id}')
                return redirect(url_for('stock.product_detail', product_id=product.id))

            # Log the stock update
            stock_log = StockLog(
                product_id=product.id,
                user_id=current_user.id,
                previous_stock=product.stock,
                new_stock=new_stock,
                adjustment_type=adjustment_type,
                change_reason=change_reason or None  
            )
            
            # Update the product's stock in the database
            product.stock = new_stock
            
            db.session.add(stock_log)
            db.session.commit()
            
            flash(f'Stock for {product.name} updated successfully.', 'success')
            logger.info(f'Stock for {product.name} updated from {product.stock} to {new_stock} by user {current_user.id} with adjustment type {adjustment_type}')
            return redirect(url_for('stock.products'))

        except ValueError as ve:
            flash('Invalid input for quantity. Please enter a valid number.', 'danger')
            logger.error(f'ValueError: {str(ve)} by user {current_user.id} on product {product.id}')
        except SQLAlchemyError as e:
            db.session.rollback()  # Rollback in case of database errors
            flash('An error occurred while updating stock. Please try again.', 'danger')
            logger.error(f'Database error: {str(e)} by user {current_user.id} on product {product.id}')
        except Exception as e:
            flash('An unexpected error occurred. Please try again.', 'danger')
            logger.error(f'Unexpected error: {str(e)} by user {current_user.id} on product {product.id}')

    # Render the appropriate template based on user role
    template_name = 'adjust_stock_cashier.html' if is_cashier else 'adjust_stock_admin.html'
    allowed_types = ['addition', 'return'] if is_cashier else [e.value for e in AdjustmentType]
    
    return render_template(template_name, product=product, allowed_types=allowed_types)


@stock_bp.route('/product/<int:product_id>/details-fragment')
@login_required
def product_details_fragment(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('fragments/product_details.html', product=product)





@stock_bp.route('/products/<int:product_id>/update_selling_price', methods=['POST'])
@login_required
def update_selling_price(product_id):
    """Update product selling price with comprehensive validation"""
    product = Product.query.get_or_404(product_id)
    is_htmx = request.headers.get('HX-Request') == 'true'
    
   
    try:
        data = request.get_json(silent=True) or request.form
        new_selling_price = parse_decimal(data.get('selling_price'))
        combination_size = parse_int(data.get('combination_size'))
        combination_price = parse_decimal(data.get('combination_price'))

        # Validate inputs
        if all(v is None for v in [new_selling_price, combination_size, combination_price]):
            raise BadRequest('No pricing updates provided')

        if new_selling_price is not None:
            if new_selling_price < 0:
                raise BadRequest('Selling price cannot be negative')
            if new_selling_price < product.cost_price:
                raise BadRequest('Selling price cannot be below cost price')

        if combination_size is not None or combination_price is not None:
            if None in (combination_size, combination_price):
                raise BadRequest('Must provide both combination size and price')
            if combination_size <= 0:
                raise BadRequest('Combination size must be positive')
            if combination_price <= 0:
                raise BadRequest('Combination price must be positive')
            
            unit_price = combination_price / combination_size
            if unit_price < product.cost_price:
                raise BadRequest('Combination unit price cannot be below cost')

        # Record changes before updating
        try:
            record_price_change(
                product_id=product.id,
                user_id=current_user.id,
                change_type='selling_price_update',
                old_price=product.selling_price,
                new_price=new_selling_price,
                old_combo=(product.combination_size, product.combination_price),
                new_combo=(combination_size, combination_price)
            )
        except Exception as e:
            current_app.logger.error(f"Error recording price change: {str(e)}")
            # Don't fail the entire operation if history recording fails
            pass

        # Apply updates
        if new_selling_price is not None:
            product.selling_price = new_selling_price
        
        if combination_size and combination_price:
            product.combination_size = combination_size
            product.combination_price = combination_price
            product.combination_unit_price = combination_price / combination_size

        db.session.commit()
        db.session.refresh(product)

        if is_htmx:
            return render_template('admin/fragments/_price_row.html', 
                                product=product,
                                message='Pricing updated successfully')
        
        return jsonify({
            'message': 'Pricing updated successfully',
            'product': product.to_dict()  # Ensure you have this method
        }), 200

    except BadRequest as e:
        db.session.rollback()
        if is_htmx:
            return render_template('admin/fragments/_error.html', message=str(e)), 400
        return jsonify({'message': str(e)}), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating product {product_id}: {str(e)}")
        if is_htmx:
            return render_template('admin/fragments/_error.html',
                               message='An error occurred while updating price'), 500
        return jsonify({'message': 'An error occurred while updating price'}), 500







@stock_bp.route('/products/<int:product_id>/update_cost_price', methods=['POST'])
@login_required
def update_cost_price(product_id):
    """
    Update product cost price with validation
    Supports both JSON and HTMX responses
    """
    product = Product.query.get_or_404(product_id)
    is_htmx = request.headers.get('HX-Request') == 'true'
    
   

    try:
        data = request.get_json(silent=True) or request.form
        new_cost_price = parse_decimal(data.get('cost_price'))
        
        if new_cost_price is None:
            raise BadRequest('Cost price is required')
        if new_cost_price < 0:
            raise BadRequest('Cost price cannot be negative')

        # Record price history before updating
        record_price_change(
            product_id=product.id,
            user_id=current_user.id,
            change_type='cost_price_update',
            old_price=product.cost_price,
            new_price=new_cost_price
        )

        product.cost_price = new_cost_price
        db.session.commit()

        # Refresh the product to ensure we have the latest data
        db.session.refresh(product)

        if is_htmx:
            # Return the updated row and success message
            return render_template('admin/fragments/_price_row.html',
                                product=product,
                                message='Cost price updated successfully')

        return jsonify({
            'message': 'Cost price updated successfully',
            'product': {
                'id': product.id,
                'name': product.name,
                'cost_price': format_currency(product.cost_price)
            }
        }), 200

    except BadRequest as e:
        db.session.rollback()
        if is_htmx:
            return render_template('admin/fragments/_error.html', message=str(e)), 400
        return jsonify({'message': str(e)}), 400
        
    except InvalidOperation:
        db.session.rollback()
        if is_htmx:
            return render_template('admin/fragments/_error.html',
                               message='Invalid numeric format'), 400
        return jsonify({'message': 'Invalid numeric format'}), 400
        
    except IntegrityError:
        db.session.rollback()
        current_app.logger.error(f"Integrity error updating product {product_id} cost price")
        if is_htmx:
            return render_template('admin/fragments/_error.html',
                               message='Database error occurred'), 500
        return jsonify({'message': 'Database error occurred'}), 500
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating product {product_id} cost: {str(e)}")
        if is_htmx:
            return render_template('admin/fragments/_error.html',
                               message='An unexpected error occurred'), 500
        return jsonify({'message': 'An unexpected error occurred'}), 500



@stock_bp.route('/products/<int:product_id>/update_pricing', methods=['POST'])
@login_required
def update_product_pricing(product_id):
    """Unified endpoint for all price updates"""
    product = Product.query.get_or_404(product_id)
    is_htmx = request.headers.get('HX-Request') == 'true'
    
   

    try:
        data = request.get_json(silent=True) or request.form
        
        # Parse inputs
        cost_price = parse_decimal(data.get('cost_price'))
        selling_price = parse_decimal(data.get('selling_price'))
        combo_size = parse_int(data.get('combination_size'))
        combo_price = parse_decimal(data.get('combination_price'))
        combo = (combo_size, combo_price) if combo_size and combo_price else None

        # Validate at least one update is requested
        if all(v is None for v in [cost_price, selling_price, combo]):
            raise BadRequest('No pricing updates provided')

        # Business validations
        if selling_price is not None and selling_price < product.cost_price:
            if cost_price is None or selling_price < cost_price:
                raise BadRequest('Selling price cannot be below cost price')

        if combo:
            if combo_price / combo_size < (cost_price or product.cost_price):
                raise BadRequest('Bundle unit price cannot be below cost price')

        # Perform update
        if product.update_pricing(
            new_cost=cost_price,
            new_selling=selling_price,
            new_combo=combo,
            user_id=current_user.id
        ):
            db.session.commit()
            return success_response(product, 'Prices updated', is_htmx)
        
        return success_response(product, 'No changes made', is_htmx)

    except (BadRequest, ValueError) as e:
        db.session.rollback()
        return error_response(str(e), 400, is_htmx)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Price update failed: {str(e)}", exc_info=True)
        return error_response('Update failed', 500, is_htmx)




@stock_bp.route('/price_fragment', methods=['GET'])
@login_required
def price_fragment():
    products = Product.query.order_by(Product.name.asc()).limit(50).all()

    if request.headers.get('HX-Request'):  # HTMX request — return fragment only
        return render_template('admin/fragments/price_fragment.html', products=products)
    else:
        return render_template(
            'auth/admin_dashboard.html',  # or your main shell layout
            fragment_template='admin/fragments/price_fragment.html',
            products=products
        )


@stock_bp.route('/price_rows_fragment', methods=['GET'])
@login_required
def price_rows_fragment():
    """HTMX-only table rows for price updates"""
    products = Product.query.order_by(Product.name.asc()).limit(50).all()
    return render_htmx('admin/fragments/_price_rows.html', products=products)



@stock_bp.route('/products/<int:product_id>/edit_selling_price_form', methods=['GET'])
@login_required
def edit_selling_price_form(product_id):
    """Selling price edit form modal (no permission check)"""
    product = Product.query.get_or_404(product_id)
    return render_template('admin/fragments/_edit_selling_price_form.html', product=product)

@stock_bp.route('/products/<int:product_id>/edit_cost_price_form', methods=['GET'])
@login_required
def edit_cost_price_form(product_id):
    """Cost price edit form modal (no permission check)"""
    product = Product.query.get_or_404(product_id)
    return render_template('admin/fragments/_edit_cost_price_form.html', product=product)



@stock_bp.route('/search_products', methods=['GET'])
@login_required
def search_products():
    """Search endpoint for HTMX"""
    query = request.args.get('query', '')
    if not query:
        products = Product.query.order_by(Product.name.asc()).limit(50).all()
    else:
        products = Product.query.filter(
            Product.name.ilike(f'%{query}%') | 
            Product.sku.ilike(f'%{query}%')
        ).order_by(Product.name.asc()).limit(50).all()
    return render_template('admin/fragments/_price_rows.html', products=products)




@stock_bp.route('/stock-logs', methods=['GET'])
@login_required
def stock_logs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    logs = db.session.query(
        StockLog,
        Product.name.label('product_name'),
        User.username.label('user_name')
    ).join(Product).join(User).order_by(
        StockLog.date.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)

    if request.headers.get('HX-Request'):
        return render_template('admin/fragments/_stock_logs_table.html', logs=logs)
    
    return render_template(
        'auth/admin_dashboard.html',  # or your layout wrapper
        fragment_template='admin/fragments/_stock_logs_table.html',
        logs=logs
    )




@stock_bp.route('/api/stock-logs', methods=['GET'])
@login_required
def get_stock_logs():
    """JSON API endpoint for stock logs"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)
        
        # Paginated query with joined data
        paginated_logs = db.session.query(
            StockLog,
            Product.name.label('product_name'),
            User.username.label('user_name')
        ).join(Product).join(User).order_by(
            StockLog.date.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

        logs_data = [{
            'id': log.id,
            'product_name': product_name,
            'user_name': user_name,
            'date': log.date.isoformat(),
            'previous_stock': log.previous_stock,
            'new_stock': log.new_stock,
            'adjustment_type': log.adjustment_type.value,
            'notes': log.notes or ''
        } for log, product_name, user_name in paginated_logs.items]

        return jsonify({
            'logs': logs_data,
            'total': paginated_logs.total,
            'pages': paginated_logs.pages,
            'current_page': paginated_logs.page
        }), 200

    except Exception as e:
        current_app.logger.error(f"Error fetching stock logs: {str(e)}")
        return jsonify({'error': 'Failed to load stock logs'}), 500