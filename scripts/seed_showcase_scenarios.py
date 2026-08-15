# 포트폴리오 캡처용 큐레이션 mock 시나리오 시딩.
# seed_mock_patients/diagnoses/summaries.py의 랜덤 생성과 달리, 브리핑·유사사례
# 응답이 의도한 서사를 만들어내도록 날짜·confidence_score·처방·환자우려점을
# 직접 고정값으로 설계한다. 재실행 안전성은 patient_id 존재 여부로 판단한다.
import sys
from datetime import datetime

sys.path.insert(0, ".")

from app import models
from scripts._db import get_session

# --- 시나리오 1: 브리핑용 "점진적 호전" 환자 -------------------------------
# 동일 부위(lower_extremity)에 악성(melanoma) 진단이 3회 반복되지만, 매 방문마다
# confidence_score가 낮아지고 처방이 "즉시 조직검사 -> 국소 처방 -> 경과 관찰
# 전환"으로 완화되며, 환자 우려점도 "불안 호소 -> 다소 완화 -> 안심"으로 이어진다.
# 방문 간격은 1차->2차 1개월, 2차->3차 3개월로 벌려, narrative_summary가
# "방문 간격이 벌어졌다"는 점을 구체적인 수치로 서술할 근거 데이터가 되게 한다.
MAIN_PATIENT = {
    "patient_id": "IP_0000021",
    "name": "환자021",
    "age": 48,
    "sex": models.SexEnum.female,
}

MAIN_VISITS = [
    {
        "date": datetime(2026, 3, 20, 10, 30),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.78,
        "의사소견": "하지 부위 병변, 악성 의심 소견. 비대칭성 및 경계 불규칙성 관찰됨, 조직검사 필요.",
        "처방": "조직검사 의뢰, 2주 후 재방문 안내",
        "환자우려점": "병변 크기가 최근 커진 것 같다는 불안 호소",
        "진료계획": "1개월 후 재검",
    },
    {
        "date": datetime(2026, 4, 20, 14, 15),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.61,
        "의사소견": "하지 부위 병변, 이전 대비 경계가 다소 뚜렷해지고 비대칭성 완화됨. 경과 관찰 지속 필요.",
        "처방": "국소 스테로이드 연고 처방, 3개월 후 재방문 권장",
        "환자우려점": "병변 크기가 안정된 것 같다며 불안 다소 완화",
        "진료계획": "3개월 후 재검",
    },
    {
        "date": datetime(2026, 7, 20, 11, 0),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.53,
        "의사소견": "하지 부위 병변, 크기 감소 및 경계 명확해짐. 악성 소견 약화, 경과 관찰로 전환 가능.",
        "처방": "특이 처방 없음, 경과 관찰 전환, 6개월 후 정기 검진 권장",
        "환자우려점": "특이 증상 없음, 안심하는 모습",
        "진료계획": "6개월 후 정기 검진",
    },
]

# --- 시나리오 2: 유사사례용 비교 환자 --------------------------------------
# 둘 다 MAIN_PATIENT의 3차(가장 최근) 진단과 동일 부위(lower_extremity)·동일
# 진단명(malignant)이지만, 서로 반대되는 경과를 보여 similar_cases의
# shared_features/differences/clinical_note가 구체적인 근거를 갖게 한다.
# - COMPARISON_A: 나이·성별이 MAIN_PATIENT와 뚜렷이 다름(70세 남성) + 급격히
#   악화되어 광범위 절제술까지 간 사례(대비되는 경과).
# - COMPARISON_B: 나이·성별이 MAIN_PATIENT와 비슷함(45세 여성) + MAIN_PATIENT와
#   유사하게 호전된 사례(유사한 경과, 반복되는 패턴 강조).
COMPARISON_A_PATIENT = {
    "patient_id": "IP_0000022",
    "name": "환자022",
    "age": 70,
    "sex": models.SexEnum.male,
}

COMPARISON_A_VISITS = [
    {
        "date": datetime(2026, 5, 1, 15, 45),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.81,
        "의사소견": "하지 부위 병변, 악성 의심 소견. 경계 불규칙 및 최근 급격한 크기 변화 관찰됨, 즉시 조직검사 필요.",
        "처방": "즉시 조직검사 의뢰, 응급 2차 병원 전원",
        "환자우려점": "병변이 최근 몇 주 사이 급격히 커지고 출혈이 있었다는 불안 호소",
        "진료계획": "1개월 후 재검",
    },
    {
        "date": datetime(2026, 6, 5, 10, 0),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.89,
        "의사소견": "하지 부위 병변, 조직검사 결과 악성 확진. 광범위 절제술 필요, 림프절 전이 여부 추가 검사 권고.",
        "처방": "광범위 절제술 시행, 림프절 조직검사 추가 의뢰",
        "환자우려점": "수술 후 회복 및 전이 여부에 대한 극심한 불안",
        "진료계획": "1개월 후 재검",
    },
]

