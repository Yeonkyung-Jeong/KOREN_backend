# communication_summaries mock 시딩 (PRD §8).
# 진단 1건당 CommunicationSummary row 1개(카테고리 4개는 컬럼)를 생성하고,
# diagnosis.communication_summary_id를 확정적으로 연결한다(시간 근접성 추정 아님).
import random
import sys
from datetime import timedelta

sys.path.insert(0, ".")

from app import models
from scripts._db import get_session, RNG_SEED

ANATOMY_SITE_KOR = {
    "head_neck": "두경부",
    "upper_extremity": "상지",
    "lower_extremity": "하지",
    "torso": "몸통",
}

처방_POOL = {
    "benign": [
        "경과 관찰 권장, 별도 처방 없음",
        "보습제 처방, 4주 후 재방문 권장",
    ],
    "malignant": [
        "조직검사 의뢰, 2차 병원 전원 안내",
        "절제술 일정 협의, 스테로이드 연고 병행 처방",
    ],
}

환자우려점_POOL = {
    "benign": [
        "특이 증상 없음, 정기 검진 목적",
        "가려움 및 색 변화 보고",
    ],
    "malignant": [
        "환부 크기 변화에 대한 불안 호소",
        "가려움 및 색 변화 보고",
    ],
}

# PRD §8에 예시가 없어 처방/환자우려점 풀과 톤을 맞춰 직접 설계.
의사소견_TEMPLATES = {
    "benign": [
        "{site} 부위 병변, 양성 소견으로 판단됨. 경계 명확하고 비대칭성 낮음.",
        "{site} 부위 병변, 양성 소견. 색조 균일하며 급격한 크기 변화 없음.",
    ],
    "malignant": [
        "{site} 부위 병변, 악성 의심 소견. 비대칭성 및 경계 불규칙성 관찰됨, 조직검사 필요.",
        "{site} 부위 병변, 악성 의심 소견. 색조 불균일 및 최근 크기 변화 관찰됨, 정밀 검사 권고.",
    ],
}

# 방문 간격 연동: 직전 진단이 malignant면 다음 방문 계획을 더 짧게
FOLLOWUP_SHORT_POOL = ["1개월 후 재검", "3개월 후 재검"]
FOLLOWUP_LONG_POOL = ["6개월 후 정기 검진", "1년 후 정기 검진"]


def pick_처방(rng: random.Random, diagnosis: str) -> str:
    return rng.choice(처방_POOL[diagnosis])


def pick_환자우려점(rng: random.Random, diagnosis: str) -> str:
    return rng.choice(환자우려점_POOL[diagnosis])


def pick_의사소견(rng: random.Random, diagnosis: str, anatomy_site: str) -> str:
    site = ANATOMY_SITE_KOR.get(anatomy_site, anatomy_site)
    template = rng.choice(의사소견_TEMPLATES[diagnosis])
    return template.format(site=site)


def pick_followup_plan(rng: random.Random, previous_diagnosis) -> str:
    if previous_diagnosis == "malignant":
        return rng.choice(FOLLOWUP_SHORT_POOL)
    return rng.choice(FOLLOWUP_LONG_POOL)


def _diagnosis_value(diagnosis) -> str:
    # models.Diagnosis.diagnosis는 Enum(DiagnosisEnum) 컬럼 -> DB에서 읽으면 문자열/Enum 둘 다 가능
    return diagnosis.value if hasattr(diagnosis, "value") else diagnosis


def seed():
    session = get_session()
    rng = random.Random(RNG_SEED)
    try:
        patients = session.query(models.Patient).order_by(models.Patient.id).all()
        if not patients:
            print("[seed_mock_summaries] patients 테이블이 비어 있습니다. "
                  "scripts/seed_mock_patients.py, seed_mock_diagnoses.py를 먼저 실행하세요.")
            return

        created = 0
        skipped = 0
        for patient in patients:
            diagnoses = session.query(models.Diagnosis) \
                .filter(models.Diagnosis.patient_id == patient.id) \
                .order_by(models.Diagnosis.diagnosed_at.asc(), models.Diagnosis.id.asc()) \
                .all()

            previous_diagnosis_value = None
            for diagnosis in diagnoses:
                diagnosis_value = _diagnosis_value(diagnosis.diagnosis)
                anatomy_site_value = _diagnosis_value(diagnosis.anatomy_site)

                existing = session.query(models.CommunicationSummary) \
                    .filter(models.CommunicationSummary.diagnosis_id == diagnosis.id).first()
                if existing:
                    previous_diagnosis_value = diagnosis_value
                    skipped += 1
                    continue

                summary_created_at = diagnosis.diagnosed_at + timedelta(
                    days=rng.randint(0, 3),
                    seconds=rng.randint(0, 86399),
                )

                summary = models.CommunicationSummary(
                    diagnosis_id=diagnosis.id,
                    summary_created_at=summary_created_at,
                    의사소견=pick_의사소견(rng, diagnosis_value, anatomy_site_value),
                    처방=pick_처방(rng, diagnosis_value),
                    환자우려점=pick_환자우려점(rng, diagnosis_value),
                    진료계획=pick_followup_plan(rng, previous_diagnosis_value),
                )
                session.add(summary)
                session.flush()  # summary.id 확보

                diagnosis.communication_summary_id = summary.id  # 양방향 FK 동기화
                created += 1

                previous_diagnosis_value = diagnosis_value

            session.commit()

        print(f"[seed_mock_summaries] created={created}, skipped={skipped}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
