"""FMS 목적지 코드를 승인된 한글 LCD 문구로 바꾸는 표."""

DESTINATION_LABELS = {
    'FROZEN': '냉동창고',
    'CHILLED': '냉장창고',
    'AMBIENT': '상온창고',
    'PACKING': '포장대',
    'RETURN': '대기/충전소\n복귀',
}


def destination_label(code: str) -> str | None:
    return DESTINATION_LABELS.get(code)
