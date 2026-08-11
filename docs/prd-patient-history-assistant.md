# PRD: 환자 히스토리 브리핑 어시스턴트

## 0. 문서 상태

- 이 문서는 기존 `docs/prd-second-opinion-report.md`(AI 세컨드 오피니언 리포트 + 조건부 아카이빙, v1~v2)를 전체 폐기하고 새로 작성한 문서다. 주제가 "세컨드 오피니언 리포트 생성 + MCP 기반 조건부 아카이빙"에서 "재진 환자 진단 이력 브리핑 + 유사 환자 사례 검색 챗봇"으로 완전히 바뀌었다.
- MCP는 이번 프로젝트 범위에서 제외한다.
- 버전: v1 (최초 작성)

## 1. 배경 및 목적

KOREN 백엔드는 현재 병변 이미지 1장을 업로드하면 EfficientNetB2 모델이 즉시 benign/malignant를 예측하고(`POST /diagnose`), 진료 대화를 요약해 구조화된 한국어 메모로 저장하는(`POST /summarize`) 두 가지 핵심 기능만 제공한다. 재진 환자가 왔을 때 의사가 과거 진단 이력을 한눈에 보거나, 비슷한 사례를 참고할 수 있는 기능은 없다 — `GET /diagnosis/{patient_id}`가 최신 진단 1건만 반환하는 것이 전부다.

이 PRD는 의사가 자연어로 질문하면(예: "환자 OOO 브리핑 해줘", "이 환자와 비슷한 사례 있어?") LLM이 의도를 스스로 판단해 환자 본인의 과거 기록과 다른 환자의 유사 사례를 검색·종합해 답하는 **단일 챗봇 엔드포인트**를 추가하는 것을 목표로 한다. RAG 기초 실습 수준의 포트폴리오 데모이며, 임상적으로 검증된 정확도를 목표로 하지 않는다.

## 2. 목표 / 비목표

**목표**
- 재진 환자의 진단 이력(시각화 가능한 타임라인 + 서술형 요약)을 챗봇 대화로 브리핑
- pgvector 기반 벡터 검색으로 타 환자의 유사 사례를 익명화하여 인용
- 단일 ReAct 에이전트 + 단일 검색 도구(`retrieve_patient_history`)로 두 기능을 모두 처리
- LangGraph 체크포인터로 멀티턴 대화(세션) 유지

**비목표**
- MCP 서버/클라이언트 구축 (범위 제외)
- 별도의 "브리핑" 버튼이나 전용 UI — 순수 챗봇 인터페이스만 지원
- 진단 이상 패턴 자동 탐지 (도메인에 맞지 않는다고 판단해 제외, 순수 요약만 수행)
- 인증/인가 체계 신규 도입 (현재 코드베이스에 이미 없으며, 이 문서에서도 다루지 않음 — §11 리스크에 별도 명시)
- 실제 임상 검증된 유사도 판단 (ISIC 기반 mock 데이터로 시연 가능한 수준이면 충분)

## 3. 기존 코드베이스 분석 요약

새 기능을 설계하기 전에 확인한 기존 컨벤션은 다음과 같다.

