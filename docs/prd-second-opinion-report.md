# PRD: AI 세컨드 오피니언 리포트 + 조건부 아카이빙

- 상태: Draft v2
- 작성일: 2026-08-06
- 관련 코드: `app/routers.py`, `app/models.py`, `app/schema.sql`, `app/model_loader.py`
- 변경 이력:
  - v1: 최초 작성 (필터 기준 `anatomy_site` 가정)
  - v2-1: 검색 1차 필터를 `anatomy_site`에서 `diagnosis`(benign/malignant)로 변경
  - v2-2 (본 변경): `diagnosis` 필터가 AI 자신의 판정값이라 발생하는 확증 편향(§7 리스크 6번)에
    대응하기 위해, 지지 근거(`supporting_cases`)와 반박 근거(`contradicting_cases`)를 함께 검색·제시하는
    구조로 §4.3, §5.2, §6.1~6.4, §7 반영

## 1. 배경 및 목적

현재 `/diagnose`는 EfficientNetB2 모델의 `confidence_score` 하나와 고정 문구(`ai_description`)만
반환한다. 의사가 판정 근거를 검토할 방법이 없고, 특히 confidence가 애매한 케이스에서 참고할 과거
유사 사례도 조회할 수 없다.

본 기능은 의사가 저장된 진단 건에 대해 **수동으로** 요청하면, 과거 유사 사례를 pgvector로 검색하고
LangGraph 파이프라인으로 근거 있는 세컨드 오피니언 리포트를 생성한다. 리포트가 "희귀 패턴"으로
판정되고 의사가 승인하면 Notion에 아카이빙(MCP 연동)한다.

## 2. 목표 / 비목표

**목표**
- 진단 1건에 대해 유사 과거 사례 기반 세컨드 오피니언 리포트를 생성한다.
- 생성 과정을 SSE로 실시간 스트리밍한다 (동기 대기 없이 `/diagnose` 응답 지연을 유발하지 않음).
- 희귀 패턴 감지 시, 의사 승인을 거쳐 Notion에 아카이빙한다.

**비목표**
- 환자에게 직접 노출되는 결과물은 만들지 않는다 (2차 사용자인 의사 전용).
- 기존 `/diagnose` 동기 흐름에 개입하지 않는다 (완전히 별도 파이프라인).
- 실시간 인증/인가 체계 구축은 범위 밖이다 (§7 참고).

## 3. 기존 코드베이스 분석 요약

| 항목 | 현재 상태 | 본 기능 설계에 대한 영향 |
|---|---|---|
| 인증 미들웨어 | **없음.** `main.py`에 CORS 외 미들웨어 없음. `Diagnosis.diagnosed_by`도 자유 문자열(`"AI_MODEL"` 또는 의사명)일 뿐 실제 사용자 테이블/토큰 검증 없음 | 새 엔드포인트도 동일 컨벤션(요청자 이름을 body 필드로 받는 자유 문자열)을 따르되, PRD 내 리스크로 명시 |
| 응답 컨벤션 | `JSONResponse(content={...})` 또는 dict 직접 반환. 공통 응답 래퍼(`{success, data}` 등) 없음. 에러는 전부 `HTTPException(status_code=500, detail=str(e))`로 뭉뚱그림 | 기존 컨벤션을 유지하되, 비동기 작업 상태를 표현해야 하므로 job 테이블을 신설해 상태를 명시적 필드로 관리 |
| 라우터 구조 | 서브라우터 분리 없이 `app/routers.py` 하나에 전부 등록 | 새 엔드포인트도 동일 파일에 추가 (또는 파일이 커지면 `second_opinion` 섹션으로 그룹화, 별도 router 파일 분리는 선택사항으로 남김) |
| `Diagnosis` 스키마 | `id, patient_id, medical_image_id, communication_summary_id, diagnosis, anatomy_site, confidence_score, target_value, diagnosed_by, ai_description, diagnosed_at` | `diagnosis`(benign/malignant 2값 enum)를 1차 필터 컬럼으로 확정 → §6.1. ISIC 원본의 세부 `diagnosis` 카테고리(nevus, melanoma 등)는 이 프로젝트 DB에 저장되지 않고 benign/malignant 2값으로만 존재하며, 그마저도 라벨링이 부실한 세부 카테고리 대신 신뢰도가 높은 이 이진값을 필터로 채택 |
| 모델 구조 | `Sequential([EfficientNetB2, GAP, Dense(1024), Dense(512), Dense(256), Dense(128), Dense(1, sigmoid)])` | 마지막 sigmoid 직전 `Dense(128, relu)` 출력을 임베딩으로 재사용 (재학습 불필요, intermediate model만 추가) |
| 이미지 원본 | `MedicalImage.file_path`에 업로드 원본이 `./uploads/`에 보존됨 | 임베딩 미존재 시 저장된 원본 이미지로 온디맨드 재생성 가능 |
| DB | PostgreSQL, `echo=True`로 전체 SQL 로깅 | pgvector 확장 설치 필요. 로깅 볼륨 증가 고려 (§8 리스크) |

