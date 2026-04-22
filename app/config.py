import os

class Settings:
    DATABASE_URL: str = os.environ.get(
        "DATABASE_URL",
        "postgresql://neondb_owner:npg_cNbr6p8mPvqH@ep-frosty-rice-aoea3obe.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require"
    )
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "computepool2024secretkeyx99")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 43200
    PLATFORM_FEE: float = 0.20
    CASHIOUT_MIN: float = 500.0

_settings = None

def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
