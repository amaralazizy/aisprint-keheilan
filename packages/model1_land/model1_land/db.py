import os
from sqlmodel import SQLModel, create_engine, Session

_RAW_URL = os.getenv("DATABASE_URL", "sqlite:///model1_land.db")

# Neon and many other providers hand out `postgres://` URLs — SQLAlchemy 2.x
# requires the explicit `postgresql+psycopg://` driver scheme.
if _RAW_URL.startswith("postgres://"):
    DB_URL = "postgresql+psycopg://" + _RAW_URL[len("postgres://"):]
elif _RAW_URL.startswith("postgresql://") and "+psycopg" not in _RAW_URL.split("://", 1)[0]:
    DB_URL = "postgresql+psycopg://" + _RAW_URL[len("postgresql://"):]
else:
    DB_URL = _RAW_URL

_connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, echo=False, connect_args=_connect_args, pool_pre_ping=True)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
