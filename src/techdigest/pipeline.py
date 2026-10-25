import datetime
import re
import time
from pathlib import Path

from techdigest.ai.elenco import nomes_dos_analistas
from techdigest.ai.llm import get_provider
from techdigest.ai.maquina import ExecucaoInterrompida, ProviderVigiado
from techdigest.ai.summarizer import QAReprovado, Summarizer
from techdigest.audio.tts import atribuir_vozes, gerar_podcast
from techdigest.collectors.rss import collect_rss
from techdigest.config import Settings
from techdigest.delivery import deliver_aviso, deliver_footer, deliver_item
from techdigest.processing import filtro
from techdigest.processing.extractor import extrair
from techdigest.registro import RegistroDaExecucao, limpar_antigas
from techdigest.storage.dedup import SeenStore
from techdigest.trava import TravaOcupada, trava_do_modelo
import logging

logger = logging.getLogger("techdigest.pipeline")
settings = Settings()


class FalhasDeEntregaSeguidas(RuntimeError):
    """MAX_FALHAS_ENTREGA entregas seguidas falharam: o canal está fora do ar, e a execução para."""


class _Andamento:
    """O que a execução já fez, para o aviso de parada dizer quantos itens saíram."""
    entregues = 0


def run(sem_audio: bool = False):
    """Uma execução, com a trava do modelo (ver `trava.py`): UMA por vez em tudo o que chama o modelo.

    Duas execuções simultâneas poderiam processar e entregar a mesma notícia (o mark_seen só vem
    após a entrega), disputar o Ollama e sobrescrever os mesmos mp3. Com a trava ocupada, registra
    quem a tem e levanta TravaOcupada; uma trava da máquina que dispara levanta ExecucaoInterrompida
    (ver `ai/maquina.py`). Nos dois casos o motivo já está no log, e `main` sai com status 1.
    `sem_audio` só vem da simulação (`techdigest --simular --sem-audio`).

    Quando a execução não começa, para numa trava da máquina ou termina com um erro inesperado, o
    processo avisa antes de sair (ajuste 8 e decisão do dono de 25/10/2026; ver `_avisar`): pelo
    Telegram, em produção, e no `AVISO.txt` da pasta, na simulação. O `OnFailure=` da futura unit
    fica só com o que o processo não consegue avisar (OOM, tempo esgotado, sinal).
    """
    andamento = _Andamento()
    try:
        with trava_do_modelo():
            _executar(sem_audio, andamento)
    except TravaOcupada as e:
        logger.error("Execução não começou: %s", e)
        _avisar(f"TechDigest não começou às {_agora()}: {e}.")
        raise
    except ExecucaoInterrompida as e:   # o "Execução interrompida" já está no log, com o motivo
        _avisar(f"TechDigest parou às {_agora()}: {e}. Entregues: {_entregues(andamento)}; o resto volta na próxima execução.")
        raise
    except Exception as e:              # o traceback vai para o log pelo `main` ("Falha fatal no pipeline")
        _avisar(f"TechDigest parou às {_agora()} por um erro inesperado ({type(e).__name__}). "
                f"Entregues: {_entregues(andamento)}; o resto volta na próxima execução. O detalhe está no log.")
        raise


def _agora() -> str:
    return f"{datetime.datetime.now():%H:%M}"


def _entregues(andamento: _Andamento) -> str:
    return f"{andamento.entregues} de {settings.max_news}"


def _avisar(texto: str) -> None:
    """O aviso de parada: uma linha de texto fixo no log (o `resumo_lotes.py` a mostra) e a mensagem no canal.

    Se o próprio aviso falhar, fica o log e o status 1. A mensagem não leva URL nem token: no Telegram ela
    passa pelo mesmo `_post` que já esconde o token dos erros.
    """
    logger.warning("Aviso de parada: %s", texto)
    try:
        deliver_aviso(texto)
    except Exception as e:
        logger.error("Aviso de parada não enviado (%s: %s)", type(e).__name__, str(e)[:200])


def _abrir_registro() -> RegistroDaExecucao | None:
    """O registro desta execução (ver `registro.py`), depois de apagar os de mais de EXECUCOES_DIAS dias. Uma falha
    aqui não impede a execução: ela segue sem registro, com o aviso no log."""
    try:
        for pasta in limpar_antigas(settings.execucoes_dir, settings.execucoes_dias):
            logger.info("Registro de execução apagado (mais de %d dias): %s", settings.execucoes_dias, pasta.name)
        registro = RegistroDaExecucao(settings.execucoes_dir, num_ctx=settings.ollama_num_ctx)
    except Exception as e:
        logger.warning("Execução sem registro (%s: %s)", type(e).__name__, str(e)[:200])
        return None
    logger.info("Registro da execução: %s", registro.pasta)
    return registro


