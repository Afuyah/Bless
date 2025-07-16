from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, g, make_response
from flask_login import login_required, current_user
from app.models import  Product, Category, Supplier, Expense ,AdjustmentType, StockLog, User, PriceChange, Role 
from app import socketio
from app import db, csrf, role_required, shop_access_required, business_access_required
from decimal import Decimal, InvalidOperation
from sqlalchemy.exc import IntegrityError
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime, date
import logging
from werkzeug.exceptions import BadRequest
from app.utils.render import render_htmx



logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
inventory_bp = Blueprint('inventory', __name__)

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

@inventory_bp.route('/shops/<int:shop_id>/categories')
@login_required
@shop_access_required  # Sets g.current_shop
@role_required(Role.ADMIN, Role.TENANT)
def categories(shop_id):
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 10, type=int)

        categories = Category.query.filter_by(shop_id=shop_id).order_by(Category.name).paginate(
            page=page, per_page=per_page, error_out=False
        )

        if not categories.items:
            flash('No categories found. Create your first category to get started.', 'info')

        return render_htmx(
            'admin/fragments/_categories_fragment.html',
            categories=categories,
            page=page,
            per_page=per_page,
            total_pages=categories.pages,
            total_items=categories.total,
            active_page='categories',
            shop=g.current_shop
        )

    except Exception as e:
        current_app.logger.error(f"Error fetching categories for shop {shop_id}: {str(e)}", exc_info=True)
        flash('An error occurred while loading categories. Please try again.', 'danger')
        return redirect(url_for('admin.admin_dashboard', shop_id=shop_id))



@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/categories/new', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def create_category(shop_id):
    shop = g.get('current_shop')
    if not shop:
        abort(400, "Shop context is missing.")

    name = request.form.get('name', '').strip()

    if not name:
        return render_htmx(
            'admin/fragments/_new_category_form.html',
            error="Category name cannot be empty.",
            shop=shop
        )

    # Check uniqueness scoped to shop
    existing = Category.query.filter_by(name=name, shop_id=shop.id).first()
    if existing:
        return render_htmx(
            'admin/fragments/_new_category_form.html',
            error="A category with this name already exists in this shop.",
            shop=shop
        )

    # Create and save
    new_category = Category(name=name, shop_id=shop.id)
    db.session.add(new_category)
    db.session.commit()

    # Re-fetch paginated categories
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.filter_by(shop_id=shop.id).order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total,
        shop=shop
    )




@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/categories/new-fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def new_category_form_fragment(shop_id):
    return render_htmx('admin/fragments/_new_category_form.html', shop_id=shop_id)



@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/categories/<int:id>/edit', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_category(shop_id, id):
    shop = g.current_shop

    category = Category.query.get_or_404(id)

    # Ensure category belongs to the shop
    if category.shop_id != shop.id:
        return "<div class='text-red-600 p-4'>Access Denied: Category does not belong to this shop</div>", 403

    name = request.form.get('name', '').strip()

    if not name:
        return render_htmx(
            'admin/fragments/_edit_category_form.html',
            category=category,
            shop=shop,
            error="Category name cannot be empty."
        )

    existing = Category.query.filter_by(name=name, shop_id=shop.id).first()
    if existing and existing.id != id:
        return render_htmx(
            'admin/fragments/_edit_category_form.html',
            category=category,
            shop=shop,
            error="A category with this name already exists in this shop."
        )

    # Update
    category.name = name
    db.session.commit()

    # Fetch updated paginated list
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.filter_by(shop_id=shop.id).order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total,
        shop=shop
    )



