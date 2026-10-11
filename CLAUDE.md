# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

TechDigest is a batch pipeline that collects news from RSS feeds (technology + Brazilian politics), has an LLM write a summary and a multi-voice podcast script for each item, synthesizes the audio with Edge-TTS, and delivers each item to Telegram. It is meant to run unattended from a systemd timer (the unit files are not in this repo).

Everything in the codebase is written in Brazilian Portuguese: identifiers, comments, docstrings, log messages, LLM prompts and commit messages. Keep new code consistent with that.

## Commands

```bash
.venv/bin/pip install -e .                       # install (already installed editable in .venv, Python 3.14; requires >=3.11)
.venv/bin/techdigest                             # run the pipeline (same as: .venv/bin/python -m techdigest)
.venv/bin/python scripts/resumo_lotes.py         # per-run summary table parsed from today's log
.venv/bin/python scripts/resumo_lotes.py 07/10   # same, for a given day (DD/MM)
.venv/bin/python scripts/testar_agrupamento.py   # grouping diagnostic: no Telegram, digest.db opened read-only, LLM only with --etapa3
.venv/bin/python scripts/testar_episodio.py --amostra <file>   # generates a few multi-source episodes from a saved sample: LLM only, nothing delivered
.venv/bin/pip install -e '.[dev]'                # dev extra (pytest)
.venv/bin/pytest                                 # tests
```

- `scripts/testar_agrupamento.py` collects the feeds, extracts the texts (about a minute of network I/O), prints the "pautas" it would form and writes the top-scoring pairs to `data/agrupamento/pares_<timestamp>.csv`. Options: `--limiar`, `--peso-titulo`, `--max-candidatos`, `--incluir-vistos`. Every live collection returns different articles, so to compare thresholds on the same data use `--salvar-amostra` (also writes the extracted candidates to `data/agrupamento/amostra_<timestamp>.json`) and then `--amostra <file>`, which reruns the comparison on a saved sample with no network access. On a saved sample, `--rotulos <csv>` checks the result against hand-labelled pairs, and `--etapa3` asks the project's LLM to confirm each provisional pauta (one call per pauta, repeated with `--repeticoes N`) and writes `data/agrupamento/etapa3_<timestamp>.csv`. Before using `--etapa3`, make sure the LLM server is up and that no pipeline run is in progress or about to start, since both would compete for the model.
- `scripts/testar_episodio.py` rebuilds the final pautas of a saved sample (stages 1 to 3) and calls `Summarizer.process` for up to 4 multi-source pautas plus one single-source pauta as a control. It writes each episode and a `relatorio_<timestamp>.json` (rewritten after every episode) to `data/agrupamento/episodios/`, prints memory, swap and temperatures before every LLM call and stops if available memory drops below `--min-memoria` GiB. On the local model it takes about 15 minutes when no episode needs the revision call (about 2 minutes per call). The script's own output goes to stdout only: redirect it to a file under `data/`, not `/tmp`. Same precautions as `--etapa3`.
- Tests cover the pure functions in `processing/agrupamento.py`, the JSON parsing and the options each call sends in `ai/llm.py`, the input budget and the `process` flow in `ai/summarizer.py`, and the source rule in `ai/qa.py` (all through fake clients; no test calls an LLM). There is no linter and no formatter configured. `requirements.txt` is empty and gitignored; dependencies live in `pyproject.toml`.
- **Running the pipeline has real side effects and there is no dry-run mode**: it calls the LLM, sends messages and audio to the configured Telegram chat, and marks URLs as seen in `data/digest.db`. Do not run it just to check a change; exercise the individual function instead (e.g. `collect_rss()`, `extract_full_text(url)`, `qa.problemas(result)`).
- Always enter through `techdigest.main` (the console script or `python -m techdigest`). `python -m techdigest.pipeline` skips `setup_logging()`, so nothing reaches the log file.
- System requirements outside pip: `ffmpeg`/`ffprobe` on PATH (audio concat and duration), network access for Edge-TTS, and an Ollama server at `OLLAMA_HOST` when `LLM_PROVIDER=ollama`.

## Configuration