def _anotar(registro: RegistroDaExecucao | None, metodo: str, *args, **kwargs):
    """Chama um método do registro; uma falha ao gravar fica no log e nunca derruba a execução."""
    if registro is None:
        return None
    try:
        return getattr(registro, metodo)(*args, **kwargs)
    except Exception as e:
        logger.warning("Registro da execução: falha ao gravar (%s: %s)", type(e).__name__, str(e)[:200])
        return None


def _anotar_item(registro, art, extracao, principal: dict, situacao: str, summarizer, episodio, inicio: float):
    """Registra um item que passou pela geração: o artigo, o diagnóstico do Summarizer e o episódio, se houver."""
    if registro is None:
        return None
    try:
        diagnostico = summarizer.ultimo_diagnostico
        analise = diagnostico.get("lados")
        nomes = nomes_dos_analistas(analise.lados, [f"{principal['title']}\n{principal['text']}"]) if analise else None
        artigo = {"veiculo": art.source, "titulo": art.title, "url": art.url, "url_resolvida": extracao.url_resolvida,
                  "texto": principal["text"], "data": art.published, "feed": art.feed, "categorias": art.categorias}
    except Exception as e:
        logger.warning("Registro da execução: falha ao montar o item (%s: %s)", type(e).__name__, str(e)[:200])
        return None
    return _anotar(registro, "item", [artigo], situacao, diagnostico, episodio, time.monotonic() - inicio, nomes,
                   (episodio or {}).get("vozes"))


def _contar_reprovacao(seen: SeenStore, registro, art) -> None:
    """Conta a reprovação do item pelo QA; na MAX_REPROVACOES-ésima execução reprovada, o item é abandonado.

    Só `QAReprovado` conta (decisão de 16/10/2026): erro de rede ou do Ollama não. O item abandonado não entra em `seen`,
    que continua significando "entregue": a contagem fica na tabela `reprovacoes` (ver `SeenStore`).
    """
    try:
        vezes = seen.registrar_reprovacao(art.url)
    except Exception:
        logger.exception("Falha ao contar a reprovação: %s", art.url)
        return
    if vezes >= settings.max_reprovacoes:
        logger.warning("Item abandonado (reprovado pelo QA em %d execuções): %r ↳ %s", vezes, art.title, art.url)
        _anotar(registro, "abandonado", art.url, art.title, f"reprovado pelo QA em {vezes} execuções")