- **인증/미들웨어**: `app/main.py`는 CORS 미들웨어만 등록되어 있고, 별도의 인증 미들웨어나 의존성(`Depends`)은 어디에도 없다. 모든 기존 엔드포인트는 인증 없이 열려 있다. 새 `/chat` 엔드포인트도 이 컨벤션을 그대로 따르되, 환자의 진단 이력을 대화형으로 노출하는 기능이므로 §11에 별도 리스크로 기록한다.
- **라우팅 구조**: 서브라우터 분리 없이 `app/routers.py` 한 파일에 모든 엔드포인트가 나열되어 있다. 새 엔드포인트도 이 파일에 추가하는 것을 기본안으로 하되, 파일이 커지므로 `app/routers/chat.py`로 분리하는 대안도 §10에서 제시한다.
- **조회 키**: 라우터의 path param은 내부 PK(`patients.id`)가 아니라 비즈니스 키인 `patients.patient_id`(문자열)를 사용한다 (`GET /diagnosis/{patient_id}` 등). 새 엔드포인트도 동일하게 `patient_id` 문자열을 path param으로 받는다.
- **에러 컨벤션**: 환자 미존재 시 `HTTPException(status_code=404, detail="Patient not found")`, 그 외 예외는 최상위에서 잡아 `HTTPException(status_code=500, detail=str(e))`로 감싼다. 새 엔드포인트도 동일한 패턴을 따른다.
- **응답 컨벤션**: `JSONResponse(content={...})` 또는 dict를 그대로 반환(FastAPI가 자동 직렬화)하며, Pydantic `response_model`은 `/summarize`에서만 느슨하게 사용된다. 새 엔드포인트는 응답 스키마가 3종으로 분기되므로 Pydantic `Union` 모델을 명시적으로 정의해 타입 안정성을 확보한다 (§6).
- **DB 세션**: `Depends(get_db)`로 `SessionLocal`을 주입받는 동기 SQLAlchemy 세션. `echo=True`로 모든 SQL이 로깅된다 — 벡터 컬럼 값(1536차원 float 배열)이 로그에 그대로 찍히면 로그가 매우 커지므로 §11에 언급.
- **`Diagnosis` ↔ `CommunicationSummary` 관계**: `communication_summaries`는 진단 1건당 row 1개(카테고리 4개는 컬럼: `의사소견`/`처방`/`환자우려점`/`진료계획`)로 설계되어 있고, `communication_summaries.diagnosis_id`(NOT NULL FK) → `diagnoses.id`로 직접 연결된다. `POST /summarize`가 이 FK와 `Diagnosis.communication_summary_id`(캐시 컬럼)를 같은 트랜잭션에서 채운다. 브리핑 기능의 `narrative_summary` 생성도 시간 근접성 추정 없이 `diagnosis_id` 조인만으로 처방/환자 반응 텍스트를 진단 타임라인에 매칭한다.
- **`DiagnosisEnum`**: 현재 `benign` / `malignant` 2종뿐이다. 설계 확정사항 5번("diagnosis 세부 라벨, unknown 다수")은 SIIM-ISIC 원본 데이터셋의 `diagnosis` 컬럼(melanoma, nevus, seborrheic_keratosis, unknown 등 세분류)을 가리키는 것으로 판단된다 — 이 세부 라벨은 현재 스키마에 없으므로 §7에서 `diagnosis_detail` 컬럼 신설을 제안한다.
- **모델/전처리**: `model_loader.py`, `utils.py`는 이번 기능과 직접 관련 없다(이미지 분류 파이프라인은 그대로 유지). 챗봇은 기존 `diagnoses` 테이블에 이미 저장된 결과를 검색 대상으로 삼는다.

## 4. 컨셉 및 사용자 흐름

단일 ReAct 에이전트가 `retrieve_patient_history` 검색 도구 하나를 상황에 따라 다르게 호출한다. 별도 UI 분기 없이, 의사의 메시지 의도를 LLM이 판단한다.

```
의사: "환자 P001 최근 진료 이력 브리핑 해줘"
  → 에이전트가 retrieve_patient_history(scope="this_patient") 호출
  → type: "brief" 응답

의사: "이 환자랑 비슷한 케이스 있어?"
  → 에이전트가 retrieve_patient_history(scope="similar_patients") 호출
  → type: "similar_cases" 응답

의사: "이 환자 최근에 두피 쪽도 본 적 있어?"
  → 에이전트가 retrieve_patient_history(scope="this_patient", query_text="두피 진단 이력") 호출
  → type: "answer" 응답 (citations 포함)
```

세션은 `patient_id`에 종속되며, 첫 요청에서 `session_id`가 발급되고 이후 요청부터 프론트가 이를 포함해 보내 멀티턴 문맥을 유지한다.

## 5. API 스펙: `POST /patients/{patient_id}/chat`

### 5.1 요청

```
POST /patients/{patient_id}/chat
Content-Type: application/json
```

Path parameter
| 필드 | 타입 | 설명 |
|---|---|---|
| `patient_id` | string | `patients.patient_id` 비즈니스 키 (기존 엔드포인트와 동일) |

Body
```json
{
  "message": "환자 최근 진료 이력 브리핑 해줘",
  "session_id": null
}
```
| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `message` | string | Y | 의사의 자연어 메시지. 공백/빈 문자열 불가 |
| `session_id` | string \| null | N | 최초 요청 시 생략(또는 `null`). 이후 요청부터 첫 응답에서 받은 값을 그대로 포함 |

### 5.2 응답 (200)

```json
{
  "session_id": "P001:3f9a1c2e4b6d4a7c",
  "response": { "type": "brief", "...": "..." }
}
```
- `session_id`: LangGraph `thread_id`로 그대로 사용되는 값. 포맷은 `{patient_id}:{uuid4 hex}` (§9).
- `response`: §6에서 정의하는 3종 스키마 중 하나. 매 턴 새로 생성되며 이전 턴의 응답 타입과 무관하게 결정된다.

