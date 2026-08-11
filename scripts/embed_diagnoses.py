# diagnoses 임베딩 백필 (PRD §7.2).
# communication_summary는 diagnosis_id FK로 직접 조인한다 (시간 근접성 매칭 불필요 —
# communication_summaries가 진단 1건당 1 row로 재설계되었기 때문).
import sys
import os
from datetime import datetime

sys.path.insert(0, ".")

from openai import OpenAI

from app import models
from scripts._db import get_session

EMBEDDING_MODEL = "text-embedding-3-small"


def build_embedding_text(anatomy_site, diagnosis, diagnosis_detail, confidence_score, prescription, concern) -> str:
    diagnosis_detail_text = diagnosis_detail or ""
    prescription_text = prescription or ""
    concern_text = concern or ""
    score = confidence_score if confidence_score is not None else 0.0
    return (
        f"{anatomy_site} 부위, {diagnosis}({diagnosis_detail_text}) 소견, confidence {score:.2f}. "
        f"처방: {prescription_text}. 환자 반응: {concern_text}."
    )


def _value(x):
    return x.value if hasattr(x, "value") else x


def resolve_embedding_text(diagnosis) -> str:
    summary = diagnosis.communication_summary
    prescription = summary.처방 if summary else None
    concern = summary.환자우려점 if summary else None
    return build_embedding_text(
        anatomy_site=_value(diagnosis.anatomy_site),
        diagnosis=_value(diagnosis.diagnosis),
        diagnosis_detail=diagnosis.diagnosis_detail,
        confidence_score=diagnosis.confidence_score,
        prescription=prescription,
        concern=concern,
    )


def backfill():
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    session = get_session()
    try:
        diagnoses = session.query(models.Diagnosis).order_by(models.Diagnosis.id.asc()).all()
        if not diagnoses:
            print("[embed_diagnoses] diagnoses 테이블이 비어 있습니다. "
                  "scripts/seed_mock_diagnoses.py를 먼저 실행하세요.")
            return

        embedded = 0
        skipped = 0
        failed = 0
        for diagnosis in diagnoses:
            text = resolve_embedding_text(diagnosis)

            if diagnosis.embedding_updated_at and diagnosis.embedding_source == text:
                skipped += 1
                continue  # 이미 동일한 텍스트로 임베딩됨 (재실행 안전성, 비용 절감)

            try:
                response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
                vector = response.data[0].embedding
            except Exception as e:
                print(f"[embed_diagnoses] diagnosis_id={diagnosis.id} 임베딩 실패, 스킵: {e}")
                failed += 1
                continue

            diagnosis.embedding = vector
            diagnosis.embedding_source = text
            diagnosis.embedding_updated_at = datetime.utcnow()
            session.commit()
            embedded += 1

        print(f"[embed_diagnoses] embedded={embedded}, skipped={skipped}, failed={failed}")
    finally:
        session.close()


if __name__ == "__main__":
    backfill()