- All settings are fields of `Settings` in `src/techdigest/config.py` (pydantic-settings), read from `.env` at the repo root. The env var name is the field name in upper case (`max_news` → `MAX_NEWS`).
- Reading `.env` is denied in `.claude/settings.json`. Use `config.py` as the reference for which keys exist and their defaults, and ask the user for actual values. The feed list in particular comes from `RSS_FEEDS` (comma-separated) in `.env`; the defaults in code are not what runs in practice.
- Every module creates its own `settings = Settings()` at import time, and `ai/qa.py` copies the `QA_*` limits into module constants at import. Settings therefore cannot be overridden in one place at runtime; an override has to be in the environment before the modules are imported.
- `LLM_PROVIDER=ollama` selects `OllamaProvider`; any other value selects `OpenAIProvider`, which covers every OpenAI-compatible endpoint (Groq, OpenRouter) through `OPENAI_BASE_URL`.

## Editorial rules

The rules below are the ones in force today. They are referred to by name, not by number: the comments in the code mention "regra 1", "regras 2, 3 e 6" and similar, but the numbered list is not in the repository and those numbers could not be matched to specific rules. Do not infer a number's meaning from the code; ask the owner.

**Verified by code.** An item that violates one of these is revised once and, if it still violates, is skipped (`ai/qa.py`):
- Summary with 7 to 10 sentences (`resumo_didatico`).
- Script with 240 to 480 words per character.
- Script with 600 to 1300 words in total.
- Every speaking character is declared in the cast, and every declared character speaks.
- Source text with at least 1200 characters, so headlines alone never become an episode (`pipeline.py`).
- Article published no more than 7 days ago (`MAX_IDADE_DIAS`).
- When an episode has two or more outlets as sources, every one of them appears in `fontes_citadas` (accent- and case-insensitive, one name may be contained in the other, compared by whole words). Single-source episodes are not affected, and the pipeline only produces single-source episodes today.

**Requested in the prompt only.** The model is instructed to follow these, but nothing checks them (`ai/prompt.py`):
- Use only information from the sources; do not invent data or quotes.
- Short, attention-grabbing title without sensationalism.
- 2 to 5 self-contained key points.
- "Why it matters" section with 1 to 3 sentences.
- At most 3 characters: Helena is fixed as the presenter, plus 1 or 2 analysts.
- Script with 14 to 24 turns and 50 to 90 words per turn.
- Helena opens, moderates and closes the episode.
- Written to be spoken: no markdown, URLs or lists.
- Cite outlets by name.
- Divergence rule: divergence means conflict between sources (figures that do not match, opposite readings, criticism or a warning); information that only one source carries is a complement. With a real divergence each analyst defends one side and `houve_divergencia` is true; without one, Helena and one analyst deepen the consensus. Inventing a divergence is treated as seriously as omitting a real one.
- With several sources, `resumo_didatico` carries the consensus, plus one sentence announcing the debate when there is a real divergence.

**Other editorial principles in the code:**
- "Boletim duplo": feeds are interleaved so `MAX_NEWS` is not consumed by the first feeds alone, since TechDigest and PulsoBR share each batch (`collectors/rss.py`).

## Architecture

`main.main()` sets up logging and calls `pipeline.run()`, which takes an exclusive `flock` on `data/techdigest.lock` (one run at a time) and then loops over the articles in `pipeline._executar()`:

1. `collectors/rss.collect_rss()` downloads each feed, filters by age (`MAX_IDADE_DIAS`) before applying `MAX_POR_FEED`, and **interleaves** the feeds so `MAX_NEWS` is not consumed by the first feeds only.
2. `storage/dedup.SeenStore` (SQLite table `seen`, keyed by SHA-256 of the URL) skips items already delivered.
3. `processing/extractor.extract_full_text()` fetches the article body with trafilatura. Google News links are first resolved to the publisher URL with `googlenewsdecoder`; trafilatura is never run against a google.com URL (it would return the cookie-consent page). Items with less than `MIN_TEXTO_CHARS` of text are discarded.
4. `ai/summarizer.Summarizer.process()` assembles the input within a size budget (see below), calls the provider with `PROMPT_SISTEMA`, runs the deterministic checks in `ai/qa.py`, and on failure makes **one** revision call with `PROMPT_REVISOR`. If the revision still fails it raises `QAReprovado`.
5. `audio/tts.gerar_podcast()` synthesizes one mp3 per dialogue turn, inserts silences with ffmpeg and concatenates into `data/audio/<slug>.mp3`.
6. `delivery.deliver_item()` sends the text and then the audio to Telegram, and only after that does the pipeline call `seen.mark_seen()`.

