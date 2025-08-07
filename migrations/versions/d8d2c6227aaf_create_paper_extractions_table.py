"""create_paper_extractions_table

Revision ID: d8d2c6227aaf
Revises: 07d1c06231f0
Create Date: 2025-05-29 16:52:56.041878

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = 'd8d2c6227aaf'
down_revision: Union[str, None] = '07d1c06231f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Buat tabel paper_extractions
    op.create_table(
        'paper_extractions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('paper_id', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('pdf_url', sa.Text(), nullable=False),
        sa.Column('extracted_text', sa.Text(), nullable=True),
        sa.Column('extraction_status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('extraction_date', sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column('last_accessed_at', sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('extraction_time', sa.Integer(), nullable=True),
        sa.Column('text_length', sa.Integer(), nullable=True),
    )
    
    # Membuat tabel chat_sessions dengan relasi ke users
    op.create_table(
        'chat_sessions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True),
        sa.Column('paper_id', sa.String(255), nullable=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column('last_message_at', sa.DateTime(), nullable=False, server_default=func.now()),
    )
    
    # Membuat tabel chat_messages dengan relasi ke chat_sessions
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('is_user', sa.Boolean(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=func.now()),
    )
    
    # Buat indeks tambahan untuk optimasi
    op.create_index('idx_paper_extractions_status', 'paper_extractions', ['extraction_status'])
    op.create_index('idx_chat_sessions_user_paper', 'chat_sessions', ['user_id', 'paper_id'])
    op.create_index('idx_chat_messages_session_id', 'chat_messages', ['session_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Hapus tabel dalam urutan terbalik (karena constraint foreign key)
    op.drop_table('chat_messages')
    op.drop_table('chat_sessions')
    op.drop_table('paper_extractions')