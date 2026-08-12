-- ENUM
CREATE TYPE sex_enum AS ENUM ('male', 'female');
CREATE TYPE anatomy_site_enum AS ENUM ('head_neck', 'upper_extremity', 'lower_extremity', 'torso');
CREATE TYPE diagnosis_enum AS ENUM ('benign', 'malignant');

-- PATIENTS
CREATE TABLE patients (
                          id SERIAL PRIMARY KEY,
                          patient_id VARCHAR(255) UNIQUE NOT NULL,
                          name VARCHAR(255) NOT NULL,
                          age INTEGER,
                          sex sex_enum,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- MEDICAL_IMAGES
CREATE TABLE medical_images (
                                id SERIAL PRIMARY KEY,
                                image_name VARCHAR(255) UNIQUE NOT NULL,
                                patient_id INTEGER REFERENCES patients(id) ON DELETE CASCADE,
                                file_path VARCHAR(255) NOT NULL,
                                anatomy_site anatomy_site_enum,
                                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- COMMUNICATION_SUMMARIES
-- 진단 1건당 row 1개(카테고리별 row 아님). diagnosis_id FK는 diagnoses 테이블 생성 후
-- 별도 ALTER TABLE로 추가한다(diagnoses.communication_summary_id와의 순환 참조 회피).
CREATE TABLE communication_summaries (
                                         id SERIAL PRIMARY KEY,
                                         diagnosis_id INTEGER NOT NULL UNIQUE,
                                         summary_created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                         의사소견 TEXT,
                                         처방 TEXT,
                                         환자우려점 TEXT,
                                         진료계획 TEXT
);

-- DIAGNOSES
CREATE TABLE diagnoses (
                           id SERIAL PRIMARY KEY,
                           patient_id INTEGER REFERENCES patients(id) ON DELETE CASCADE,
                           medical_image_id INTEGER REFERENCES medical_images(id) ON DELETE CASCADE,
                           communication_summary_id INTEGER REFERENCES communication_summaries(id) ON DELETE SET NULL,
                           diagnosis diagnosis_enum,
                           anatomy_site anatomy_site_enum,
                           confidence_score FLOAT,
                           target_value INTEGER,
                           diagnosed_by VARCHAR(255),
                           ai_description TEXT,
                           diagnosed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE communication_summaries
  ADD CONSTRAINT communication_summaries_diagnosis_id_fkey
  FOREIGN KEY (diagnosis_id) REFERENCES diagnoses(id) ON DELETE CASCADE;

-- PGVECTOR (docs/prd-patient-history-assistant.md §7)
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE diagnoses
  ADD COLUMN diagnosis_detail   VARCHAR(64),      -- ISIC mock 세부 라벨 (melanoma/nevus/unknown 등). 필터링에는 미사용, 인용/서술 참고용
  ADD COLUMN embedding          vector(1536),      -- OpenAI text-embedding-3-small 기준
  ADD COLUMN embedding_source   TEXT,              -- 임베딩 생성에 사용한 원문(디버깅/재임베딩용)
  ADD COLUMN embedding_updated_at TIMESTAMP;

-- 코사인 유사도 기준 ANN 인덱스 (pgvector 0.5+ 가정)
CREATE INDEX diagnoses_embedding_hnsw_idx
  ON diagnoses USING hnsw (embedding vector_cosine_ops);

-- LANGGRAPH CHECKPOINTER (docs/prd-patient-history-assistant.md §9.1)
-- checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations 테이블은
-- 여기서 수동으로 만들지 않는다. app/agent/checkpointer.py의 PostgresSaver.setup()이
-- 앱 기동 시(app/main.py 스타트업 훅) 멱등적으로 생성/마이그레이션한다.