### 3.1 경로 파라미터 네이밍 주의사항

기존 `GET /diagnosis/{patient_id}`의 `{patient_id}`는 `Patient.patient_id`(문자열 식별자)이지만,
본 기능의 세 엔드포인트는 특정 진단 1건(이미지 1건)에 대한 리포트이므로 `Diagnosis.id`(정수 PK)를
사용해야 한다. 같은 `/diagnosis/{...}` 프리픽스 아래 파라미터 의미가 다르므로 **혼동 가능성이 있음을
인지하고**, 아래와 같이 확정한다.

> **확정:** 신규 3개 엔드포인트의 `{id}`는 전부 `Diagnosis.id`(정수)이다. 프론트/문서에서 기존
> `/diagnosis/{patient_id}` (문자열)와 명확히 구분 표기할 것.

## 4. 데이터 모델 변경

### 4.1 `diagnoses` 테이블에 벡터 컬럼 추가

```sql
-- 1) pgvector 확장 설치 (DB당 1회)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2) 임베딩 컬럼 추가
ALTER TABLE diagnoses
  ADD COLUMN embedding vector(128),              -- Dense(128) 레이어 출력, L2 정규화 후 저장
  ADD COLUMN embedding_model_version VARCHAR(64), -- 예: "base_model072" — 임베딩을 만든 가중치 버전
  ADD COLUMN embedding_generated_at TIMESTAMP;

-- 3) 유사도 검색 인덱스 (코사인 거리)
CREATE INDEX idx_diagnoses_embedding_hnsw
  ON diagnoses USING hnsw (embedding vector_cosine_ops);
```

**설계 근거**
- 컬럼 위치: `Diagnosis`는 `MedicalImage`와 1:1이고 실제 추론이 일어나는 단위이므로, 요청대로
  `diagnoses` 테이블에 직접 추가한다 (별도 임베딩 테이블 대신).
- `vector(128)`: `model_loader.py`의 `Dense(128, relu)` 레이어 출력 차원과 일치.
- `embedding_model_version`: 연합학습으로 모델 가중치가 갱신되면 임베딩 공간이 달라져 서로 다른
  버전의 벡터를 비교하면 무의미해진다. 검색 쿼리에서 반드시 `WHERE embedding_model_version = :current_version`
  조건을 걸어야 한다. **(§8 리스크에서 재언급)**
- 인덱스: `ivfflat`은 학습(lists 파라미터)에 최소 데이터량이 필요하고 벌크 재빌드가 번거로워, 해커톤/
  포트폴리오 규모(수백~수천 행)에서는 `hnsw`가 더 안전한 기본값. 코사인 거리(`vector_cosine_ops`) 채택.
- `embedding`은 nullable — 기존 행은 즉시 채워지지 않음 (§4.2 백필 전략 참고).
- **1차 필터용 신규 컬럼은 불필요**: 검색 1차 필터는 `diagnoses.diagnosis`(기존 `diagnosis_enum`: benign/malignant) 컬럼을 그대로 사용하므로 추가 컬럼이 필요 없다 (§6.1). 이 값은 ISIC 데이터셋의 세부 `diagnosis` 카테고리(대부분 `unknown`으로 라벨링 부실)를 대체해, 신뢰도가 낮은 라벨보다 이미지 임베딩 유사도에 더 의존하는 방향으로 필터를 단순화한 것이다.
- (선택, 성능) 데이터가 커지면 `diagnosis` 값별 partial index(`WHERE diagnosis = 'benign'` / `'malignant'`)로 HNSW 인덱스를 분리하는 것도 고려할 수 있으나, 현재 규모(수백~수천 행)에서는 단일 인덱스 + WHERE 필터로 충분하다.

