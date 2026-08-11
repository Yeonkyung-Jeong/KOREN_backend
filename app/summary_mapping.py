# OpenAI가 반환하는 요약 JSON 키(띄어쓰기 있음) ↔ communication_summaries 컬럼명(띄어쓰기 없음) 매핑
KOR_SUMMARY_KEY_TO_COLUMN = {
    "의사 소견": "의사소견",
    "환자의 우려점": "환자우려점",
    "진료 계획": "진료계획",
    "처방": "처방",
}

COLUMN_TO_KOR_SUMMARY_KEY = {column: key for key, column in KOR_SUMMARY_KEY_TO_COLUMN.items()}
