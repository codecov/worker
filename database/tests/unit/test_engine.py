from sqlalchemy.dialects.postgresql import insert
from sqlalchemy_utils import get_mapper

from database.engine import SessionFactory
from database.models import Commit
from database.models.timeseries import Measurement


class TestDatabaseEngine:
    def test_session_get_bind_timeseries_disabled(self, sqlalchemy_connect_url, mocker):
        mocker.patch("database.engine.timeseries_enabled", return_value=False)

        session_factory = SessionFactory(
            database_url=sqlalchemy_connect_url,
            timeseries_database_url=sqlalchemy_connect_url,
        )
        session = session_factory.create_session()
        assert session_factory.main_engine is not None
        assert session_factory.timeseries_engine is None

        engine = session.get_bind(mapper=get_mapper(Commit))
        assert engine == session_factory.main_engine

        clause = insert(Commit.__table__)
        engine = session.get_bind(clause=clause)
        assert engine == session_factory.main_engine

        engine = session.get_bind(mapper=get_mapper(Measurement))
        assert engine == session_factory.main_engine

        clause = insert(Measurement.__table__)
        engine = session.get_bind(clause=clause)
        assert engine == session_factory.main_engine

    def test_session_get_bind_timeseries_enabled(self, sqlalchemy_connect_url, mocker):
        mocker.patch("database.engine.timeseries_enabled", return_value=True)

        session_factory = SessionFactory(
            database_url=sqlalchemy_connect_url,
            timeseries_database_url=sqlalchemy_connect_url,
        )

        session = session_factory.create_session()
        assert session_factory.main_engine is not None
        assert session_factory.timeseries_engine is not None

        engine = session.get_bind(mapper=get_mapper(Commit))
        assert engine == session_factory.main_engine

        clause = insert(Commit.__table__)
        engine = session.get_bind(clause=clause)
        assert engine == session_factory.main_engine

        engine = session.get_bind(mapper=get_mapper(Measurement))
        assert engine == session_factory.timeseries_engine

        clause = insert(Measurement.__table__)
        engine = session.get_bind(clause=clause)
        assert engine == session_factory.timeseries_engine