### 4.2 임베딩 백필 전략

- **신규 진단**: `/diagnose` 처리 중 추론과 함께 임베딩도 함께 계산해 저장하도록 확장 (본 PRD 범위에
  포함, `routers.py`의 `/diagnose`에 3줄 내외 추가 — intermediate model 호출 + 컬럼 저장).
- **기존 진단(과거 데이터)**: 일회성 백필 스크립트(`scripts/backfill_embeddings.py`, 별도 구현)로
  `MedicalImage.file_path` 원본을 다시 전처리해 임베딩 생성.
- **온디맨드 폴백**: `retrieve_similar_cases` 노드 진입 시 대상 진단의 `embedding IS NULL`이면 그
  자리에서 1회 생성 후 저장 (백필이 안 된 상태에서도 세컨드 오피니언 요청이 실패하지 않도록).

### 4.3 신규 테이블: `second_opinion_reports`

비동기 작업 상태, SSE 스트리밍 소스, 아카이빙 상태를 한 테이블에서 관리한다 (기존 코드에 job/task
테이블 컨벤션이 없으므로 최소 설계로 신설).

```sql
CREATE TYPE second_opinion_status_enum AS ENUM (
  'pending', 'retrieving', 'summarizing', 'drafting', 'completed', 'failed'
);

CREATE TYPE archive_status_enum AS ENUM (
  'not_archived', 'archived', 'archive_failed'
);

CREATE TABLE second_opinion_reports (
  id SERIAL PRIMARY KEY,
  diagnosis_id INTEGER NOT NULL REFERENCES diagnoses(id) ON DELETE CASCADE,
  status second_opinion_status_enum NOT NULL DEFAULT 'pending',
  requested_by VARCHAR(255) NOT NULL,
  requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  completed_at TIMESTAMP,

  -- 결과 스키마 (v2: 지지/반박 근거 분리 — §7 리스크 6번 확증 편향 대응)
  diagnosis_candidate diagnosis_enum,
  confidence_score FLOAT,          -- 원본 Diagnosis.confidence_score를 그대로 echo (LLM이 재계산하지 않음)
  supporting_cases JSONB,          -- 동일 diagnosis 라벨 top-k. [{diagnosis_id, similarity, diagnosis, confidence_score, anatomy_site, age, sex, diagnosed_at}]
  contradicting_cases JSONB,       -- 반대 diagnosis 라벨 top-k' (동일 원소 스키마, k' < k)
  reasoning TEXT,                  -- LLM이 생성한 한국어 소견. 지지/반박 근거를 균형 있게 언급하도록 프롬프트로 강제 (§6.3)
  is_rare_pattern BOOLEAN,         -- supporting_cases 기준 결정론적 규칙 (§6.4), LLM 판단 아님
  is_conflicting_evidence BOOLEAN, -- contradicting_cases가 supporting_cases만큼/그 이상 강한 경우 (§6.4), LLM 판단 아님

  error_message TEXT,

  -- 아카이빙 상태
  archive_status archive_status_enum NOT NULL DEFAULT 'not_archived',
  notion_page_url VARCHAR(512),
  archived_by VARCHAR(255),
  archived_at TIMESTAMP
);

CREATE INDEX idx_sor_diagnosis_id ON second_opinion_reports (diagnosis_id);
```

**설계 근거**
- 진단 1건에 대해 여러 번 재요청이 가능하도록 이력을 남긴다 (최신순 조회, 기존 `get_latest_summary`의
  "최신 N개" 패턴과 동일 철학).
- `status`를 컬럼으로 명시해 SSE가 재연결되어도 현재 상태를 바로 조회할 수 있게 한다.
- `is_rare_pattern`은 LLM 출력이 아니라 코드가 계산한 값을 그대로 저장 — 아카이빙 게이팅 로직의
  감사가능성(auditability) 확보 목적.
