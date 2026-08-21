
import re
from pathlib import Path


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "db" / "migrations" / "001_physical_v1_baseline.sql"
KOREAN_TEXT = re.compile(r"[가-힣]")
TABLE_COMMENT = re.compile(r"ENGINE=InnoDB COMMENT='([^']+)';")
COLUMN_COMMENT = re.compile(r"\bCOMMENT '([^']+)'", re.IGNORECASE)


def test_schema_metadata_uses_web_safe_english_comments() -> None:
    """Schema comments shown by the web UI must not depend on Korean decoding."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    table_comments = TABLE_COMMENT.findall(schema)
    column_comments = COLUMN_COMMENT.findall(schema)

    assert table_comments
    assert column_comments
    comments = table_comments + column_comments
    assert all(comment.strip() and comment.isascii() for comment in comments)
    assert not any(KOREAN_TEXT.search(comment) for comment in comments)
