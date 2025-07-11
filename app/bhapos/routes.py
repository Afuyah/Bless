from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func, case
from app.models import User, Business, Role, Shop, BusinessStatus, Sale, Product, RegisterSession, CartItem, StockLog
from app.bhapos.forms import CreateBusinessForm, CreateTenantForm, CreateShopForm, CreateUserForm
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app import db, csrf
import logging
import re

bhapos_bp = Blueprint('bhapos', __name__)



import random
import string

def generate_temp_password(length=10):
    """Generate a temporary password with letters and digits."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choices(characters, k=length))

@bhapos_bp.route('/superadmin/dashboard')
@login_required
def superadmin_dashboard():
    if not current_user.is_superadmin():
        flash('Access denied: Superadmin only.', 'danger')
        return redirect(url_for('home.index'))

    # Get counts using single query for performance
    stats = db.session.query(
        db.func.count(Business.id).label('total_businesses'),
        db.func.count(db.distinct(User.id)).filter(User.role == Role.TENANT).label('total_tenants'),
        db.func.count(Business.id).filter(
            Business.is_approved == False,
            Business.is_deleted == False
        ).label('pending_businesses'),
        db.func.count(Business.id).filter(
            Business.status == BusinessStatus.ACTIVE
        ).label('active_businesses')
    ).first()

    # Get recent businesses with optimized loading
    recent_businesses = db.session.query(Business).outerjoin(
        User, db.and_(
            User.business_id == Business.id,
            User.role == Role.TENANT
        )
    ).options(
        db.contains_eager(Business.users, alias=User)
    ).order_by(
        Business.created_at.desc()
    ).limit(5).all()

    # Get business status distribution
    status_counts = dict(db.session.query(
        Business.status,
        db.func.count(Business.id)
    ).group_by(Business.status).all())

    return render_template('bhapos/superadmin_dashboard.html',
        total_businesses=stats.total_businesses,
        total_tenants=stats.total_tenants,
        pending_businesses=stats.pending_businesses,
        active_businesses=stats.active_businesses,
        recent_businesses=recent_businesses,
        status_counts=status_counts,
        BusinessStatus=BusinessStatus,
        now=datetime.utcnow()  
    )



@bhapos_bp.route('/users')
@login_required
def list_users():
    if not current_user.is_superadmin():
        flash('Access denied: Superadmin only.', 'danger')
        return redirect(url_for('home.index'))

    role = request.args.get('role')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    query = User.query.filter_by(is_deleted=False)
    
    if role and role.upper() in Role.__members__:
        query = query.filter_by(role=Role[role.upper()])
    
    users = query.options(
        db.joinedload(User.business)
    ).order_by(
        User.created_at.desc()
    ).paginate(page=page, per_page=per_page)

    return render_template('bhapos/users_list.html',
        users=users,
        role=role,
        Role=Role
    )


@bhapos_bp.route('/businesses/pending')
@login_required
def pending_businesses():
    if not current_user.is_superadmin():
        flash('Access denied: Superadmin only.', 'danger')
        return redirect(url_for('home.index'))

    page = request.args.get('page', 1, type=int)
    per_page = 10

    pending = Business.query.filter(
        Business.is_approved == False,
        Business.is_deleted == False
    ).options(
        db.joinedload(Business.users)
    ).order_by(
        Business.created_at.desc()
    ).paginate(page=page, per_page=per_page)

    return render_template('bhapos/pending_businesses.html',
        businesses=pending
    )



@bhapos_bp.route('/businesses/<int:id>', methods=['GET'])
@login_required
def view_business(id):
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.options(
        db.joinedload(Business.users),
        db.joinedload(Business.shops),
        db.joinedload(Business.approved_by)
    ).get_or_404(id)

    return render_template('bhapos/view_business.html', 
                         business=business,
                         BusinessStatus=BusinessStatus)


@bhapos_bp.route('/business/create', methods=['GET', 'POST'])
@login_required
def create_business():
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    form = CreateBusinessForm()
    if form.validate_on_submit():
        if Business.query.filter(db.or_(
            Business.name == form.name.data,
            Business.email == form.email.data
        )).first():
            flash('Business with this name or email already exists.', 'warning')
        else:
            new_business = Business(
                name=form.name.data,
                email=form.email.data,
                phone=form.phone.data,
                registration_number=form.registration_number.data,
                tax_identification=form.tax_id.data,
                address=form.address.data,
                city=form.city.data,
                country=form.country.data
            )
            db.session.add(new_business)
            db.session.commit()
            
            # Create initial tenant if email was provided
            if form.email.data:
                tenant = create_initial_tenant(new_business, form.email.data)
                flash(f'Business created successfully! Initial tenant account created for {tenant.username}', 'success')
            else:
                flash('Business created successfully! Please add a tenant account.', 'success')
                
            return redirect(url_for('bhapos.view_business', id=new_business.id))

    return render_template('bhapos/create_business.html', form=form)

def create_initial_tenant(business, email):
    """Helper function to create initial tenant user"""
    username = email.split('@')[0]
    tenant = User(
        username=username,
        email=email,
        role=Role.TENANT,
        business=business
    )
    # Generate random password
    temp_password = generate_temp_password()
    tenant.set_password(temp_password)
    db.session.add(tenant)
    
    # Send welcome email with temp password (implementation omitted)
    # send_welcome_email(email, username, temp_password)
    
    return tenant


@bhapos_bp.route('/business/<int:business_id>/create-tenant', methods=['GET', 'POST'])
@login_required
def create_tenant(business_id):
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.get_or_404(business_id)
    form = CreateTenantForm()

    if request.method == 'POST' and form.validate_on_submit():
        try:
            tenant = User(
                username=form.username.data.lower(),
                email=form.email.data if form.email.data else None,
                role=Role.TENANT,
                business_id=business.id,
                
            )
            tenant.set_password(form.password.data)
            db.session.add(tenant)

            if not business.users:
                business.is_approved = True
                business.status = BusinessStatus.ACTIVE
                business.approved_at = datetime.utcnow()
                business.approved_by_id = current_user.id
                db.session.add(business)

            db.session.commit()

            # Send welcome email
            if form.send_welcome_email.data == 'yes' and tenant.email:
                try:
                    send_welcome_email(
                        recipient=tenant.email,
                        username=tenant.username,
                        business_name=business.name
                    )
                    flash('Welcome email sent successfully', 'info')
                except Exception as e:
                    current_app.logger.error(f"Failed to send welcome email: {str(e)}")
                    flash('Tenant created but welcome email failed to send', 'warning')

            flash('Tenant account created successfully!', 'success')
            return redirect(url_for('bhapos.view_business', id=business.id))

        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.error(f"Database integrity error: {str(e)}")
            flash('Username or email already exists in database', 'danger')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating tenant: {str(e)}", exc_info=True)
            flash(f'An error occurred: {str(e)}', 'danger')

    if form.errors:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"{getattr(form, field).label.text}: {error}", 'warning')

    return render_template('bhapos/create_tenant.html', form=form, business=business)



@bhapos_bp.route('/business/<int:id>/approve', methods=['POST'])
@login_required
def approve_business(id):
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.get_or_404(id)
    notes = request.json.get('notes') if request.is_json else None
    business.approve(current_user, notes)
    db.session.commit()
    
    if request.is_json:
        return jsonify({'message': f'Business {business.name} approved successfully!'}), 200
    else:
        flash(f'Business {business.name} approved successfully!', 'success')
        return redirect(url_for('bhapos.view_business', id=id))


@bhapos_bp.route('/business/<int:id>/reject', methods=['POST'])
@login_required
def reject_business(id):
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.get_or_404(id)
    business.reject()
    db.session.commit()
    
    flash(f'Business {business.name} has been rejected', 'warning')
    return redirect(url_for('bhapos.pending_businesses'))


@bhapos_bp.route('/business/<int:id>/update-status', methods=['POST'])
@login_required
def update_business_status(id):
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.get_or_404(id)
    new_status = request.form.get('status')
    
    if new_status not in BusinessStatus.__members__:
        flash('Invalid status', 'danger')
        return redirect(url_for('bhapos.view_business', id=id))

    business.status = BusinessStatus[new_status]
    db.session.commit()
    
    flash(f'Business status updated to {new_status}', 'success')
    return redirect(url_for('bhapos.view_business', id=id))




@bhapos_bp.route('/businesses')
@login_required
def list_businesses():
    """List all businesses with filtering, sorting, and pagination"""
    if not current_user.is_superadmin():
        flash("Unauthorized access", "danger")
        return redirect(url_for('main.home'))

    # Pagination parameters
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    per_page = min(per_page, 100)  # Limit maximum items per page

    # Filter parameters
    status = request.args.get('status', type=str)
    search_term = request.args.get('search', type=str)
    sort_by = request.args.get('sort_by', 'created_at')
    sort_order = request.args.get('sort_order', 'desc')

    # Base query
    query = Business.query.filter_by(is_deleted=False)

    # Apply filters
    if status and status in BusinessStatus.__members__:
        query = query.filter(Business.status == BusinessStatus[status])
    
    if search_term:
        query = query.filter(
            db.or_(
                Business.name.ilike(f'%{search_term}%'),
                Business.email.ilike(f'%{search_term}%'),
                Business.registration_number.ilike(f'%{search_term}%')
            )
        )

    # Apply sorting
    if sort_by in ['name', 'created_at', 'status']:
        if sort_order == 'asc':
            query = query.order_by(getattr(Business, sort_by).asc())
        else:
            query = query.order_by(getattr(Business, sort_by).desc())
    else:
        query = query.order_by(Business.created_at.desc())

    # Get paginated results with tenant information
    businesses = query.options(
        db.joinedload(Business.users)
    ).paginate(page=page, per_page=per_page, error_out=False)


    # Get status counts for filter sidebar
    status_counts = db.session.query(
        Business.status,
        db.func.count(Business.id)
    ).filter_by(is_deleted=False).group_by(Business.status).all()

    return render_template(
        'bhapos/business_list.html',
        businesses=businesses,
        status_counts=dict(status_counts),
        current_filters={
            'status': status,
            'search': search_term,
            'sort_by': sort_by,
            'sort_order': sort_order
        },
        BusinessStatus=BusinessStatus
    )


@bhapos_bp.route('/tenant/dashboard')
@login_required
def tenant_dashboard():
    """
    Comprehensive Tenant Dashboard with business performance analytics.
    Provides key metrics, trends, and insights across all business shops.
    """
    # Authorization and business validation
    if not validate_tenant_access(current_user):
        return redirect(url_for('home.index'))
    
    business = current_user.business
    if not business:
        flash('No business associated with your account.', 'warning')
        return redirect(url_for('bhapos.list_businesses'))

    # Get all active shop IDs for the business
    shop_ids = get_business_shop_ids(business.id)
    
    # Time periods for analytics
    time_periods = get_analytics_time_periods()
    
    # Dashboard data sections
    dashboard_data = {
        'business_overview': get_business_overview(business, shop_ids),
        'sales_performance': get_sales_performance(business.id, shop_ids, time_periods),
        'shop_comparison': get_shop_comparison(business.id, shop_ids),
        'inventory_insights': get_inventory_insights(business.id),
        'staff_performance': get_staff_performance(business.id, shop_ids),
        'recent_activity': get_recent_activity(business.id, shop_ids),
        'time_periods': time_periods,
    }

    return render_template(
        'bhapos/tenants/tenant_dashboard.html',
        business=business.serialize(include_related=True),
        **dashboard_data,
        current_time=datetime.utcnow()

        
    )
def get_shop_transaction_counts(business_id, shop_ids, days=30):
    """
    Return a dictionary of shop_id -> transaction count for a given business over N days.
    """
    if not shop_ids:
        return {}
    
    start_date = datetime.utcnow() - timedelta(days=days)
    
    try:
        results = db.session.query(
            Shop.id,
            func.count(Sale.id).label('transaction_count')
        ).join(
            Sale, Sale.shop_id == Shop.id
        ).filter(
            Shop.id.in_(shop_ids),
            Shop.is_deleted == False,
            Sale.created_at >= start_date,
            Sale.is_deleted == False
        ).group_by(
            Shop.id
        ).order_by(
            func.count(Sale.id).desc()
        ).all()
        
        return {
            shop_id: transaction_count or 0
            for shop_id, transaction_count in results
        }

    except SQLAlchemyError as e:
        current_app.logger.error(f"Error fetching shop transaction counts: {str(e)}")
        return {}


# ======================
# VALIDATION & UTILITIES
# ======================

def validate_tenant_access(user):
    """Verify user has tenant access"""
    if user.role != Role.TENANT:
        flash('Access denied: Tenant only.', 'danger')
        return False
    return True

def get_business_shop_ids(business_id):
    """Get all active shop IDs for a business"""
    return [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]

def get_analytics_time_periods():
    """Define standard time periods for analytics"""
    now = datetime.utcnow()
    today = now.date()
    thirty_days_ago = now - timedelta(days=30)
    current_month_start = now.replace(day=1, hour=0, minute=0, second=0)
    last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
    last_month_end = current_month_start - timedelta(days=1)
    
    return {
        'today': today,
        'thirty_days_ago': thirty_days_ago,
        'current_month_start': current_month_start,
        'last_month_start': last_month_start,
        'last_month_end': last_month_end,
    }


# ======================
# DATA RETRIEVAL FUNCTIONS
# ======================

def get_business_overview(business, shop_ids):
    """Get high-level business metrics"""
    return {
        'total_shops': len(business.active_shops),
        'active_users': len(business.active_users),
        'total_products': get_product_count(business.id),
        'active_sessions': get_active_register_sessions_count(shop_ids),
    }

def get_sales_performance(business_id, shop_ids, time_periods):
    """Get comprehensive sales analytics"""
    return {
        'today': get_sales_metrics(business_id, shop_ids, time_periods['today']),
        'last_30_days': get_sales_metrics(business_id, shop_ids, time_periods['thirty_days_ago']),
        'current_month': get_sales_metrics(
            business_id, 
            shop_ids, 
            time_periods['current_month_start']
        ),
        'last_month': get_sales_metrics(
            business_id, 
            shop_ids, 
            time_periods['last_month_start'],
            time_periods['last_month_end']
        ),
        'trends': get_sales_trends(business_id, shop_ids),
        'payment_methods': get_payment_method_distribution(business_id, shop_ids),
        'hourly_patterns': get_hourly_sales_patterns(business_id, shop_ids),
    }

def get_shop_comparison(business_id, shop_ids):
    return {
        'top_performing': get_top_performing_shops(business_id, shop_ids),
        'sales_distribution': get_sales_by_shop(business_id, shop_ids),
        'profit_margins': get_shop_profit_margins(business_id, shop_ids),
        'conversion_rates': get_shop_conversion_rates(business_id, shop_ids),
        'shop_transactions': get_shop_transaction_counts(business_id, shop_ids),
    }

def get_inventory_insights(business_id):
    """Get inventory-related metrics"""
    return {
        'stock_status': get_inventory_status(business_id),
        'fast_moving': get_fast_moving_products(business_id),
        'slow_moving': get_slow_moving_products(business_id),
        'reorder_needs': get_products_needing_reorder(business_id),
    }

def get_staff_performance(business_id, shop_ids):
    """Get staff productivity metrics"""
    return {
        'top_performers': get_top_performing_staff(business_id, shop_ids),
        'sales_by_staff': get_sales_by_staff(business_id, shop_ids),
        'attendance': get_staff_attendance_metrics(business_id),
    }

def get_recent_activity(business_id, shop_ids):
    """Get recent business activity"""
    return {
        'latest_sales': get_recent_sales(business_id, shop_ids),
        'register_sessions': get_recent_register_sessions(shop_ids),
        'stock_changes': get_recent_stock_changes(business_id),
        'user_activities': get_recent_user_activities(business_id),
    }


# ======================
# DETAILED QUERY FUNCTIONS
# ======================

def get_sales_metrics(business_id, shop_ids, start_date, end_date=None):
    """Get comprehensive sales metrics for a period"""
    if not shop_ids:
        return empty_sales_metrics()
    
    query = db.session.query(
        func.sum(Sale.total).label('total_sales'),
        func.count(Sale.id).label('transaction_count'),
        func.avg(Sale.total).label('average_sale'),
        func.sum(Sale.profit).label('total_profit'),
        (func.sum(Sale.profit) / func.nullif(func.sum(Sale.total), 0) * 100).label('profit_margin'),
        func.max(Sale.total).label('largest_sale'),
        func.min(Sale.total).label('smallest_sale'),
    ).filter(
        Sale.shop_id.in_(shop_ids),
        Sale.created_at >= start_date,
        Sale.is_deleted == False
    )
    
    if end_date:
        query = query.filter(Sale.created_at <= end_date)
    
    result = query.first()
    
    return format_sales_metrics(result)

def get_sales_trends(business_id, shop_ids):
    """Get daily sales trends for the last 30 days"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        func.date(Sale.created_at).label('date'),
        func.sum(Sale.total).label('total_sales'),
        func.count(Sale.id).label('transaction_count'),
        func.sum(Sale.profit).label('total_profit'),
    ).filter(
        Sale.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False
    ).group_by(
        func.date(Sale.created_at)
    ).order_by(
        func.date(Sale.created_at)
    ).all()

