from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]

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
    ollama_num_ctx: int = 8192              
    ollama_num_predict: int = 4096          
    ollama_temperature: float = 0.5         
    ollama_keep_alive: str = "30m" 
    openai_model: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""          #ex.: https://api.groq.com/openai/v1
    openai_reasoning_effort: str = ""  #ex.: "low"/"medium"/"high" p/ modelos reasoning
    llm_max_tokens: int = 8192
    llm_max_prompt_chars: int = 4096
    

    #Telegram
    delivery_channel: str = "telegram"    
    telegram_token: str = ""
    telegram_chat_id: str = ""

    # SMTP / e-mail
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    email_user: str = ""
    email_password: str = ""
    email_to: str = ""

    # Pipeline
    max_news: int = 20
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

