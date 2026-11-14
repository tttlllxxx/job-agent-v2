"""Create the independently migrated v2 workspace."""

from alembic import op
from app.database import Base

revision = "20261112_workspace"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(op.get_bind())


def downgrade():
    Base.metadata.drop_all(op.get_bind())
