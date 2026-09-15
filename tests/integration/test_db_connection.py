from sqlalchemy import Engine, text


def test_database_connection_reaches_test_postgres(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        result = connection.execute(text("SELECT 1"))

        assert result.scalar_one() == 1
