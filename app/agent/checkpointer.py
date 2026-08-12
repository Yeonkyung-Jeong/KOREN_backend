# app/agent/checkpointer.py
# 멀티턴 대화(PRD §9.1)를 위한 PostgresSaver. 기존 DATABASE_URL(psycopg2용
# SQLAlchemy 방언 문자열)을 그대로 재사용하되, PostgresSaver는 psycopg3
# 드라이버를 쓰므로 DSN을 psycopg3 형식으로 변환해서 별도 커넥션 풀을 연다.
import os
from functools import lru_cache

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

load_dotenv()


def _psycopg3_dsn() -> str:
    url = os.getenv("DATABASE_URL", "")
    return url.replace("postgresql+psycopg2://", "postgresql://")


@lru_cache
def get_checkpoint_pool() -> ConnectionPool:
    """psycopg3 커넥션 풀 싱글턴을 반환한다(lru_cache로 프로세스당 1개만 생성).

    open=False로 만든 뒤 즉시 pool.open()을 호출하는 이유: psycopg_pool
    최신 버전은 생성자에서 암묵적으로 커넥션을 여는 동작을 지원 중단했으므로,
    명시적으로 열어야 한다.
    """
    pool = ConnectionPool(
        conninfo=_psycopg3_dsn(),
        kwargs={"autocommit": True, "row_factory": dict_row},
        max_size=5,
        open=False,
    )
    pool.open()
    return pool


@lru_cache
def get_checkpointer() -> PostgresSaver:
    """PostgresSaver 싱글턴을 반환한다. build_production_graph()가 compile 시 주입한다."""
    return PostgresSaver(get_checkpoint_pool())


def setup_checkpointer() -> None:
    """앱 기동 시 1회 호출 — 체크포인트 테이블이 없으면 생성한다(멱등, PRD §9.1)."""
    get_checkpointer().setup()
