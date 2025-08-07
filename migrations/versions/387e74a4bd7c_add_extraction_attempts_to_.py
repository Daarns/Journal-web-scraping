"""Add extraction_attempts to PaperExtraction

Revision ID: 387e74a4bd7c
Revises: d8d2c6227aaf
Create Date: 2025-06-03 16:02:52.892117

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '387e74a4bd7c'
down_revision: Union[str, None] = 'd8d2c6227aaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Tambahkan kolom extraction_attempts dengan tipe Integer
    op.add_column('paper_extractions', sa.Column('extraction_attempts', sa.Integer(), nullable=True))
    
    # Update nilai default untuk row yang sudah ada
    op.execute("UPDATE paper_extractions SET extraction_attempts = 1 WHERE extraction_attempts IS NULL")
    
    # Opsional: Mengubah kolom menjadi non-nullable setelah mengisi data
    # op.alter_column('paper_extractions', 'extraction_attempts', nullable=False, server_default='1')


def downgrade() -> None:
    """Downgrade schema."""
    # Hapus kolom jika perlu rollback
    op.drop_column('paper_extractions', 'extraction_attempts')
