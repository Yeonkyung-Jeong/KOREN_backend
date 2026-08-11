# 시딩/임베딩 스크립트 전용 DB 접속 모듈.
# app/database.py의 전역 SessionLocal은 echo=True라 임베딩 값(1536차원)까지 로그에
# 찍혀 로그가 폭증하므로, 여기서는 별도로 echo=False 엔진/세션을 만든다.
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 시딩 스크립트 간 재현 가능한 랜덤 결과를 위한 공유 seed
RNG_SEED = 42


def get_session():
    return SessionLocal()
