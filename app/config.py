from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./prospector.db"
    pagespeed_api_key: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
