import datetime
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from techdigest.ai.elenco import nomes_dos_analistas
from techdigest.ai.llm import get_provider
from techdigest.ai.maquina import ExecucaoInterrompida, ProviderVigiado
from techdigest.ai.summarizer import QAReprovado, Summarizer
from techdigest.audio.tts import atribuir_vozes, gerar_podcast
from techdigest.collectors.rss import ColetaRSS, collect_rss
from techdigest.config import Settings
from techdigest.delivery import deliver_aviso, deliver_footer, deliver_item
from techdigest.processing import agrupamento as ag
from techdigest.processing import filtro
from techdigest.processing.extractor import extrair, extrair_em_lote
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


def _rotulo_do_feed(url: str) -> str:
    """O feed para uma mensagem curta: o endereço do site, e a busca quando é uma busca do Google Notícias."""
    partes = urlsplit(url)
    busca = parse_qs(partes.query).get("q")
    return f"{partes.netloc} ({busca[0]})" if busca else (partes.netloc or url)


def _coletar(registro: RegistroDaExecucao | None) -> list:
    """Coleta os feeds (com as novas tentativas de `collect_rss`), grava o que ficou de fora no registro e avisa.

    Com algum feed fora depois das tentativas: uma mensagem curta no canal (texto simples, sem URL com token, o mesmo
    caminho do aviso de parada) e a execução segue com os outros. Com todos fora: a execução para (status 1, aviso de
    parada), porque sem feed não há o que entregar e, com o timer, ninguém veria uma execução vazia com status 0.
    """
    coleta = ColetaRSS()
    artigos = collect_rss(coleta=coleta)
    _anotar(registro, "feeds_da_coleta", coleta)
    if coleta.total and len(coleta.fora) == coleta.total:
        raise ExecucaoInterrompida(
            f"todos os {coleta.total} feeds ficaram fora da coleta depois de {settings.feed_tentativas} tentativa(s) "
            "(a rede, provavelmente)")
    if coleta.fora:
        texto = (f"TechDigest às {_agora()}: {len(coleta.fora)} de {coleta.total} feed(s) ficaram fora da coleta depois de "
                 f"{settings.feed_tentativas} tentativa(s): {'; '.join(_rotulo_do_feed(f['url']) for f in coleta.fora)}. "
                 "A execução segue com os outros.")
        logger.warning("Aviso de feeds: %s", texto)
        try:
            deliver_aviso(texto)
        except Exception as e:
            logger.error("Aviso de feeds não enviado (%s: %s)", type(e).__name__, str(e)[:200])
    return artigos


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


@dataclass
class _Item:
    """O que vira um episódio: um artigo, com o agrupamento desligado, ou uma pauta, com ele ligado.

    `principal` e `relacionados` vão para o Summarizer e `artigos` para o registro (o principal primeiro). O texto
    entregue leva o link do principal (o do feed) e, numa pauta, o de cada relacionado (`outras_fontes`) e a lista das
    duplicatas e dos excedentes (`tambem`). Depois da entrega, os links de `vistos` são marcados de uma vez; na
    reprovação pelo QA, a conta vale para cada link de `reprovaveis` (o artigo, ou os artigos gerados e as duplicatas).
    """
    titulo: str
    url: str
    source: str
    principal: dict
    relacionados: list[dict] = field(default_factory=list)
    artigos: list[dict] = field(default_factory=list)
    outras_fontes: list[dict] = field(default_factory=list)
    tambem: list[dict] = field(default_factory=list)
    vistos: list[str] = field(default_factory=list)
    reprovaveis: list[tuple[str, str]] = field(default_factory=list)   # (link, título)
    outros: dict[str, list[dict]] = field(default_factory=dict)        # duplicatas e excedentes, para o registro


def _item_do_artigo(art, extracao) -> _Item:
    """Um artigo, com o agrupamento desligado: o episódio de uma fonte só, como sempre."""
    artigo = {"veiculo": art.source, "titulo": art.title, "url": art.url, "url_resolvida": extracao.url_resolvida,
              "texto": extracao.texto, "data": art.published, "feed": art.feed, "categorias": art.categorias}
    return _Item(art.title, art.url, art.source, {"source": art.source, "title": art.title, "text": extracao.texto, "data": art.published},
                 artigos=[artigo], vistos=[art.url], reprovaveis=[(art.url, art.title)])


