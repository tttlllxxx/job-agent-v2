from alembic import context
from app.config import settings
from app.database import Base, make_engine

context.config.set_main_option("sqlalchemy.url", settings().database_url)
if context.is_offline_mode():
    context.configure(
        url=settings().database_url, target_metadata=Base.metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with make_engine(settings().database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