def get_top_performing_shops(business_id, shop_ids):
    """Get top performing shops by sales volume"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        Shop.id,
        Shop.name,
        func.sum(Sale.total).label('total_sales'),
        func.sum(Sale.profit).label('total_profit'),
        (func.sum(Sale.profit) / func.nullif(func.sum(Sale.total), 0) * 100).label('profit_margin'),
    ).join(
        Sale, Sale.shop_id == Shop.id
    ).filter(
        Shop.id.in_(shop_ids),
        Shop.business_id == business_id,
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False
    ).group_by(
        Shop.id,
        Shop.name
    ).order_by(
        func.sum(Sale.total).desc()
    ).limit(5).all()


def get_inventory_status(business_id):
    """Get comprehensive inventory status by querying through shops"""
    # First get all shop IDs for this business
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return {
            'total_products': 0,
            'low_stock': 0,
            'out_of_stock': 0,
            'total_inventory': 0,
            'inventory_value': 0
        }
    
    # Now query products through these shop IDs
    result = db.session.query(
        func.count(Product.id).label('total_products'),
        func.sum(case((Product.stock <= 10, 1), else_=0)).label('low_stock'),
        func.sum(case((Product.stock <= 0, 1), else_=0)).label('out_of_stock'),
        func.sum(Product.stock).label('total_inventory'),
        func.sum(Product.stock * Product.selling_price).label('inventory_value'),
    ).filter(
        Product.shop_id.in_(shop_ids),  # Changed from business_id to shop_id
        Product.is_deleted == False,
        Product.is_active == True
    ).first()
    
    return {
        'total_products': result.total_products or 0,
        'low_stock': result.low_stock or 0,
        'out_of_stock': result.out_of_stock or 0,
        'total_inventory': result.total_inventory or 0,
        'inventory_value': result.inventory_value or 0,
    }


def get_fast_moving_products(business_id):
    """Get fastest moving products through business shops"""
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        Product.id.label('product_id'),
        Product.name.label('product_name'),
        func.sum(CartItem.quantity).label('total_sold')
    ).join(
        CartItem, CartItem.product_id == Product.id
    ).join(
        Sale, Sale.id == CartItem.sale_id
    ).filter(
        Product.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False,
        Product.is_deleted == False
    ).group_by(
        Product.id,
        Product.name
    ).order_by(
        func.sum(CartItem.quantity).desc()
    ).limit(5).all()


def get_slow_moving_products(business_id):
    """Get slow moving products through business shops"""
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        Product,
        func.sum(CartItem.quantity).label('total_sold')
    ).join(
        CartItem, CartItem.product_id == Product.id
    ).join(
        Sale, Sale.id == CartItem.sale_id
    ).filter(
        Product.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False,
        Product.is_deleted == False
    ).group_by(
        Product.id,
        Product.name
    ).order_by(
        func.sum(CartItem.quantity).asc()
    ).limit(5).all()



def get_products_needing_reorder(business_id):
    """Get products that need reordering through business shops"""
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return []
    
    return db.session.query(Product).filter(
        Product.shop_id.in_(shop_ids),
        Product.stock <= Product.low_stock_threshold,
        Product.is_deleted == False,
        Product.is_active == True
    ).limit(5).all()



def get_top_performing_staff(business_id, shop_ids):
    """Get top performing staff members"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        User,
        func.count(Sale.id).label('sale_count'),
        func.sum(Sale.total).label('total_sales'),
        func.sum(Sale.profit).label('total_profit'),
        (func.sum(Sale.profit) / func.nullif(func.sum(Sale.total), 0) * 100).label('profit_margin'),
    ).join(
        Sale, Sale.user_id == User.id
    ).filter(
        User.business_id == business_id,
        Sale.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False,
        User.is_deleted == False
    ).group_by(
        User.id,
        User.username
    ).order_by(
        func.sum(Sale.total).desc()
    ).limit(5).all()

