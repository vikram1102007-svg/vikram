from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings


BACKEND_DIR = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def test_feedback_review_migration_preserves_existing_rows_and_downgrades(
    tmp_path, monkeypatch
):
    database_url = f"sqlite:///{tmp_path / 'migration-compatibility.db'}"
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    engine = None

    try:
        config = alembic_config()
        command.upgrade(config, "0001_initial")

        engine = create_engine(database_url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO facilities "
                    "(id, name, district, address, phone, is_active) "
                    "VALUES (1, 'Test PHC', 'Test District', 'Test address', NULL, 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO medicines (id, name, strength, form) "
                    "VALUES (1, 'Paracetamol', '500 mg', 'tablet')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO facility_access_keys "
                    "(id, facility_id, key_hash, created_at, revoked_at) "
                    "VALUES (1, 1, :key_hash, '2026-11-24 12:00:00', NULL)"
                ),
                {"key_hash": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO inventory_records "
                    "(id, facility_id, medicine_id, status, quantity, verified_at, source, is_demo) "
                    "VALUES (1, 1, 1, 'available', 12, '2026-11-24 12:00:00', "
                    "'facility_staff_portal', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO availability_feedback "
                    "(id, inventory_record_id, outcome, comment, created_at, review_required) "
                    "VALUES (1, 1, 'not_available', NULL, '2026-11-24 12:01:00', 1)"
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("availability_feedback")}
            assert "reviewed_at" in columns
            assert "reviewed_by_access_key_id" in columns
            row = connection.execute(
                text(
                    "SELECT review_required, reviewed_at, reviewed_by_access_key_id "
                    "FROM availability_feedback WHERE id = 1"
                )
            ).one()
            assert row.review_required in (True, 1)
            assert row.reviewed_at is None
            assert row.reviewed_by_access_key_id is None

        command.downgrade(config, "0001_initial")

        with engine.connect() as connection:
            columns = {column["name"] for column in inspect(connection).get_columns("availability_feedback")}
            assert "reviewed_at" not in columns
            assert "reviewed_by_access_key_id" not in columns
            row = connection.execute(
                text(
                    "SELECT id, outcome, review_required "
                    "FROM availability_feedback WHERE id = 1"
                )
            ).one()
            assert row.id == 1
            assert row.outcome == "not_available"
            assert row.review_required in (True, 1)
    finally:
        if engine is not None:
            engine.dispose()
        get_settings.cache_clear()


def test_feedback_review_migration_compiles_to_postgresql_ddl(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://migration_user:migration_password@db.example:5432/medireach",
    )
    monkeypatch.setenv("CORS_ORIGINS", "https://medireach.example")
    get_settings.cache_clear()

    try:
        settings = get_settings()
        assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")

        output = StringIO()
        with redirect_stdout(output):
            command.upgrade(alembic_config(), "head", sql=True)

        sql = output.getvalue()
        assert "ALTER TABLE availability_feedback ADD COLUMN reviewed_at" in sql
        assert "ADD COLUMN reviewed_by_access_key_id INTEGER" in sql
        assert "fk_availability_feedback_reviewed_by_access_key_id" in sql
        assert "FOREIGN KEY(reviewed_by_access_key_id)" in sql
        assert "ON DELETE RESTRICT" in sql
        assert "CREATE INDEX ix_availability_feedback_reviewed_by_access_key_id" in sql
        assert "migration_password" not in sql
    finally:
        get_settings.cache_clear()
