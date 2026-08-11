# ISIC mock 포맷 진단 시딩. 이미 시딩된 patients 기준으로 환자당 1~4회 방문을
# 만들고, 방문마다 MedicalImage + Diagnosis row를 생성한다.
# 실제 이미지 파일은 생성하지 않는다 (메타데이터만 필요).
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from app import models
from scripts._db import get_session, RNG_SEED

# 데모 목적으로 malignant 비중을 실제 ISIC 유병률(~2%)보다 높게 잡아,
# malignant 관련 문구 풀/방문 간격 단축 로직이 시딩 데이터에서 충분히 나타나게 한다.
MALIGNANT_RATE = 0.3

BENIGN_DETAILS = ["nevus", "seborrheic_keratosis", "unknown"]
MALIGNANT_DETAILS = ["melanoma", "unknown"]

VISIT_COUNT_WEIGHTS = {1: 4, 2: 3, 3: 2, 4: 1}  # 재진 환자는 일부만


def pick_diagnosis_detail(rng: random.Random, diagnosis: str) -> str:
    pool = MALIGNANT_DETAILS if diagnosis == "malignant" else BENIGN_DETAILS
    return rng.choice(pool)


def pick_confidence_score(rng: random.Random, diagnosis: str) -> float:
    # /diagnose와 동일하게 confidence를 "malignant일 확률"로 통일
    if diagnosis == "malignant":
        return round(rng.uniform(0.51, 0.99), 4)
    return round(rng.uniform(0.01, 0.49), 4)


def build_visit_dates(rng: random.Random, n_visits: int, now: datetime) -> list:
    # 과거 ~2년 범위에서 방문 횟수만큼 오름차순 날짜 생성 (최소 간격 3주)
    dates = []
    cursor = now - timedelta(days=rng.randint(60, 730))
    for _ in range(n_visits):
        dates.append(cursor)
        cursor = cursor + timedelta(days=rng.randint(21, 180))
        if cursor > now:
            cursor = now
    return dates


def seed():
    session = get_session()
    rng = random.Random(RNG_SEED)
    now = datetime.utcnow()
    image_seq = 1
    try:
        patients = session.query(models.Patient).order_by(models.Patient.id).all()
        if not patients:
            print("[seed_mock_diagnoses] patients 테이블이 비어 있습니다. "
                  "scripts/seed_mock_patients.py를 먼저 실행하세요.")
            return

        created_diagnoses = 0
        for patient in patients:
            already = session.query(models.Diagnosis) \
                .filter(models.Diagnosis.patient_id == patient.id).count()
            if already:
                continue  # 재실행 안전성: 이미 진단이 있는 환자는 스킵

            n_visits = rng.choices(
                list(VISIT_COUNT_WEIGHTS.keys()),
                weights=list(VISIT_COUNT_WEIGHTS.values()),
            )[0]
            visit_dates = build_visit_dates(rng, n_visits, now)

            for diagnosed_at in visit_dates:
                anatomy_site = rng.choice(list(models.AnatomySiteEnum))
                image_name = f"ISIC_{image_seq:07d}.jpg"
                image_seq += 1

                medical_image = models.MedicalImage(
                    image_name=image_name,
                    patient_id=patient.id,
                    file_path=f"./uploads/mock_{image_name}",
                    anatomy_site=anatomy_site,
                    uploaded_at=diagnosed_at,
                )
                session.add(medical_image)
                session.flush()  # medical_image.id 확보

                diagnosis_result = "malignant" if rng.random() < MALIGNANT_RATE else "benign"
                confidence = pick_confidence_score(rng, diagnosis_result)
                diagnosis_detail = pick_diagnosis_detail(rng, diagnosis_result)
                ai_description = f"진단 결과, {diagnosis_result} 이(가) 의심됩니다. 관련된 추가적인 처방을 제공해주세요."

                diagnosis = models.Diagnosis(
                    patient_id=patient.id,
                    medical_image_id=medical_image.id,
                    communication_summary_id=None,
                    diagnosis=diagnosis_result,
                    anatomy_site=anatomy_site,
                    confidence_score=confidence,
                    target_value=1 if diagnosis_result == "malignant" else 0,
                    diagnosed_by="AI_MODEL",
                    ai_description=ai_description,
                    diagnosed_at=diagnosed_at,
                    diagnosis_detail=diagnosis_detail,
                )
                session.add(diagnosis)
                created_diagnoses += 1

            session.commit()

        print(f"[seed_mock_diagnoses] created_diagnoses={created_diagnoses}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
