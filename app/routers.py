# routers.py
from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from openai import OpenAI
from datetime import datetime
import os, uuid, json, ast

from app.database import get_db
from app import models
from app.utils import preprocess_image
from app.summary_mapping import KOR_SUMMARY_KEY_TO_COLUMN, COLUMN_TO_KOR_SUMMARY_KEY

router = APIRouter()

# AI 모델 로드
from app.model_loader import load_model
model = load_model()

# OpenAI 클라이언트 초기화
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -----------------------------
# POST: 진단하기
# -----------------------------
@router.post("/diagnose")
async def diagnose(
    file: UploadFile = File(...),
    patient_name: str = Form(...),
    patient_age: int = Form(...),
    patient_id: str = Form(...),
    patient_sex: str = Form(...),
    anatomy_site: str = Form(...),
    db: Session = Depends(get_db)
):
  try:
    # 환자 조회 / 생성
    patient = db.query(models.Patient).filter(models.Patient.patient_id==patient_id).first()
    if not patient:
      patient = models.Patient(
          patient_id=patient_id,
          name=patient_name,
          age=patient_age,
          sex=patient_sex
      )
      db.add(patient)
      db.commit()
      db.refresh(patient)

    # 이미지 저장
    contents = await file.read()
    image = preprocess_image(contents)
    image_name = f"{uuid.uuid4().hex}_{file.filename}"
    file_path = f"./uploads/{image_name}"
    os.makedirs("./uploads", exist_ok=True)
    with open(file_path, "wb") as f:
      f.write(contents)

    medical_image = models.MedicalImage(
        image_name=image_name,
        patient_id=patient.id,
        file_path=file_path,
        anatomy_site=anatomy_site
    )
    db.add(medical_image)
    db.commit()
    db.refresh(medical_image)

    # AI 모델 예측
    pred = model.predict(image)[0][0]
    confidence = float(pred)
    diagnosis_result = "malignant" if confidence > 0.5 else "benign"
    target_value = 1 if diagnosis_result=="malignant" else 0
    ai_description = f"진단 결과, {diagnosis_result} 이(가) 의심됩니다. 관련된 추가적인 처방을 제공해주세요." # TODO: 나중에 보완할 때는 AI LLM 소견으로 바꾸기

    # Diagnosis 생성
    diagnosis = models.Diagnosis(
        patient_id=patient.id,
        medical_image_id=medical_image.id,
        communication_summary_id=None,
        diagnosis=diagnosis_result,
        confidence_score=confidence,
        target_value=target_value,
        diagnosed_by="AI_MODEL", # TODO: 나중에 연합학습으로 갱신된 모델 버전으로 표시해도 좋을 듯
        ai_description=ai_description,
        anatomy_site=anatomy_site,
        diagnosed_at=datetime.utcnow()
    )
    db.add(diagnosis)
    db.commit()
    db.refresh(diagnosis)

    # 이전 대화 요약 불러오기 (해당 환자의 과거 진단에 연결된 가장 최근 요약 1건)
    latest_summary = db.query(models.CommunicationSummary) \
      .join(models.Diagnosis, models.CommunicationSummary.diagnosis_id == models.Diagnosis.id) \
      .filter(models.Diagnosis.patient_id == patient.id) \
      .order_by(models.CommunicationSummary.summary_created_at.desc(),
                models.CommunicationSummary.id.desc()) \
      .first()
    previous_summary_data = (
        {COLUMN_TO_KOR_SUMMARY_KEY[col]: getattr(latest_summary, col) for col in KOR_SUMMARY_KEY_TO_COLUMN.values()}
        if latest_summary else {}
    )

    return JSONResponse(content={
      "diagnosis": diagnosis_result,
      "medical_image_id": medical_image.id,
      "ai_description": ai_description,
      "confidence_score": confidence,
      "previous_summary": previous_summary_data
    })

  except Exception as e:
    raise HTTPException(status_code=500, detail=str(e))