- `supporting_cases`/`contradicting_cases`를 분리 저장: 대상 진단 자신의 `diagnosis` 값으로 1차
  필터링하면 검색 대상이 이미 그 판정을 지지하는 쪽으로 좁혀지는 확증 편향이 생긴다(§7 리스크 6번).
  반대 라벨 쪽 근접 사례도 함께 저장·노출해 리포트가 한쪽 근거만 보여주지 않도록 한다.
- `is_conflicting_evidence`도 `is_rare_pattern`과 동일하게 결정론적 계산값을 저장 — LLM의 `reasoning`
  서술이 어느 쪽으로 치우치더라도, 이 필드는 항상 독립적으로 노출되어 의사가 최종 판단할 수 있게 한다.

## 5. API 스펙

공통사항: 기존 컨벤션대로 인증 헤더는 없음. 요청자 식별은 `diagnosed_by`와 동일하게 자유 문자열
필드(`requested_by`, `approved_by`)로 받는다 (§7 리스크 참고). 에러는 기존과 동일하게
`HTTPException(status_code, detail)` 형태.

### 5.1 `POST /diagnosis/{id}/second-opinion`

세컨드 오피니언 파이프라인을 비동기로 시작한다 (`BackgroundTasks` 또는 워커 큐로 실행, 응답은 즉시 반환).

**Path params**
| 이름 | 타입 | 설명 |
|---|---|---|
| id | int | `Diagnosis.id` |

**Request body**
```json
{
  "requested_by": "김민준"
}
```
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| requested_by | string | Y | 요청 의사 이름/식별자. `Diagnosis.diagnosed_by`와 동일 컨벤션 |

**Response `202 Accepted`**
```json
{
  "second_opinion_id": 12,
  "diagnosis_id": 101,
  "status": "pending",
  "stream_url": "/diagnosis/101/second-opinion/stream?second_opinion_id=12",
  "requested_at": "2026-08-06T10:00:00Z"
}
```

**에러 케이스**
| 상태코드 | 조건 | detail 예시 |
|---|---|---|
| 404 | `Diagnosis.id` 없음 | `"Diagnosis not found"` |
| 409 | 동일 `diagnosis_id`에 대해 `status`가 `pending/retrieving/summarizing/drafting`인 리포트가 이미 존재 | `"Second opinion already in progress for this diagnosis"` |
| 422 | `requested_by` 누락 (FastAPI 기본 검증) | — |
| 500 | 파이프라인 시작 자체 실패 (DB insert 등) | `str(e)` |

### 5.2 `GET /diagnosis/{id}/second-opinion/stream`

SSE(Server-Sent Events)로 진행상태를 스트리밍한다. `text/event-stream` (`sse-starlette` 사용 —
`requirements.txt`/`README.md`의 수동 설치 목록에 추가 필요).

**Path params**: `id` = `Diagnosis.id`

**Query params**
| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| second_opinion_id | int | N | 특정 리포트 지정. 생략 시 해당 진단의 가장 최근 리포트를 스트리밍 |

**이벤트 스트림**
```
event: progress
data: {"status": "retrieving", "node": "retrieve_similar_cases", "message": "유사 사례 검색 중"}

event: progress
data: {"status": "summarizing", "node": "summarize_findings", "message": "유사 사례 분석 중"}

event: progress
data: {"status": "drafting", "node": "draft_report", "message": "리포트 작성 중"}

event: complete
data: {
  "second_opinion_id": 12,
  "diagnosis_id": 101,
  "status": "completed",
  "diagnosis_candidate": "malignant",
  "confidence_score": 0.62,
  "supporting_cases": [
    {"diagnosis_id": 87, "similarity": 0.81, "diagnosis": "malignant", "confidence_score": 0.71, "anatomy_site": "torso", "diagnosed_at": "2026-05-11T09:00:00Z"}
  ],
  "contradicting_cases": [
    {"diagnosis_id": 54, "similarity": 0.69, "diagnosis": "benign", "confidence_score": 0.58, "anatomy_site": "torso", "diagnosed_at": "2026-03-02T09:00:00Z"}
  ],
  "reasoning": "지지 근거 4건(유사도 0.81 최고), 반박 근거 1건(유사도 0.69)이 확인됩니다. 지지 근거가 더 우세하나...",
  "is_rare_pattern": false,
  "is_conflicting_evidence": false
}
```
`supporting_cases`/`contradicting_cases`가 비어 있을 수 있다 (예: 반대 라벨 데이터가 아직 없는 초기
운영 단계) — 이 경우 해당 필드는 빈 배열 `[]`로 반환하고, `is_conflicting_evidence`는 `false`로 계산된다
(§6.4, `contradicting_cases`가 비면 `contradicting_top1=0`이므로 조건 불성립).
실패 시:
```
event: error
data: {"second_opinion_id": 12, "status": "failed", "error_message": "OpenAI API timeout"}
```
`complete` 또는 `error` 이벤트 전송 후 서버가 연결을 종료한다. 클라이언트가 이미 `completed`/`failed`
상태로 연결한 경우, 접속 직후 해당 이벤트 1개만 보내고 바로 종료한다 (재연결 시 즉시 최종 상태 회신).