Invariants worth preserving:

- **Deliver first, mark seen after.** An interrupted run neither loses nor repeats a delivered item, and anything not delivered comes back on the next run. This includes QA rejections (retried next run) and the case where the text was sent but the audio upload failed (`AudioNaoEnviado`): the item is not marked seen, so the next run sends it again in full.
- **One bad item never kills the run.** Generation errors are caught per item and logged. Only `MAX_FALHAS_ENTREGA` consecutive delivery failures abort the run, by raising, which makes `main` exit with status 1 for systemd.
- **Time budget.** No new item starts after `MAX_RUNTIME_MIN`; the systemd unit kills the process at 4 hours.
- **The Telegram token must not reach the logs.** The token is part of the request URL and `requests` errors quote the URL, so `delivery/telegram._post` re-raises with `from None` and without the URL.

### The input budget

`summarizer.montar_entrada()` builds the message for the episode and keeps it inside a character limit, so the provider never has to truncate it:

- Headers, the editor's notice (`AVISO DO EDITOR-CHEFE`) and the reminder are never cut. The texts share what is left: each keeps its usual ceiling (5000 characters for the principal, 3000 for each of up to 2 related articles); if they do not fit, the principal gets about half and the related ones split the rest, unused share is passed on, and cuts fall at a paragraph end. A related article that would get less than 400 characters is dropped, and the notice only counts and names what was actually included.
- The limit comes from `Summarizer._limite_da_entrada()`. With Ollama it is `OLLAMA_NUM_CTX` minus the output reserve and a margin, converted to characters, minus the system prompt. The reserve is the smaller of `OLLAMA_NUM_PREDICT` and `LLM_RESERVA_SAIDA`, because `num_predict` may be larger than the window itself. With an OpenAI-compatible provider the limit is `LLM_MAX_PROMPT_CHARS`; if a message still exceeds it, `OpenAIProvider` cuts it and logs an error.
- Characters per token start at a conservative 3.0 and are then measured from `provider.ultimo_uso` after every call (90% of the lowest value seen).
- The revision call carries the original episode too, so its source text is rebuilt with what is left of the window and can be shorter than in the generation call.
- A single-source input that fits is byte-for-byte what it was before the budget existed.

### The LLM output contract

The episode is a JSON object with 8 keys (`titulo_reescrito`, `resumo_didatico`, `pontos_chave`, `por_que_importa`, `personagens`, `roteiro_podcast`, `houve_divergencia`, `fontes_citadas`). That shape is repeated in several places that must change together:

- `SCHEMA` / `REQUIRED_KEYS` in `ai/llm.py`. The schema is not sent to the provider (Ollama gets `format="json"`, OpenAI gets `json_object`); only the presence of the required keys is enforced, in `parse_json`.
- The prose in `ai/prompt.py` (both prompts) and the reminder appended in `Summarizer._montar_entrada`.
- The consumers: `ai/qa.py`, `audio/tts.py` and `_render_item` in `delivery/telegram.py`.

There is a second, much smaller contract: the grouping verdict (stage 3 of the news grouping, see "Unfinished or dormant code"). The model receives one provisional pauta, with its articles numbered from 1, and answers with a JSON object whose required keys are `tipos`, `grupos` and `isolados`:

```json
{"tipos": {"1": "fato_unico", "2": "fato_unico", "3": "varios_fatos"}, "grupos": [{"principal": 1, "membros": [{"id": 2, "relacao": "mesmo_acontecimento"}]}], "isolados": [3], "motivo": "one sentence"}
```

`tipos` classifies every article first: `varios_fatos` is a text that covers several unrelated events (agenda, weekly roundup, bulletin, live coverage) and can never be part of a group. `membros` lists the other articles of the group (never the principal), `relacao` is `mesmo_acontecimento` or `desdobramento`, and every number must appear exactly once between `grupos` and `isolados`. A missing or invalid type, id or relation discards the whole verdict and leaves every article on its own. From a valid verdict the code takes who stays together, the types and how the articles relate: an article typed `varios_fatos` is removed from its group even if the model grouped it, and the model's choice of `principal` is ignored. Its pieces must also change together:

