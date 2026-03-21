"""Alembic environment configuration for clawwrap schema."""

from alembic import context

# Target schema for all clawwrap tables
SCHEMA_NAME = "clawwrap"

config = context.config


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA_NAME,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    from sqlalchemy import create_engine, text

    url = config.get_main_option("sqlalchemy.url")
    engine = create_engine(url)

    with engine.connect() as connection:
        # Ensure the clawwrap schema exists
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA_NAME}"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=None,
            version_table_schema=SCHEMA_NAME,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.execute(f"SET search_path TO {SCHEMA_NAME}")
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