### 5.3 에러 케이스

| 상태 코드 | 상황 | detail 예시 |
|---|---|---|
| 404 | `patient_id`에 해당하는 환자 없음 | `"Patient not found"` |
| 404 | `session_id`가 제공되었으나 존재하지 않거나 다른 `patient_id`에 속함 | `"Session not found or expired"` |
| 400 | `message`가 빈 문자열/공백 | `"message is empty"` |
| 502 | 에이전트가 3종 스키마 중 어느 것도 아닌 형식으로 최종 응답을 생성(강제 구조화 출력 실패) | `"Failed to generate structured response"` |
| 500 | 그 외 예외(OpenAI 호출 실패, DB 오류 등) | `str(e)` (기존 컨벤션 유지) |

`session_id` 불일치/만료 시 자동으로 새 세션을 발급하지 않고 404로 명시적으로 실패시킨다 — 프론트가 `session_id` 없이 재요청하면 새 세션이 시작되는 것을 클라이언트가 스스로 판단하게 하기 위함이며, 기존 "환자 미존재 → 404" 컨벤션과 일관된다.

## 6. 응답 스키마 3종

에이전트가 대화 의도에 따라 아래 세 가지 중 하나를 최종적으로 구조화 생성한다(§9.3에서 이를 강제하는 방법 설명).

### 6.1 `type: "brief"` — 브리핑 요청

```json
{
  "type": "brief",
  "summary": { "total_diagnoses": 5, "date_range": "2023-02-10 ~ 2025-11-03" },
  "timeline": [
    {
      "date": "2025-11-03",
      "anatomy_site": "upper_extremity",
      "diagnosis": "benign",
      "confidence_score": 0.82
    }
  ],
  "narrative_summary": "최근 2년간 총 5회 내원, 평균 방문 간격 약 5개월...",
  "recommendation": "직전 방문 이후 8개월이 경과했습니다. 정기 관찰 주기(6개월)를 초과했으므로 재검진을 권장합니다."
}
```
- `timeline`은 `diagnoses` 테이블을 `diagnosed_at` 오름차순으로 나열한 것.
- `narrative_summary` / `recommendation`은 LLM이 (a) `timeline`의 방문 간격/공백, (b) `communication_summaries`의 "처방", "환자의 우려점" 텍스트 변화를 근거로 생성한다.

### 6.2 `type: "similar_cases"` — 유사 환자 사례 질문

```json
{
  "type": "similar_cases",
  "cases": [
    {
      "anonymized_label": "유사 사례 A",
      "date": "2024-06-12",
      "anatomy_site": "torso",
      "diagnosis": "malignant",
      "similarity": 0.87,
      "shared_features": ["동일 부위(torso)", "유사 confidence_score 구간"],
      "differences": ["환자 연령대 차이(60대 vs 40대)"],
      "clinical_note": "연령대 차이로 인해 진행 속도가 다를 수 있어 경과 관찰 주기를 별도로 판단하십시오."
    }
  ],
  "answer_text": "환자와 유사한 사례 2건을 찾았습니다. 두 사례 모두 동일 부위에서 악성 소견이 있었습니다."
}
```
- 타 환자 식별정보(`patient_id`, `name` 등)는 응답에 절대 포함하지 않는다. `anonymized_label`만 노출.

### 6.3 `type: "answer"` — 일반 질문

```json
{
  "type": "answer",
  "answer_text": "네, 2025년 3월 두피 부위 진단 기록이 있습니다. 당시 결과는 benign이었습니다.",
  "citations": [
    { "diagnosis_id": 42, "date": "2025-03-14", "anatomy_site": "head_neck" }
  ]
}
```
- `citations`는 이 환자 본인의 기록만 인용 가능(타 환자 인용이 필요하면 `similar_cases` 타입으로 유도).

Pydantic으로는 `discriminated union`(`type` 필드를 discriminator로 사용)으로 구현한다:
```python
ChatResponse = Annotated[
    Union[BriefResponse, SimilarCasesResponse, AnswerResponse],
    Field(discriminator="type"),
]
```

## 7. DB 설계 변경안 (pgvector)

### 7.1 확장 및 컬럼 추가

