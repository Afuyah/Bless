from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from enum import Enum
from datetime import datetime, date
from sqlalchemy import func, Index, ForeignKey
from sqlalchemy.orm import validates, relationship
from app import db
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.ext.declarative import declared_attr
import enum
import logging
from sqlalchemy import Numeric, Integer, Float, ForeignKey, String, DateTime, JSON, Boolean, Text 
from sqlalchemy import and_
import sqlalchemy as sa
from sqlalchemy.sql import expression

# Configure logging
logging.basicConfig(level=logging.DEBUG)


# Define Python Enum for unit types
class UnitType(enum.Enum):
    piece = 'piece'
    kg = 'kg'            
    grams = 'grams'
    punnet = 'punnet'
    bunch = 'bunch'
    packet = 'packet'
    litr = 'litre'

class ShopType(enum.Enum):
    pos = 'point of sale'
    pop ='point of purchase'


class AdjustmentType(enum.Enum):
    addition = "addition"  # Adding stock
    reduction = "reduction"
    returned = "returned"  # Stock returned from sales
    inventory_adjustment = "inventory_adjustment"  # Adjustments made during inventory counts
    damage = "damage"  # Stock that is damaged and unsellable

    def __str__(self):
        return self.value.capitalize() 
 

class BusinessStatus(str, Enum):
    ACTIVE = 'active'
    INACTIVE = 'inactive'
    SUSPENDED = 'suspended'
    CLOSED = 'closed'
    PENDING = 'pending'


# User Roles Enum
class Role(Enum):
    SUPERADMIN = 'superadmin'
    TENANT = 'tenant'
    ADMIN = 'admin'
    CASHIER = 'cashier'


class BaseModel(db.Model):
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow,  server_default=sa.func.now(),  nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = db.Column(Boolean, default=False, server_default=expression.false(), nullable=True, index=True)

    def soft_delete(self):
        """Mark record as deleted without physical removal"""
        self.is_deleted = True
        db.session.add(self)
        return self

    def restore(self):
        """Restore a soft-deleted record"""
        self.is_deleted = False
        db.session.add(self)
        return self

    @classmethod
    def get_active(cls):
        """Get all non-deleted records"""
        return cls.query.filter_by(is_deleted=False)

    @classmethod
    def get_deleted(cls):
        """Get all deleted records"""
        return cls.query.filter_by(is_deleted=True)

    @classmethod
    def bulk_delete(cls, ids):
        """Soft delete multiple records"""
        return cls.query.filter(cls.id.in_(ids)).update(
            {'is_deleted': True},
            synchronize_session=False
        )

    def before_save(self):
        """Hook for pre-save operations"""
        pass

    def after_save(self):
        """Hook for post-save operations"""
        pass

    def save(self):
        """Save with hooks"""
        self.before_save()
        db.session.add(self)
        db.session.commit()
        self.after_save()
        return self

class BusinessScopedMixin:
    @declared_attr
    def business_id(cls):
        return db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=True)

    @declared_attr
    def business(cls):
        return db.relationship('Business', back_populates=cls.__tablename__, lazy='joined')

class ShopScopedMixin:
    @declared_attr
    def shop_id(cls):
        return db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=True)

    @declared_attr
    def shop(cls):
        return db.relationship('Shop', back_populates=cls.__tablename__, lazy='joined')