def _executar(sem_audio: bool, andamento: _Andamento):
    inicio = time.monotonic()
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    seen = SeenStore(settings.db_path)
    logger.info("=== TechDigest iniciando ===")
    registro = _abrir_registro()
    falhas_seguidas = 0
    abortada = False
    tentadas: set[str] = set()  # URLs já tentadas nesta execução (não repete o mesmo item)

    try:
        # As travas da máquina (ai/maquina.py): a GPU antes de carregar o modelo, ainda antes da coleta,
        # e, a cada chamada, memória, temperatura e o Ollama. Uma trava que dispara levanta
        # ExecucaoInterrompida, que herda de SystemExit: nenhum except Exception abaixo a pega.
        provider = ProviderVigiado(get_provider(settings), log_ollama=settings.ollama_log)
        provider.conferir_antes_de_carregar()
        summarizer = Summarizer(provider=provider)

        for art in collect_rss():
            if andamento.entregues >= settings.max_news:
                break
            if settings.max_runtime_min and time.monotonic() - inicio >= settings.max_runtime_min * 60:
                logger.warning(
                    "Orçamento de tempo (%d min) esgotado: encerrando. "
                    "O que sobrou fica para a próxima execução.", settings.max_runtime_min,
                )
                break
            if art.url in tentadas or not seen.is_new(art.url):
                continue
            tentadas.add(art.url)
            if seen.reprovacoes(art.url) >= settings.max_reprovacoes:
                logger.debug("Item já abandonado (reprovado pelo QA em %d execuções): %s", settings.max_reprovacoes, art.url)
                continue
            # O filtro de esporte, ofertas e sites de partido (processing/filtro.py): antes da extração, pelo link do
            # feed e pela categoria; depois dela, pela URL resolvida (o link do Google Notícias não mostra o site).
            if motivo := filtro.motivo_do_filtro(art.url, art.categorias):
                logger.info("Item filtrado (%s): %r ↳ %s", motivo, art.title, art.url)
                _anotar(registro, "filtrado", art.url, art.title, motivo, False)
                continue

            # 1) Gera o episódio. Guarda de resiliência nº 1: um item ruim é pulado com log
            #    e o digest sobrevive.
            inicio_do_item = time.monotonic()
            extracao = principal = result = None
            try:
                extracao = extrair(art.url, fallback=art.summary)
                if extracao.url_resolvida != art.url and (motivo := filtro.pela_url(extracao.url_resolvida)):
                    logger.info("Item filtrado (%s, depois da extração): %r ↳ %s", motivo, art.title, extracao.url_resolvida)
                    _anotar(registro, "filtrado", art.url, art.title, motivo, True, extracao.url_resolvida)
                    continue
                text = extracao.texto
                if len(text) < settings.min_texto_chars:
                    logger.info(
                        "Item descartado (texto insuficiente: %d caracteres, mínimo %d): %r",
                        len(text), settings.min_texto_chars, art.title,
                    )
                    continue

                principal = {"source": art.source, "title": art.title, "text": text}
                summarizer.ultimo_diagnostico = {}
                result = summarizer.process(principal)
                result["url"], result["source"] = art.url, art.source
                # A voz de cada personagem (a Helena com a voz fixa, cada analista com a da vaga do nome dele): vai para
                # o log e para o episódio, para a simulação conferir.
                result["vozes"] = atribuir_vozes(result["personagens"])
                logger.info("Vozes: %s", "; ".join(f"{nome} → {voz}" for nome, voz in result["vozes"].items()))

                if sem_audio:
                    path = None
                    logger.info("✅ %s — episódio sem áudio (simulação)", result["titulo_reescrito"])
                else:
                    slug = re.sub(r"\W+", "-", result["titulo_reescrito"].lower())[:50]
                    path, dur_s = gerar_podcast(
                        result["roteiro_podcast"], result["personagens"],
                        f"{settings.audio_dir}/{slug}.mp3",
                    )
                    logger.info(
                        "✅ %s — episódio: %.1f min", result["titulo_reescrito"], dur_s / 60
                    )
            except QAReprovado as e:
                # Rejeição editorial esperada (regras 2, 3 e 6): WARNING sem traceback.
                # O item não é marcado como visto e volta a ser tentado no próximo lote, até o limite de tentativas.
                logger.warning("Item pulado pelo QA: %r — %s ↳ %s", art.title, e, art.url)
                _anotar_item(registro, art, extracao, principal, f"reprovado pelo QA ({e})", summarizer,
                             summarizer.ultimo_diagnostico.get("episodio"), inicio_do_item)
                _contar_reprovacao(seen, registro, art)
                continue
            except Exception as e:
                logger.exception(  # .exception = nível ERROR + traceback COMPLETO (erro inesperado)
                    "Item pulado: %r ↳ %s", art.title, art.url
                )
                if principal is not None:   # chegou à geração: fica no registro, com o que houver
                    _anotar_item(registro, art, extracao, principal, f"falhou ({type(e).__name__}: {str(e)[:300]})",
                                 summarizer, result or summarizer.ultimo_diagnostico.get("episodio"), inicio_do_item)
                continue
            entrada = _anotar_item(registro, art, extracao, principal, "aprovado", summarizer, result, inicio_do_item)

            # 2) Entrega NA HORA e só então marca como visto. Se o processo for interrompido
            #    (timeout, reboot), o que já foi entregue não se perde nem se repete, e o
            #    que não foi entregue volta na próxima execução.
            try:
                deliver_item(result, path)
            except Exception:
                falhas_seguidas += 1
                logger.exception(
                    "Falha ao entregar %r — fica para a próxima execução", result["titulo_reescrito"]
                )
                if falhas_seguidas >= settings.max_falhas_entrega:
                    logger.error(
                        "%d falhas de entrega seguidas: encerrando a execução.", falhas_seguidas
                    )
                    abortada = True
                    break
                continue
            falhas_seguidas = 0
            andamento.entregues += 1
            if entrada is not None:
                _anotar(registro, "entregue", entrada)
            try:
                seen.mark_seen(art.url)
            except Exception:
                logger.exception("Falha ao marcar como visto: %s", art.url)
    except ExecucaoInterrompida as e:
        logger.error("Execução interrompida: %s (%d notícia(s) entregue(s) antes; o que não foi entregue "
                     "fica para a próxima execução).", e, andamento.entregues)
        raise

    minutos = (time.monotonic() - inicio) / 60
    if abortada:
        raise FalhasDeEntregaSeguidas(
            f"Execução encerrada por falhas de entrega seguidas ({andamento.entregues} entregue(s) antes)."
        )
    if andamento.entregues:
        try:
            deliver_footer(andamento.entregues)
        except Exception:
            logger.warning("Não foi possível enviar o fechamento do digest.", exc_info=True)
        logger.info("Execução concluída: %d notícia(s) entregue(s) em %.0f min.", andamento.entregues, minutos)
    else:
        logger.warning("Nenhuma notícia entregue nesta execução (%.0f min).", minutos)


if __name__ == "__main__":
    run()
