"""add paused_until to chat_sessions

Revision ID: f6a1b2c3d4e5
Revises: e5f0a1b2c3d4
Create Date: 2026-08-13 15:40:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, None] = 'e5f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_sessions', sa.Column('paused_until', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('chat_sessions', 'paused_until')