def _item_da_pauta(pauta: ag.Pauta) -> _Item:
    """Uma pauta final do agrupamento: o principal e os relacionados vão para a geração; as duplicatas e os excedentes
    são listados no texto e marcados como vistos com ela (decisões de 16/10/2026)."""
    def artigo(c: ag.Candidato, relacao: str | None) -> dict:
        return {"veiculo": c.veiculo, "titulo": c.titulo, "url": c.url, "url_resolvida": c.url_veiculo, "texto": c.texto,
                "data": c.data, "feed": c.feed, "categorias": c.categorias, "relacao": relacao}

    def fonte(c: ag.Candidato) -> dict:
        relacao = pauta.relacoes.get(c)
        return {"source": c.veiculo, "title": c.titulo, "text": c.texto, "data": c.data, **({"relacao": relacao} if relacao else {})}

    p = pauta.principal
    fora = (*pauta.duplicatas, *pauta.excedentes)
    return _Item(
        p.titulo, p.url, p.veiculo, fonte(p), [fonte(c) for c in pauta.relacionados],
        artigos=[artigo(p, "principal"), *(artigo(c, pauta.relacoes.get(c)) for c in pauta.relacionados)],
        outras_fontes=[{"source": c.veiculo, "url": c.url} for c in pauta.relacionados],
        tambem=[{"source": c.veiculo, "titulo": c.titulo, "url": c.url} for c in fora],
        vistos=[c.url for c in (*pauta.artigos, *fora)],
        reprovaveis=[(c.url, c.titulo) for c in (*pauta.artigos, *pauta.duplicatas)],
        outros={"duplicatas": [artigo(c, None) for c in pauta.duplicatas], "excedentes": [artigo(c, None) for c in pauta.excedentes]},
    )


