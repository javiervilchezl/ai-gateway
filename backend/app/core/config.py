from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ai-gateway-backend"
    app_env: str = "development"
    log_level: str = "INFO"
    provider: str = "openai"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    pdf_service_url: str = "http://pdf-service:8000"
    classifier_service_url: str = "http://classifier-service:8000"
    intent_service_url: str = "http://intent-service:8000"
    helicone_api_key: str = ""
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    enable_openlit: bool = False
    gateway_api_key: str = ""
    gateway_api_key_header: str = "X-API-Key"
    internal_service_api_key: str = ""
    internal_service_api_key_header: str = "X-Service-API-Key"
    cors_allow_origins: str = "*"
    trusted_client_ips: str = ""
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60
    auth_require_jwt: bool = False
    database_url: str = "mysql+pymysql://gateway_user:gateway_pass@mysql:3306/gateway_db"
    admin_default_username: str = "admin"
    admin_default_password: str = ""
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 120
    rate_limit_window_seconds: int = 60
    rate_limit_login_requests: int = 10
    rate_limit_login_window_seconds: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_allow_origins_list(self) -> list[str]:
        return _split_csv(self.cors_allow_origins) or ["*"]

    @property
    def trusted_client_ips_list(self) -> list[str]:
        return _split_csv(self.trusted_client_ips)


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


settings = Settings()
