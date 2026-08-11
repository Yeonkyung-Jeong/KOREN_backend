from app.summary_mapping import KOR_SUMMARY_KEY_TO_COLUMN, COLUMN_TO_KOR_SUMMARY_KEY

# app/routers.py의 OpenAI 프롬프트(POST /summarize)가 요청하는 4개 키와 일치해야 함
EXPECTED_KEYS = {"의사 소견", "환자의 우려점", "진료 계획", "처방"}


def test_keys_match_openai_prompt_categories():
    assert set(KOR_SUMMARY_KEY_TO_COLUMN.keys()) == EXPECTED_KEYS


def test_roundtrip_mapping():
    for key, column in KOR_SUMMARY_KEY_TO_COLUMN.items():
        assert COLUMN_TO_KOR_SUMMARY_KEY[column] == key


def test_column_names_have_no_spaces():
    for column in KOR_SUMMARY_KEY_TO_COLUMN.values():
        assert " " not in column
