from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BASELINE_SQL = REPOSITORY_ROOT / "db/migrations/001_physical_v1_baseline.sql"
HARDWARE_SEED_SQL = REPOSITORY_ROOT / "db/seeds/seed_hardware.sql"
DEV_SEED_SQL = REPOSITORY_ROOT / "db/seeds/seed_dev.sql"
