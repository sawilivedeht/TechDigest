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
    ollama_think: str = ""             # "" = padrão do modelo | "true"/"false" liga/desliga o raciocínio (thinking)
    openai_model: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""          #ex.: https://api.groq.com/openai/v1
    openai_reasoning_effort: str = ""  #ex.: "low"/"medium"/"high" p/ modelos reasoning
    llm_max_tokens: int = 153600
    llm_max_prompt_chars: int = 4096


    #Telegram
    delivery_channel: str = "telegram"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_tentativas_audio: int = 3     # tentativas de upload do áudio em falha de rede (o texto não é reenviado)
    telegram_pausa_s: int = 10             # pausa entre as tentativas
    telegram_forcar_ipv4: bool = True      # a rota IPv6 até o Telegram trava neste host (3 MB: ~2 s via IPv4, 15-120 s via IPv6)

    # SMTP / e-mail
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    email_user: str = ""
    email_password: str = ""
    email_to: str = ""

    # Pipeline
    max_news: int = 20
    min_texto_chars: int = 1200        # abaixo disso o item é descartado (não gera episódio a partir de manchete/snippet)
    feed_timeout_s: int = 30           # timeout de download de cada feed RSS (evita travar a execução)
    max_por_feed: int = 15             # entradas lidas por feed
    max_idade_dias: int = 7            # só notícias publicadas há no máximo N dias (data do feed); 0 = sem limite
    gnews_resolver: bool = True        # resolve links do Google Notícias para a URL do veículo (False = desliga)
    max_runtime_min: int = 180         # não inicia novos itens depois desse tempo (0 = sem limite); o systemd mata em 4h
    max_falhas_entrega: int = 3        # falhas de entrega SEGUIDAS que encerram a execução (canal fora do ar)

    # QA editorial (regras 2, 3 e 6). Os defaults são as regras originais; ajuste no .env (QA_*)
    qa_min_por_personagem: int = 240
    qa_max_por_personagem: int = 480
    qa_min_total: int = 600
    qa_max_total: int = 1300
    qa_min_frases: int = 7
    qa_max_frases: int = 10
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