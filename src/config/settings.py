import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AbeiroZero"
    BASE_CRS: str = "EPSG:25829"
    AOI_NAME: str = "Larouco, Ourense, Galicia, Spain"
    DATA_DIR: str = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'data'))
    AOI_PATH: str = f"{DATA_DIR}/reference/master_aoi.gpkg"
    DB_URL: str = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/abeiro")

    class Config:
        env_file = ".env"

settings = Settings()