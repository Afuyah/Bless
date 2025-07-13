from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, HiddenField, EmailField, TelField, validators, TextAreaField, FileField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError, Email, Regexp, Optional
from app.models import User, Role  
import re

countries = ["Kenya", "Uganda", "Tanzania", "Rwanda"]

class CreateBusinessForm(FlaskForm):
    name = StringField('Business Name', validators=[
        DataRequired(message="Business name is required"),
        Length(min=2, max=150, message="Name must be between 2-150 characters"),
        Regexp(r'^[a-zA-Z0-9\s\-&.,]+$', 
               message="Name can only contain letters, numbers, spaces, and basic punctuation")
    ], render_kw={
        "placeholder": "Acme Corporation",
        "class": "peer focus:ring-2 focus:ring-indigo-500"
    })

    email = EmailField('Contact Email', validators=[
        Optional(),
        Email(message="Please enter a valid email address"),
        Length(max=150, message="Email cannot exceed 150 characters")
    ], render_kw={
        "placeholder": "contact@example.com",
        "class": "pl-10 peer focus:ring-2 focus:ring-indigo-500"
    })

    phone = TelField('Phone Number', validators=[
        Optional(),
        Length(max=20, message="Phone number cannot exceed 20 characters"),
        Regexp(r'^[\d\s\+\(\)\-]+$', message="Please enter a valid phone number")
    ], render_kw={
        "placeholder": "+254 700 000000",
        "class": "pl-10 peer focus:ring-2 focus:ring-indigo-500"
    })

    registration_number = StringField('Registration Number', validators=[
        Optional(),
        Length(max=50, message="Registration number cannot exceed 50 characters"),
        Regexp(r'^[a-zA-Z0-9\-]+$', message="Only alphanumeric characters and hyphens allowed")
    ], render_kw={
        "placeholder": "CPR123456",
        "class": "peer focus:ring-2 focus:ring-indigo-500"
    })

    tax_id = StringField('Tax Identification', validators=[
        Optional(),
        Length(max=50, message="Tax ID cannot exceed 50 characters"),
        Regexp(r'^[a-zA-Z0-9\-]+$', message="Only alphanumeric characters and hyphens allowed")
    ], render_kw={
        "placeholder": "P123456789X",
        "class": "peer focus:ring-2 focus:ring-indigo-500"
    })

    address = TextAreaField('Address', validators=[
        Optional(),
        Length(max=500, message="Address cannot exceed 500 characters")
    ], render_kw={
        "placeholder": "123 Business Street",
        "rows": 2,
        "class": "peer focus:ring-2 focus:ring-indigo-500"
    })

    city = StringField('City', validators=[
        Optional(),
        Length(max=100, message="City name cannot exceed 100 characters"),
        Regexp(r'^[a-zA-Z\s\-]+$', message="Only letters, spaces and hyphens allowed")
    ], render_kw={
        "placeholder": "Nairobi",
        "class": "peer focus:ring-2 focus:ring-indigo-500"
    })

    country = SelectField('Country', 
        choices=[(c, c) for c in countries], 
        default='Kenya',
        validators=[DataRequired()],
        render_kw={
            "class": "peer focus:ring-2 focus:ring-indigo-500"
        }
    )

    submit = SubmitField("Create Business", render_kw={
        "class": "inline-flex items-center px-4 py-2.5 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition"
    })



class CreateTenantForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=50),
        Regexp(r'^[a-zA-Z0-9_]+$', 
               message='Username can only contain letters, numbers and underscores')
    ], render_kw={
        "placeholder": "john.doe",
        "class": "pl-10 peer focus:ring-2 focus:ring-indigo-500"
    })
    
    email = EmailField('Email', validators=[
        Optional(),
        Email(),
        Length(max=120)
    ], render_kw={
        "placeholder": "optional@example.com", 
        "class": "pl-10 peer focus:ring-2 focus:ring-indigo-500"
    })
    
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters'),
        Regexp(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)', 
               message='Must contain uppercase, lowercase and number')
    ], render_kw={
        "placeholder": "••••••••",
        "class": "pl-10 peer focus:ring-2 focus:ring-indigo-500"
    })
    
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    
    send_welcome_email = SelectField('Send Welcome Email', 
        choices=[('yes', 'Yes'), ('no', 'No')],
        default='yes'
    )
    
    submit = SubmitField('Create Tenant', render_kw={
        "class": "inline-flex items-center px-4 py-2.5 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 transition"
    })

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data.lower()).first()
        if user:
            raise ValidationError('That username is already taken.')

    def validate_email(self, email):
        if email.data:  # Only validate if email is provided
            user = User.query.filter_by(email=email.data.lower()).first()
            if user:
                raise ValidationError('That email is already registered.')




class CreateShopForm(FlaskForm):
    name = StringField('Shop Name', validators=[
        DataRequired(),
        Length(min=2, max=150),
        Regexp(r'^[\w\s\-\.\']+$', message="Only letters, numbers, spaces, and -.' allowed")
    ])
    
    location = StringField('Location', validators=[
        DataRequired(),
        Length(max=255),
        Regexp(r'^[\w\s\-\.\,]+$', message="Invalid location characters")
    ])
    
    phone = StringField('Phone Number', validators=[
        DataRequired(),
        Length(min=10, max=20)
    ])
    
    email = EmailField('Email (Optional)', validators=[
        Optional(),
        Email(),
        Length(max=120)
    ])
    
    currency = SelectField('Currency', choices=[
        ('KES', 'KES (Kenyan Shilling)'),
        ('USD', 'USD (US Dollar)'), 
        ('EUR', 'EUR (Euro)')
    ], default='KES')
    
    submit = SubmitField('Create Shop')
    
    def validate_phone(self, field):
        phone = field.data.strip()
        if not re.match(r'^\+?[\d\s-]{10,20}$', phone):
            raise ValidationError('Invalid phone format. Use +XXX... or local digits')



class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[
        DataRequired(),
        Length(min=3, max=25, message="Username must be between 3 and 25 characters.")
    ])
    
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=6, message="Password must be at least 6 characters long.")
    ])
    
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message="Passwords must match.")
    ])
    
    role = SelectField('Role', choices=[], validators=[DataRequired()])
    
    shop_id = SelectField('Shop (Optional)', coerce=int, choices=[], validate_choice=False)
    
    submit = SubmitField('Create User')

    def validate_username(self, field):
        existing_user = User.query.filter_by(username=field.data.strip().lower()).first()
        if existing_user:
            raise ValidationError('Username already exists.')

    def validate_role(self, field):
        if field.data.upper() not in Role.__members__:
            raise ValidationError('Invalid role selected.')
