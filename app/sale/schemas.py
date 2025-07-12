from marshmallow import Schema, fields, validate, ValidationError
from enum import Enum

class AdjustmentType(Enum):
    SALE = 'sale'
    RESTOCK = 'restock'
    DAMAGED = 'damaged'
    RETURN = 'return'

class CartItemSchema(Schema):
    product_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "ID of the product being added to cart"}
    )
    quantity = fields.Integer(
        required=False,  # ← change here
        validate=validate.Range(min=1, max=999),
        metadata={"description": "Quantity of the product"}
    )


class CheckoutSchema(Schema):
    payment_method = fields.String(
        required=True,
        validate=validate.OneOf(['cash', 'card', 'credit', 'mobile']),
        metadata={"description": "Payment method used for the transaction"}
    )
    customer_name = fields.String(
        allow_none=True,
        metadata={"description": "Optional customer name for the sale"}
    )
    customer_phone = fields.String(
        allow_none=True,
        validate=validate.Length(max=20),
        metadata={"description": "Optional customer phone number"}
    )
    discount_code = fields.String(
        allow_none=True,
        metadata={"description": "Optional discount code to apply"}
    )
    
    cart_items = fields.List(
        fields.Nested(CartItemSchema),
        required=True,
        validate=validate.Length(min=1),
        metadata={"description": "List of items being purchased"}
    )


class ProductSearchSchema(Schema):
    """
    Schema for product search in POS
    """
    query = fields.String(
        required=True,
        validate=validate.Length(min=1, max=100),
        metadata={"description": "Search term for products"}
    )
    category_id = fields.Integer(
        allow_none=True,
        metadata={"description": "Optional category filter"}
    )
    in_stock_only = fields.Boolean(
        load_default=True, 
        metadata={"description": "Only show products in stock"}
    )

class ReceiptSchema(Schema):
    """
    Schema for receipt generation requests
    """
    sale_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "ID of the sale to generate receipt for"}
    )
    format = fields.String(
        validate=validate.OneOf(['thermal', 'pdf', 'email', 'sms']),
        load_default='thermal',  # Changed from 'missing' to 'load_default'
        metadata={"description": "Output format for the receipt"}
    )
    include_tax_details = fields.Boolean(
        load_default=False, 
        metadata={"description": "Include detailed tax information"}
    )

class PaymentProcessingSchema(Schema):
    """
    Schema for payment processing data
    """
    amount = fields.Float(
        required=True,
        validate=validate.Range(min=0.01),
        metadata={"description": "Amount to be processed"}
    )
    payment_note = fields.String(
        allow_none=True,
        validate=validate.Length(max=100),
        metadata={"description": "Optional note for the payment"}
    )

class RefundSchema(Schema):
    """
    Schema for processing refunds
    """
    sale_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1),
        metadata={"description": "Original sale ID for the refund"}
    )
    items = fields.List(
        fields.Nested(CartItemSchema),
        required=True,
        metadata={"description": "List of items to refund"}
    )
    reason = fields.String(
        required=True,
        validate=validate.Length(max=200),
        metadata={"description": "Reason for the refund"}
    )


from marshmallow import Schema, fields, validate, validates_schema, ValidationError
from datetime import datetime

class RegisterSessionSchema(Schema):
    id = fields.Int(dump_only=True)
    shop_id = fields.Int(required=True)
    opening_cash = fields.Float(
        required=True,
        validate=validate.Range(min=0, error="Opening cash must be positive")
    )
    opening_notes = fields.Str(allow_none=True)
    closing_cash = fields.Float(
        allow_none=True,
        validate=validate.Range(min=0, error="Closing cash must be positive")
    )
    closing_notes = fields.Str(allow_none=True)
    opened_at = fields.DateTime(dump_only=True)
    closed_at = fields.DateTime(dump_only=True)
    expected_cash = fields.Float(dump_only=True)
    discrepancy = fields.Float(dump_only=True)
    status = fields.Str(dump_only=True)  # 'open', 'closed'

    @validates_schema
    def validate_closure(self, data, **kwargs):
        if 'closing_cash' in data and data['closing_cash'] is not None:
            if 'opening_cash' not in data:
                raise ValidationError("Opening cash required for closure")

class SaleItemSchema(Schema):
    product_id = fields.Int(required=True)
    quantity = fields.Int(
        required=True,
        validate=validate.Range(min=1, error="Quantity must be at least 1")
    )
    price = fields.Float(
        required=True,
        validate=validate.Range(min=0, error="Price must be positive")
    )

class SaleSchema(Schema):
    id = fields.Int(dump_only=True)
    register_session_id = fields.Int(required=True)
    payment_method = fields.Str(
        required=True,
        validate=validate.OneOf(['cash', 'mpesa', 'card', 'other'])
    )
    customer_name = fields.Str(allow_none=True)
    items = fields.Nested(SaleItemSchema, many=True, required=True)
    subtotal = fields.Float(dump_only=True)
    tax = fields.Float(dump_only=True)
    total = fields.Float(dump_only=True)
    created_at = fields.DateTime(dump_only=True)