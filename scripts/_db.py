# 시딩/임베딩 스크립트 전용 DB 접속 모듈.
# app/database.py의 전역 SessionLocal은 echo=True라 임베딩 값(1536차원)까지 로그에
# 찍혀 로그가 폭증하므로, 여기서는 별도로 echo=False 엔진/세션을 만든다.
#
# 엔진 생성을 get_session() 호출 시점까지 지연한다 — 이 스크립트를 import하는
# 순간(예: 순수 함수만 재사용하는 tests/)에는 DATABASE_URL이 없어도 되게 하기 위함.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

# 시딩 스크립트 간 재현 가능한 랜덤 결과를 위한 공유 seed
RNG_SEED = 42

_engine = None
_SessionLocal = None


def get_session():
    global _engine, _SessionLocal
    if _SessionLocal is None:
        load_dotenv()
        _engine = create_engine(os.getenv("DATABASE_URL"), echo=False)
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _SessionLocal()