class Business(BaseModel):
    __tablename__ = 'businesses'
    
    # Core Business Information
    name = db.Column(db.String(150), nullable=False, unique=True, index=True)
    display_name = db.Column(db.String(150), nullable=True)
    description = db.Column(db.Text, nullable=True)
    
    # Contact Information
    email = db.Column(db.String(150), nullable=True, unique=True)
    phone = db.Column(db.String(20), nullable=True)
    secondary_phone = db.Column(db.String(20), nullable=True)
    website = db.Column(db.String(255), nullable=True)
    
    # Location Information
    address = db.Column(db.Text, nullable=True)
    city = db.Column(db.String(100), nullable=True)
    state = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), default="Kenya")
    postal_code = db.Column(db.String(20), nullable=True)
    timezone = db.Column(db.String(50), default="Africa/Nairobi")
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    
    # Legal Information
    registration_number = db.Column(db.String(50), nullable=True, unique=True)
    tax_identification = db.Column(db.String(50), nullable=True, unique=True)
    business_type = db.Column(db.String(50), nullable=True)  # LLC, Sole Proprietorship, etc.
    
    # Financial Settings
    currency = db.Column(db.String(10), default="KES")
    fiscal_year_start = db.Column(db.Date, default=date(date.today().year, 1, 1))
    tax_rate = db.Column(db.Float, default=0.0)  # Default tax rate
    
    # Status and Approval
    status = db.Column(db.Enum(BusinessStatus), default=BusinessStatus.PENDING, index=True)
    is_approved = db.Column(db.Boolean, default=False, nullable=True, index=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    approval_notes = db.Column(db.Text, nullable=True)
    # Media
    logo_url = db.Column(db.String(255), nullable=True)
    banner_url = db.Column(db.String(255), nullable=True)
    
    # Relationships
    approved_by = db.relationship('User', foreign_keys=[approved_by_id])
    shops = db.relationship('Shop', back_populates='business', cascade='all, delete-orphan')
    users = db.relationship(
        'User',
        back_populates='business',
        cascade='all, delete-orphan',
        foreign_keys='User.business_id'  # Disambiguates User ↔ Business
    )
    
    
    # Indexes
    __table_args__ = (
        db.Index('ix_business_status', 'status'),
        db.Index('ix_business_approved', 'is_approved'),
    )

    def approve(self, approved_by_user, notes=None):
        """Approve the business and set approval details"""
        self.is_approved = True
        self.status = BusinessStatus.ACTIVE
        self.approved_by = approved_by_user
        self.approved_at = datetime.utcnow()
        self.approval_notes = notes

    def reject(self, reason=None):
        """Reject the business application"""
        self.is_approved = False
        self.status = BusinessStatus.REJECTED
        if reason:
            self.rejection_reason = reason
        return self.save()

    def suspend(self, reason=None):
        """Suspend the business"""
        self.status = BusinessStatus.SUSPENDED
        if reason:
            self.suspension_reason = reason
        return self.save()

    def activate(self):
        """Activate a suspended business"""
        self.status = BusinessStatus.ACTIVE
        return self.save()

    def close(self, reason=None):
        """Close the business"""
        self.status = BusinessStatus.CLOSED
        if reason:
            self.closing_reason = reason
        return self.save()

    @property
    def tenant(self):
        """Get the primary tenant/admin user"""
        return next((u for u in self.users if u.role == Role.TENANT), None)

    @property
    def active_shops(self):
        """Get all non-deleted shops"""
        return [shop for shop in self.shops if not shop.is_deleted]

    @property
    def active_users(self):
        """Get all non-deleted users"""
        return [user for user in self.users if not user.is_deleted]

    def serialize(self, include_related=False):
        """Serialize business data for API responses"""
        data = {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'status': self.status.value if self.status else None,
            'email': self.email,
            'phone': self.phone,
            'address': self.address,
            'city': self.city,
            'country': self.country,
            'registration_number': self.registration_number,
            'tax_identification': self.tax_identification,
            'currency': self.currency,
            'logo_url': self.logo_url,
            'is_approved': self.is_approved,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'shop_count': len(self.active_shops),
            'user_count': len(self.active_users),
            'tenant': self.tenant.username if self.tenant else None
        }

        if include_related:
            data['shops'] = [shop.serialize() for shop in self.active_shops]
            data['users'] = [user.serialize() for user in self.active_users]

        return data



    def before_save(self):
        """Ensure display name defaults to name"""
        if not self.display_name:
            self.display_name = self.name


class Shop(BaseModel, BusinessScopedMixin):
    __tablename__ = 'shops'
    __table_args__ = (
        db.Index('ix_shops_business_id', 'business_id'),  
        db.Index('ix_shops_name', 'name'),
        db.Index('ix_shops_phone', 'phone'),
        db.Index('ix_shops_is_active', 'is_active'),
        {'extend_existing': True}  
    )

    name = db.Column(db.String(150), nullable=False)
    location = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(20), nullable=True, unique=True)
    email = db.Column(db.String(150), nullable=True, unique=True)
    currency = db.Column(db.String(10), default="KES", nullable=True)
    logo_url = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    type = db.Column(SQLAlchemyEnum(ShopType), nullable=True)  
    

    # Rest of your model relationships and methods...
    register_sessions = db.relationship('RegisterSession', back_populates='shop', cascade='all, delete-orphan')
    # Optimized relationships with explicit join conditions and load strategies
    users = db.relationship( 'User', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic'  )
    price_changes = db.relationship('PriceChange', back_populates='shop', cascade="all, delete-orphan")    
    products = db.relationship( 'Product',  back_populates='shop', cascade="all, delete-orphan", lazy='dynamic',   order_by='Product.name' )    
    sales = db.relationship('Sale', back_populates='shop',  cascade="all, delete-orphan", lazy='dynamic', order_by='Sale.created_at.desc()')    
    categories = db.relationship('Category',  back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='Category.name' )    
    cart_items = db.relationship('CartItem',  back_populates='shop', cascade="all, delete-orphan",  lazy='dynamic')

    # Other relationships with optimized loading
    suppliers = db.relationship( 'Supplier', back_populates='shop', cascade="all, delete-orphan",  lazy='dynamic', order_by='Supplier.name' )    
    expenses = db.relationship( 'Expense',  back_populates='shop',  cascade="all, delete-orphan",  lazy='dynamic', order_by='Expense.date.desc()')

    # Added bulk operations for stock logs
    stock_logs = db.relationship('StockLog', back_populates='shop', cascade="all, delete-orphan", lazy='dynamic', order_by='StockLog.created_at.desc()'
    )
    # Tax relationship with optimized loading
    taxes = db.relationship( 'Tax',  back_populates='shop', cascade="all, delete-orphan",  lazy='selectin',  order_by='Tax.name')

    def __repr__(self):
        return f"<Shop {self.name} (ID: {self.id})>"

    def serialize(self, include_relations=None):
        """
        Enhanced serialization with configurable relation inclusion
        and optimized query patterns.
        
        Args:
            include_relations (list): Optional list of relations to include
                ('taxes', 'categories', etc.)
        """
        data = {
            'id': self.id,
            'name': self.name,
            'location': self.location,
            'business_id': self.business_id,
            'phone': self.phone,
            'currency': self.currency,
            'logo_url': self.logo_url,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        # Dynamic relation inclusion
        if include_relations:
            for relation in include_relations:
                if relation == 'taxes':
                    data['taxes'] = [tax.serialize() for tax in self.taxes]
                elif relation == 'categories':
                    data['categories'] = [c.serialize() for c in self.categories.all()]
                elif relation == 'stats':
                    data.update(self.get_business_stats())
        
        return data

    def get_business_stats(self):
        """
        Get key business statistics with optimized queries
        """
        from sqlalchemy import func
        
        return {
            'product_count': self.products.count(),
            'active_product_count': self.products.filter_by(is_active=True).count(),
            'category_count': self.categories.count(),
            'sale_count': self.sales.count(),
            'revenue_30days': db.session.query(
                func.sum(Sale.total_amount)
            ).filter(
                Sale.shop_id == self.id,
                Sale.created_at >= func.date_sub(func.now(), {'days': 30})
            ).scalar() or 0
        }

    @classmethod
    def find_by_name(cls, business_id, name):
       
        return cls.query.filter(
            cls.business_id == business_id,
            func.lower(cls.name) == func.lower(name)
        ).first()

    @classmethod
    def search(cls, business_id, query, limit=10):
        """
        Full-text search implementation
        """
        return cls.query.filter(
            cls.business_id == business_id,
            cls.name.ilike(f'%{query}%')
        ).limit(limit).all()

    def deactivate(self):
        """
        Soft delete implementation
        """
        self.is_active = False
        db.session.commit()
        return self   


class RegisterSession(BaseModel, ShopScopedMixin):
    __tablename__ = 'register_sessions'

    opened_at = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(DateTime, nullable=True)

    opening_cash = db.Column(Float, nullable=False)   
    closing_cash = db.Column(Float, nullable=True)    
    expected_cash = db.Column(Float, nullable=True)     
    discrepancy = db.Column(Float, nullable=True)       
    notes = db.Column(Text, nullable=True)

    opened_by_id = db.Column(Integer, db.ForeignKey('users.id'), nullable=False)
    closed_by_id = db.Column(Integer, db.ForeignKey('users.id'), nullable=True)

    opened_by = db.relationship('User', foreign_keys=[opened_by_id])
    closed_by = db.relationship('User', foreign_keys=[closed_by_id])

    sales = db.relationship('Sale', backref='register_session')

    __table_args__ = (
        db.Index('ix_register_shop_date', 'shop_id', 'opened_at'),
        db.Index('ix_register_shop_closed', 'shop_id', 'closed_at'),
        db.Index('ix_register_opened_by', 'opened_by_id'),
        db.Index('ix_register_closed_by', 'closed_by_id'),
        db.Index('ix_register_opened_at', 'opened_at'),
        db.Index('ix_register_closed_at', 'closed_at'),
    )


    def is_open(self):
        return self.closed_at is None

    def serialize(self):
        return {
            'id': self.id,
            'opened_at': self.opened_at.isoformat(),
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'opening_cash': self.opening_cash,
            'closing_cash': self.closing_cash,
            'expected_cash': self.expected_cash,
            'discrepancy': self.discrepancy,
            'notes': self.notes,
            'opened_by_id': self.opened_by_id,
            'closed_by_id': self.closed_by_id,
            'shop_id': self.shop_id
        }

    @property
    def duration(self):
        if self.closed_at:
            return (self.closed_at - self.opened_at).total_seconds()
        return None
        
    @property
    def status(self):
        return 'OPEN' if self.closed_at is None else 'CLOSED'



class Tax(BaseModel, ShopScopedMixin):
    __tablename__ = 'taxes'

    name = db.Column(db.String(100), nullable=False)
    rate = db.Column(db.Float, nullable=False) 
    description = db.Column(db.String(255), nullable=True)
    kra_code = db.Column(db.String(50), nullable=True) 
    is_active = db.Column(db.Boolean, default=True, nullable=False)


    __table_args__ = (
        db.UniqueConstraint('shop_id', 'name', name='uq_tax_name_per_shop'),
    )


    @staticmethod
    def get_tax_rate(shop_id: int) -> float:
        tax = Tax.query.filter_by(shop_id=shop_id, is_active=True, is_deleted=False).first()
        return float(tax.rate if tax else 0.0) 

    def serialize(self):
        return {
            'id': self.id,
            'name': self.name,
            'rate': self.rate,
            'description': self.description,
            'kra_code': self.kra_code,
            'shop_id': self.shop_id
        }


# User Model with Role-based Access
class User(UserMixin, BaseModel, ShopScopedMixin, BusinessScopedMixin):
    __tablename__ = 'users'
    
    # Authentication
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True, unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)
    last_password_change = db.Column(db.DateTime, nullable=True)
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)
    business_id = db.Column(db.Integer, db.ForeignKey('businesses.id'), nullable=True)
    shop_id = db.Column(db.Integer, db.ForeignKey('shops.id'), nullable=True)
    
    # Security
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)
    email_verification_token = db.Column(db.String(100), nullable=True)
    email_verified = db.Column(db.Boolean, default=False)
    
    # Profile
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(20), nullable=True)

    
    # Permissions
    role = db.Column(db.Enum(Role), nullable=False, index=True)
    permissions = db.Column(db.JSON, nullable=True)  
    
    # Relationships
    sales = db.relationship('Sale', back_populates='user')
    opened_sessions = db.relationship('RegisterSession', foreign_keys='RegisterSession.opened_by_id', back_populates='opened_by')
    closed_sessions = db.relationship('RegisterSession', foreign_keys='RegisterSession.closed_by_id', back_populates='closed_by')
    business = db.relationship(
        'Business',
        back_populates='users',
        foreign_keys=[business_id],
        lazy='joined'
    )

    shop = db.relationship(
        'Shop',
        back_populates='users',
        foreign_keys=[shop_id],
        lazy='joined'
    )
    # Indexes
    __table_args__ = (
        db.Index('ix_user_role', 'role'),
        db.Index('ix_user_business', 'business_id'),
        db.Index('ix_user_shop', 'shop_id'),
    )

    def get_full_name(self):
        """Get user's full name"""
        return f"{self.first_name or ''} {self.last_name or ''}".strip() or self.username

    def set_password(self, password):
        """Hash and set password"""
        self.password_hash = generate_password_hash(password)
        self.last_password_change = datetime.utcnow()
        return self

    def check_password(self, password):
        """Verify password"""
        return check_password_hash(self.password_hash, password)

    def generate_reset_token(self, expires_in=3600):
        """Generate password reset token"""
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(seconds=expires_in)
        return self.save()

    def clear_reset_token(self):
        """Clear reset token"""
        self.reset_token = None
        self.reset_token_expires = None
        return self.save()

    def record_login(self):
        """Record successful login"""
        self.last_login = datetime.utcnow()
        self.login_attempts = 0
        self.locked_until = None
        return self.save()

    def record_failed_login(self):
        """Record failed login attempt"""
        self.login_attempts += 1
        if self.login_attempts >= current_app.config.get('MAX_LOGIN_ATTEMPTS', 5):
            self.locked_until = datetime.utcnow() + timedelta(
                minutes=current_app.config.get('LOCKOUT_MINUTES', 30)
            )
        return self.save()

    def is_locked(self):
        """Check if account is locked"""
        return self.locked_until and self.locked_until > datetime.utcnow()

    # Role checking methods
    def is_superadmin(self):
        return self.role == Role.SUPERADMIN

    def is_tenant(self):
        return self.role == Role.TENANT

    def is_admin(self):
        return self.role == Role.ADMIN

    def is_cashier(self):
        return self.role == Role.CASHIER

    def has_permission(self, permission):
        """Check if user has specific permission"""
        if self.is_superadmin():
            return True
        return permission in (self.permissions or [])

    def serialize(self, include_sensitive=False):
        """Serialize user data for API responses"""
        data = {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.get_full_name(),
            'phone': self.phone,
            'role': self.role.value if self.role else None,
            'business_id': self.business_id,
            'shop_id': self.shop_id,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

        if include_sensitive:
            data['email_verified'] = self.email_verified
            data['is_locked'] = self.is_locked()

        return data

           
class Category(BaseModel, ShopScopedMixin):
    __tablename__ = 'categories'
    
    name = db.Column(String(100), nullable=False, index=True)
    is_active = db.Column(Boolean, default=True)
    position = db.Column(Integer, default=0)
    image_url = db.Column(String(255))
    
    # Relationship with explicit back_populates
    products = db.relationship('Product', back_populates='category', lazy='selectin')

    
    __table_args__ = (
        db.UniqueConstraint('shop_id', 'name', name='uq_category_shop_name'),
    )

    @property
    def active_products(self):
        return [p for p in self.products if p.is_active and p.stock > 0]

    @property
    def product_count(self):
        return len(self.active_products)


    def serialize(self, include_products=False):
        """Enhanced serialization with options"""
        data = {
            'id': self.id,
            'name': self.name,
            'position': self.position,
            'image_url': self.image_url,
            'product_count': self.product_count,
            'shop_id': self.shop_id
        }
        
        if include_products:
            data['products'] = [p.serialize() for p in self.active_products]
        
        return data

    @classmethod
    def get_for_shop(cls, shop_id, include_products=False):
        """Get all active categories for a shop with error handling"""
        try:
            query = cls.query.filter_by(
                shop_id=shop_id,
                is_active=True
            ).order_by(cls.position, cls.name)
            
            if include_products:
                query = query.options(
                    db.joinedload(cls.products).filter(
                        and_(
                            Product.is_active == True,
                            Product.stock > 0
                        )
                    ).load_only('id', 'name', 'price', 'image_url', 'stock')
                )
            
            return query.all()
        except Exception as e:
            current_app.logger.error(f"Error loading categories for shop {shop_id}: {str(e)}")
            raise ValueError("Failed to load categories") from e

    def __repr__(self):
        return f'<Category {self.id}: {self.name}>'



class Sale(BaseModel, ShopScopedMixin):
    __tablename__ = 'sales'

    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    total = db.Column(Float, nullable=False)
    profit = db.Column(Float, nullable=True)
    payment_method = db.Column(String(50), nullable=False)
    customer_phone = db.Column(String(20), nullable=True)
    customer_name = db.Column(String(200), nullable=True)
    subtotal = db.Column(Float, nullable=True)
    tax = db.Column(Float, nullable=True)
    register_session_id = db.Column(Integer, db.ForeignKey('register_sessions.id'), nullable=True)

    user_id = db.Column(Integer, db.ForeignKey('users.id'))  # Associate with User
    
    # Relationships
    cart_items = relationship('CartItem', back_populates='sale')
    user = relationship('User')  

    __table_args__ = (
        db.Index('ix_sale_total', 'total'),
        db.Index('ix_sale_date', 'date'),
        db.Index('ix_sale_shop_date', 'shop_id', 'date'),
        db.Index('ix_sale_session', 'register_session_id'),
        db.Index('ix_sale_user', 'user_id'),
        db.Index('ix_sale_payment', 'payment_method'),
        db.Index('ix_sale_shop_pay_date', 'shop_id', 'payment_method', 'date'),
    )

    @validates('payment_method')
    def validate_payment_method(self, key, value):
        allowed_methods = ['cash', 'card', 'mobile', 'credit']
        if value not in allowed_methods:
            raise ValueError(f"Invalid payment method: {value}")
        return value


    def serialize(self):
        """Serialize sale object for API response."""
        return {
            'id': self.id,
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'total': self.total,
            'profit': self.profit,
            'payment_method': self.payment_method,
            'customer_name': self.customer_name,
            'user': {
                'id': self.user.id if self.user else None,
                'username': self.user.username if self.user else None,
                'role': self.user.role.value if self.user else None
            },
            'items': [item.serialize() for item in self.cart_items],
        }

    @classmethod
    def create_sale(cls, total, profit, payment_method, customer_name, user_id=None):
        """Create a new sale instance."""
        return cls(
            date=datetime.utcnow(),
            total=total,
            profit=profit,
            payment_method=payment_method,
            customer_name=customer_name,
            user_id=user_id
        )

    def finalize_sale(self):
        """Finalize the sale by updating stock and committing to the database."""
        try:
            # Check stock availability for each cart item
            for item in self.cart_items:
                if item.product.stock < item.quantity:
                    raise ValueError(f"Not enough stock for {item.product.name}")

            # Update stock and finalize the sale
            for item in self.cart_items:
                item.product.stock -= item.quantity

            db.session.commit()  # Commit changes if everything is valid
        except Exception as e:
            db.session.rollback()  # Rollback in case of error
            raise ValueError(f"Error finalizing sale: {str(e)}")

    def __repr__(self):
        return f'<Sale id={self.id}, total={self.total}, date={self.date.strftime("%Y-%m-%d %H:%M:%S")}>'


class CartItem(BaseModel, ShopScopedMixin):
    __tablename__ = 'cart_items'

    product_id = db.Column(Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity = db.Column(Integer, nullable=False)
    sale_id = db.Column(Integer, db.ForeignKey('sales.id'), nullable=False, index=True)
    total_price = db.Column(db.Float, nullable=True)
    unit_price = db.Column(db.Float, nullable=True)

    # Relationships
    product = relationship('Product', back_populates='sale_items', lazy='select')
    sale = relationship('Sale', back_populates='cart_items')

    __table_args__ = (
        db.Index('ix_cartitem_product_sale', 'product_id', 'sale_id'),
        db.Index('ix_cartitem_sale_product', 'sale_id', 'product_id'),
        db.Index('ix_cartitem_shop_product', 'shop_id', 'product_id'),
        db.Index('ix_cartitem_shop_sale', 'shop_id', 'sale_id'),
    )

    @validates('quantity')
    def validate_quantity(self, key, value):
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value

    def __repr__(self):
        return f'<CartItem product_id={self.product_id}, quantity={self.quantity}>'

    def serialize(self):
        return {
            'product_name': self.product.name if self.product else 'Unknown Product',
            'quantity': self.quantity,
            'total_price': str(self.total_price),
        }



class Product(BaseModel, ShopScopedMixin):
    __tablename__ = 'products'

    name = db.Column(String(200), nullable=False, index=True)
    description = db.Column(Text)
    barcode = db.Column(String(50), unique=True)
    sku = db.Column(String(50), unique=True)
    cost_price = db.Column(Numeric(10, 2), nullable=False, default=0.00)
    selling_price = db.Column(Numeric(10, 2), nullable=False, default=0.00)
    stock = db.Column(Integer, nullable=False, default=0)
    low_stock_threshold = db.Column(Integer, default=10)
    image_url = db.Column(String(255))
    unit = db.Column(SQLAlchemyEnum(UnitType), nullable=True)
    
    # Relationships
    category_id = db.Column(Integer, db.ForeignKey('categories.id'), nullable=False, index=True)
    supplier_id = db.Column(Integer, db.ForeignKey('suppliers.id'), index=True)
    
    # Combination pricing
    combination_size = db.Column(Integer)
    combination_price = db.Column(Numeric(10, 2))
    combination_unit_price = db.Column(Numeric(10, 2))
    
    # Status flags
    is_active = db.Column(Boolean, default=True)
    is_featured = db.Column(Boolean, default=False)
    
    # Relationships
    category = db.relationship('Category', back_populates='products')
    supplier = db.relationship('Supplier', back_populates='products')
    sale_items = db.relationship('CartItem', back_populates='product', lazy='dynamic')

    __table_args__ = (
        db.Index('ix_product_shop_category', 'shop_id', 'category_id'),
        db.Index('ix_product_name_shop', 'name', 'shop_id'),
        db.Index('ix_product_barcode', 'barcode'),
        db.Index('ix_product_sku', 'sku'),
        db.Index('ix_product_shop_supplier', 'shop_id', 'supplier_id'),
        db.Index('ix_product_shop_active', 'shop_id', 'is_active'),
        db.Index('ix_product_shop_stock', 'shop_id', 'stock'),
        db.Index('ix_product_shop_combo', 'shop_id', 'combination_size'),
    )


    @validates('cost_price', 'selling_price', 'stock')
    def validate_prices_stock(self, key, value):
        if key in ['cost_price', 'selling_price'] and value < 0:
            raise ValueError(f"{key.replace('_', ' ').title()} cannot be negative")
        if key == 'stock' and value < 0:
            raise ValueError("Stock cannot be negative")
        return value

    @hybrid_property
    def profit(self):
        return self.selling_price - self.cost_price

    @hybrid_property
    def profit_margin(self):
        return (self.profit / self.selling_price * 100) if self.selling_price > 0 else 0.0

    @hybrid_property
    def is_low_stock(self):
        if self.stock is None or self.low_stock_threshold is None:
            return False
        return self.stock < self.low_stock_threshold

    @hybrid_property
    def is_combo(self):
        return self.combination_size is not None and self.combination_size > 1
        
    @hybrid_property
    def display_price(self):
        """Returns the appropriate price based on combination settings"""
        if self.combination_size and self.combination_size > 1:
            return {
                'single': float(self.selling_price),
                'combination': float(self.combination_price),
                'size': self.combination_size,
                'unit_price': float(self.combination_unit_price)
            }
        return float(self.selling_price)

    def serialize(self, for_pos=False):
        """Enhanced serialization with POS-specific options"""
        data = {
            'id': self.id,
            'name': self.name,
            'price': float(self.selling_price),
            'cost_price': float(self.cost_price),
            'stock': self.stock,
            'image_url': self.image_url,
            'barcode': self.barcode,
            'category_id': self.category_id,
            'is_active': self.is_active,
            'is_low_stock': self.is_low_stock,
            'profit': float(self.profit),
            'profit_margin': float(self.profit_margin),
            'is_combo': self.is_combo  
        }

        if for_pos:
            data.update({
                'display_price': self.display_price,
                'combination_size': self.combination_size,
                'combination_price': float(self.combination_price) if self.combination_price else None,
                'combination_unit_price': float(self.combination_unit_price) if self.combination_unit_price else None,
                'category_name': self.category.name if self.category else None
            })

        return data


    def update_stock(self, quantity):
        """Safe stock update with validation"""
        new_stock = self.stock + quantity
        if new_stock < 0:
            raise ValueError("Insufficient stock available")
        self.stock = new_stock
        return self

    def __repr__(self):
        return f'<Product {self.id}: {self.name}>'



class Supplier(BaseModel, ShopScopedMixin):
    __tablename__ = 'suppliers'
    
    
    name = db.Column(String(200), nullable=False)  # Removed unique=True
    phone = db.Column(String(20), nullable=True)
    
    products = db.relationship("Product", back_populates="supplier")
 

    def __repr__(self):
        return f'<Supplier {self.name}>'

    def serialize(self):
        """Serialize the supplier object."""
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'product_count': len(self.products),  # Include count of products for context
            'products': [product.serialize() for product in self.products]  # Serialize all products
        }


class Expense(BaseModel, ShopScopedMixin):
    __tablename__ = 'expenses'
 
    description = db.Column(String(200), nullable=False)
    amount = db.Column(Numeric(10, 2), nullable=False)  # Changed to Numeric for precision
    date = db.Column(DateTime, default=datetime.utcnow, index=True)
    category = db.Column(String(100), nullable=True, default="Daily Expenses")  # Default category
    product_id = db.Column(Integer, ForeignKey('products.id'), nullable=True)
    quantity = db.Column(Integer, nullable=True)

    __table_args__ = (
        Index('ix_expense_date_category', 'date', 'category'),  # Composite index
    )

    product = relationship('Product', backref='expenses', lazy='select')  # Changed to select for efficiency

    @validates('amount', 'quantity')
    def validate_amount_quantity(self, key, value):
        """Validate that the expense amount and quantity are positive."""
        if key == 'amount' and value <= 0:  # Allow zero only for quantity
            raise ValueError("Expense amount must be positive.")
        if key == 'quantity' and value <= 0:
            raise ValueError("Quantity must be positive.")
        return value

    def serialize(self):
        """Serialize the expense object."""
        return {
            'id': self.id,
            'description': self.description,
            'amount': str(self.amount),  # Convert to string for JSON serialization
            'date': self.date.strftime("%Y-%m-%d %H:%M:%S"),
            'category': self.category,
            'product_id': self.product_id,
            'quantity': self.quantity,
            'product_name': self.product.name if self.product else None  # Optional product name
        }


class StockLog(BaseModel, ShopScopedMixin):
    __tablename__ = 'stock_logs'
    
    
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date = db.Column(db.DateTime, default=func.now())
    previous_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    adjustment_type = db.Column(SQLAlchemyEnum(AdjustmentType), nullable=False)  
    change_reason = db.Column(db.String(200), nullable=True)
    log_metadata = db.Column(JSON, nullable=True) 
    
    product = db.relationship('Product', back_populates='stock_logs')
    user = db.relationship('User', back_populates='stock_logs')
    
    def __repr__(self):
        return f"<StockLog(product_id={self.product_id}, previous_stock={self.previous_stock}, new_stock={self.new_stock})>"

# Adding stock_logs relationship to Product and User models
Product.stock_logs = db.relationship('StockLog', order_by=StockLog.date, back_populates='product')
User.stock_logs = db.relationship('StockLog', back_populates='user')        


class PriceChange(BaseModel, ShopScopedMixin):
    __tablename__ = 'price_changes'
    
   
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    change_type = db.Column(db.String(50), nullable=False)  
    old_price = db.Column(db.Numeric(10, 2), nullable=False)
    new_price = db.Column(db.Numeric(10, 2), nullable=False)
    old_combo_size = db.Column(db.Integer, nullable=True)
    old_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    new_combo_size = db.Column(db.Integer, nullable=True)
    new_combo_price = db.Column(db.Numeric(10, 2), nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    product = db.relationship('Product', backref='price_changes')
    user = db.relationship('User', backref='price_changes')


    @classmethod
    def create_record(cls, product_id, user_id, change_type, old_price, new_price,
                     old_combo=None, new_combo=None):
        """Create and return a new price change record"""
        record = cls(
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
        db.session.add(record)
        return record
    

    