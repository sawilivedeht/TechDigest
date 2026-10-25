import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
# Fora das pastas do projeto, para a pasta principal e a worktree verem o mesmo arquivo: é o %S/techdigest
# das units de usuário (deploy/systemd), onde a unit do Ollama grava a saída do servidor.
PASTA_DE_ESTADO = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "techdigest"

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
    ollama_log: str = str(PASTA_DE_ESTADO / "ollama_serve.log")   # a saída do `ollama serve` da unit ollama.service, onde
                                       # as conferências da GPU (ai/gpu.py) leem a placa e a carga do modelo
    openai_model: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""          #ex.: https://api.groq.com/openai/v1
    openai_reasoning_effort: str = ""  #ex.: "low"/"medium"/"high" p/ modelos reasoning
    llm_max_tokens: int = 153600
    llm_max_prompt_chars: int = 4096
    llm_reserva_saida: int = 3000      # tokens da janela guardados para a resposta no orçamento da entrada (vale o menor entre isto e OLLAMA_NUM_PREDICT)


    #Telegram
    delivery_channel: str = "telegram"
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_tentativas_audio: int = 3     # tentativas de upload do áudio em falha de rede (o texto não é reenviado)
    telegram_pausa_s: int = 10             # pausa entre as tentativas
    telegram_forcar_ipv4: bool = True      # a rota IPv6 até o Telegram trava neste host (3 MB: ~2 s via IPv4, 15-120 s via IPv6)
    arquivo_dir: str = str(BASE_DIR / "data" / "entregas")   # DELIVERY_CHANNEL=arquivo, o canal da simulação: onde
                                       # ficam as entregas (techdigest --simular aponta para <pasta>/entregas)

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
    max_reprovacoes: int = 2           # execuções em que o QA reprovou o item até ele ser abandonado (só QAReprovado conta)
    execucoes_dir: str = str(BASE_DIR / "data" / "execucoes")   # o registro de cada execução (registro.py): os textos usados
                                       # e os episódios, no formato que checar_fidelidade.py e refazer_qa.py leem
    execucoes_dias: int = 30           # dias que o registro de uma execução fica guardado (0 = guarda todos)

    # Extração em lote (extractor.extrair_em_lote)
    extracao_workers: int = 6          # itens extraídos em paralelo
    extracao_workers_gnews: int = 2    # no máximo N resolvendo links do Google Notícias ao mesmo tempo (evita bloqueio)

    # Agrupamento de notícias em pautas. Só scripts/testar_agrupamento.py usa; o pipeline ainda não agrupa
    agrup_chars_texto: int = 1500      # caracteres iniciais do texto extraído que entram no TF-IDF
    agrup_peso_titulo: float = 0.4     # score = peso × título + (1 − peso) × texto
    agrup_limiar: float = 0.18         # score mínimo da pauta provisória; quem confirma é o LLM. Mantido depois de uma segunda
                                       # amostra (12/10/2026): entre 0,15 e 0,18 só havia pares de fatos diferentes
    agrup_limiar_duplicata: float = 0.95   # similaridade de texto a partir da qual é republicação, não outra fonte
    agrup_max_artigos: int = 3         # artigos por pauta (principal + 2 relacionados, o limite do _montar_entrada)
    agrup_chars_etapa3: int = 900      # caracteres iniciais de cada texto que o LLM recebe para confirmar a pauta

    # QA editorial (regras 2, 3 e 6). Os padrões são os valores em vigor; ajuste no .env (QA_*)
    qa_min_por_personagem: int = 240
    qa_min_helena_com_debate: int = 180   # o mínimo de Helena em episódio com dois analistas ou mais
    qa_min_lado_fino: int = 120        # o mínimo do analista de um lado fino (atores em no máximo uma frase dos textos)
    qa_max_lado_fino: int = 200        # o teto que o prompt pede a ele: só diagnóstico, o QA não cobra
    qa_max_por_personagem: int = 650   # o teto do QA; os prompts pedem até 480, como margem (como as 8 a 9 frases
                                       # do resumo contra as 7 a 10 que o QA cobra). Era o valor do .env até a fase 4
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