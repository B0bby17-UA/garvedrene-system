from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./app.db")

# Render/Heroku usa postgres:// mas SQLAlchemy exige postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    # Migration: add target_user_id column if not exists (SQLite)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN target_user_id VARCHAR(12)"))
            conn.commit()
    except Exception:
        pass
    # Migration: add npcs column to campaigns
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE campaigns ADD COLUMN npcs JSON"))
            conn.commit()
    except Exception:
        pass  # already exists
