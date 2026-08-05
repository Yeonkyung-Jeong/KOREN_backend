# 연합학습 기반 의료 진단 AI 플랫폼
## K-디지털 챌린지: NET 챌린지 캠프 공모전 (25.07.08 - 25.11.07)
### 👥 프론트엔드 1명, 백엔드 1명, AI 1명, 인프라 1명
<br> </br>
### 프로젝트 개요
**군·면 지역 보건소 및 중소병원의 진단 역량 향상과 지역 간 의료 격차 해소를 목표**로 하는 온디바이스 AI 진단 플랫폼입니다.

각 병원 노드는 의료 데이터를 외부로 공유하지 않고 모델 파라미터만 중앙 서버로 전달하여 연합학습을 수행하며,

중앙 서버에서 집계된 글로벌 모델을 다시 각 노드에 배포하는 구조로 설계되었습니다.

‘AI 진단 결과 0.5초 이내 반환’을 목표로 백엔드를 개발했습니다

<img width="1514" height="733" alt="image" src="https://github.com/user-attachments/assets/f7da8afa-0af7-439a-90a3-fd4e698998a8" />

<img width="1446" height="790" alt="image" src="https://github.com/user-attachments/assets/e71593e2-3a86-4565-ac13-c7f9e7c7fe4f" />

<img width="1511" height="641" alt="image" src="https://github.com/user-attachments/assets/9ef5cde0-d5e5-44a9-beaf-c54ff14d4f56" />

<br> </br>

### 역할

- 연합학습 ↔ 로컬 진단 파이프라인 기획
- FastAPI 기반 백엔드 개발
- TensorFlow 기반 AI 진단 모델 추론 백엔드 구현

<br> </br>

### 사용 기술

<aside>

`FastAPI` `TensorFlow` `React` `OpenAI API` `PostgreSQL` `Github` 

</aside>

<br> </br>

### 시스템 아키텍처

<img width="1144" height="689" alt="image" src="https://github.com/user-attachments/assets/c37bb5ed-4d57-4f63-ac0c-f913877fcffb" />
- KOREN 고속망 안에 Openstack VM을 만들고, 그 위에 K-PaaS 관리 기반 도커 컨테이너들로 구성했습니다. 해당 도커 컨테이너는 병원 노드를 의미하며, React + FastAPI + PostgreSQL로 진단플랫폼을 구현하였음을 표현했습니다.
<br> </br>
- 각 노드는 의료 데이터를 외부에 노출하지 않고 모델 파라미터만 중앙 집계 서버로 전송해 연합학습을 수행하며, 집계된 글로벌 모델은 다시 각 노드에 배포됩니다.

<br> </br>

### 사용 모델 및 연합학습 결과
<img width="1508" height="557" alt="image" src="https://github.com/user-attachments/assets/d1d82098-6081-43e6-8e43-653475e5eb19" />
<img width="1561" height="641" alt="image" src="https://github.com/user-attachments/assets/f0cc13b1-7d20-44c2-be69-be7c550047ee" />

-----
<details>
<summary>개발 공유 사항</summary>

- 백엔드 설계 문서: https://glossy-cello-8d3.notion.site/ERD-API-2563ae1b20c680ccb481f7223dd5a73a?source=copy_link
- 모델 의존성 버전 변경사항: https://glossy-cello-8d3.notion.site/_-2583ae1b20c6809cacedf700028e200a?source=copy_link
- 포스트맨 테스트 문서: https://glossy-cello-8d3.notion.site/2583ae1b20c6807c925ad399ecfa92c4?source=copy_link
- 통합테스트 QA 문서: https://glossy-cello-8d3.notion.site/QA-2583ae1b20c68016841bd5059ef4b7f4?source=copy_link
- .env: https://www.notion.so/env-2583ae1b20c680d6b986e0984822b7cc?source=copy_link

---

requirements.txt 의존성들을 모두 받아야 모델이 로컬에서 동작함.
두 번째 '모델 의존성 버전 변경사항'을 읽어보면 알겠지만, 해당 requirements는 python 3.11, window 기준으로 호환되도록 변경되어서 각자 로컬에 맞게 변경이 필요할 수 있습니다..🤮🤮

### venv 사용 시:
```
1. python -m venv venv        # 가상환경 생성
2. source venv/bin/activate   # Windows: .venv\Scripts\activate       -> 좌측에 (.venv) 표시 뜨면 venv 환경에 들어온 것.
3. pip install -r requirements.txt    # requirements.txt 내 의존성들 모두 설치
4. 프로젝트 구조에서 python SDK를 .venv/Scripts/python.exe로 바꿔주기
```

### 전역 Python 환경 사용 시:
```
pip install -r requirements.txt
```

### 기타 서버실행을 위한 필수 설치 패키지 
```
pip install fastapi
pip install uvicorn
pip install sqlalchemy
pip install openai
pip install dotenv
pip install psycopg2
```
</details>
