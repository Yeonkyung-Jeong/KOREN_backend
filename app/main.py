import os
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from app.routers import router
from app.model_loader import load_model

app = FastAPI()
model = load_model()

front_url = os.getenv("FRONT_URL")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=[front_url],  # 프론트 서버 주소 포트가 사용 중이라고 자꾸 변경되어서 환경변수 처리
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(router)