**에러 케이스**
| 상태코드 | 조건 |
|---|---|
| 404 | `Diagnosis.id` 없음, 또는 해당 진단에 리포트가 하나도 없음, 또는 지정한 `second_opinion_id`가 해당 `diagnosis_id`에 속하지 않음 |

### 5.3 `POST /diagnosis/{id}/archive`

의사 승인을 받아 Notion에 아카이빙한다 (MCP 연동). `is_rare_pattern=true` **또는**
`is_conflicting_evidence=true`인 리포트를 기본 허용한다 (§6.4에서 결정, §7 리스크 7번 참고). 두 플래그가
모두 `false`인 경우에만 `force=true`가 필요하다.

**Path params**: `id` = `Diagnosis.id`

**Request body**
```json
{
  "second_opinion_id": 12,
  "approved_by": "김민준",
  "force": false
}
```
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| second_opinion_id | int | Y | 아카이빙 대상 리포트 |
| approved_by | string | Y | 승인 의사 |
| force | bool | N (기본 false) | `is_rare_pattern=false` **AND** `is_conflicting_evidence=false`여도 의사 판단으로 강제 아카이빙 |

**Response `201 Created`**
```json
{
  "diagnosis_id": 101,
  "second_opinion_id": 12,
  "archive_status": "archived",
  "notion_page_url": "https://www.notion.so/...",
  "archived_by": "김민준",
  "archived_at": "2026-08-06T10:05:00Z"
}
```

**에러 케이스**
| 상태코드 | 조건 | detail 예시 |
|---|---|---|
| 404 | `diagnosis_id`/`second_opinion_id` 불일치 또는 미존재 | `"Second opinion report not found"` |
| 400 | 리포트 `status != completed` | `"Report is not ready for archiving"` |
| 400 | `is_rare_pattern=false` **AND** `is_conflicting_evidence=false` 이고 `force=false` | `"Report is not flagged as rare pattern or conflicting evidence; set force=true to archive anyway"` |
| 409 | 이미 `archive_status=archived` | `"Already archived"` |
| 502 | Notion MCP 호출 실패 (네트워크/인증 등) — `archive_status`를 `archive_failed`로 갱신 후 응답 | `"Notion archiving failed: <원인>"` |

## 6. LangGraph 파이프라인

```
retrieve_similar_cases → summarize_findings → draft_report
```

### 6.1 `retrieve_similar_cases`
- 입력: `diagnosis_id`
- 처리:
  1. 대상 `Diagnosis` 로드. `embedding IS NULL`이면 온디맨드 생성 (§4.2).
  2. **Supporting cases 검색** — 동일 `diagnosis`(benign/malignant) 라벨 내에서 top-k.
     `WHERE diagnosis = :target_diagnosis AND embedding_model_version = :version AND id != :self_id
     ORDER BY embedding <=> :query_embedding LIMIT :SUPPORTING_TOP_K` (기본 5, 기존 v1 로직과 동일).
  3. **Contradicting cases 검색** — 반대 `diagnosis` 라벨 내에서 top-k′.
     `WHERE diagnosis = :opposite_diagnosis AND embedding_model_version = :version
     ORDER BY embedding <=> :query_embedding LIMIT :CONTRADICTING_TOP_K` (기본 2). 대상 진단 자신의
     라벨과 반대이므로 자기 자신이 포함될 일은 없지만 `id != :self_id` 조건은 방어적으로 유지.
     이 두 번째 검색이 확증 편향 대응의 핵심 — 대상 진단 자신의 판정값 하나로만 후보를 좁히지 않고,
     반대 라벨 쪽 근접 사례도 반드시 함께 조회한다 (§7 리스크 6번).
  4. 두 결과 모두 코사인 유사도 = `1 - cosine_distance`로 변환.
  5. **`is_rare_pattern`, `is_conflicting_evidence` 결정론적 계산** (§6.4) — 이 노드에서 계산해
     state에 싣는다. 둘 다 LLM 판단이 아니라 코드 계산인 이유는 아카이빙 게이팅/의사 판단의
     감사가능성 확보.
