from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://jobsearch:jobsearch@db:5432/jobsearch"
    anthropic_api_key: str = ""
    redis_url: str = "redis://redis:6379/0"
    credit_budget_usd: float = 5.00

    model_config = {"env_file": ".env"}


settings = Settings()