class _Lote:
    """O que os itens de uma execução compartilham: o banco, o registro, o Summarizer e a contagem das entregas."""

    def __init__(self, seen: SeenStore, registro: RegistroDaExecucao | None, summarizer, sem_audio: bool, andamento: _Andamento):
        self.seen, self.registro, self.summarizer, self.sem_audio, self.andamento = seen, registro, summarizer, sem_audio, andamento
        self.falhas_seguidas = 0

    def gerar_e_entregar(self, item: _Item) -> bool:
        """Gera o episódio do item, entrega e só então marca como visto. Devolve False quando as falhas de entrega
        seguidas chegam a MAX_FALHAS_ENTREGA e a execução tem de parar."""
        # 1) Gera o episódio. Guarda de resiliência nº 1: um item ruim é pulado com log e o digest sobrevive.
        inicio_do_item = time.monotonic()
        result = None
        try:
            self.summarizer.ultimo_diagnostico = {}
            if item.relacionados:
                logger.info("Pauta de %d textos (%s): %r", 1 + len(item.relacionados),
                            ", ".join(a["veiculo"] for a in item.artigos), item.titulo)
                result = self.summarizer.process(item.principal, item.relacionados)
            else:
                result = self.summarizer.process(item.principal)
            result["url"], result["source"] = item.url, item.source
            if item.outras_fontes:
                result["outras_fontes"] = item.outras_fontes
            if item.tambem:
                result["tambem_noticiaram"] = item.tambem
            # A voz de cada personagem (a Helena com a voz fixa, cada analista com a da vaga do nome dele): vai para
            # o log e para o episódio, para a simulação conferir.
            result["vozes"] = atribuir_vozes(result["personagens"])
            logger.info("Vozes: %s", "; ".join(f"{nome} → {voz}" for nome, voz in result["vozes"].items()))

            if self.sem_audio:
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
            logger.warning("Item pulado pelo QA: %r — %s ↳ %s", item.titulo, e, item.url)
            self._anotar_item(item, f"reprovado pelo QA ({e})", self.summarizer.ultimo_diagnostico.get("episodio"), inicio_do_item)
            self._contar_reprovacao(item)
            return True
        except Exception as e:
            logger.exception(  # .exception = nível ERROR + traceback COMPLETO (erro inesperado)
                "Item pulado: %r ↳ %s", item.titulo, item.url
            )
            self._anotar_item(item, f"falhou ({type(e).__name__}: {str(e)[:300]})",
                              result or self.summarizer.ultimo_diagnostico.get("episodio"), inicio_do_item)
            return True
        entrada = self._anotar_item(item, "aprovado", result, inicio_do_item)

        # 2) Entrega NA HORA e só então marca como visto. Se o processo for interrompido
        #    (timeout, reboot), o que já foi entregue não se perde nem se repete, e o
        #    que não foi entregue volta na próxima execução.
        try:
            deliver_item(result, path)
        except Exception:
            self.falhas_seguidas += 1
            logger.exception(
                "Falha ao entregar %r — fica para a próxima execução", result["titulo_reescrito"]
            )
            if self.falhas_seguidas >= settings.max_falhas_entrega:
                logger.error(
                    "%d falhas de entrega seguidas: encerrando a execução.", self.falhas_seguidas
                )
                return False
            return True
        self.falhas_seguidas = 0
        self.andamento.entregues += 1
        if entrada is not None:
            _anotar(self.registro, "entregue", entrada)
        try:
            self.seen.marcar_vistos(item.vistos)   # a pauta inteira de uma vez: os gerados, as duplicatas e os excedentes
        except Exception:
            logger.exception("Falha ao marcar como visto: %s", item.url)
        return True

    def _anotar_item(self, item: _Item, situacao: str, episodio, inicio: float):
        """Registra um item que passou pela geração: os artigos, o diagnóstico do Summarizer e o episódio, se houver."""
        if self.registro is None:
            return None
        try:
            diagnostico = self.summarizer.ultimo_diagnostico
            analise = diagnostico.get("lados")
            textos = [f"{a['title']}\n{a['text']}" for a in (item.principal, *item.relacionados)]
            nomes = nomes_dos_analistas(analise.lados, textos) if analise else None
        except Exception as e:
            logger.warning("Registro da execução: falha ao montar o item (%s: %s)", type(e).__name__, str(e)[:200])
            return None
        return _anotar(self.registro, "item", item.artigos, situacao, diagnostico, episodio, time.monotonic() - inicio,
                       nomes, (episodio or {}).get("vozes"), item.outros or None)

    def _contar_reprovacao(self, item: _Item) -> None:
        """Conta a reprovação de cada link do item; na MAX_REPROVACOES-ésima execução reprovada, o link é abandonado.

        Só `QAReprovado` conta (decisão de 16/10/2026): erro de rede ou do Ollama não. O item abandonado não entra em
        `seen`, que continua significando "entregue": a contagem fica na tabela `reprovacoes` (ver `SeenStore`).
        """
        for url, titulo in item.reprovaveis:
            try:
                vezes = self.seen.registrar_reprovacao(url)
            except Exception:
                logger.exception("Falha ao contar a reprovação: %s", url)
                continue
            if vezes >= settings.max_reprovacoes:
                logger.warning("Item abandonado (reprovado pelo QA em %d execuções): %r ↳ %s", vezes, titulo, url)
                _anotar(self.registro, "abandonado", url, titulo, f"reprovado pelo QA em {vezes} execuções")


def _sem_vaga(inicio: float, andamento: _Andamento) -> bool:
    """Se a execução para de começar itens: MAX_NEWS entregues ou o orçamento de tempo esgotado."""
    if andamento.entregues >= settings.max_news:
        return True
    if settings.max_runtime_min and time.monotonic() - inicio >= settings.max_runtime_min * 60:
        logger.warning(
            "Orçamento de tempo (%d min) esgotado: encerrando. "
            "O que sobrou fica para a próxima execução.", settings.max_runtime_min,
        )
        return True
    return False


