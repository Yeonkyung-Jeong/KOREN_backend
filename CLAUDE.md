# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

KOREN backend is a FastAPI service for a melanoma (skin lesion) diagnosis system. It accepts a lesion image plus patient metadata, runs a locally-loaded EfficientNetB2 classifier to predict benign/malignant, persists the result to PostgreSQL, and separately summarizes doctor-patient conversations via OpenAI into structured Korean-language notes.

The classifier model itself is trained externally in a federated-learning setup (see `woosung-universe/koren_NeulMed` on GitHub); this repo only downloads and serves the resulting weights.

## Setup and running

There is no single "install everything" file — `requirements.txt` only contains ML/data-science dependencies (tensorflow, efficientnet, flwr, pandas, etc.) exported from the model-training environment. The web-serving stack must be installed separately:

```
pip install -r requirements.txt
pip install fastapi uvicorn sqlalchemy openai dotenv psycopg2
```

Using a venv (Windows). `requirements.txt` is pinned for Python 3.11 on Windows (see README), so create the venv with 3.11 specifically:
```
py -3.11 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
pip install fastapi uvicorn sqlalchemy openai dotenv psycopg2
```

Run the server:
```
uvicorn app.main:app --reload
```

Required environment variables (loaded via `.env` / `python-dotenv`):
- `OPENAI_API_KEY` — used for conversation summarization (`app/routers.py`, `app/config.py`)
- `DATABASE_URL` — PostgreSQL connection string (`app/database.py`)
- `LOCAL_MODEL_PATH` — filesystem path where the downloaded `.h5` model weights are cached (`app/model_loader.py`)
- `FRONT_URL` — allowed CORS origin for the frontend (`app/main.py`)

There are no tests, linter, or CI configuration in this repo currently.

## Architecture

- `app/main.py` — FastAPI app entrypoint. Loads the model once at import time (`load_model()`), configures CORS from `FRONT_URL`, and mounts `app/routers.py`'s router.
- `app/model_loader.py` — Downloads the melanoma classifier weights (`base_model072.h5`) from a hardcoded GitHub URL on first run (cached at `LOCAL_MODEL_PATH`), then rebuilds the exact Keras `Sequential` architecture (EfficientNetB2 backbone + dense/dropout head) and loads the weights into it. The architecture here must stay in sync with whatever produced the `.h5` file upstream — it is not stored in the weights file itself.
- `app/utils.py` — `preprocess_image()` converts uploaded image bytes into the 256x256 normalized tensor the model expects.
- `app/routers.py` — All API endpoints live here (not split into sub-routers):
  - `POST /diagnose` — accepts an image + patient form fields, upserts the `Patient`, saves the image to `./uploads/`, runs model inference, writes a `Diagnosis` row, and returns the result along with the patient's last 4 `CommunicationSummary` entries for context.
  - `GET /diagnosis/{patient_id}` — latest diagnosis for a patient.
  - `POST /summarize` — sends a raw conversation transcript to `gpt-4o-mini`, asking it to infer speaker roles (transcripts have no speaker labels) and return a fixed-shape Korean JSON object (의사 소견 / 환자의 우려점 / 진료 계획 / 처방). Each key is stored as a separate `CommunicationSummary` row. Falls back to `ast.literal_eval` if the model's output isn't strict JSON.
  - `GET /summary/{patient_id}` — latest 4 summaries for a patient, oldest-first.
  - `GET /diagnoses` — full diagnosis history across all patients, shaped to match the field names of the public SIIM-ISIC melanoma dataset (`anatom_site_general_challenge`, `benign_malignant`, etc.) for downstream compatibility.
- `app/models.py` — SQLAlchemy ORM models: `Patient` → `MedicalImage` / `Diagnosis` / `CommunicationSummary`. A `Diagnosis` optionally links to one `CommunicationSummary` via `communication_summary_id`, but nothing currently populates that link (see TODO in `routers.py`) — summaries and diagnoses for a patient are currently correlated only by `patient_id` and timestamp, not by foreign key.
- `app/schema.sql` — Hand-written raw-SQL equivalent of `models.py`, used for provisioning the Postgres schema directly. Keep it in sync manually if `models.py` changes; SQLAlchemy is not set up to auto-migrate here.
- `app/database.py` — Engine/session setup (`echo=True`, so all SQL is logged) and the `get_db()` FastAPI dependency.
- `app/config.py` — Loads `OPENAI_API_KEY` from `.env`.
- `workspace/clientResults/` — Local cache location matching the federated-learning workspace layout from the upstream training repo; contains the downloaded model weights.

