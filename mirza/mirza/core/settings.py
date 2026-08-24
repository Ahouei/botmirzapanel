"""Application settings via pydantic-settings (env + .env). Replaces config.php."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIRZA_DB_")

    driver: str = "postgresql+asyncpg"  # or "sqlite+aiosqlite"
    host: str = "localhost"
    port: int = 5432
    name: str = "mirza"
    user: str = "mirza"
    password: str = ""

    @property
    def url(self) -> str:
        if self.driver.startswith("sqlite"):
            return f"{self.driver}:///{self.name}.db"
        return (
            f"{self.driver}://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIRZA_TG_")

    bot_token: str = ""
    admin_ids: list[int] = []
    use_local_bot_api: bool = False
    local_api_server: str = ""


class WebSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MIRZA_WEB_")

    # Public base URL; webhook path is /webhook/<secret>
    base_url: str = "https://example.com"
    listen_host: str = "127.0.0.1"
    listen_port: int = 8080
    webhook_secret: str = "changeme"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__")

    app_name: str = "mirza-bot"
    debug: bool = False
    timezone: str = "Asia/Tehran"

    db: DatabaseSettings = DatabaseSettings()
    telegram: TelegramSettings = TelegramSettings()
    web: WebSettings = WebSettings()

    # Directories for plugins and locale files (colon-separated allowed)
    plugin_dirs: str = "plugins"
    locale_dir: str = "locales"


@lru_cache
def get_settings() -> Settings:
    return Settings()
