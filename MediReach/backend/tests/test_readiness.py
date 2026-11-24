from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def readiness_context():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, TestingSession
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        engine.dispose()


def migration_heads():
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(config).get_heads()


def set_migration_revisions(session_factory, revisions):
    with session_factory() as db:
        db.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        )
        db.execute(text("DELETE FROM alembic_version"))
        for revision in revisions:
            db.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
                {"revision": revision},
            )
        db.commit()


def test_readiness_accepts_database_at_all_packaged_migration_heads(readiness_context):
    client, session_factory = readiness_context
    heads = migration_heads()
    assert heads
    set_migration_revisions(session_factory, heads)

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.parametrize("revision", ["old_unapplied_revision", "future_unknown_revision"])
def test_readiness_rejects_database_behind_or_ahead_of_migrations(
    readiness_context, revision
):
    client, session_factory = readiness_context
    set_migration_revisions(session_factory, [revision])

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database schema is not up to date"}


def test_readiness_rejects_database_without_migration_history(readiness_context):
    client, _ = readiness_context

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database schema is not up to date"}


def test_readiness_returns_generic_error_without_exposing_database_url(readiness_context):
    client, _ = readiness_context

    class UnavailableSession:
        def execute(self, statement):
            raise OperationalError(
                str(statement),
                {},
                RuntimeError("postgresql://user:secret@db.example/medireach"),
            )

    def unavailable_db():
        yield UnavailableSession()

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = unavailable_db
    try:
        response = client.get("/health/ready")
    finally:
        app.dependency_overrides[get_db] = previous_override

    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "secret" not in response.text
    assert "db.example" not in response.text


def test_liveness_probe_does_not_depend_on_database(readiness_context):
    client, _ = readiness_context

    class UnavailableSession:
        def execute(self, statement):
            raise OperationalError(
                str(statement),
                {},
                RuntimeError("database unavailable"),
            )

    def unavailable_db():
        yield UnavailableSession()

    previous_override = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = unavailable_db
    try:
        response = client.get("/health")
    finally:
        app.dependency_overrides[get_db] = previous_override

    assert response.status_code == 200


def test_container_contract_includes_migrations_and_non_root_user():
    dockerfile = (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY migrations ./migrations" in dockerfile
    assert "COPY alembic.ini ./alembic.ini" in dockerfile
    assert "USER app" in dockerfile
    assert "COPY .env" not in dockerfile
    assert "COPY . " not in dockerfile


def test_dockerignore_excludes_environment_files_and_local_databases():
    dockerignore = (BACKEND_DIR / ".dockerignore").read_text(encoding="utf-8")

    assert ".env" in dockerignore
    assert ".env.*" in dockerignore
    assert "*.db" in dockerignore
    assert ".git/" in dockerignore