## LangGraph agentic RAG conventions (`app/agent/`)

These conventions were established while building the `app/agent/` StateGraph (patient history chat, `POST /patients/{patient_id}/chat`) and should be followed for future agent/graph work in this repo:

- **Reasoning before verdict in structured-output schemas.** When a Pydantic schema used with `llm.with_structured_output()` combines a boolean judgment with a `reasoning` field, declare `reasoning` *before* the boolean field. OpenAI structured outputs fill fields in declaration order, so a verdict-first schema lets the model commit to a conclusion and rationalize it afterward; reasoning-first forces it to work through the evidence before deciding. See `DocumentGrade` / `AnswerGrade` in `app/agent/schemas.py`.
- **Deterministic logic over LLM judgment where there's no real ambiguity.** If a check has only one correct answer given the inputs (e.g. grading a confirmed, query-independent SQL result), implement it as a plain Python rule instead of an LLM call — it's cheaper, faster, and can't be talked into the wrong answer. See the `this_patient`-scope branch of `grade_documents` in `app/agent/nodes.py`.
- **Reserve the stronger model for the node(s) where the cost of being wrong is highest.** Keep a cheap model (`gpt-4o-mini`) as the default for routing/rewriting/generation, and only upgrade a specific node (e.g. the hallucination-check grader) to a stronger model once the cheap model has shown unreliable judgment there in practice. See `LLM_MODEL` vs `GRADING_LLM_MODEL` in `app/agent/nodes.py`.
- **Custom `StateGraph` over `create_agent` once multiple node roles need conditional routing/retry loops.** `create_agent`'s prebuilt single ReAct loop fits one LLM-decides-when-to-stop pattern; once the flow needs distinct roles (rewrite/retrieve/grade/generate) wired together with conditional edges and retry loops, build the graph explicitly with `StateGraph` + `add_node`/`add_edge`/`add_conditional_edges` instead. Each node then calls its own `llm.with_structured_output(Schema, method="function_calling")` rather than relying on a single agent-wide structured-output contract. See `app/agent/graph.py`.

## Notes on current behavior

- The model is loaded twice at process startup: once in `main.py` and once in `routers.py` (both call `load_model()` independently at import time).
- `uploads/` (raw patient images) is gitignored and created on demand; there's no cleanup logic.
- Korean-language field names and comments are used throughout for domain concepts (diagnosis categories, summary fields) — preserve them when editing rather than translating, since the frontend and OpenAI prompt both depend on the exact Korean keys.
- Indentation is intentionally mixed: newer modules (`app/agent/`, `app/routers/chat.py`, `app/routers/__init__.py`) use standard PEP8 4-space indentation, while older files (`app/models.py`, `app/routers/core.py`, etc.) use 2-space. Don't reformat existing files to 4-space, and don't reformat new files to 2-space to "match" — the split is deliberate, not drift.

## 커밋 메시지 규칙

형식: `type: 세부 구현 사항`

**type 목록**
- `feat` — 새로운 기능 구현
- `fix` — 에러 처리
- `style` — 공백 등 스타일 변경
- `refactor` — 기능 변경 없이 구현 개선
- `comment` — 주석만 추가
- `docs` — README 수정 등

예시:
```
feat: User 로그인 기능 구현
fix: User 확인 오류 수정
```

**작성 규칙**
1. type은 소문자로 쓴다. 괄호로 도메인을 표기하지 않는다 (예: `fix(server): ...` 금지, `fix: ...`로 작성).
2. 엔티티, 메소드명은 대소문자를 그대로 지켜 쓴다.
3. 수정/추가/생성 등은 한국말로 명시한다.
4. `,` 이외의 특수 기호는 금지한다.
5. 최대한 간결하게 쓰되 변경 사항이 잘 드러나도록 작성한다.
