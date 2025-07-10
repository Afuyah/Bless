from functools import wraps
from flask import jsonify, request
from flask_login import current_user
from ..models import Shop, Role

def shop_access_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        shop_id = kwargs.get('shop_id')
        if not shop_id:
            return jsonify({'error': 'Shop ID required'}), 400
        
        # Check if user has access to this shop
        if not current_user.can_access_shop(shop_id):
            return jsonify({'error': 'Shop access denied'}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return jsonify({'error': 'Authentication required'}), 401
                
            if current_user.role not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return wrapper