def _etapa3_para_registro(provisoria: ag.Pauta, veredito: ag.Veredito) -> dict:
    """Uma pauta provisória e o que a etapa 3 fez dela, pelos links do feed."""
    resposta = veredito.resposta if isinstance(veredito.resposta, dict) else {}
    return {
        "artigos": [{"veiculo": c.veiculo, "titulo": c.titulo, "url": c.url} for c in provisoria.artigos],
        "duplicatas": [c.url for c in provisoria.duplicatas], "erro": veredito.erro, "motivo": resposta.get("motivo", ""),
        "finais": [{"principal": f.principal.url, "relacionados": [c.url for c in f.relacionados],
                    "excedentes": [c.url for c in f.excedentes], "duplicatas": [c.url for c in f.duplicatas]}
                   for f in veredito.finais],
    }


def _agrupar(candidatos: list[ag.Candidato], provider, registro) -> list[ag.Pauta]:
    """As etapas 1 a 3 sobre os candidatos da execução: as pautas finais.

    As etapas 1 e 2 formam as pautas provisórias, de até AGRUP_MAX_PROVISORIA artigos; a etapa 3 pede ao LLM o
    veredito de cada provisória de 2 artigos ou mais, e o que ele confirma além de AGRUP_MAX_ARTIGOS textos fica em
    excedentes. A chamada que falha, ou o veredito descartado, deixa os artigos separados.
    """
    if len(candidatos) < 2:
        return [ag.Pauta(principal=c) for c in candidatos]
    titulos = ag.comparar_titulos(candidatos, settings.agrup_chars_texto)
    textos = ag.comparar_textos(candidatos, settings.agrup_chars_texto)
    pares = ag.pontuar_pares(candidatos, titulos, textos, settings.agrup_peso_titulo, settings.agrup_limiar_duplicata)
    provisorias, _ = ag.formar_pautas(candidatos, pares, settings.agrup_limiar, settings.agrup_max_provisoria)
    finais, etapa3 = [], []
    for provisoria in provisorias:
        if not provisoria.relacionados:
            finais.append(provisoria)   # um artigo só, com as suas duplicatas, se houver
            continue
        veredito = ag.confirmar_pauta(provider.chat_json, provisoria, settings.agrup_chars_etapa3, settings.agrup_max_artigos)
        finais += veredito.finais
        etapa3.append(_etapa3_para_registro(provisoria, veredito))
        logger.info("Etapa 3: pauta provisória de %d artigos → %s%s", len(provisoria.artigos), "; ".join(
            f"{len(f.artigos)} texto(s)" + (f" + {len(f.excedentes)} excedente(s)" if f.excedentes else "")
            for f in veredito.finais), f" ({veredito.erro})" if veredito.erro else "")
    _anotar(registro, "agrupamento", etapa3)
    return finais


