from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://neondb_owner:npg_cNbr6p8mPvqH@ep-frosty-rice-aoea3obe.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    connect_args={"sslmode": "require"} if "sslmode" not in DATABASE_URL else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
