
from flask_socketio import emit, join_room
from .. import socketio
from ..models import Product, Shop

def register_socket_events(blueprint):
    @socketio.on('connect')
    def handle_connect():
        if current_user.is_authenticated:
            join_room(f'user_{current_user.id}')
            if current_user.shop_id:
                join_room(f'shop_{current_user.shop_id}')

    @socketio.on('subscribe_inventory')
    def handle_inventory_subscribe(data):
        shop_id = data.get('shop_id')
        if shop_id and current_user.has_shop_access(shop_id):
            join_room(f'inventory_{shop_id}')

    @socketio.on('request_stock_update')
    def handle_stock_update(data):
        shop_id = data.get('shop_id')
        if not current_user.has_shop_access(shop_id):
            return
            
        product = ProductRepository.get_for_shop(
            data['product_id'],
            shop_id
        )
        if product:
            emit('stock_updated', {
                'product_id': product.id,
                'stock': product.stock,
                'shop_id': shop_id
            }, room=f'inventory_{shop_id}')