```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE diagnoses
  ADD COLUMN diagnosis_detail   VARCHAR(64),      -- ISIC mock 세부 라벨 (melanoma/nevus/unknown 등). 필터링에는 미사용, 인용/서술 참고용
  ADD COLUMN embedding          vector(1536),      -- OpenAI text-embedding-3-small 기준
  ADD COLUMN embedding_source   TEXT,              -- 임베딩 생성에 사용한 원문(디버깅/재임베딩용)
  ADD COLUMN embedding_updated_at TIMESTAMP;

-- 코사인 유사도 기준 ANN 인덱스 (pgvector 0.5+ 가정)
CREATE INDEX diagnoses_embedding_hnsw_idx
  ON diagnoses USING hnsw (embedding vector_cosine_ops);
```

`app/models.py`에는 `pgvector.sqlalchemy.Vector(1536)` 타입으로 `embedding` 컬럼을 추가하고, `app/schema.sql`도 위 DDL로 동기화한다(README에 명시된 대로 수동 동기화 필요).

### 7.2 임베딩 대상 텍스트 구성

```
"{anatomy_site} 부위, {diagnosis}({diagnosis_detail}) 소견, confidence {confidence_score:.2f}. "
"처방: {communication_summary.처방}. 환자 반응: {communication_summary.환자우려점}."
```
`communication_summary`는 `diagnosis_id` FK로 `diagnoses`와 직접 조인해 채운다(§3) — 시간 근접성 매칭은 필요하지 않다. 연결된 요약이 없는 진단(아직 `/summarize`가 호출되지 않은 경우)은 처방/환자 반응 부분을 공란으로 둔다.

### 7.3 임베딩 생성 시점

- **신규 진단 생성 시**: `POST /diagnose`에서 `Diagnosis` row를 커밋한 직후, 위 원문을 조합해 OpenAI 임베딩 API를 동기 호출하고 `embedding`/`embedding_source`/`embedding_updated_at`을 채운다. (해당 시점엔 아직 대화 요약이 없을 수 있으므로 처방/반응 부분은 공란으로 시작)
- **대화 요약 생성 시**: `POST /summarize`가 요약을 연결한 `Diagnosis`(해당 환자의 최신 진단, `diagnosis_id` FK로 확정적으로 연결됨)를 재임베딩해 처방/반응 텍스트를 반영한다.
- **초기 시드**: `scripts/embed_diagnoses.py` 배치 스크립트로 mock 데이터 전체를 일괄 임베딩(§8).

### 7.4 필터링 원칙 (기존 프로젝트 확정 원칙 재사용)

유사 사례 검색은 세분류 `diagnosis_detail`(unknown 다수, 신뢰도 낮음)이 아니라 **`diagnosis`(benign/malignant) 컬럼으로 1차 필터링한 후** 벡터 유사도로 정렬한다.

```sql
SELECT id, patient_id, anatomy_site, diagnosis, diagnosis_detail,
       confidence_score, diagnosed_at,
       1 - (embedding <=> :query_embedding) AS similarity
FROM diagnoses
WHERE diagnosis = :benign_or_malignant
  AND patient_id != :current_patient_pk
ORDER BY embedding <=> :query_embedding
LIMIT :top_k;
```

## 8. `communication_summaries` 목데이터 설계 방향

`communication_summaries`는 진단 1건당 row 1개, 카테고리 4개(`의사소견`, `처방`, `환자우려점`, `진료계획`)는 컬럼으로 분리되어 있다(§3). 포트폴리오 데모용으로 ISIC mock 진단 데이터(§7에서 seed할 `diagnoses`)마다 이 4개 컬럼을 템플릿 기반으로 채운다.

- **소스 스크립트**: `scripts/seed_mock_summaries.py` — `diagnosis`(benign/malignant)와 `anatomy_site`별로 문구 풀(pool)을 두고 조합해 자연스러운 변형을 만들고, 생성한 row의 `id`를 `diagnoses.communication_summary_id`에 즉시 연결한다(시간 근접성 추정이 아니라 확정적 FK 연결).
- **타임스탬프**: `summary_created_at`은 대응하는 `diagnosed_at`에서 0~3일 이내로 설정해, 브리핑의 방문 주기 계산이 자연스럽게 맞물리게 한다.
- **`처방` 예시 문구 풀**:
  - benign: `"경과 관찰 권장, 별도 처방 없음"`, `"보습제 처방, 4주 후 재방문 권장"`
  - malignant: `"조직검사 의뢰, 2차 병원 전원 안내"`, `"절제술 일정 협의, 스테로이드 연고 병행 처방"`
