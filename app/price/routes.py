from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app
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

price_bp = Blueprint('price', __name__)



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
                        old_combo=None, new_combo=None, shop_id=None):
    """Record price changes in the audit log with optional shop context"""
    change = PriceChange(
        product_id=product_id,
        user_id=user_id,
        shop_id=shop_id,  # Optional: only if your model includes it
        change_type=change_type,
        old_price=old_price,
        new_price=new_price,
        old_combo_size=old_combo[0] if old_combo else None,
        old_combo_price=old_combo[1] if old_combo else None,
        new_combo_size=new_combo[0] if new_combo else None,
        new_combo_price=new_combo[1] if new_combo else None
    )
    db.session.add(change)


@csrf.exempt
@price_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_selling_price', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_selling_price(shop_id, product_id):
    """Update product selling price with comprehensive validation"""
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    is_htmx = request.headers.get('HX-Request') == 'true'

    try:
        data = request.get_json(silent=True) or request.form
        new_selling_price = parse_decimal(data.get('selling_price'))
        combination_size = parse_int(data.get('combination_size'))
        combination_price = parse_decimal(data.get('combination_price'))

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
            # continue without failing

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
            'product': product.to_dict()
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



@csrf.exempt
@price_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_cost_price', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_cost_price(shop_id, product_id):
    """Update product cost price for a given shop"""
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    is_htmx = request.headers.get('HX-Request') == 'true'

    try:
        data = request.get_json(silent=True) or request.form
        raw_cost = data.get('cost_price')
        if raw_cost is None or raw_cost.strip() == '':
            raise BadRequest('Cost price is required')

        try:
            new_cost_price = Decimal(raw_cost.strip().replace(',', ''))
        except InvalidOperation:
            raise InvalidOperation()

        if new_cost_price < 0:
            raise BadRequest('Cost price cannot be negative')

        # Record price history before updating
        record_price_change(
            product_id=product.id,
            user_id=current_user.id,
            change_type='cost_price_update',
            old_price=product.cost_price,
            new_price=new_cost_price,
            shop_id=shop_id
        )

        product.cost_price = new_cost_price
        db.session.commit()
        db.session.refresh(product)

        if is_htmx:
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



@csrf.exempt
@price_bp.route('/shops/<int:shop_id>/products/<int:product_id>/update_pricing', methods=['POST'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def update_product_pricing(shop_id, product_id):
    """Unified endpoint for updating product cost, selling, and bundle pricing within a shop"""
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    is_htmx = request.headers.get('HX-Request') == 'true'

    try:
        data = request.get_json(silent=True) or request.form

        # Parse inputs
        cost_price = parse_decimal(data.get('cost_price'))
        selling_price = parse_decimal(data.get('selling_price'))
        combo_size = parse_int(data.get('combination_size'))
        combo_price = parse_decimal(data.get('combination_price'))
        combo = (combo_size, combo_price) if combo_size and combo_price else None

        # Ensure at least one update is provided
        if all(v is None for v in [cost_price, selling_price, combo]):
            raise BadRequest('No pricing updates provided.')

        # Validation
        base_cost = cost_price or product.cost_price

        if selling_price is not None and selling_price < base_cost:
            raise BadRequest('Selling price cannot be below cost price.')

        if combo:
            unit_price = combo_price / combo_size
            if unit_price < base_cost:
                raise BadRequest('Bundle unit price cannot be below cost price.')

        # Perform update (assumes product model has `.update_pricing(...)` method)
        if product.update_pricing(
            new_cost=cost_price,
            new_selling=selling_price,
            new_combo=combo,
            user_id=current_user.id,
            shop_id=shop_id  # Optional if needed by the audit log
        ):
            db.session.commit()
            return success_response(product, 'Prices updated', is_htmx)

        return success_response(product, 'No changes made', is_htmx)

    except (BadRequest, ValueError) as e:
        db.session.rollback()
        return error_response(str(e), 400, is_htmx)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"[Pricing Error] {str(e)}", exc_info=True)
        return error_response('Price update failed. Please try again.', 500, is_htmx)



@price_bp.route('/shops/<int:shop_id>/price_fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def price_fragment(shop_id):
    products = Product.query.join(Category).filter(Category.shop_id == shop_id).order_by(Product.name.asc()).limit(50).all()

    if request.headers.get('HX-Request'):
        return render_template('admin/fragments/price_fragment.html', products=products, shop_id=shop_id)
    else:
        return render_template(
            'auth/admin_dashboard.html',
            fragment_template='admin/fragments/price_fragment.html',
            products=products,
            shop_id=shop_id
        )


@price_bp.route('/shops/<int:shop_id>/price_rows_fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def price_rows_fragment(shop_id):
    products = Product.query.join(Category).filter(Category.shop_id == shop_id).order_by(Product.name.asc()).limit(50).all()
    return render_htmx('admin/fragments/_price_rows.html', products=products, shop_id=shop_id)


@price_bp.route('/shops/<int:shop_id>/products/<int:product_id>/edit_selling_price_form', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def edit_selling_price_form(shop_id, product_id):
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    return render_template('admin/fragments/_edit_selling_price_form.html', product=product, shop_id=shop_id)


@price_bp.route('/shops/<int:shop_id>/products/<int:product_id>/edit_cost_price_form', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def edit_cost_price_form(shop_id, product_id):
    product = Product.query.join(Category).filter(
        Product.id == product_id,
        Category.shop_id == shop_id
    ).first_or_404()

    return render_template('admin/fragments/_edit_cost_price_form.html', product=product, shop_id=shop_id)


@price_bp.route('/shops/<int:shop_id>/search_products', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def search_products(shop_id):
    query = request.args.get('query', '')
    base_query = Product.query.join(Category).filter(Category.shop_id == shop_id)

    if query:
        base_query = base_query.filter(
            Product.name.ilike(f'%{query}%') |
            Product.sku.ilike(f'%{query}%')
        )

    products = base_query.order_by(Product.name.asc()).limit(50).all()

    return render_template('admin/fragments/_price_rows.html', products=products, shop_id=shop_id)