def get_sales_by_staff(business_id, shop_ids):
    """Get sales performance by staff"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        User,
        func.sum(Sale.total).label('total_sales'),
        func.sum(Sale.profit).label('total_profit'),
    ).join(
        Sale, Sale.user_id == User.id
    ).filter(
        User.business_id == business_id,
        Sale.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False,
        User.is_deleted == False
    ).group_by(
        User.id,
        User.username
    ).all()

def get_staff_attendance_metrics(business_id):
    """Get staff attendance metrics (simplified placeholder implementation)"""
    # First get all users belonging to this business
    users = User.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).all()
    
    if not users:
        return {
            'total_staff': 0,
            'active_today': 0,
            'on_leave': 0
        }
    
    # Placeholder logic - replace with your actual attendance tracking
    today = datetime.utcnow().date()
    active_today_count = 0
    
    return {
        'total_staff': len(users),
        'active_today': active_today_count,
        'on_leave': 0  # Replace with actual leave tracking
    }




def get_product_count(business_id):
    """Get count of active products for a business through its shops"""
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return 0
        
    return db.session.query(func.count(Product.id)).filter(
        Product.shop_id.in_(shop_ids),
        Product.is_deleted == False,
        Product.is_active == True
    ).scalar() or 0


def get_active_register_sessions_count(shop_ids):
    """Get count of active register sessions"""
    if not shop_ids:
        return 0
    return db.session.query(func.count(RegisterSession.id)).filter(
        RegisterSession.shop_id.in_(shop_ids),
        RegisterSession.closed_at.is_(None)
    ).scalar() or 0    



def get_payment_method_distribution(business_id, shop_ids):
    """Get sales distribution by payment method"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    
    return db.session.query(
        Sale.payment_method,
        func.sum(Sale.total).label('total'),
        func.count(Sale.id).label('count'),
    ).filter(
        Sale.shop_id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False
    ).group_by(
        Sale.payment_method
    ).all()

