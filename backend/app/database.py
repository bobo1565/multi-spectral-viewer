from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import shutil
from pathlib import Path

if os.getenv("ENV") == "production":
    PROJECT_ROOT = Path("/app")
else:
    # 在本地开发/Trae 沙箱下，优先将 DB 放在 backend 目录内，避免跨目录写入受限
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = str(PROJECT_ROOT / "uploads" / "data")
os.makedirs(DATA_DIR, exist_ok=True)

DB_PATH = Path(DATA_DIR) / "sql_app.db"
LEGACY_DB_PATH = Path(__file__).resolve().parent.parent.parent / "uploads" / "data" / "sql_app.db"

# 迁移旧路径 DB（仅在新路径不存在时复制一次）
if not DB_PATH.exists() and LEGACY_DB_PATH.exists():
    shutil.copy2(LEGACY_DB_PATH, DB_PATH)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
