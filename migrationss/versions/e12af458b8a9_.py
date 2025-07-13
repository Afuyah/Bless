"""empty message

Revision ID: e12af458b8a9
Revises: 08b9e4ca0f22
Create Date: 2025-07-13 12:21:00
"""
from alembic import op
import sqlalchemy as sa
import enum


# revision identifiers, used by Alembic.
revision = 'e12af458b8a9'
down_revision = '08b9e4ca0f22'
branch_labels = None
depends_on = None


# Define the shop type enum
class ShopType(enum.Enum):
    pos = "pos"
    pop = "pop"

shop_enum = sa.Enum(ShopType, name="shoptype")

def upgrade():
    # Create the ENUM first
    shop_enum.create(op.get_bind(), checkfirst=True)

    # Then add the column
    op.add_column('shops', sa.Column('type', shop_enum, nullable=True))


def downgrade():
    op.drop_column('shops', 'type')
    shop_enum.drop(op.get_bind(), checkfirst=True)
