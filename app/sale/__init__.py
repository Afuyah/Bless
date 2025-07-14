from flask import Blueprint, jsonify, current_app
from . import controllers, sockets
from .schemas import ReceiptSchema, ProductSearchSchema
from app import  shop_access_required, role_required, csrf
from ..models import Role
from flask_login import login_required
from .repositories import RegisterSessionRepository
from .services import SalesService
from .controllers import (
    SalesController,
    TransactionController,
    ReceiptController,
    ProductAPIController,         
    ProductSearchAPIController,   
    CategoryAPIController,
    RegisterCloseAPI,
    RegisterHistoryAPI,
    RegisterOpenAPI          
)
from decimal import Decimal

# Create the blueprints
sales_bp = Blueprint('sales', __name__, url_prefix='/shops/<int:shop_id>')
api_bp = Blueprint('sales_api', __name__, url_prefix='/api/shops/<int:shop_id>')

# HTML View Routes
sales_bp.add_url_rule(
    '/sales',
    view_func=controllers.SalesController.as_view('sales_screen'),
    methods=['GET']
)

sales_bp.add_url_rule(
    '/transactions',
    view_func=controllers.TransactionController.as_view('transaction_history'),
    methods=['GET', 'POST']
)
sales_bp.add_url_rule(
    '/receipts',
    view_func=controllers.ReceiptController.as_view('receipt_generation'),
    methods=['GET']
)

api_bp.add_url_rule(
    '/products',
    view_func=ProductAPIController.as_view('products_api'),
    methods=['GET']
)

api_bp.add_url_rule(
    '/products/search',
    view_func=ProductSearchAPIController.as_view('products_search_api'),
    methods=['POST']
)

api_bp.add_url_rule(
    '/categories',
    view_func=CategoryAPIController.as_view('categories_api'),
    methods=['GET']
)



api_bp.add_url_rule(
    '/transactions/recent',
    view_func=controllers.TransactionController.as_view('recent_transactions_api'),
    methods=['GET']
)

# Transaction API
api_bp.add_url_rule(
    '/transactions',
    view_func=controllers.TransactionController.as_view('transaction_create_api'),
    methods=['POST']
)

# API Receipt endpoint 
api_bp.add_url_rule(
    '/receipts',
    view_func=controllers.ReceiptController.as_view('receipt_api'),
    methods=['GET']
)

#sales summary api

api_bp.add_url_rule(
    '/sales/summary',
    view_func=controllers.RegisterSummaryAPI.as_view('sales_summary_api'),
    methods=['GET']
)


# Historical register sessions
api_bp.add_url_rule(
    '/register/history',
    view_func=RegisterHistoryAPI.as_view('register_history_api'),
    methods=['GET']
)

# Open register
api_bp.add_url_rule(
    '/register/open',
    view_func=RegisterOpenAPI.as_view('register_open_api'),
    methods=['POST']
)

# Close register
api_bp.add_url_rule(
    '/register/close',
    view_func=RegisterCloseAPI.as_view('register_close_api'),
    methods=['PUT']
)




@api_bp.route('/shop-info')
@login_required
@shop_access_required
def get_shop_info(shop_id):
    """Endpoint for getting basic shop information"""
    from ..models import Shop
    shop = Shop.query.get_or_404(shop_id)
    return jsonify({
        'id': shop.id,
        'name': shop.name,
        'location': shop.location,
        'currency': shop.currency,
        'logo_url': shop.logo_url
    })



@api_bp.route('/register/status')
@login_required
@shop_access_required
def check_register_status(shop_id):
    from .repositories import RegisterSessionRepository
    session = RegisterSessionRepository.get_open_session(shop_id)
    return jsonify({
        'is_open': bool(session),
        'session_id': session.id if session else None,
        'opened_at': session.opened_at.isoformat() if session else None,
        'opened_by': session.opened_by.username if session else None
    })

@api_bp.route('/register/summary')
@login_required
@shop_access_required
def register_summary(shop_id):
    from decimal import Decimal
    from .repositories import RegisterSessionRepository, SaleRepository
    
    try:
        session = RegisterSessionRepository.get_open_session(shop_id)
        if not session:
            return jsonify({
                'success': True,
                'is_open': False,
                'message': 'Register is currently closed'
            }), 200

        total_sales = SaleRepository.get_session_sales_total(session.id)
        opening_cash = Decimal(str(session.opening_cash))
        expected_cash = opening_cash + total_sales
        recent_sales = SaleRepository.get_recent_sales(shop_id, session_id=session.id)
        
        return jsonify({
            'success': True,
            'is_open': True,
            'summary': {
                'session_id': session.id,
                'opened_at': session.opened_at.isoformat(),
                'opened_by': session.opened_by.username if session.opened_by else None,

                'opening_cash': float(opening_cash),
                'total_sales': float(total_sales),
                'expected_cash': float(expected_cash),
                'sales_count': len(recent_sales),
                'total_tax': sum(float(sale.tax) for sale in recent_sales),
            },
            'recent_sales': [{
                'id': sale.id,
                'total': float(sale.total),
                'date': sale.date.isoformat(),
                'payment_method': sale.payment_method
            } for sale in recent_sales]
        }), 200

    except Exception as e:
        current_app.logger.error(f"Register summary error: {str(e)}")
        return jsonify({
            'success': False,
            'error': 'Failed to get register summary'
        }), 500



@api_bp.route('/register/info')
@login_required
@shop_access_required
def get_register_info(shop_id):
    

    session = RegisterSessionRepository.get_open_session(shop_id)
    if not session:
        return jsonify({'is_open': False})
    
    summary = SalesService.get_register_summary(shop_id, session.id)

    return jsonify({
        'is_open': True,
        'session_id': session.id,
        'opened_by': session.opened_by.username,
        'opened_at': session.opened_at.isoformat(),
        'summary': summary
    })




@csrf.exempt
@api_bp.route('/register/close', methods=['PUT'])
@login_required
@shop_access_required
def close_register(shop_id):
    from .repositories import SaleRepository, RegisterSessionRepository

    try:
        data = request.get_json()

        session = RegisterSessionRepository.get_open_session(shop_id)
        if not session:
            return jsonify({'error': 'No open register session'}), 404

        try:
            closing_cash = Decimal(str(data['closing_cash']))
            if closing_cash < 0:
                raise ValueError("Closing cash must be non-negative")
        except (KeyError, InvalidOperation, ValueError):
            return jsonify({'error': 'Invalid or missing closing cash amount'}), 400

        total_sales = SaleRepository.get_session_sales_total(session.id)
        expected_cash = session.opening_cash + total_sales

        closed_session = RegisterSessionRepository.close(
            session_id=session.id,
            user_id=current_user.id,
            closing_cash=closing_cash,
            expected_cash=expected_cash,
            notes=data.get('notes', '')
        )

        return jsonify({
            'success': True,
            'session': {
                'id': closed_session.id,
                'opening_cash': float(closed_session.opening_cash),
                'closing_cash': float(closed_session.closing_cash),
                'expected_cash': float(closed_session.expected_cash),
                'discrepancy': float(closed_session.discrepancy)
            },
            'sales_summary': SaleRepository.get_daily_summary(shop_id, session.id)
        })

    except Exception as e:
        current_app.logger.error(f"Register close error: {str(e)}")
        return jsonify({'error': 'Failed to close register'}), 500


# Register socket events
sockets.register_socket_events(sales_bp)

def register_blueprints(app):
    """Helper function to register all blueprints"""
    app.register_blueprint(sales_bp)
    app.register_blueprint(api_bp)
    

    
   