- 출력: `supporting_cases: list[dict]`, `contradicting_cases: list[dict]`, `is_rare_pattern: bool`,
  `is_conflicting_evidence: bool`

### 6.2 `summarize_findings`
- 입력: `supporting_cases`, `contradicting_cases`, 대상 진단의 메타데이터(부위/연령/성별/confidence)
- 처리: LLM(`gpt-4o-mini`) 호출로 두 그룹을 **각각** 요약한다 — 지지 그룹의 진단 분포/최고 유사도,
  반박 그룹의 진단 분포/최고 유사도를 모두 산출하고, 두 그룹의 강도를 비교한 문장을 포함시킨다.
  프롬프트에 "지지 사례와 반박 사례를 모두 검토하고, 반박 사례가 존재하면 반드시 언급하라"는 지시를
  명시적으로 포함해 한쪽 근거만 언급하고 넘어가는 출력을 방지한다. `contradicting_cases`가 빈
  배열이면 "반박 사례 없음"을 그대로 명시하도록 지시한다 (침묵으로 누락되지 않게).
- 출력: `findings_summary: str` (지지/반박 요약을 모두 포함)

### 6.3 `draft_report`
- 입력: `findings_summary`, `supporting_cases`, `contradicting_cases`, 대상 진단
- 처리: LLM 호출로 최종 한국어 리포트 문장(`reasoning`) 생성. 프롬프트 요구사항:
  - "지지 근거 N건, 반박 근거 M건"처럼 **양쪽 건수를 수치로 명시**할 것.
  - `is_conflicting_evidence=true`인 경우, 반박 근거가 지지 근거만큼 강하다는 점을 얼버무리지 않고
    문장 앞부분에서 명시할 것 (확신에 찬 어조로만 작성 금지).
  - **`confidence_score`는 원본 `Diagnosis.confidence_score`를 그대로 echo** — LLM이 새 숫자를
    만들어내지 않도록 고정.
- 출력: 스키마 전체 `{diagnosis_candidate, confidence_score, supporting_cases, contradicting_cases,
  reasoning, is_rare_pattern, is_conflicting_evidence}` → `second_opinion_reports` row에 저장,
  `status='completed'`, `completed_at` 기록.

### 6.4 판정 규칙: `is_rare_pattern` / `is_conflicting_evidence`

두 플래그는 서로 다른 질문에 답하는 독립적인 결정론적 계산이다.
- `is_rare_pattern`: "이 판정을 지지할 만한 과거 사례가 (같은 라벨 안에서) 충분한가?"
- `is_conflicting_evidence`: "반대 라벨 쪽에도 지지 근거만큼 강한 근거가 있는가?"

```
supporting_top1 = supporting_cases[0].similarity if supporting_cases else 0
supporting_matches = count(c.similarity >= SIMILARITY_THRESHOLD for c in supporting_cases)
is_rare_pattern = (supporting_top1 < SIMILARITY_THRESHOLD) OR (supporting_matches < 2)

contradicting_top1 = contradicting_cases[0].similarity if contradicting_cases else 0
is_conflicting_evidence = (contradicting_top1 >= SIMILARITY_THRESHOLD) AND (contradicting_top1 >= supporting_top1)
```

