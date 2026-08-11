from sqlalchemy import Column, Integer, String, Float, Enum, ForeignKey, Text, DateTime
from sqlalchemy.orm import relationship, declarative_base
from pgvector.sqlalchemy import Vector
from datetime import datetime
import enum

Base = declarative_base()

# ENUM
class SexEnum(str, enum.Enum):
  male = "male"
  female = "female"

class AnatomySiteEnum(str, enum.Enum):
  head_neck = "head_neck"
  upper_extremity = "upper_extremity"
  lower_extremity = "lower_extremity"
  torso = "torso"

class DiagnosisEnum(str, enum.Enum):
  benign = "benign"
  malignant = "malignant"

# Patient
class Patient(Base):
  __tablename__ = "patients"

  id = Column(Integer, primary_key=True, index=True)
  patient_id = Column(String, unique=True, index=True)
  name = Column(String, nullable=False)
  age = Column(Integer)
  sex = Column(Enum(SexEnum, name="sex_enum"))
  created_at = Column(DateTime, default=datetime.utcnow)
  updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

  medical_images = relationship("MedicalImage", back_populates="patient")
  diagnoses = relationship("Diagnosis", back_populates="patient")

# MedicalImage
class MedicalImage(Base):
  __tablename__ = "medical_images"

  id = Column(Integer, primary_key=True, index=True)
  image_name = Column(String, unique=True, index=True)
  patient_id = Column(Integer, ForeignKey("patients.id"))
  file_path = Column(String, nullable=False)
  anatomy_site = Column(Enum(AnatomySiteEnum, name="anatomy_site_enum"))
  uploaded_at = Column(DateTime, default=datetime.utcnow)

  patient = relationship("Patient", back_populates="medical_images")
  diagnoses = relationship("Diagnosis", back_populates="medical_image")

# CommunicationSummary
# 진단 1건당 row 1개(카테고리별 row 아님). 카테고리 4개는 컬럼으로 분리되어 있다.
class CommunicationSummary(Base):
  __tablename__ = "communication_summaries"

  id = Column(Integer, primary_key=True, index=True)
  diagnosis_id = Column(Integer, ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False, unique=True)
  summary_created_at = Column(DateTime, default=datetime.utcnow)
  의사소견 = Column(Text)
  처방 = Column(Text)
  환자우려점 = Column(Text)
  진료계획 = Column(Text)

  diagnosis = relationship(
      "Diagnosis",
      foreign_keys=[diagnosis_id],
      back_populates="communication_summary",
  )

# Diagnosis
class Diagnosis(Base):
  __tablename__ = "diagnoses"

  id = Column(Integer, primary_key=True, index=True)
  patient_id = Column(Integer, ForeignKey("patients.id"))
  medical_image_id = Column(Integer, ForeignKey("medical_images.id"))
  communication_summary_id = Column(Integer, ForeignKey("communication_summaries.id")) # 연결된 CommunicationSummary의 id를 캐시. 실제 1:1 관계의 근거는 CommunicationSummary.diagnosis_id 쪽이며, 이 컬럼은 애플리케이션 계층(routers.py)에서 함께 동기화된다.
  diagnosis = Column(Enum(DiagnosisEnum, name="diagnosis_enum"))
  anatomy_site = Column(Enum(AnatomySiteEnum, name="anatomy_site_enum"))
  confidence_score = Column(Float)
  target_value = Column(Integer)  # 0: benign, 1: malignant
  diagnosed_by = Column(String)  # AI_MODEL 또는 DOCTOR_NAME
  ai_description = Column(Text)
  diagnosed_at = Column(DateTime, default=datetime.utcnow)
  diagnosis_detail = Column(String(64))  # ISIC mock 세부 라벨 (melanoma/nevus/unknown 등)
  embedding = Column(Vector(1536))  # OpenAI text-embedding-3-small 기준
  embedding_source = Column(Text)  # 임베딩 생성에 사용한 원문(디버깅/재임베딩용)
  embedding_updated_at = Column(DateTime)


  patient = relationship("Patient", back_populates="diagnoses")
  medical_image = relationship("MedicalImage", back_populates="diagnoses")
  communication_summary = relationship(
      "CommunicationSummary",
      primaryjoin="Diagnosis.id == CommunicationSummary.diagnosis_id",
      foreign_keys="[CommunicationSummary.diagnosis_id]",
      uselist=False,
      back_populates="diagnosis",
  )