def _pautas_da_execucao(artigos: list, seen: SeenStore, registro, provider) -> list[_Item]:
    """Com o agrupamento ligado (ajuste 7 de 17/10/2026): as pautas da execução, na ordem das vagas de MAX_NEWS.

    Tira os já entregues, os abandonados e os filtrados pelo link e pela categoria do feed, extrai todos os candidatos
    em lote, aplica o filtro na URL resolvida, descarta os textos curtos e agrupa (ver `_agrupar`). Cada pauta ocupa a
    posição do primeiro dos seus artigos na lista intercalada da coleta (contando principal, relacionados, duplicatas e
    excedentes): o boletim duplo continua valendo, e uma pauta de vários feeds ocupa uma vaga só. Se o agrupamento
    falhar por um erro inesperado, os candidatos seguem um por um.
    """
    posicao: dict[str, int] = {}
    novos = []
    for art in artigos:
        if art.url in posicao or not seen.is_new(art.url):
            continue
        posicao[art.url] = len(posicao)
        if seen.reprovacoes(art.url) >= settings.max_reprovacoes:
            logger.debug("Item já abandonado (reprovado pelo QA em %d execuções): %s", settings.max_reprovacoes, art.url)
            continue
        if motivo := filtro.motivo_do_filtro(art.url, art.categorias):
            logger.info("Item filtrado (%s): %r ↳ %s", motivo, art.title, art.url)
            _anotar(registro, "filtrado", art.url, art.title, motivo, False)
            continue
        novos.append(art)

    logger.info("Agrupamento: extraindo %d candidato(s) em lote", len(novos))
    candidatos = []
    for art, extracao in zip(novos, extrair_em_lote([(a.url, a.summary) for a in novos])):
        if extracao.url_resolvida != art.url and (motivo := filtro.pela_url(extracao.url_resolvida)):
            logger.info("Item filtrado (%s, depois da extração): %r ↳ %s", motivo, art.title, extracao.url_resolvida)
            _anotar(registro, "filtrado", art.url, art.title, motivo, True, extracao.url_resolvida)
            continue
        if len(extracao.texto) < settings.min_texto_chars:
            logger.info(
                "Item descartado (texto insuficiente: %d caracteres, mínimo %d): %r",
                len(extracao.texto), settings.min_texto_chars, art.title,
            )
            continue
        titulo, veiculo = ag.separar_veiculo(art.title, art.source)
        candidatos.append(ag.Candidato(
            titulo=titulo, veiculo=veiculo, url=art.url, url_veiculo=extracao.url_resolvida or art.url,
            texto=extracao.texto, data=art.published, feed=art.feed, categorias=art.categorias,
        ))

    try:
        pautas = _agrupar(candidatos, provider, registro)
    except Exception as e:   # a trava da máquina (ExecucaoInterrompida, um SystemExit) passa e para a execução
        logger.exception("Agrupamento falhou: os %d candidato(s) seguem um por um", len(candidatos))
        _anotar(registro, "falha_do_agrupamento", f"{type(e).__name__}: {str(e)[:300]}; os {len(candidatos)} candidato(s) "
                                                   f"seguiram um por um")
        pautas = [ag.Pauta(principal=c) for c in candidatos]
    pautas.sort(key=lambda p: min(posicao[c.url] for c in (*p.artigos, *p.duplicatas, *p.excedentes)))
    logger.info("Agrupamento: %d candidato(s) em %d pauta(s), %d com várias fontes", len(candidatos), len(pautas),
                sum(1 for p in pautas if p.relacionados))
    return [_item_da_pauta(p) for p in pautas]


def _executar(sem_audio: bool, andamento: _Andamento):
    inicio = time.monotonic()
    Path(settings.audio_dir).mkdir(parents=True, exist_ok=True)
    seen = SeenStore(settings.db_path)
    logger.info("=== TechDigest iniciando ===")
    registro = _abrir_registro()
    abortada = False

    try:
        # As travas da máquina (ai/maquina.py): a GPU antes de carregar o modelo, ainda antes da coleta,
        # e, a cada chamada, memória, temperatura e o Ollama. Uma trava que dispara levanta
        # ExecucaoInterrompida, que herda de SystemExit: nenhum except Exception abaixo a pega.
        provider = ProviderVigiado(get_provider(settings), log_ollama=settings.ollama_log)
        provider.conferir_antes_de_carregar()
        lote = _Lote(seen, registro, Summarizer(provider=provider), sem_audio, andamento)

        if settings.agrupamento_ativo:
            for item in _pautas_da_execucao(_coletar(registro), seen, registro, provider):
                if _sem_vaga(inicio, andamento):
                    break
                if not lote.gerar_e_entregar(item):
                    abortada = True
                    break
        else:
            tentadas: set[str] = set()  # URLs já tentadas nesta execução (não repete o mesmo item)
            for art in _coletar(registro):
                if _sem_vaga(inicio, andamento):
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
                try:
                    extracao = extrair(art.url, fallback=art.summary)
                except Exception:
                    logger.exception("Item pulado: %r ↳ %s", art.title, art.url)
                    continue
                if extracao.url_resolvida != art.url and (motivo := filtro.pela_url(extracao.url_resolvida)):
                    logger.info("Item filtrado (%s, depois da extração): %r ↳ %s", motivo, art.title, extracao.url_resolvida)
                    _anotar(registro, "filtrado", art.url, art.title, motivo, True, extracao.url_resolvida)
                    continue
                if len(extracao.texto) < settings.min_texto_chars:
                    logger.info(
                        "Item descartado (texto insuficiente: %d caracteres, mínimo %d): %r",
                        len(extracao.texto), settings.min_texto_chars, art.title,
                    )
                    continue
                if not lote.gerar_e_entregar(_item_do_artigo(art, extracao)):
                    abortada = True
                    break
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