**설계 근거 / 제안**
- `is_conflicting_evidence`를 "반박 유사도 > 지지 유사도"만으로 정의하지 않고 `contradicting_top1
  >= SIMILARITY_THRESHOLD` 조건을 추가로 요구한 이유: 둘 다 낮은 값(예: 지지 0.2, 반박 0.25)일 때도
  단순 대소비교만으로는 플래그가 켜져 노이즈가 많아진다. **절대적으로도 강한 근거**여야 실질적인
  반박으로 취급한다.
- `is_rare_pattern`과 `is_conflicting_evidence`는 동시에 `true`일 수 있다 — 지지 근거는 부족한데
  반박 근거는 강한, 가장 주의가 필요한 케이스다. 이 조합은 §6.3의 리포트 서술에서 가장 두드러지게
  강조되도록 프롬프트에 반영한다.
- 두 플래그 모두 같은 `SIMILARITY_THRESHOLD`(기본 `0.75`)를 기준선으로 재사용한다 — 지지/반박 판정에
  서로 다른 기준을 쓰면 "얼마나 강해야 근거로 인정하는가"가 방향에 따라 달라지는 비일관성이 생긴다.
- 신규 설정값: `SUPPORTING_TOP_K`(기본 5), `CONTRADICTING_TOP_K`(기본 2). `CONTRADICTING_TOP_K`를
  더 작게 잡은 이유는 반박 그룹의 목적이 "존재 여부와 강도 확인"이지 지지 그룹만큼 폭넓게 나열하는
  것이 아니기 때문. 두 상수 모두 env/config로 분리, 하드코딩 금지 (임베딩 모델 버전 교체 시 재튜닝 대상).
- **아카이빙 게이팅 결정 (§7 리스크 7번 해결)**: §5.3 `/archive`의 기본 게이팅 조건은
  `is_rare_pattern=true` **OR** `is_conflicting_evidence=true`이다. 반박 근거가 강한 케이스도
  희귀 패턴과 동일한 수준의 검토 가치가 있다고 보고, 두 플래그 중 하나라도 켜지면 별도 `force` 없이
  아카이빙을 허용한다. 두 플래그가 모두 `false`일 때만 의사가 `force=true`로 명시적으로 강제해야 한다.

### 6.5 각 노드 실패 시 처리
- 어느 노드든 예외 발생 시 `second_opinion_reports.status='failed'`, `error_message` 기록 후 SSE로
  `error` 이벤트 전송. 파이프라인은 재시도하지 않음 (의사가 §5.1을 다시 호출해 재요청).

## 7. 리스크 및 열린 이슈

1. **인증 부재**: `requested_by`/`approved_by`가 클라이언트가 보낸 자유 문자열을 그대로 신뢰한다.
   기존 `diagnosed_by`도 동일한 상태이므로 컨벤션상 일관되지만, 누구나 임의의 의사명으로 승인·아카이빙
   요청을 보낼 수 있다는 점은 실제 배포 전 반드시 해결해야 할 항목. 본 PRD 범위에서는 기존 컨벤션을
   따르되 리스크로 명시한다.
2. **임베딩 버전 불일치**: 연합학습으로 `base_model072.h5`가 갱신되면 새 임베딩 공간이 예전 벡터와
   호환되지 않는다. `embedding_model_version` 필터를 빼먹으면 유사도 검색 결과가 무의미해질 수 있음
   — 구현 시 필수 WHERE 조건으로 강제할 것.
3. **SQL 로깅 볼륨**: `database.py`의 `engine = create_engine(DATABASE_URL, echo=True)`가 전체 SQL을
   로깅 중이므로, 벡터 컬럼(128 float) 포함 쿼리가 로그에 그대로 찍혀 로그 파일이 급격히 커질 수 있음
   — 이 기능 배포 시점에 `echo=True`를 재검토 권장 (본 PRD 범위 밖이지만 부작용으로 언급).
4. **동시 재요청**: `POST /second-opinion` 409 처리로 동시 중복 요청은 막지만, `retrieve_similar_cases`
   가 self-row(자기 자신 diagnosis_id)를 유사사례 후보에서 제외하는 로직이 반드시 필요 (자기 자신과의
   유사도 1.0이 항상 top-1이 되는 버그 방지).