- The prose in `PROMPT_AGRUPADOR` (`ai/prompt.py`).
- `CHAVES_AGRUPADOR`, `TIPOS`, `RELACOES`, `entrada_agrupador()` (the text the model receives), `problemas_do_veredito()` and `compor_pautas()` in `processing/agrupamento.py`.

`parse_json(text, chaves)` and `chat_json(system, user, chaves=, temperatura=, max_saida=)` take the required keys and the sampling options per call. With no extra arguments a call is the episode call: `REQUIRED_KEYS` and the values from `.env`. `num_ctx` is never set per call, because changing it makes Ollama reload the model.

The word and turn limits are duplicated too: `ai/qa.py` enforces the `QA_*` settings, while the same numbers (600-1300 total, 240-480 per character, 14-24 turns) are hard-coded in the prompt texts and the reminder. Changing `QA_*` in `.env` does not update the prompts.

The presenter name `Helena` is fixed by the prompt and mapped to a fixed voice in `tts.VOZ_FIXA`; the other characters get voices in declaration order.

### Logging and the log-summary script

`logging_setup.py` configures the `techdigest` logger once: console at `LOG_LEVEL`, plus `data/logs/techdigest.log` always at DEBUG (rotating, 2 MB x 7). Modules log through `logging.getLogger("techdigest.<module>")`.

`scripts/resumo_lotes.py` parses that file with regexes over the line format and over exact message texts (`=== TechDigest iniciando ===`, `Execução concluída: N notícia`, `Item pulado pelo QA`, `Item descartado`, `Falha ao entregar`, and the Ollama metrics line with `tok/s`, `RAM disp.=`, `CPU=`, `GPU=`). Rewording those messages or changing the format string breaks the script silently.

## Unfinished or dormant code

- **Related articles (divergence).** `Summarizer.process(principal, relacionados)`, both prompts, the input budget and the QA source rule support several sources for one story, but `pipeline.py` never passes `relacionados`, so every delivered episode is single-source and the divergence rule is never triggered. Multi-source generation is only exercised by `scripts/testar_episodio.py`.
- **News grouping, phases 1 to 3 of 4.** `processing/agrupamento.py` groups articles that tell the same story (the same event, or a direct follow-up of it within the collection window) into "pautas": stages 1 and 2 score every pair by title and text similarity and form provisional pautas of up to `AGRUP_MAX_ARTIGOS` articles (`AGRUP_LIMIAR`, provisionally 0.18, was calibrated on a single labelled sample); in stage 3 the LLM reads the first `AGRUP_CHARS_ETAPA3` characters of each article, confirms each provisional pauta, and `compor_pautas()` builds the final ones. In a final pauta the `principal` is the article with the longest extracted text and every other confirmed article is a `relacionado`, same outlet or not; the relation (`mesmo_acontecimento` or `desdobramento`) only guides the episode. Only `principal` and `relacionados` go to generation. `duplicatas` (republications, detected by text similarity in stages 1 and 2) are not generated but are delivered with the pauta, so `Pauta.links` includes them; `excedentes` (confirmed articles beyond the limit) are neither generated nor delivered, and are meant to come back as candidates in a later run. All of this, plus `extractor.extrair_em_lote()` and the `AGRUP_*` / `EXTRACAO_*` settings, is used only by `scripts/testar_agrupamento.py`: the pipeline does not group yet, and the call to the LLM for stage 3 lives in that script. Phase 3 added the multi-source generation described above (budget, prompts, QA rule). Still to come: the pipeline integration behind `AGRUPAMENTO_ATIVO`, with `mark_seen` per pauta (phase 4).
- **E-mail delivery.** `delivery/email_smtp.py` was never finished (it references a nonexistent `settings.recipients`, and `send_digest_email` does nothing). `delivery/__init__.py` raises `NotImplementedError` for any `DELIVERY_CHANNEL` other than `telegram`.

## Repo notes

- `data/` (SQLite db, audio, logs, lock file, grouping samples and CSVs) is runtime state and is gitignored.
- `src/techdigest.egg-info/` is committed, so reinstalling the package can produce diffs there.
- `selectolax` is pinned below 1.0 because `googlenewsdecoder` depends on a backend that 1.0 removed.