def get_hourly_sales_patterns(business_id, shop_ids):
    """Get hourly sales patterns (placeholder - implement your business logic)"""
    if not shop_ids:
        return []
    
    return db.session.query(
        func.extract('hour', Sale.created_at).label('hour'),
        func.sum(Sale.total).label('total_sales'),
        func.count(Sale.id).label('transaction_count'),
    ).filter(
        Sale.shop_id.in_(shop_ids),
        Sale.is_deleted == False
    ).group_by(
        func.extract('hour', Sale.created_at)
    ).order_by(
        func.extract('hour', Sale.created_at)
    ).all()


def get_sales_by_shop(business_id, shop_ids):
    """Get sales distribution by shop"""
    if not shop_ids:
        return []
    
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    return db.session.query(
        Shop.id,
        Shop.name,
        func.sum(Sale.total).label('total_sales'),
        func.sum(Sale.profit).label('total_profit'),
        (func.sum(Sale.profit) / func.nullif(func.sum(Sale.total), 0) * 100).label('profit_margin'),
    ).join(
        Sale, Sale.shop_id == Shop.id
    ).filter(
        Shop.id.in_(shop_ids),
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False
    ).group_by(
        Shop.id,
        Shop.name
    ).all()



def get_shop_profit_margins(business_id, shop_ids):
    """Get profit margins by shop"""
    if not shop_ids:
        return []

    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    return db.session.query(
        Shop.id,
        Shop.name,
        (func.sum(Sale.profit) / func.nullif(func.sum(Sale.total), 0) * 100).label('profit_margin')
    ).join(
        Sale, Sale.shop_id == Shop.id
    ).join(
        Business, Shop.business_id == Business.id  # 🔧 Ensure this join is present
    ).filter(
        Shop.id.in_(shop_ids),
        Business.id == business_id,
        Sale.created_at >= thirty_days_ago,
        Sale.is_deleted == False
    ).group_by(
        Shop.id,
        Shop.name
    ).order_by(
        func.sum(Sale.profit).desc()
    ).all()