@inventory_bp.route('/shops/<int:shop_id>/categories/<int:id>/edit-fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def edit_category_fragment(shop_id, id):
    shop = g.current_shop

    category = Category.query.get_or_404(id)
    if category.shop_id != shop.id:
        return "<div class='text-red-600 p-4'>Access Denied: Category not in this shop</div>", 403

    return render_htmx('admin/fragments/_edit_category_form.html', category=category, shop=shop)


@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/categories/<int:id>', methods=['DELETE'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def delete_category(shop_id, id):
    shop = g.current_shop

    category = Category.query.get_or_404(id)
    if category.shop_id != shop.id:
        return "<div class='text-red-600 p-4'>Access Denied: Category not in this shop</div>", 403

    db.session.delete(category)
    db.session.commit()

    # Pagination context
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    categories = Category.query.filter_by(shop_id=shop.id).order_by(Category.name).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_htmx(
        'admin/fragments/_categories_fragment.html',
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=categories.pages,
        total_items=categories.total,
        shop=shop
    )




@inventory_bp.route('/shops/<int:shop_id>/products', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def products(shop_id):
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    shop = g.current_shop

    products_query = Product.query.filter(
        Product.shop_id == shop.id,
        Product.name.contains(search_query)
    )
    pagination = products_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    fragment_template = 'admin/fragments/_product_inventory.html'


    if request.headers.get('HX-Request'):
        return render_htmx(
            fragment_template,
            products=products,
            pagination=pagination,
            page=page,
            per_page=per_page,
            total_pages=pagination.pages,
            total_items=pagination.total,
            search_query=search_query,
            shop=shop
        )

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
        active_page='products',
        shop=shop
    )


@inventory_bp.route('/shops/<int:shop_id>/products/fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def products_fragment(shop_id):
    search_query = request.args.get('search', '')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    shop = g.current_shop

    products_query = Product.query.filter(
        Product.shop_id == shop.id,
        Product.name.contains(search_query)
    )

    pagination = products_query.paginate(page=page, per_page=per_page, error_out=False)
    products = pagination.items

    template = (
        'admin/fragments/_product_inventory.html'
        if current_user.is_admin()
        else 'admin/fragments/_cashier_products_view.html'
    )

    return render_htmx(
        template,
        products=products,
        pagination=pagination,
        search_query=search_query,
        shop=shop
    )



@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/products/new', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def new_product(shop_id):
    shop = g.current_shop
    categories = Category.query.filter_by(shop_id=shop.id).all()
    suppliers = Supplier.query.all()

    product_data = {
        'name': request.form['name'].strip(),
        'cost_price': request.form['cost_price'].strip(),
        'selling_price': request.form['selling_price'].strip(),
        'stock': request.form['stock'].strip(),
        'category_id': request.form['category'],
        'supplier_id': request.form.get('supplier'),
        'combination_size': request.form.get('combination_size', '').strip(),
        'combination_price': request.form.get('combination_price', '').strip(),
        'shop_id': shop.id
    }

    error = validate_product_data(product_data)
    if error:
        return render_htmx(
            'admin/fragments/_new_product.html', 
            error=error, 
            categories=categories, 
            suppliers=suppliers, 
            shop_id=shop.id
        )

    try:
        new_product = create_product(product_data)
        db.session.add(new_product)
        db.session.commit()
        
        # Return success response with refresh instruction
        response = make_response(render_htmx(
            'admin/fragments/_new_product.html',
            success="Product added successfully!",
            categories=categories,
            suppliers=suppliers,
            shop_id=shop.id,
            form_cleared=True  # Add this flag to clear the form
        ))
        
        # Trigger client-side refresh of product list
        response.headers['HX-Trigger'] = 'productAdded'
        return response

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating product: {str(e)}")
        return render_htmx(
            'admin/fragments/_new_product.html',
            error="An error occurred while creating the product",
            categories=categories,
            suppliers=suppliers,
            shop_id=shop.id
        )



def validate_product_data(data):
    # Check if the product already exists in the same shop
    existing = Product.query.filter_by(name=data['name'], shop_id=data['shop_id']).first()
    if existing:
        return "A product with this name already exists in this shop."

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

    # Validate combination fields (optional)
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
        category_id=int(data['category_id']),
        supplier_id=int(data['supplier_id']) if data['supplier_id'] else None,
        combination_size=int(data['combination_size']) if data['combination_size'] else None,
        combination_price=float(data['combination_price']) if data['combination_price'] else None,
        combination_unit_price=combination_unit_price,
        shop_id=data['shop_id']
    )




@inventory_bp.route('/shops/<int:shop_id>/products/new-fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def new_product_form_fragment(shop_id):
    categories = Category.query.filter_by(shop_id=shop_id).all()
    suppliers = Supplier.query.all()
    return render_htmx('admin/fragments/_new_product.html', categories=categories, suppliers=suppliers, shop_id=shop_id)


@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/products/<int:id>/edit', methods=['GET', 'POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def edit_product(shop_id: int, id: int):
    shop = g.current_shop

    # Only allow editing of products in this shop
    product = Product.query.filter_by(id=id, shop_id=shop.id).first_or_404()
    categories = Category.query.filter_by(shop_id=shop.id).all()

    if request.method == 'POST':
        try:
            product.name = request.form['name'].strip()
            product.selling_price = float(request.form['selling_price'])
            product.category_id = int(request.form['category'])

            db.session.commit()
            flash(f"Product '{product.name}' updated successfully.", "success")

            socketio.emit('product_updated', {
                'id': product.id,
                'name': product.name,
                'selling_price': product.selling_price
            }, broadcast=True)

            return redirect(url_for('inventory.products', shop_id=shop.id))

        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while updating the product: {str(e)}", "danger")
            return redirect(url_for('inventory.edit_product', shop_id=shop.id, id=id))

    return render_template('edit_product.html', product=product, categories=categories, shop=shop)


@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/products/<int:id>/delete', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def delete_product(shop_id: int, id: int):
    shop = g.current_shop

    # Ensure the product belongs to the current shop
    product = Product.query.filter_by(id=id, shop_id=shop.id).first_or_404()

    try:
        db.session.delete(product)
        db.session.commit()
        flash(FLASH_PRODUCT_DELETED.format(product.name), 'success')

        # Emit real-time update to clients
        socketio.emit('stock_updated', {
            'id': product.id,
            'name': product.name,
            'stock': 0
        }, broadcast=True)

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to delete product: {e}")
        flash('An error occurred while deleting the product. Please try again.', 'danger')

    return redirect(url_for('inventory.products', shop_id=shop.id))





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
@inventory_bp.route('/admin_update_stock', methods=['GET'])
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_stock_page():
    products = Product.query.filter_by(shop_id=shop_id)

    return render_template(
        'auth/admin_dashboard.html',
        fragment_template='admin/fragments/_update_stock_fragment.html',  
        products=products,
        active_page='update_stock',
        sales_data={"change": 0},  # prevent sidebar errors
        monthly_revenue=0,
        date=date,
        datetime=datetime, 
        shop_id=shop_id
    )

@inventory_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_stock_form')
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_stock_form_fragment(shop_id, product_id):
    # Subquery for category IDs in this shop
    category_ids = Category.query.with_entities(Category.id).filter_by(shop_id=shop_id)

    # Ensure product belongs to this shop via category
    product = Product.query.filter(
        Product.id == product_id,
        Product.category_id.in_(category_ids)
    ).first_or_404()

    allowed_types = ['addition', 'reduction', 'inventory_adjustment', 'damage', 'returned']

    return render_htmx(
        'admin/fragments/_update_stock_form.html',
        product=product,
        allowed_types=allowed_types,
        shop_id=shop_id
    )





@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_stock', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def submit_update_stock(shop_id, product_id):
    shop = g.current_shop

    # Ensure product belongs to this shop
    category_ids = [cat.id for cat in Category.query.filter_by(shop_id=shop.id)]
    product = Product.query.filter(Product.id == product_id, Product.category_id.in_(category_ids)).first_or_404()

    try:
        update_type = request.form.get('update_type')
        quantity = int(request.form.get('quantity'))
        total_amount = float(request.form.get('total_amount', 0))  # optional

        if update_type not in ['addition', 'reduction', 'inventory_adjustment', 'damage', 'returned']:
            return render_htmx('admin/fragments/_update_stock_form.html',
                               product=product,
                               error="Invalid update type selected.",
                               shop_id=shop_id)

        if quantity <= 0:
            return render_htmx('admin/fragments/_update_stock_form.html',
                               product=product,
                               error="Quantity must be greater than zero.",
                               shop_id=shop_id)

        # Apply stock update logic
        if update_type in ['addition', 'returned']:
            update_product_stock(product, quantity, total_amount)
        elif update_type in ['reduction', 'damage']:
            if product.stock < quantity:
                return render_htmx('admin/fragments/_update_stock_form.html',
                                   product=product,
                                   error="Cannot reduce more than current stock.",
                                   shop_id=shop_id)
            product.stock -= quantity
        elif update_type == 'inventory_adjustment':
            product.stock = quantity

        db.session.commit()

        socketio.emit('stock_updated', {
            'id': product.id,
            'name': product.name,
            'stock': product.stock
        }, broadcast=True)

        flash(f"Stock for '{product.name}' updated successfully.", 'success')

        # Return updated fragment
        products = Product.query.join(Category).filter(Category.shop_id == shop.id).all()
        return render_htmx(
            'admin/fragments/_update_stock_fragment.html',
            products=products,
            shop_id=shop_id
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error updating stock: {str(e)}")
        return render_htmx('admin/fragments/_update_stock_form.html',
                           product=product,
                           error="An error occurred. Please try again.",
                           shop_id=shop_id)



@inventory_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_stock_modal', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_stock_modal(shop_id: int, product_id: int):
    """Render stock update modal for a specific product in a shop"""
    shop = g.current_shop

    # Ensure product belongs to the shop (via category)
    category_ids = Category.query.with_entities(Category.id).filter_by(shop_id=shop.id).subquery()
    product = Product.query.filter(Product.id == product_id, Product.category_id.in_(category_ids)).first_or_404()

    return render_template(
        'update_stock_modal.html',
        product=product,
        current_quantity=product.stock,
        form_action=url_for('inventory.submit_update_stock', shop_id=shop_id, product_id=product_id)
    )



@inventory_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_stock', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_stock_product(shop_id: int, product_id: int):
    shop = g.current_shop

    # Ensure product belongs to this shop via category
    category_ids = Category.query.with_entities(Category.id).filter_by(shop_id=shop.id).subquery()
    product = Product.query.filter(Product.id == product_id, Product.category_id.in_(category_ids)).first_or_404()

    try:
        quantity_to_add = int(request.form['quantity'])
        total_amount = float(request.form['total_amount'])

        if quantity_to_add <= 0:
            return jsonify({'message': "Quantity must be a positive integer."}), 400
        if total_amount < 0:
            return jsonify({'message': "Total amount cannot be negative."}), 400

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
        return jsonify({'message': str(ve)}), 400
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({'message': 'Database error. Please try again.'}), 500
    except Exception as e:
        return jsonify({'message': str(e)}), 500



@inventory_bp.route('/shops/<int:shop_id>/api/low-stock-products', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def get_low_stock_products(shop_id):
    shop = g.current_shop

    # Get all categories in this shop
    category_ids = Category.query.with_entities(Category.id).filter_by(shop_id=shop.id).subquery()

    # Only fetch products belonging to this shop
    low_stock_products = Product.query.filter(
        Product.category_id.in_(category_ids),
        Product.stock < 5
    ).all()

    products_data = [
        {
            'id': product.id,
            'name': product.name,
            'stock': product.stock,
            'cost_price': product.cost_price,
            'selling_price': product.selling_price
        }
        for product in low_stock_products
    ]

    return jsonify({
        'low_stock_count': len(products_data),
        'products': products_data
    })


@csrf.exempt
@inventory_bp.route('/shops/<int:shop_id>/adjust-stock/<int:product_id>', methods=['GET', 'POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.CASHIER)
def adjust_stock(shop_id, product_id):
    shop = g.current_shop

    product = Product.query.get_or_404(product_id)

    # Ensure the product belongs to this shop
    if product.category.shop_id != shop.id:
        abort(403, description="This product doesn't belong to your shop.")

    is_admin = current_user.is_admin()
    is_cashier = current_user.is_cashier()

    if request.method == 'POST':
        try:
            adjustment_quantity = int(request.form['adjustment_quantity'])
            change_reason = request.form.get('change_reason', '').strip()
            adjustment_type = request.form.get('adjustment_type')

            if adjustment_quantity < 1:
                flash('Adjustment quantity must be greater than zero.', 'danger')
                return redirect(url_for('inventory.adjust_stock', shop_id=shop_id, product_id=product_id))

            if change_reason and len(change_reason) < 5:
                flash('Change reason must be at least 5 characters long.', 'danger')
                return redirect(url_for('inventory.adjust_stock', shop_id=shop_id, product_id=product_id))

            allowed_types = ['addition', 'reduction', 'returned'] if is_cashier else [e.value for e in AdjustmentType]
            if adjustment_type not in allowed_types:
                flash('Unauthorized adjustment type.', 'danger')
                return redirect(url_for('inventory.adjust_stock', shop_id=shop_id, product_id=product_id))

            if adjustment_type == 'addition':
                new_stock = product.stock + adjustment_quantity
            elif adjustment_type == 'reduction':
                new_stock = max(product.stock - adjustment_quantity, 0)
            elif adjustment_type == 'returned':
                new_stock = product.stock + adjustment_quantity
            elif adjustment_type in ['spoilage', 'damage', 'theft']:
                new_stock = max(product.stock - adjustment_quantity, 0)
            elif adjustment_type == 'inventory_adjustment':
                new_stock = adjustment_quantity
            else:
                flash('Invalid adjustment type.', 'danger')
                return redirect(url_for('inventory.adjust_stock', shop_id=shop_id, product_id=product_id))

            stock_log = StockLog(
                product_id=product.id,
                user_id=current_user.id,
                previous_stock=product.stock,
                new_stock=new_stock,
                adjustment_type=adjustment_type,
                change_reason=change_reason or None
            )

            product.stock = new_stock
            db.session.add(stock_log)
            db.session.commit()

            flash(f'Stock for {product.name} updated successfully.', 'success')
            return redirect(url_for('inventory.products', shop_id=shop_id))

        except ValueError:
            flash('Invalid quantity.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            flash('Database error occurred.', 'danger')
        except Exception as e:
            logger.exception(e)
            flash('Unexpected error occurred.', 'danger')

    template_name = 'adjust_stock_cashier.html' if is_cashier else 'adjust_stock_admin.html'
    allowed_types = ['addition', 'returned'] if is_cashier else [e.value for e in AdjustmentType]

    return render_template(template_name, product=product, allowed_types=allowed_types, shop=shop)


@inventory_bp.route('/shops/<int:shop_id>/products/<int:product_id>/details-fragment')
@login_required
@shop_access_required
def product_details_fragment(shop_id, product_id):
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    return render_template('fragments/product_details.html', product=product)



@inventory_bp.route('/shops/<int:shop_id>/stock-logs', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def stock_logs(shop_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    logs = db.session.query(
        StockLog,
        Product.name.label('product_name'),
        User.username.label('user_name')
    ).join(Product).join(Category).join(User).filter(
        Category.shop_id == shop_id
    ).order_by(StockLog.date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    if request.headers.get('HX-Request'):
        return render_template('admin/fragments/_stock_logs_table.html', logs=logs, shop_id=shop_id)

    return render_template(
        'auth/admin_dashboard.html',
        fragment_template='admin/fragments/_stock_logs_table.html',
        logs=logs,
        shop_id=shop_id
    )



@inventory_bp.route('/shops/<int:shop_id>/api/stock-logs', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def get_stock_logs(shop_id):
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)

        paginated_logs = db.session.query(
            StockLog,
            Product.name.label('product_name'),
            User.username.label('user_name')
        ).join(Product).join(Category).join(User).filter(
            Category.shop_id == shop_id
        ).order_by(StockLog.date.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

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