COMPARISON_B_PATIENT = {
    "patient_id": "IP_0000023",
    "name": "환자023",
    "age": 45,
    "sex": models.SexEnum.female,
}

COMPARISON_B_VISITS = [
    {
        "date": datetime(2026, 4, 1, 13, 20),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.68,
        "의사소견": "하지 부위 병변, 악성 의심 소견. 경계 다소 불규칙, 조직검사 권고.",
        "처방": "조직검사 의뢰, 국소 마취 하 절제 생검 시행",
        "환자우려점": "병변 색 변화에 대한 불안 호소",
        "진료계획": "3개월 후 재검",
    },
    {
        "date": datetime(2026, 7, 1, 11, 40),
        "anatomy_site": models.AnatomySiteEnum.lower_extremity,
        "diagnosis": models.DiagnosisEnum.malignant,
        "diagnosis_detail": "melanoma",
        "confidence_score": 0.55,
        "의사소견": "하지 부위 병변, 생검 후 절제연 음성 확인. 잔여 병변 크기 감소, 예후 양호.",
        "처방": "특이 처방 없음, 경과 관찰 전환, 6개월 후 정기 검진 권장",
        "환자우려점": "치료 결과에 안도, 특이 증상 없음",
        "진료계획": "6개월 후 정기 검진",
    },
]

SCENARIOS = [
    (MAIN_PATIENT, MAIN_VISITS),
    (COMPARISON_A_PATIENT, COMPARISON_A_VISITS),
    (COMPARISON_B_PATIENT, COMPARISON_B_VISITS),
]


def seed_patient(session, patient_data: dict, visits: list) -> None:
    existing = (
        session.query(models.Patient)
        .filter(models.Patient.patient_id == patient_data["patient_id"])
        .first()
    )
    if existing:
        print(f"[seed_showcase_scenarios] {patient_data['patient_id']} 이미 존재, 스킵")
        return

    patient = models.Patient(**patient_data)
    session.add(patient)
    session.flush()  # patient.id 확보

    # 환자별로 스코프된 이름을 써서, 기존 환자가 스킵되더라도(전역 시퀀스가
    # 진행되지 않는 상황) 다른 환자와 image_name이 충돌하지 않게 한다.
    for index, visit in enumerate(visits, start=1):
        image_name = f"SHOWCASE_{patient_data['patient_id']}_{index:02d}.jpg"

        medical_image = models.MedicalImage(
            image_name=image_name,
            patient_id=patient.id,
            file_path=f"./uploads/mock_{image_name}",
            anatomy_site=visit["anatomy_site"],
            uploaded_at=visit["date"],
        )
        session.add(medical_image)
        session.flush()  # medical_image.id 확보

        diagnosis_value = visit["diagnosis"]
        diagnosis = models.Diagnosis(
            patient_id=patient.id,
            medical_image_id=medical_image.id,
            communication_summary_id=None,
            diagnosis=diagnosis_value,
            anatomy_site=visit["anatomy_site"],
            confidence_score=visit["confidence_score"],
            target_value=1 if diagnosis_value == models.DiagnosisEnum.malignant else 0,
            diagnosed_by="AI_MODEL",
            ai_description=f"진단 결과, {diagnosis_value.value} 이(가) 의심됩니다. 관련된 추가적인 처방을 제공해주세요.",
            diagnosed_at=visit["date"],
            diagnosis_detail=visit["diagnosis_detail"],
        )
        session.add(diagnosis)
        session.flush()  # diagnosis.id 확보

        summary = models.CommunicationSummary(
            diagnosis_id=diagnosis.id,
            summary_created_at=visit["date"],
            의사소견=visit["의사소견"],
            처방=visit["처방"],
            환자우려점=visit["환자우려점"],
            진료계획=visit["진료계획"],
        )
        session.add(summary)
        session.flush()  # summary.id 확보

        diagnosis.communication_summary_id = summary.id

    session.commit()
    print(
        f"[seed_showcase_scenarios] {patient_data['patient_id']} 생성 완료 "
        f"(방문 {len(visits)}건)"
    )


def seed():
    session = get_session()
    try:
        for patient_data, visits in SCENARIOS:
            seed_patient(session, patient_data, visits)
    finally:
        session.close()


if __name__ == "__main__":
    seed()