def get_shop_conversion_rates(business_id, shop_ids):
    """Get conversion rates by shop (placeholder - implement your business logic)"""
    return []

def get_recent_sales(business_id, shop_ids, limit=5):
    """Get recent sales"""
    if not shop_ids:
        return []
    
    return db.session.query(Sale).filter(
        Sale.shop_id.in_(shop_ids),
        Sale.is_deleted == False
    ).order_by(
        Sale.created_at.desc()
    ).limit(limit).all()

def get_recent_register_sessions(shop_ids, limit=5):
    """Get recent register sessions"""
    if not shop_ids:
        return []
    
    return db.session.query(RegisterSession).filter(
        RegisterSession.shop_id.in_(shop_ids),
        RegisterSession.closed_at.isnot(None)
    ).order_by(
        RegisterSession.closed_at.desc()
    ).limit(limit).all()


def get_recent_stock_changes(business_id):
    """Get recent stock changes through business shops"""
    # First get all shop IDs for this business
    shop_ids = [shop.id for shop in Shop.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).with_entities(Shop.id).all()]
    
    if not shop_ids:
        return []
    
    # Now query stock logs through these shop IDs
    return db.session.query(StockLog).filter(
        StockLog.shop_id.in_(shop_ids)  # Changed from business_id to shop_id
    ).order_by(
        StockLog.created_at.desc()
    ).limit(5).all()      


