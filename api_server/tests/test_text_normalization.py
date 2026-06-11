from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import api_app
from app.utils.text_normalization import normalize_display_text, normalize_payload_text


@api_app.get("/__test__/text-normalization")
def text_normalization_fixture() -> dict[str, object]:
    return {
        "TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m": 88,
        "candidate": {
            "name": "NguyÃ¡Â»â€¦n VÃ„Æ’n An",
            "details": [
                {
                    "TiÃƒÂªu chÃƒÂ­": "PhÃƒÂ¹ hÃ¡Â»Â£p JD",
                    "GiÃ¡ÂºÂ£i thÃƒÂ­ch": "Ã¡Â»Â¨ng viÃƒÂªn cÃƒÂ³ kinh nghiÃ¡Â»â€¡m phÃƒÂ¹ hÃ¡Â»Â£p.",
                }
            ],
        },
    }


def test_normalize_display_text_fixes_common_vietnamese_mojibake() -> None:
    assert normalize_display_text("NguyÃ¡Â»â€¦n VÃ„Æ’n An") == "Nguyễn Văn An"
    assert normalize_display_text("TÃ¡Â»â€¢ng Ã„â€˜iÃ¡Â»Æ’m") == "Tổng điểm"


def test_normalize_display_text_repairs_damaged_ui_phrases() -> None:
    assert normalize_display_text("Tiáº?p tá»£c") == "Tiếp tục"
    assert normalize_display_text("ThÆ° viá»‡n CV") == "Thư viện CV"


def test_normalize_payload_text_recursively_fixes_keys_and_values() -> None:
    payload = {"Chi tiÃ¡ÂºÂ¿t": [{"TiÃƒÂªu chÃƒÂ­": "PhÃƒÂ¹ hÃ¡Â»Â£p JD"}]}

    assert normalize_payload_text(payload) == {
        "Chi tiết": [{"Tiêu chí": "Phù hợp JD"}],
    }


def test_json_response_middleware_normalizes_payload_text() -> None:
    client = TestClient(api_app)

    response = client.get("/__test__/text-normalization")

    assert response.status_code == 200
    assert response.json() == {
        "Tổng điểm": 88,
        "candidate": {
            "name": "Nguyễn Văn An",
            "details": [
                {
                    "Tiêu chí": "Phù hợp JD",
                    "Giải thích": "Ứng viên có kinh nghiệm phù hợp.",
                }
            ],
        },
    }