- **`환자우려점` 예시 문구 풀**: `"환부 크기 변화에 대한 불안 호소"`, `"가려움 및 색 변화 보고"`, `"특이 증상 없음, 정기 검진 목적"`
- **`의사소견` 문구 풀**: `diagnosis`(benign/malignant) × `anatomy_site` 조합별로 직접 설계(예: `"{부위} 부위 병변, 양성 소견으로 판단됨. 경계 명확하고 비대칭성 낮음."`, `"{부위} 부위 병변, 악성 의심 소견. 비대칭성 및 경계 불규칙성 관찰됨, 조직검사 필요."`) — 처방/환자우려점 풀과 톤을 맞춘다.
- **`진료계획`**: 방문 간격과 연동 — 직전 방문에서 malignant였던 경우 다음 방문 계획을 더 짧게(예: `"3개월 후 재검"`) 생성해 브리핑의 `recommendation` 로직과 일관성을 유지한다.
- 실제 문구 다양성보다 **카테고리별 텍스트가 임베딩·narrative_summary 생성에 쓸 만큼 구체적인지**가 중요하다 — 지나치게 짧은 placeholder는 벡터 검색 품질을 떨어뜨린다.

## 9. LangGraph 에이전트 아키텍처

### 9.1 상태 및 체크포인터

- State: `messages: list[AnyMessage]` (기본 `MessagesState` 확장) + `patient_id: str` (그래프 실행 시 `configurable`로 주입, LLM이 임의로 바꿀 수 없도록 도구 인자에서 제외)
- 체크포인터: `langgraph-checkpoint-postgres`의 `PostgresSaver`를 기존 `DATABASE_URL`에 연결해 재사용 — 별도 저장소를 늘리지 않고 기존 Postgres 인프라를 그대로 쓴다. 앱 기동 시 `PostgresSaver.setup()`을 1회 실행해 체크포인트 테이블을 생성한다.
- `thread_id` = `session_id` = `f"{patient_id}:{uuid4().hex}"`, 최초 턴에 발급 후 매 요청 `configurable={"thread_id": session_id}`로 그래프를 재호출한다.

### 9.2 도구 정의: `retrieve_patient_history`

```python
class RetrievePatientHistoryArgs(BaseModel):
    scope: Literal["this_patient", "similar_patients"]
    query_text: str = Field(description="검색 의도를 담은 자연어 질의")
    benign_malignant: Optional[Literal["benign", "malignant"]] = Field(
        default=None,
        description="similar_patients일 때 1차 필터. 미지정 시 이 환자의 최신 진단값을 기본으로 사용",
    )
    top_k: int = 5
```

- `scope="this_patient"`: 벡터 검색이 아니라 `patient_id`로 단순 필터 + `diagnosed_at` 정렬(전체 이력 브리핑에는 유사도 랭킹이 불필요하므로). `communication_summaries`도 함께 조인해 반환.
- `scope="similar_patients"`: §7.4의 SQL대로 `benign_malignant` 1차 필터 + 벡터 유사도 정렬, 현재 환자 제외, 결과의 `patient_id`는 도구 반환값에서부터 노출하지 않고 `"유사 사례 A/B/C"`로 즉시 치환한다(에이전트가 실수로 실제 환자 식별자를 응답에 포함시키는 것을 도구 레벨에서 원천 차단).
- 실제 `patient_id`(현재 세션의 환자)는 도구 인자가 아니라 `RunnableConfig`를 통해 도구 구현부에 주입 — LLM이 다른 환자의 `patient_id`를 임의로 넣어 조회하는 경로 자체를 차단.

### 9.3 그래프 구조

```
START → agent
agent --(tool_call: retrieve_patient_history)--> tools → agent
agent --(tool_call: emit_brief | emit_similar_cases | emit_answer)--> END
```