def get_recent_user_activities(business_id, limit=5):
    """Get recent user activities (placeholder)"""
    return User.query.filter_by(
        business_id=business_id,
        is_deleted=False
    ).order_by(
        User.last_login.desc()
    ).limit(limit).all()
    
# ======================
# HELPER FUNCTIONS
# ======================

def empty_sales_metrics():
    """Return empty metrics structure"""
    return {
        'total_sales': 0,
        'transaction_count': 0,
        'average_sale': 0,
        'total_profit': 0,
        'profit_margin': 0,
        'largest_sale': 0,
        'smallest_sale': 0,
    }

def format_sales_metrics(result):
    """Format raw sales metrics query result"""
    return {
        'total_sales': result.total_sales or 0,
        'transaction_count': result.transaction_count or 0,
        'average_sale': round(float(result.average_sale or 0), 2),
        'total_profit': result.total_profit or 0,
        'profit_margin': round(float(result.profit_margin or 0), 2),
        'largest_sale': result.largest_sale or 0,
        'smallest_sale': result.smallest_sale or 0,
    }




@bhapos_bp.route('/business/<int:business_id>/create-shop', methods=['GET', 'POST'])
@login_required
def create_shop(business_id):
    business = Business.query.get_or_404(business_id)

    if not current_user.is_tenant() or current_user.business_id != business.id:
        flash("Unauthorized", "danger")
        return redirect(url_for('bhapos.tenant_dashboard'))

    form = CreateShopForm()
    if form.validate_on_submit():
        shop = Shop(
            name=form.name.data,
            location=form.location.data,
            business=business
        )
        db.session.add(shop)
        db.session.commit()
        flash('Shop created successfully.', 'success')
        return redirect(url_for('bhapos.tenant_dashboard'))

    return render_template('bhapos/tenants/create_shop.html', form=form, business=business)

