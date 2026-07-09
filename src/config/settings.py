from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AbeiroZero-Larouco"
    DATABASE_URL: str = "postgresql+asyncpg://postgres:secret@db:5432/abeiro"
    METEO_API_KEY: str | None = None
    TARGET_CRS: int = 25829
    
    class Config:
        env_file = ".env"

settings = Settings()