# -----------------------------
# GET: 진단 결과
# -----------------------------
@router.get("/diagnosis/{patient_id}")
def get_diagnosis(patient_id: str, db: Session = Depends(get_db)):
  patient = db.query(models.Patient).filter(models.Patient.patient_id==patient_id).first()
  if not patient:
    raise HTTPException(status_code=404, detail="Patient not found")

  diagnosis = db.query(models.Diagnosis) \
    .filter(models.Diagnosis.patient_id==patient.id) \
    .order_by(models.Diagnosis.diagnosed_at.desc()) \
    .first()
  if not diagnosis:
    raise HTTPException(status_code=404, detail="No diagnosis found for this patient")

  return {
    "diagnosis": diagnosis.diagnosis,
    "confidence_score": diagnosis.confidence_score,
    "ai_description": diagnosis.ai_description
  }

# -----------------------------
# POST: STT 기반 대화 요약
# -----------------------------
class ConversationInput(BaseModel):
  patient_id: str
  conversation: str

@router.post("/summarize", response_model=dict)
def create_summary(input_data: ConversationInput, db: Session = Depends(get_db)):
  try:
    # 환자 조회
    patient = db.query(models.Patient).filter(models.Patient.patient_id == input_data.patient_id).first()
    if not patient:
      raise HTTPException(status_code=404, detail="Patient not found")

    # 요약을 연결할 대상 진단: 해당 환자의 가장 최근 진단 1건
    target_diagnosis = db.query(models.Diagnosis) \
      .filter(models.Diagnosis.patient_id == patient.id) \
      .order_by(models.Diagnosis.diagnosed_at.desc(), models.Diagnosis.id.desc()) \
      .first()
    if not target_diagnosis:
      raise HTTPException(status_code=404, detail="No diagnosis found for this patient")

    # conversation 전처리: 빈 문자열 체크, 줄바꿈 제거
    conversation = (input_data.conversation or "").strip().replace("\n", " ").replace("\r", "")
    if not conversation:
      raise HTTPException(status_code=400, detail="conversation is empty")

    # STT 기반 대화 요약
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
          {"role": "system", "content": "You are a medical assistant. Summarize the doctor-patient conversation."},
          {"role": "user", "content": f"""
대화:
\"\"\"{conversation}\"\"\"

대화 텍스트에는 화자 정보가 없습니다. 
문맥을 보고 의사와 환자 중 누가 말하는지 추론하여 JSON으로 요약하십시오:
{{
  "의사 소견": "...",
  "환자의 우려점": "...",
  "진료 계획": "...",
  "처방": "..."
}}
"""}
        ],
        response_format={"type": "json_object"}
    )

    # OpenAI 응답에서 content 가져오기
    summary_text = response.choices[0].message.content

    # JSON 파싱 안전하게 처리
    try:
      summary_json_kor = json.loads(summary_text)
    except json.JSONDecodeError:
      # LLM 출력이 완전히 올바른 JSON이 아닐 때
      summary_json_kor = ast.literal_eval(summary_text)

    # JSON 키를 컬럼명으로 변환해 대상 진단의 CommunicationSummary 1 row에 UPSERT
    column_updates = {}
    for category, content in summary_json_kor.items():
      column = KOR_SUMMARY_KEY_TO_COLUMN.get(category)
      if column is None:
        continue  # 4개 컬럼 고정 스키마이므로 예상 밖 키(오탈자 등)는 저장하지 않음
      # content 전처리: 긴 문자열, 특수문자 방어
      content_safe = (content or "").encode('utf-8', errors='replace').decode('utf-8')
      if len(content_safe) > 10000:
        content_safe = content_safe[:10000]
      column_updates[column] = content_safe

    try:
      existing = db.query(models.CommunicationSummary) \
        .filter(models.CommunicationSummary.diagnosis_id == target_diagnosis.id).first()
      if existing:
        for col, val in column_updates.items():
          setattr(existing, col, val)
        existing.summary_created_at = datetime.utcnow()
        summary_row = existing
      else:
        summary_row = models.CommunicationSummary(
            diagnosis_id=target_diagnosis.id,
            summary_created_at=datetime.utcnow(),
            **column_updates
        )
        db.add(summary_row)
      db.flush()  # summary_row.id 확보 (커밋 전)
      target_diagnosis.communication_summary_id = summary_row.id  # 양방향 FK 동기화
      db.commit()
    except Exception as e:
      db.rollback()
      raise HTTPException(status_code=500, detail=f"DB insert error: {e}")

    return summary_json_kor

  except HTTPException:
    raise
  except Exception as e:
    raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