5. **`force=true` 아카이빙 남용**: 희귀 패턴이 아닌데도 의사가 습관적으로 `force=true`를 쓰면 게이팅
   로직의 의미가 퇴색됨. MVP에서는 로그만 남기고(누가 언제 force로 아카이빙했는지는 `archived_by`/
   `archived_at`로 이미 추적됨) 별도 제재는 두지 않는다.
6. **(v2에서 설계로 대응) 1차 필터가 검증 대상과 같은 필드라는 순환 검증 위험**: v1에서는
   `retrieve_similar_cases`가 대상 진단 자신의 `diagnosis`(benign/malignant, 즉 AI가 방금 내린 판정
   그 자체)로만 필터링해, AI 판정이 틀렸을 경우(예: 실제로는 benign인데 malignant로 오판) 검색 대상도
   처음부터 malignant로 라벨된 케이스로만 좁혀지고 "유사 사례들이 이 판정을 지지한다"는 리포트가 나올
   확률이 구조적으로 높아지는 확증 편향(confirmation bias) 위험이 있었다.
   **v2 설계 변경**: 동일 라벨 검색(`supporting_cases`)과 별개로 반대 라벨 검색(`contradicting_cases`)을
   항상 함께 수행하고, `is_conflicting_evidence` 플래그로 반박 근거가 지지 근거만큼/그 이상 강한 경우를
   결정론적으로 표시하도록 파이프라인을 변경했다 (§6.1, §6.4). 리포트의 `reasoning`도 프롬프트 지시로
   양쪽 근거 건수를 모두 언급하도록 강제한다 (§6.2, §6.3).
   **잔여 리스크** (완전히 해소되지 않음):
   - `contradicting_cases`는 top-2(`CONTRADICTING_TOP_K`)로 제한돼 있어 반박 근거의 전체 분포가 아니라
     "존재 여부와 강도" 확인용이다. 반박 근거가 실제로는 더 많을 수 있다.
   - 임베딩 자체가 편향된 학습 데이터로 만들어졌다면, 지지/반박을 나눠 검색해도 두 그룹의 임베딩 품질
     자체가 그 편향에서 자유롭지 않다 — 이는 검색 로직이 아니라 모델 학습 단계의 문제라 본 PRD 범위 밖.
   - LLM이 `reasoning`을 작성할 때 프롬프트 지시에도 불구하고 서술이 지지 쪽으로 치우칠 가능성은 완전히
     배제할 수 없다 — `is_conflicting_evidence`가 LLM 서술과 무관하게 항상 별도 필드로 노출되므로,
     의사가 `reasoning` 문장에만 의존하지 않고 이 필드를 직접 확인하도록 프론트에서도 강조 표시할 것을
     권장 (UI는 본 PRD 범위 밖이나 API 응답에는 이미 반영됨, §5.2).
7. **(해결) 아카이빙 게이팅에 `is_conflicting_evidence` 포함**: §5.3 `/archive`의 기본 게이팅 조건을
   `is_rare_pattern=true` **OR** `is_conflicting_evidence=true`로 확정했다 (기존에는 `is_rare_pattern`만
   조건이었음). 반박 근거가 강한 케이스를 게이팅에서 빠뜨리면, 정작 "지지 근거는 충분해 보이지만 반박도
   그만큼 강한" 가장 주의가 필요한 케이스가 아카이빙 없이 넘어갈 수 있기 때문이다. 두 플래그가 모두
   `false`일 때만 `force=true`가 필요하다 (§5.3, §6.4).
   잔여 고려사항: 게이팅 조건이 `OR`로 넓어진 만큼 자동 허용되는 케이스가 늘어난다 — 이후 실사용
   데이터에서 아카이빙 빈도가 과도하게 높아지면(Notion 페이지 남발) 두 플래그 중 하나를 우선순위/
   가중치로 구분할지 재검토가 필요할 수 있다.

## 8. 범위 밖 (Out of scope)

- 새 벡터DB/서버 도입 (pgvector로 기존 PostgreSQL 내에서 해결).
- 자동 트리거 (본 기능은 전량 수동 트리거 — §확정된 설계).
- 실사용자 인증/인가 시스템 구축.
- Notion 외 아카이빙 대상(Slack 등) — 추후 MCP 서버 교체로 확장 가능하도록 인터페이스만 열어둠.
