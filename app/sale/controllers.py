from flask import request, jsonify, render_template
from flask.views import MethodView
from flask_login import login_required, current_user
from marshmallow import ValidationError
from decimal import Decimal, InvalidOperation
from sqlalchemy import and_
from .repositories import ProductRepository, CategoryRepository, RegisterSessionRepository, SaleRepository
from .services import (
    SalesService,

    ProductService,
    ReceiptService,
    CategoryService,
    PaymentService,
    TaxService,
    RegisterService,
    SalesSummaryService
)
from .schemas import (
    CheckoutSchema,
    CartItemSchema,
    ProductSearchSchema,
    ReceiptSchema,
    RegisterSessionSchema
)
from app import shop_access_required, role_required, csrf
from app.models import Role, Shop, Category, Product
import logging

logger = logging.getLogger(__name__)

class SalesController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """Render POS page (products/categories are loaded via API)"""
        try:
            shop = Shop.query.get_or_404(shop_id)
            return render_template('sales/pos.html', shop=shop.serialize())
        except Exception as e:
            logger.error(f"Failed to load POS UI: {str(e)}", exc_info=True)
            return render_template('sales/error.html', error="Failed to load POS page"), 500


class ProductAPIController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """API: Return all available products"""
        try:
            products = ProductService.get_available_for_sale(shop_id)
            return jsonify(products)
        except Exception as e:
            logger.error(f"Failed to load products: {str(e)}", exc_info=True)
            return jsonify({'error': 'Failed to load products'}), 500