@bhapos_bp.route('/tenant/<int:business_id>/create-user', methods=['GET', 'POST'])
@login_required
def create_user(business_id):
    if current_user.role != Role.TENANT:
        flash("Unauthorized", "danger")
        return redirect(url_for('main.home'))

    business = Business.query.get_or_404(business_id)

    if business.id != current_user.business_id:
        flash("Access denied: Not your business", "danger")
        return redirect(url_for('bhapos.tenant_dashboard'))

    form = CreateUserForm()

    allowed_roles = [role for role in Role if role not in [Role.SUPERADMIN, Role.TENANT]]
    form.role.choices = [(role.name, role.name.title()) for role in allowed_roles]

    shops = business.shops
    form.shop_id.choices = [(0, '-- Select Shop (Optional) --')] + [(shop.id, shop.name) for shop in shops]

    if form.validate_on_submit():
        existing_user = User.query.filter_by(username=form.username.data.lower()).first()
        if existing_user:
            flash("Username already exists", "warning")
        else:
            selected_shop_id = form.shop_id.data
            shop_id = selected_shop_id if selected_shop_id != 0 else None

            new_user = User(
                username=form.username.data.lower(),
                role=Role[form.role.data],
                business_id=business.id,
                shop_id=shop_id
            )
            new_user.set_password(form.password.data)
            db.session.add(new_user)
            db.session.commit()
            flash("User created", "success")
            return redirect(url_for('bhapos.tenant_dashboard'))

    return render_template('bhapos/tenants/create_user.html', form=form, business=business)