- `agent` 노드는 4개의 도구를 바인딩한다: 검색용 `retrieve_patient_history` 1개 + 최종 응답용 `emit_brief`/`emit_similar_cases`/`emit_answer` 3개(§6의 3개 Pydantic 스키마를 그대로 도구 인자 스키마로 사용).
- 최종 응답을 "일반 텍스트"가 아니라 "도구 호출"로 강제함으로써 §6의 구조화 출력을 보장한다 — `tool_choice`를 매 스텝 `"required"`로 설정해 에이전트가 자유 텍스트로 종료하지 못하게 막는다.
- `emit_*` 도구가 호출되면 실제로 실행되지 않고(그래프가 바로 `END`로 라우팅), 해당 도구 호출의 인자를 그대로 API 응답의 `response` 필드로 사용한다.
- 도구 호출이 반복되며 무한 루프에 빠지는 것을 막기 위해 `agent` 노드 방문 횟수에 상한(예: 6회)을 두고, 초과 시 `emit_answer`로 강제 전환해 "죄송합니다, 요청을 처리하지 못했습니다"류의 안전한 답변을 생성한다.

### 9.4 신규 의존성

```
langgraph
langchain-openai
langgraph-checkpoint-postgres
pgvector
```

## 10. 구현 범위 / 마일스톤

| 단계 | 내용 |
|---|---|
| 1 | `app/schema.sql` / `app/models.py`에 pgvector 컬럼 추가, 마이그레이션 적용 |
| 2 | `scripts/embed_diagnoses.py`, `scripts/seed_mock_summaries.py` 작성 및 ISIC mock 데이터 시드 |
| 3 | `retrieve_patient_history` 도구 구현 (this_patient / similar_patients 두 경로) |
| 4 | LangGraph 그래프 구성 + `PostgresSaver` 연결 |
| 5 | `POST /patients/{patient_id}/chat` 엔드포인트 배선 (신규 라우터 파일로 분리 권장: `app/routers/chat.py`, 기존 `router`에 `include_router`) |
| 6 | 3종 응답 스키마 수동 QA (브리핑/유사사례/일반질문 각 시나리오) |

## 11. 리스크 및 오픈 이슈

- **인증 부재**: 현재 코드베이스 전체에 인증 미들웨어가 없다. `/chat` 엔드포인트는 환자의 전체 진단 이력과 대화 요약을 대화형으로 노출하므로, 다른 엔드포인트보다 민감도가 높다. 이 PRD는 기존 컨벤션(무인증)을 그대로 따르되, 실제 배포 전 별도 인가 계층 도입을 후속 과제로 남긴다.
- **SQL 로그 노출**: `app/database.py`의 `engine`이 `echo=True`로 설정되어 있어 1536차원 임베딩 벡터가 INSERT/UPDATE 시 로그에 그대로 출력된다. 로그 볼륨/가독성 문제가 있으므로 이 테이블에 한해 로깅 레벨 조정을 고려해야 한다.
- **`communication_summary_id` 미연결** (해결됨): `communication_summaries`를 진단 1건당 row 1개 구조로 재설계하고 `diagnosis_id` FK를 NOT NULL로 두면서, `POST /summarize`가 대상 `Diagnosis`의 `communication_summary_id`를 확정적으로 채우도록 변경했다. 브리핑 narrative, 임베딩 원문 구성 모두 이제 `diagnosis_id` 조인 하나로 처리되어 매칭 로직 중복 문제가 해소됐다.
- **pgvector 인덱스 방식**: HNSW는 pgvector 0.5.0 이상에서만 지원된다. 배포 환경의 pgvector 버전을 사전에 확인하고, 미지원 시 `ivfflat`으로 대체해야 한다.
- **임베딩 재생성 비용**: 대화 요약이 추가될 때마다 관련 `Diagnosis`를 재임베딩하는 구조라, 요약이 잦은 환자는 OpenAI 임베딩 호출이 누적된다. 데모 규모에서는 무시 가능한 수준이나 확장 시 배치화 검토 필요.
- **`diagnosis_detail` 컬럼의 데이터 출처**: 이 문서에서 신설을 제안한 컬럼이며, 현재 `DiagnosisEnum`에는 대응 값이 없다. ISIC mock 시드 스크립트가 유일한 데이터 소스가 되므로, 실제 모델(`model_loader.py`)이 세분류를 예측하지 않는 한 이 필드는 시연용 mock 데이터에서만 채워진다는 점을 명확히 인지해야 한다.
- **임베딩 재생성 타이밍의 매칭 오류 위험** (해결됨): `communication_summaries.diagnosis_id` FK로 진단-요약이 확정적으로 연결되면서, 재진 환자가 짧은 간격으로 여러 번 방문해도 "가장 최근 진단"이 엉뚱한 진단 건을 가리키는 문제 자체가 발생하지 않는다. `POST /summarize`가 항상 명시적으로 지정된 `Diagnosis`(해당 환자의 최신 진단)에만 요약을 연결·재임베딩한다.
