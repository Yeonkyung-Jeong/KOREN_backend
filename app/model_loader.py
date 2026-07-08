import os
import requests
import tensorflow as tf
from tensorflow.keras import layers as L
import efficientnet.tfkeras as efn

# GitHub 모델 URL
MODEL_URL = "https://github.com/woosung-universe/koren_NeulMed/raw/main/Melanoma-Classifier-Federated-Learning/workspace/clientResults/base_model072.h5"

# 서버에 저장할 경로
model_path = os.getenv("LOCAL_MODEL_PATH")

def load_model():
  # 디렉토리 생성
  os.makedirs(os.path.dirname(model_path), exist_ok=True)

  # 모델 파일이 없으면 다운로드
  if not os.path.exists(model_path):
    print("모델 다운로드 중...")
    r = requests.get(MODEL_URL)
    r.raise_for_status()
    with open(model_path, "wb") as f:
      f.write(r.content)
    print("모델 다운로드 완료.")

  # 모델 아키텍처 정의
  model = tf.keras.Sequential([
    efn.EfficientNetB2(
        input_shape=(256, 256, 3),
        weights=None,
        include_top=False
    ),
    L.GlobalAveragePooling2D(),
    L.Dense(1024, activation='relu'),
    L.Dropout(0.3),
    L.Dense(512, activation='relu'),
    L.Dropout(0.2),
    L.Dense(256, activation='relu'),
    L.Dropout(0.2),
    L.Dense(128, activation='relu'),
    L.Dropout(0.1),
    L.Dense(1, activation='sigmoid')
  ])

  # 깃허브에서 다운로드한 가중치 로드
  model.load_weights(model_path)
  print("모델 로드 완료.")
  return model
