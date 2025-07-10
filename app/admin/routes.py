from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session, current_app, abort
from flask_login import login_user, logout_user, current_user, login_required
from sqlalchemy import func
from app.models import User, db, Role, Sale, Product, Category, StockLog, CartItem, Shop, Business
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta, datetime
from sqlalchemy.exc import SQLAlchemyError
from app.utils.render import render_htmx
from urllib.parse import urlparse, urljoin
import logging
from app import db, csrf, role_required, shop_access_required, business_access_required
admin_bp = Blueprint('admin', __name__)

# Create a logger instance
logger = logging.getLogger(__name__)


def prepare_dashboard_data(shop_id):
    """Prepare admin dashboard data scoped to a specific shop"""
    dashboard_data = {
        'sales_data': {
            'today': 0, 'yesterday': 0, 'week': 0, 'month': 0,
            'change': 0, 'total_revenue': 0, 'transactions': 0,
            'chart_labels': [], 'chart_values': []
        },
        'inventory_data': {
            'low_stock': {'count': 0, 'critical': 0, 'products': []},
            'total_value': 0, 'category_count': 0, 'product_count': 0,
            'recent_logs': 0
        },
        'system_data': {
            'users': {'total': 0, 'active': 0, 'admins': 0}
        },
        'transactions': {
            'recent': [], 'payment_methods': []
        },
        'products': {
            'top_selling': [], 'recently_added': []
        }
    }

    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # --- SALES DATA ---
    dashboard_data['sales_data']['today'] = db.session.query(func.sum(Sale.total)).filter(
        Sale.shop_id == shop_id, func.date(Sale.date) == today
    ).scalar() or 0

    dashboard_data['sales_data']['yesterday'] = db.session.query(func.sum(Sale.total)).filter(
        Sale.shop_id == shop_id, func.date(Sale.date) == yesterday
    ).scalar() or 0

    dashboard_data['sales_data']['week'] = db.session.query(func.sum(Sale.total)).filter(
        Sale.shop_id == shop_id, func.date(Sale.date) >= week_ago
    ).scalar() or 0

    dashboard_data['sales_data']['month'] = db.session.query(func.sum(Sale.total)).filter(
        Sale.shop_id == shop_id, func.date(Sale.date) >= month_ago
    ).scalar() or 0

    dashboard_data['sales_data']['total_revenue'] = db.session.query(func.sum(Sale.total)).filter(
        Sale.shop_id == shop_id
    ).scalar() or 0

    dashboard_data['sales_data']['transactions'] = Sale.query.filter_by(shop_id=shop_id).count()

    if dashboard_data['sales_data']['yesterday'] > 0:
        dashboard_data['sales_data']['change'] = (
            (dashboard_data['sales_data']['today'] - dashboard_data['sales_data']['yesterday']) /
            dashboard_data['sales_data']['yesterday']
        ) * 100

    # --- SALES CHART (last 30 days) ---
    sales_chart_data = db.session.query(
        func.date(Sale.date).label('sale_date'),
        func.sum(Sale.total).label('daily_total')
    ).filter(
        Sale.shop_id == shop_id, func.date(Sale.date) >= month_ago
    ).group_by(func.date(Sale.date)).order_by(func.date(Sale.date)).all()

    chart_map = {str(row.sale_date): float(row.daily_total or 0) for row in sales_chart_data}
    for n in range(30):
        day = today - timedelta(days=n)
        label = day.strftime('%b %d')
        dashboard_data['sales_data']['chart_labels'].append(label)
        dashboard_data['sales_data']['chart_values'].append(chart_map.get(str(day), 0))
    dashboard_data['sales_data']['chart_labels'].reverse()
    dashboard_data['sales_data']['chart_values'].reverse()

    # --- INVENTORY DATA ---
    dashboard_data['inventory_data']['low_stock']['count'] = Product.query.filter_by(shop_id=shop_id).filter(
        Product.stock <= 10
    ).count()

    dashboard_data['inventory_data']['low_stock']['critical'] = Product.query.filter_by(shop_id=shop_id).filter(
        Product.stock <= 5
    ).count()

    dashboard_data['inventory_data']['low_stock']['products'] = Product.query.filter_by(shop_id=shop_id).filter(
        Product.stock <= 10
    ).order_by(Product.stock.asc()).limit(5).all()

    dashboard_data['inventory_data']['total_value'] = db.session.query(
        func.sum(Product.stock * Product.cost_price)
    ).filter_by(shop_id=shop_id).scalar() or 0

    dashboard_data['inventory_data']['category_count'] = Category.query.filter_by(shop_id=shop_id).count()
    dashboard_data['inventory_data']['product_count'] = Product.query.filter_by(shop_id=shop_id).count()
    dashboard_data['inventory_data']['recent_logs'] = StockLog.query.filter_by(shop_id=shop_id).filter(
        StockLog.date >= datetime.now() - timedelta(days=7)
    ).count()

    # --- SYSTEM USERS ---
    dashboard_data['system_data']['users']['total'] = User.query.filter_by(shop_id=shop_id).count()
    dashboard_data['system_data']['users']['active'] = User.query.filter_by(shop_id=shop_id, is_active=True).count()
    dashboard_data['system_data']['users']['admins'] = User.query.filter_by(shop_id=shop_id, role=Role.ADMIN).count()

    # --- RECENT TRANSACTIONS ---
    dashboard_data['transactions']['recent'] = Sale.query.options(
        db.joinedload(Sale.cart_items).joinedload(CartItem.product)
    ).filter_by(shop_id=shop_id).order_by(Sale.date.desc()).limit(5).all()

    dashboard_data['transactions']['payment_methods'] = db.session.query(
        Sale.payment_method,
        func.count(Sale.id),
        func.sum(Sale.total)
    ).filter(
        Sale.shop_id == shop_id,
        func.date(Sale.date) >= month_ago
    ).group_by(Sale.payment_method).all()

    # --- PRODUCT DATA ---
    dashboard_data['products']['top_selling'] = db.session.query(
        Product.id,
        Product.name,
        Product.image_url,
        Product.selling_price,
        func.sum(CartItem.quantity).label('total_quantity'),
        func.sum(CartItem.quantity * Product.selling_price).label('total_sales')
    ).join(
        CartItem, Product.id == CartItem.product_id
    ).join(
        Sale, Sale.id == CartItem.sale_id
    ).filter(
        Sale.shop_id == shop_id,
        Product.shop_id == shop_id,
        func.date(Sale.date) >= month_ago
    ).group_by(
        Product.id, Product.name, Product.image_url, Product.selling_price
    ).order_by(
        func.sum(CartItem.quantity).desc()
    ).limit(5).all()

    dashboard_data['products']['recently_added'] = Product.query.filter_by(shop_id=shop_id).order_by(
        Product.created_at.desc()).limit(3).all()

    dashboard_data['chart_labels'] = dashboard_data['sales_data']['chart_labels']
    dashboard_data['chart_values'] = dashboard_data['sales_data']['chart_values']

    monthly_revenue = dashboard_data['sales_data']['month']
    return dashboard_data, monthly_revenue

