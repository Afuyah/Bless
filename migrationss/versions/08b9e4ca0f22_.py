"""empty message

Revision ID: 08b9e4ca0f22
Revises: 
Create Date: 2025-07-13 11:41:08.951653
"""
from alembic import op
import sqlalchemy as sa
import enum


# revision identifiers, used by Alembic.
revision = '08b9e4ca0f22'
down_revision = None
branch_labels = None
depends_on = None


# Define the enum again inside the migration
class UnitType(enum.Enum):
    piece = 'piece'
    kg = 'kg'
    grams = 'grams'
    punnet = 'punnet'
    bunch = 'bunch'
    packet = 'packet'
    litre = 'litre'

unit_enum = sa.Enum(UnitType, name='unittype')

def upgrade():
    # Create ENUM type first
    unit_enum.create(op.get_bind(), checkfirst=True)

    # Now use it in the column
    op.add_column('products', sa.Column('unit', unit_enum, nullable=True))
    op.add_column('shops', sa.Column('is_active', sa.Boolean(), nullable=True))
    op.create_index('ix_shops_business_id', 'shops', ['business_id'], unique=False)
    op.create_index('ix_shops_is_active', 'shops', ['is_active'], unique=False)
    op.create_index('ix_shops_name', 'shops', ['name'], unique=False)
    op.create_index('ix_shops_phone', 'shops', ['phone'], unique=False)

def downgrade():
    op.drop_index('ix_shops_phone', table_name='shops')
    op.drop_index('ix_shops_name', table_name='shops')
    op.drop_index('ix_shops_is_active', table_name='shops')
    op.drop_index('ix_shops_business_id', table_name='shops')
    op.drop_column('shops', 'is_active')
    op.drop_column('products', 'unit')
    unit_enum.drop(op.get_bind(), checkfirst=True)
