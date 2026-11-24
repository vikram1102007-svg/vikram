import pytest
from pydantic import ValidationError

from app.config import Settings


def make_settings(**values):
    return Settings(_env_file=None, **values)


def test_development_keeps_local_sqlite_available():
    settings = make_settings()
    assert settings.environment == "development"
    assert settings.database_url.startswith("sqlite://")
    assert settings.sqlalchemy_database_url == settings.database_url


@pytest.mark.parametrize("database_url", ["sqlite:///./medireach.db", ""])
def test_production_rejects_sqlite_or_missing_database(database_url):
    with pytest.raises(ValidationError):
        make_settings(
            environment="production",
            database_url=database_url,
            cors_origins="https://medireach.example",
        )


def test_production_rejects_invalid_database_url():
    with pytest.raises(ValidationError):
        make_settings(
            environment="production",
            database_url="not-a-database-url",
            cors_origins="https://medireach.example",
        )


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql://user:password@db.example:5432/medireach",
        "postgres://user:password@db.example:5432/medireach",
    ],
)
def test_production_postgresql_urls_use_installed_psycopg_driver(database_url):
    settings = make_settings(
        environment="production",
        database_url=database_url,
        cors_origins="https://medireach.example",
    )
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")
    assert settings.sqlalchemy_database_url.endswith("/medireach")


def test_production_requires_database_host_and_name():
    invalid_urls = [
        "postgresql://user:password@/medireach",
        "postgresql://user:password@db.example",
    ]
    for database_url in invalid_urls:
        with pytest.raises(ValidationError):
            make_settings(
                environment="production",
                database_url=database_url,
                cors_origins="https://medireach.example",
            )


def test_explicit_psycopg_url_is_preserved():
    database_url = "postgresql+psycopg://user:password@db.example:5432/medireach"
    settings = make_settings(
        environment="production",
        database_url=database_url,
        cors_origins="https://medireach.example",
    )
    assert settings.sqlalchemy_database_url == database_url


@pytest.mark.parametrize(
    "cors_origins",
    [
        "",
        "*",
        "http://medireach.example",
        "https://medireach.example/",
        "https://medireach.example/app",
        "https://medireach.example?mode=demo",
        "https://user:pass@medireach.example",
        "https://medireach.example:invalid",
    ],
)
def test_production_rejects_non_exact_or_insecure_cors_origins(cors_origins):
    with pytest.raises(ValidationError):
        make_settings(
            environment="production",
            database_url="postgresql+psycopg://user:password@db.example:5432/medireach",
            cors_origins=cors_origins,
        )


def test_production_accepts_multiple_exact_https_origins():
    settings = make_settings(
        environment="production",
        database_url="postgresql+psycopg://user:password@db.example:5432/medireach",
        cors_origins="https://medireach-platform.embarko.app, https://staff.medireach.example",
    )
    assert settings.allowed_origins == [
        "https://medireach-platform.embarko.app",
        "https://staff.medireach.example",
    ]


def test_non_production_can_keep_local_http_origins():
    settings = make_settings(
        environment="development",
        cors_origins="http://localhost:3000,http://127.0.0.1:5500",
    )
    assert settings.allowed_origins == [
        "http://localhost:3000",
        "http://127.0.0.1:5500",
    ]