class ProductSearchAPIController(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def post(self, shop_id):
        try:
            data = ProductSearchSchema().load(request.json)

            query = (data['query'] or '').strip()[:100]
            category_id = data.get('category_id')

            if not query:
                return jsonify([])

            results = ProductService.search(
                shop_id=shop_id,
                query=query,
                category_id=category_id,
                limit=50
            )
            return jsonify(results)

        except ValidationError as ve:
            return jsonify({'error': 'Invalid input', 'details': ve.messages}), 400
        except Exception as e:
            logger.exception("Product search error")
            return jsonify({'error': 'Search failed'}), 500



class CategoryAPIController(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """API: Get active categories and their products"""
        try:
            categories = CategoryRepository.get_for_pos(shop_id)
            return jsonify([
                {
                    **c.serialize(),
                    'products': [
                        p.serialize(for_pos=True)
                        for p in sorted(c.products, key=lambda p: p.name)
                        if p.is_active and p.stock > 0
                    ]
                }
                for c in categories
            ])
        except Exception as e:
            logger.error(f"Failed to fetch categories: {str(e)}", exc_info=True)
            return jsonify({'error': 'Failed to load categories'}), 500




class TransactionController(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]
    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """
        Get transactions - GET /api/shops/<shop_id>/transactions/recent
        """
        try:
            if request.path.endswith('/recent'):
                # Recent transactions endpoint
                transactions = SalesService.get_recent_transactions(shop_id)
                return jsonify([{
                    'id': t.id,
                    'date': t.date.isoformat(),
                    'total': t.total,
                    'payment_method': t.payment_method,
                    'customer_name': t.customer_name
                } for t in transactions])
            else:
                # Paginated history endpoint
                page = request.args.get('page', 1, type=int)
                per_page = request.args.get('per_page', 20, type=int)
                date_from = request.args.get('date_from')
                date_to = request.args.get('date_to')
                
                transactions = SalesService.get_transactions(
                    shop_id=shop_id,
                    page=page,
                    per_page=per_page,
                    date_from=date_from,
                    date_to=date_to
                )
                return jsonify({
                    'transactions': [t.to_dict() for t in transactions.items],
                    'total': transactions.total,
                    'pages': transactions.pages,
                    'current_page': page
                })
        except Exception as e:
            logger.error(f"Failed to get transactions: {str(e)}")
            return jsonify({'error': 'Failed to get transactions'}), 500
    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def post(self, shop_id):
        """
        Process checkout - POST /shops/<shop_id>/transactions
        """
        try:
            checkout_data = CheckoutSchema().load(request.json)

            result = SalesService.process_checkout(
                shop_id=shop_id,
                user_id=current_user.id,
                cart_items=checkout_data['cart_items'],  # <- use client-sent cart
                payment_method=checkout_data['payment_method'],
                customer_data={
                    'name': checkout_data.get('customer_name'),
                    'phone': checkout_data.get('customer_phone')
                }
            )

            return jsonify({
                'success': True,
                'sale_id': result['sale_id'],
                'receipt': result['receipt'],
                'amount_paid': result['amount_paid']
            })

        except ValidationError as e:
            return jsonify({'error': e.messages}), 400
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        except Exception as e:
            logger.error(f"Checkout failed: {str(e)}")
            return jsonify({'error': 'Checkout processing failed'}), 500


class ReceiptController(MethodView):
    decorators = [login_required, shop_access_required]
    
    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """
        Get receipt - GET /api/shops/<shop_id>/receipts
        """
        try:
            data = ReceiptSchema().load(request.args)
            receipt = ReceiptService.generate(
                sale_id=data['sale_id'],
                format=data['format']
            )
            return jsonify(receipt)
        except ValidationError as e:
            return jsonify({'error': e.messages}), 400
        except Exception as e:
            logger.error(f"Failed to generate receipt: {str(e)}")
            return jsonify({'error': 'Failed to generate receipt'}), 500
        
        

class RegisterSummaryAPI(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        try:
            session = RegisterSessionRepository.get_open_session(shop_id)
            if not session:
                return jsonify({
                    'success': True,
                    'is_open': False,
                    'message': 'Register is currently closed'
                }), 200

            # Get cash details
            cash_details = RegisterSessionRepository.get_session_summary(session.id)
            if not cash_details:
                return jsonify({
                    'success': False,
                    'error': 'Could not calculate cash totals'
                }), 500

            # Get sales summary and recent sales
            sales_data = SalesSummaryService.get_summary(shop_id)
            if not sales_data.get('success'):
                return jsonify({
                    'success': False,
                    'error': sales_data.get('message', 'Failed to load sales data')
                }), 500

            summary = sales_data['data']['summary']
            recent_sales = sales_data['data']['recent_sales']

            return jsonify({
                'success': True,
                'is_open': True,
                'summary': {
                    'session_id': session.id,
                    'opened_at': session.opened_at.isoformat(),
                    'opened_by': session.opened_by.username,
                    'opening_cash': float(session.opening_cash),
                    'total_sales': float(cash_details['total_sales']),
                    'expected_cash': float(cash_details['expected_cash']),
                    'sales_count': summary.get('sales_count', 0),
                    'total_tax': summary.get('total_tax', 0),
                    'payment_methods': summary.get('payment_methods', {}),  # Optional if you calculate it
                },
                'recent_sales': recent_sales  # ✅ Flattened to top level
            }), 200

        except Exception as e:
            logger.error(f"Summary error: {str(e)}", exc_info=True)
            return jsonify({
                'success': False,
                'error': 'Failed to get register summary'
            }), 500

        
        
        
class RegisterHistoryAPI(MethodView):
    decorators = [login_required, shop_access_required]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def get(self, shop_id):
        """Get historical sessions - unchanged from your version"""
        try:
            sessions = RegisterSessionRepository.get_all(shop_id)
            return jsonify({
                'success': True,
                'sessions': RegisterSessionSchema(many=True).dump(sessions)
            }), 200
        except Exception as e:
            logger.error(f"History error: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Failed to load history'
            }), 500

class RegisterOpenAPI(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def post(self, shop_id):
        """Open a new register session with validated opening cash"""
        try:
            data = request.get_json()

            if not data or 'opening_cash' not in data:
                return jsonify({'success': False, 'error': 'Opening cash amount required'}), 400

            try:
                opening_cash = Decimal(str(data['opening_cash'])).quantize(Decimal('0.01'))
                if opening_cash < 0:
                    raise ValueError
            except (ValueError, InvalidOperation):
                return jsonify({'success': False, 'error': 'Invalid opening amount'}), 400

            session = RegisterService.open_register(shop_id, current_user.id, opening_cash)

            return jsonify({
                'success': True,
                'session': RegisterSessionSchema().dump(session)
            }), 201

        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400
        except Exception as e:
            logger.error(f"Register open error: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to open register'}), 500


class RegisterCloseAPI(MethodView):
    decorators = [login_required, shop_access_required, csrf.exempt]

    @role_required(Role.CASHIER, Role.ADMIN, Role.TENANT)
    def put(self, shop_id):
        """Close the current register session with validated closing cash"""
        try:
            data = request.get_json()

            if not data or 'closing_cash' not in data:
                return jsonify({'success': False, 'error': 'Closing cash amount required'}), 400

            try:
                closing_cash = Decimal(str(data['closing_cash'])).quantize(Decimal('0.01'))
                if closing_cash < 0:
                    raise ValueError
            except (ValueError, InvalidOperation):
                return jsonify({'success': False, 'error': 'Invalid closing amount'}), 400

            # Get current open session and validate
            open_session = RegisterSessionRepository.get_open_session(shop_id)

            if not open_session:
                return jsonify({'success': False, 'error': 'No open register session found'}), 404

            # Close the session using the service (with expected cash auto-calculated)
            closed_session = RegisterService.close_register(
                shop_id=shop_id,
                user_id=current_user.id,
                session_id=open_session.id,
                closing_cash=closing_cash,
                notes=data.get('notes', '')
            )

            return jsonify({
                'success': True,
                'session': RegisterSessionSchema().dump(closed_session),
                'opening_cash': float(closed_session.opening_cash),
                'closing_cash': float(closed_session.closing_cash),
                'expected_cash': float(closed_session.expected_cash),
                'discrepancy': float(closed_session.discrepancy)
            }), 200

        except ValueError as ve:
            return jsonify({'success': False, 'error': str(ve)}), 400
        except Exception as e:
            logger.error(f"Register close error: {str(e)}", exc_info=True)
            return jsonify({'success': False, 'error': 'Failed to close register'}), 500