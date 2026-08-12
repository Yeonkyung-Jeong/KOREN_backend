from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
import os

# .env 파일 로드
load_dotenv()

# PostgreSQL 연결 URL
DATABASE_URL = os.getenv(
    "DATABASE_URL"
)

# 엔진 생성
engine = create_engine(DATABASE_URL, echo=True)

# 세션 로컬 클래스
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 조용한(echo=False) 엔진/세션 — /chat 등 임베딩 벡터(1536차원)를 다루는 경로 전용.
# echo=True로 로깅하면 벡터 값이 그대로 로그에 찍혀 로그가 폭증하므로 별도로 둔다.
quiet_engine = create_engine(DATABASE_URL, echo=False)
SessionLocalQuiet = sessionmaker(autocommit=False, autoflush=False, bind=quiet_engine)

# 의존성 (Dependency)
def get_db() -> Session:
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()

def get_db_quiet() -> Session:
  db = SessionLocalQuiet()
  try:
    yield db
  finally:
    db.close()