# -----------------------------
# GET: STT 기반 대화 요약
# -----------------------------
@router.get("/summary/{patient_id}")
def get_latest_summary(patient_id: str, db: Session = Depends(get_db)):
  # 환자 조회
  patient = db.query(models.Patient).filter(models.Patient.patient_id==patient_id).first()
  if not patient:
    raise HTTPException(status_code=404, detail="Patient not found")

  # 환자의 최신 진단(diagnosed_at 기준) 1건에 연결된 요약을 반환한다.
  # summary_created_at이 아니라 diagnosed_at 기준으로 "최신 진단"을 정하므로,
  # 최신 진단에 아직 요약이 없으면(아직 /summarize가 호출되지 않음) 이전 진단의
  # 오래된 요약으로 조용히 대체되지 않고 404를 반환한다.
  latest_diagnosis = db.query(models.Diagnosis) \
    .filter(models.Diagnosis.patient_id == patient.id) \
    .order_by(models.Diagnosis.diagnosed_at.desc(), models.Diagnosis.id.desc()) \
    .first()

  latest = latest_diagnosis.communication_summary if latest_diagnosis else None

  if not latest:
    raise HTTPException(status_code=404, detail="No communication summary found for this patient")

  result = {COLUMN_TO_KOR_SUMMARY_KEY[col]: getattr(latest, col) for col in KOR_SUMMARY_KEY_TO_COLUMN.values()}

  return {
      "patient_id": patient.patient_id,
      "latest_summary": result,
      "created_at": latest.summary_created_at
    }

# -----------------------------
# GET: 전체 진단 기록
# -----------------------------
@router.get("/diagnoses")
def get_diagnoses(db: Session = Depends(get_db)):
  # 모든 진단 기록 조회
  diagnoses = db.query(models.Diagnosis).order_by(models.Diagnosis.diagnosed_at.desc()).all()

  if not diagnoses:
    raise HTTPException(status_code=404, detail="No diagnosis records found")

  results = []
  for d in diagnoses:
    results.append({
      "image_name": d.medical_image.image_name if d.medical_image else None,
      "patient_id": d.patient.patient_id if d.patient else None,
      "sex": d.patient.sex.value if d.patient and d.patient.sex else None,
      "age_approx": d.patient.age if d.patient else None,
      "anatom_site_general_challenge": d.anatomy_site.value if d.anatomy_site else None,
      "target": d.target_value,
      "diagnosis": d.diagnosis.value if d.diagnosis else None,
      "benign_malignant": d.diagnosis.value if d.diagnosis else None,
      "location": d.anatomy_site.value if d.anatomy_site else None,
      "confidence_score": d.confidence_score, # TODO: 추후 진단 기록표에 컬럼 추가하는 확장 가능성을 위해 냅둠
      "diagnosed_by": d.diagnosed_by, # TODO: 추후 진단 기록표에 컬럼 추가하는 확장 가능성을 위해 냅둠
      "diagnosed_at": d.diagnosed_at.isoformat() # TODO: 추후 진단 기록표에 컬럼 추가하는 확장 가능성을 위해 냅둠
    })

  return {
    "total_records": len(results),
    "diagnoses": results
  }

