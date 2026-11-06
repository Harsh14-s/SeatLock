from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "SeatLock"
    API_V1_STR: str = "/api/v1"
    
    # Database Settings
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "seatlock"
    
    # Redis Settings
    REDIS_HOST: str = "127.0.0.1"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # Seat Hold Expiration
    HOLD_TTL_SECONDS: int = 300  # 5 minutes
    
    @property
    def async_database_url(self) -> str:
        # e.g. postgresql+asyncpg://postgres@127.0.0.1:5432/seatlock
        auth = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@" if self.POSTGRES_PASSWORD else f"{self.POSTGRES_USER}@"
        return f"postgresql+asyncpg://{auth}{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    @property
    def sync_database_url(self) -> str:
        auth = f"{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@" if self.POSTGRES_PASSWORD else f"{self.POSTGRES_USER}@"
        return f"postgresql://{auth}{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
