from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql://avanguardia:avanguardia@localhost:5432/avanguardia"
    redis_url: str = "redis://localhost:6379/0"
    api_key_data_gov: str = ""
    senate_lda_api_key: str = ""
    opensecrets_bulk_path: str = ""
    quiver_quant_api_key: str = ""
    admin_api_key: str = ""
    sec_edgar_user_agent: str = ""
    cors_origins: str = "https://zdoss.github.io,http://localhost:5173"

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
