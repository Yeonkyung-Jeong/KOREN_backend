# ISIC mock 포맷 환자 시딩. patients 테이블이 비어 있는 로컬 개발 DB를 채우기 위한
# 선행 스크립트 (scripts/seed_mock_diagnoses.py, seed_mock_summaries.py의 전제 조건).
import random
import sys

sys.path.insert(0, ".")

from app import models
from scripts._db import get_session, RNG_SEED

N_PATIENTS = 20


def build_mock_patients(n: int, seed: int = RNG_SEED):
    rng = random.Random(seed)
    patients = []
    for i in range(1, n + 1):
        age = rng.randint(20, 80)
        sex = rng.choice(list(models.SexEnum))
        patients.append({
            "patient_id": f"IP_{i:07d}",
            "name": f"환자{i:03d}",
            "age": age,
            "sex": sex,
        })
    return patients


def seed():
    session = get_session()
    try:
        created = 0
        for data in build_mock_patients(N_PATIENTS):
            exists = session.query(models.Patient) \
                .filter(models.Patient.patient_id == data["patient_id"]).first()
            if exists:
                continue
            session.add(models.Patient(**data))
            created += 1
        session.commit()
        print(f"[seed_mock_patients] created={created}, skipped={N_PATIENTS - created}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