@bhapos_bp.route('/business/<int:business_id>/inventory')
@login_required
def inventory(business_id):
    """Inventory management view"""
    if current_user.role != Role.TENANT:
        flash('Access denied: Tenant only.', 'danger')
        return redirect(url_for('home.index'))
    
    business = Business.query.get_or_404(business_id)
    # Add your inventory query logic here
    return render_template('bhapos/inventory.html', business=business)



# Deactivate User
@bhapos_bp.route('/tenant/user/<int:user_id>/deactivate')
@login_required
def deactivate_user(user_id):
    if current_user.role != Role.TENANT:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)
    if user.business_id != current_user.business_id:
        flash("User does not belong to your business.", "warning")
        return redirect(url_for('bhapos.tenant_dashboard'))

    user.is_deleted = True
    db.session.commit()
    flash(f"User {user.username} deactivated.", "info")
    return redirect(url_for('bhapos.tenant_dashboard'))

# Activate User
@bhapos_bp.route('/tenant/user/<int:user_id>/activate')
@login_required
def activate_user(user_id):
    if current_user.role != Role.TENANT:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)
    if user.business_id != current_user.business_id:
        flash("User does not belong to your business.", "warning")
        return redirect(url_for('bhapos.tenant_dashboard'))

    user.is_deleted = False
    db.session.commit()
    flash(f"User {user.username} activated.", "success")
    return redirect(url_for('bhapos.tenant_dashboard'))

# Soft Delete (Optional: Permanent Deletion Redirect)
@bhapos_bp.route('/tenant/user/<int:user_id>/delete')
@login_required
def delete_user(user_id):
    if current_user.role != Role.TENANT:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('main.home'))

    user = User.query.get_or_404(user_id)
    if user.business_id != current_user.business_id:
        flash("User does not belong to your business.", "warning")
        return redirect(url_for('bhapos.tenant_dashboard'))

    user.is_deleted = True  # soft delete
    db.session.commit()
    flash(f"User {user.username} marked as deleted.", "warning")
    return redirect(url_for('bhapos.tenant_dashboard'))


@bhapos_bp.route('/tenant/shop/<int:shop_id>/users')
@login_required
def manage_shop_users(shop_id):
    if not current_user.is_authenticated or current_user.role != Role.TENANT:
        flash("Unauthorized access.", "danger")
        return redirect(url_for('main.home'))

    shop = Shop.query.get_or_404(shop_id)

    # Ensure tenant owns this shop through the business
    if shop.business_id != current_user.business_id:
        flash("You do not have access to this shop.", "warning")
        return redirect(url_for('bhapos.tenant_dashboard'))

    users = User.query.filter_by(shop_id=shop.id).all()

    return render_template('bhapos/tenants/manage_shop_users.html', shop=shop, users=users)


@bhapos_bp.route('/tenant/shops')
@login_required
def tenant_shops():
    if current_user.role != Role.TENANT:
        abort(403)
    
    business = current_user.business
    if not business:
        flash("No business is associated with your account.", "warning")
        return redirect(url_for('home.index'))

    try:
        shops = Shop.query.filter_by(business_id=business.id, is_deleted=False).all()
    except SQLAlchemyError as e:
        db.session.rollback()
        logger.error(f"Error fetching shops: {e}", exc_info=True)
        flash("Unable to load shops at the moment.", "danger")
        shops = []

    return render_template('bhapos/tenants/shops.html', business=business, shops=shops)