def render_admin_dashboard_fragment(shop_id):
    dashboard_data, monthly_revenue = prepare_dashboard_data(shop_id)
    return render_template(
        'admin/fragments/_admin_fragment.html',
        date=date,
        datetime=datetime,
        monthly_revenue=monthly_revenue,
        **dashboard_data
    )



@admin_bp.route('/shops/<int:shop_id>/admin_dashboard', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def admin_dashboard(shop_id):
    try:
        logger.info(f"Admin dashboard accessed by user {current_user.username} for shop {shop_id}")

        if request.headers.get("HX-Request"):
            return render_admin_dashboard_fragment(shop_id)

        dashboard_data, monthly_revenue = prepare_dashboard_data(shop_id)
        return render_template(
            'auth/admin_dashboard.html',
            shop_id=shop_id,
            fragment_template='admin/fragments/_admin_fragment.html',
            date=date,
            datetime=datetime,
            monthly_revenue=monthly_revenue,
            **dashboard_data
        )

    except SQLAlchemyError as e:
        logger.error(f"Database error in admin dashboard: {str(e)}", exc_info=True)
        flash("Database error loading dashboard", "danger")
        abort(500)
    except Exception as e:
        logger.error(f"Unexpected error in admin dashboard: {str(e)}", exc_info=True)
        flash("Error loading dashboard", "danger")
        abort(500)


@admin_bp.route('/shops/<int:shop_id>/admin_dashboard/fragment', methods=['GET'])
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def admin_dashboard_fragment(shop_id):
    logger.info(f"Admin dashboard fragment requested for shop {shop_id} by user {current_user.username}")
    try:
        return render_admin_dashboard_fragment(shop_id)
    except Exception as e:
        logger.error(f"Error rendering admin dashboard fragment: {str(e)}", exc_info=True)
        return render_template(
            'admin/fragments/_error.html',
            message="Failed to load dashboard content"
        ), 500



@admin_bp.route('/shops/<int:shop_id>/sales_chart_data')
@login_required
@shop_access_required
@role_required(Role.ADMIN, Role.TENANT)
def sales_chart_data(shop_id):
    """Return sales chart data for a specific shop"""
    range = request.args.get('range', 'month')
    today = date.today()

    # Supported date ranges and formatting
    range_config = {
        'week': {'days': 6, 'format': '%a %d'},
        'year': {'days': 365, 'format': '%b %Y'},
        'month': {'days': 30, 'format': '%b %d'}
    }

    config = range_config.get(range, range_config['month'])
    start_date = today - timedelta(days=config['days'])
    label_format = config['format']

    try:
        # Query sales data scoped by shop
        sales_data = db.session.query(
            func.date(Sale.date).label('sale_date'),
            func.sum(Sale.total).label('daily_total')
        ).filter(
            Sale.shop_id == shop_id,
            func.date(Sale.date) >= start_date
        ).group_by(
            func.date(Sale.date)
        ).order_by(
            func.date(Sale.date)
        ).all()

        chart_labels = []
        chart_values = []

        for row in sales_data:
            try:
                date_obj = (
                    datetime.strptime(row.sale_date, '%Y-%m-%d').date()
                    if isinstance(row.sale_date, str)
                    else row.sale_date
                )
                chart_labels.append(date_obj.strftime(label_format))
                chart_values.append(float(row.daily_total or 0))
            except (ValueError, AttributeError) as e:
                current_app.logger.error(f"Error processing sale_date row: {e}")
                continue

        return render_template(
            'reports/fragments/sales_chart.html',
            chart_labels=chart_labels,
            chart_values=chart_values
        )

    except Exception as e:
        current_app.logger.error(f"Error generating sales chart data: {e}", exc_info=True)
        return render_template(
            'reports/fragments/sales_chart.html',
            chart_labels=[],
            chart_values=[]
        )


