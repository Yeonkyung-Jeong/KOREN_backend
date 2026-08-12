# app/routers/__init__.py
# 기존 app/routers.py를 core.py로 이동하고, 신규 엔드포인트(chat.py)를
# 별도 파일로 분리하기 위한 패키지 진입점. app/main.py의
# `from app.routers import router` 임포트 경로는 그대로 유지된다.
from fastapi import APIRouter

from app.routers.core import router as core_router
from app.routers.chat import router as chat_router

router = APIRouter()
router.include_router(core_router)
router.include_router(chat_router)
