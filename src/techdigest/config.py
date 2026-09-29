from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
import logging
logger = logging.getLogger("techdigest.<submódulo>")



BASE_DIR = Path(__file__).resolve().parents[2]   # src/techdigest/config.py → raiz do projeto


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",        
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )     

    # Logging
    log_level: str = "INFO"
    log_dir: str = str(BASE_DIR / "data" / "logs")

    # LLM
    llm_provider: str = "ollama"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "gemma4:26b"
    openai_model: str = ""
    openai_api_key: str = ""
    llm_max_tokens: int = 10240        
    llm_max_prompt_chars: int = 12288 

    #Telegram
    delivery_channel: str = "telegram"    # "telegram" | "email"
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # SMTP / e-mail
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    email_user: str = ""
    email_password: str = ""
    email_to: str = ""

    # Pipeline
    max_news: int = 12
    db_path: str = str(BASE_DIR / "data" / "digest.db")    
    audio_dir: str = str(BASE_DIR / "data" / "audio") 

    rss_feeds: str = (
        "https://www.theverge.com/rss/index.xml,"
        "https://feeds.arstechnica.com/arstechnica/index,"
        "https://hnrss.org/frontpage"
    )

    @property
    def feeds(self) -> list[str]:
        return [f.strip() for f in self.rss_feeds.split(",") if f.strip()]


settings = Settings()

