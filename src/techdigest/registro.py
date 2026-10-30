"""O registro de cada execução do pipeline (item 6 da fase 4): os textos usados e os episódios, para o diagnóstico.

Cada execução grava, em `EXECUCOES_DIR/<data-hora>/`, o mesmo formato que `scripts/testar_episodio.py` grava e que
`scripts/checar_fidelidade.py` e `scripts/refazer_qa.py` já leem:

- `amostra.json`: as notícias que chegaram à geração, cada uma com um id a partir de 1, o veículo, o título, o link do
  feed, a URL resolvida, a data, o feed, as categorias e o texto extraído inteiro;
- `relatorio_<data-hora>.json`: por item, os artigos (pelo id da amostra), a situação (aprovado, reprovado pelo QA ou
  falhou), a análise de lados, o que entrou de cada texto na geração e na correção, o orçamento de palavras, os
  problemas do QA, a correção usada, os nomes que o bloco deu aos analistas, a voz de cada personagem, se foi entregue e
  o arquivo do episódio; e, à parte, os itens que o filtro tirou e os abandonados pelo limite de tentativas;
- um JSON por episódio, aprovado ou não (do reprovado, a última versão inteira, com a correção já aplicada).

O relatório é reescrito depois de cada item: se a execução parar no meio, fica o que já foi feito. Uma falha ao gravar
nunca derruba a execução (o pipeline registra o erro no log e segue). As pastas com mais de `EXECUCOES_DIAS` dias saem
no começo de cada execução.

As funções que montam as partes do relatório (`lados_para_registro`, `cortes_para_registro`, `orcamento_para_registro`)
são as mesmas que o `testar_episodio.py` usa.
"""
import datetime
import json
import re
import shutil
from pathlib import Path

from techdigest.ai.lados import lados_finos
from techdigest.ai.summarizer import TETO_PRINCIPAL, TETO_RELACIONADO

FORMATO_DA_PASTA = "%Y%m%d-%H%M%S"
_NOME_DA_PASTA = re.compile(r"\d{8}-\d{6}(?:-\d+)?")


def lados_para_registro(analise, chamadas: list[dict] | None = None) -> dict:
    """A análise de lados como vai para o relatório.

    `chamadas` são as chamadas medidas do item (as do `ProviderMonitorado` do testar_episodio.py), de onde saem as
    tentativas, o tempo e os tokens da análise; sem elas (no pipeline), as tentativas saem da própria análise.
    """
    feitas = [ch for ch in chamadas or [] if ch["prompt"] == "lados"]
    tentativas = len(feitas) if chamadas is not None else 1 + (analise.primeira is not None or analise.segunda is not None)
    return {
        "quantos": len(analise.lados), "questao": analise.questao, "motivo": analise.motivo,
        "tentativas": tentativas, "lado_de_emergencia": bool(analise.problemas), "invalida_porque": analise.problemas,
        "ajustes": analise.ajustes, "atores_sem_entrada": analise.faltam, "textos_cortados_na_analise": analise.cortes,
        "sem_sim_e_nao": analise.sem_sim_e_nao, "veiculos_de_contexto": analise.contexto,
        "atores_recusados": [{"ator": r.ator, "trecho": r.trecho, "motivo": r.motivo} for r in analise.recusados],
        "ressalvas": [{"grupos": list(r.grupos), "posicao": r.posicao, "veiculos": list(r.veiculos), "trecho": r.trecho}
                      for r in analise.ressalvas],
        "ressalvas_descartadas": [{"grupos": list(r.grupos), "posicao": r.posicao, "veiculos": list(r.veiculos), "trecho": r.trecho,
                                   "motivo": motivo} for r, motivo in analise.descartadas],
        "lados": [{"resposta": lado.resposta, "posicao": lado.posicao, "atores": list(lado.atores), "veiculos": list(lado.veiculos),
                   "trechos": list(lado.trechos), "frases_com_os_atores": lado.mencoes, "fino": fino}
                  for lado, fino in zip(analise.lados, lados_finos(analise.lados))],
        "respostas_por_ator": [{"ator": e.ator, "resposta": e.resposta, "trecho": e.trecho, "veiculo": e.veiculo,
                                "comprovada": e.comprovada, "prova": e.prova, "trecho_do_llm": e.trecho_do_llm,
                                "diferencas": e.diferencas}
                               for e in analise.respostas],
        "resposta_do_llm": analise.resposta,
        "primeira_tentativa": None if analise.primeira is None else {
            "invalida_porque": analise.primeira.problemas, "atores_sem_entrada": analise.primeira.faltam,
            "atores_recusados": [{"ator": r.ator, "trecho": r.trecho, "motivo": r.motivo} for r in analise.primeira.recusados],
            "sem_sim_e_nao": analise.primeira.sem_sim_e_nao, "resposta_do_llm": analise.primeira.resposta,
        },
        "segunda_tentativa_recusada": None if analise.segunda is None else {
            "invalida_porque": analise.segunda.problemas, "sem_sim_e_nao": analise.segunda.sem_sim_e_nao,
            "lados": len(analise.segunda.lados), "resposta_do_llm": analise.segunda.resposta,
        },
        "segundos": round(sum(ch.get("segundos", 0.0) for ch in feitas), 1),
        "segundos_por_tentativa": [round(ch.get("segundos", 0.0), 1) for ch in feitas],
        "tokens_entrada": [ch.get("tokens_entrada") for ch in feitas], "tokens_saida": [ch.get("tokens_saida") for ch in feitas],
    }


def cortes_para_registro(entrada) -> list[dict]:
    """Por artigo da pauta: quanto do texto entrou na mensagem, se a janela (e não o teto) o cortou, que parágrafos
    entraram, por quê, e os que ficaram de fora tendo trecho de evidência."""
    recortes = dict(enumerate(entrada.recortes))   # na mesma ordem dos cortes, só os que a análise leu
    pela_janela = {c["indice"] for c in getattr(entrada, "pela_janela", [])}
    return [
        {**corte, "teto": TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO, "cortado_pela_janela": i in pela_janela,
         "cortado_pelo_orcamento": max(min(corte["texto"], TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) - corte["incluido"], 0),
         "paragrafos_do_texto": recortes.get(i, {}).get("paragrafos"),
         "paragrafos_que_entraram": recortes.get(i, {}).get("entraram", []),
         "paragrafos_com_trecho_fora": recortes.get(i, {}).get("fora", [])}
        for i, corte in enumerate(entrada.cortes)
    ]


def orcamento_para_registro(orc) -> dict:
    """O orçamento de palavras da pauta, com o plano das falas (o `refazer_qa.py` o reconstrói daqui)."""
    return {"helena": orc.helena, "analistas": list(orc.analistas), "total": orc.total,
            "palavras_do_texto": orc.palavras_do_texto, "reduzido": orc.reduzido,
            "turnos": orc.turnos, "falas": list(orc.plano.falas),
            "tamanhos": list(orc.plano.tamanhos), "ordem": list(orc.plano.ordem)}


def limpar_antigas(base: str | Path, dias: int, agora: datetime.datetime | None = None) -> list[Path]:
    """Apaga as pastas de execução com mais de `dias` dias e devolve as que apagou (dias 0 = guarda todas).

    Só conta uma pasta cujo nome é uma data-hora no formato do registro (com o sufixo "-2", "-3"... de duas execuções no
    mesmo segundo): nada mais em `base` é tocado.
    """
    base = Path(base)
    if dias <= 0 or not base.is_dir():
        return []
    limite = (agora or datetime.datetime.now()) - datetime.timedelta(days=dias)
    apagadas = []
    for pasta in sorted(base.iterdir()):
        if not _NOME_DA_PASTA.fullmatch(pasta.name):
            continue
        try:
            criada = datetime.datetime.strptime(pasta.name[:15], FORMATO_DA_PASTA)
        except ValueError:
            continue
        if pasta.is_dir() and criada < limite:
            shutil.rmtree(pasta)
            apagadas.append(pasta)
    return apagadas


class RegistroDaExecucao:
    """O registro de uma execução, numa pasta nova `<base>/<data-hora>/` (ver o começo do módulo)."""

    def __init__(self, base: str | Path, num_ctx: int | None = None, agora: datetime.datetime | None = None):
        carimbo = (agora or datetime.datetime.now()).strftime(FORMATO_DA_PASTA)
        Path(base).mkdir(parents=True, exist_ok=True)
        self.carimbo, n = carimbo, 1
        while True:   # duas execuções no mesmo segundo: a segunda ganha "-2"
            try:
                (Path(base) / self.carimbo).mkdir()
                break
            except FileExistsError:
                n += 1
                self.carimbo = f"{carimbo}-{n}"
        self.pasta = Path(base) / self.carimbo
        self.amostra = self.pasta / "amostra.json"
        self.relatorio = self.pasta / f"relatorio_{self.carimbo}.json"
        self.num_ctx = num_ctx
        self.candidatos: list[dict] = []
        self.episodios: list[dict] = []
        self.filtrados: list[dict] = []
        self.abandonados: list[dict] = []
        self.etapa3: list[dict] | None = None   # com o agrupamento ligado: o veredito de cada pauta provisória
        self.agrupamento_falhou = ""             # com o agrupamento ligado: o erro que deixou os candidatos um por um
        self.gravar()

    def filtrado(self, url: str, titulo: str, motivo: str, depois_da_extracao: bool, url_resolvida: str = "") -> None:
        """Um item que o filtro tirou da execução."""
        self.filtrados.append({"url": url, "url_resolvida": url_resolvida, "titulo": titulo, "motivo": motivo,
                               "depois_da_extracao": depois_da_extracao})
        self.gravar()

    def agrupamento(self, etapa3: list[dict]) -> None:
        """As pautas provisórias de 2 artigos ou mais e o que a etapa 3 fez de cada uma (com o agrupamento ligado)."""
        self.etapa3 = etapa3
        self.gravar()

    def falha_do_agrupamento(self, motivo: str) -> None:
        """O agrupamento falhou por um erro inesperado e os candidatos seguiram um por um (leitura 7 de 29/10/2026)."""
        self.agrupamento_falhou = motivo
        self.gravar()

    def abandonado(self, url: str, titulo: str, motivo: str) -> None:
        """Um item que chegou ao limite de tentativas nesta execução."""
        self.abandonados.append({"url": url, "titulo": titulo, "motivo": motivo})
        self.gravar()

    def item(self, artigos: list[dict], situacao: str, diagnostico: dict, episodio: dict | None, segundos: float,
             nomes_do_bloco: list[str] | None = None, vozes: dict[str, str] | None = None,
             outros: dict[str, list[dict]] | None = None) -> dict:
        """Registra um item que passou pela geração e devolve a entrada dele no relatório (para `entregue`).

        Cada artigo é um dict com "veiculo", "titulo", "url", "url_resolvida", "texto" e, se houver, "data" (com fuso),
        "feed", "categorias" e "relacao". `diagnostico` é o `Summarizer.ultimo_diagnostico` do item. `outros` são os
        artigos da pauta que não foram gerados ({"duplicatas": [...], "excedentes": [...]}, com veículo, título e link).
        """
        ids = []
        for artigo in artigos:
            self.candidatos.append({
                "id": len(self.candidatos) + 1, "veiculo": artigo["veiculo"], "titulo": artigo["titulo"],
                "url": artigo["url"], "url_resolvida": artigo.get("url_resolvida") or artigo["url"],
                "data": artigo["data"].isoformat() if artigo.get("data") else None, "feed": artigo.get("feed", ""),
                "categorias": list(artigo.get("categorias") or ()), "texto": artigo["texto"],
            })
            ids.append(len(self.candidatos))
        n = len(self.episodios) + 1
        entrada = {
            "episodio": n, "caso": "fonte_unica" if len(artigos) == 1 else "pauta",
            "artigos": [{"id": i, "veiculo": a["veiculo"], "titulo": a["titulo"], "caracteres": len(a["texto"]),
                         "relacao": a.get("relacao") or ("principal" if k == 0 else None)}
                        for k, (i, a) in enumerate(zip(ids, artigos))],
            "situacao": situacao, "segundos": round(segundos, 1), "entregue": False,
            "problemas_antes_da_revisao": diagnostico.get("problemas"), "tipo_de_correcao": diagnostico.get("correcao"),
            "titulos_reprovados": diagnostico.get("titulos_reprovados") or [],
            "problemas_depois_da_revisao": diagnostico.get("problemas_da_revisao"),
            "nomes_do_bloco": nomes_do_bloco, "vozes": vozes,
            "proporcao_do_texto": diagnostico.get("proporcao_do_item"), "aviso_da_janela": diagnostico.get("aviso_da_janela") or "",
            "json_incompleto_refeito": diagnostico.get("json_incompleto_refeito") or 0,
        }
        for chave, lista in (outros or {}).items():
            if lista:
                entrada[chave] = [{"veiculo": a["veiculo"], "titulo": a["titulo"], "url": a["url"]} for a in lista]
        if diagnostico.get("lados") is not None:
            entrada["lados"] = lados_para_registro(diagnostico["lados"])
        for nome, montada in (("cortes_na_geracao", diagnostico.get("entrada")), ("cortes_na_revisao", diagnostico.get("revisao"))):
            if montada is not None:
                entrada[nome] = cortes_para_registro(montada)
        if diagnostico.get("orcamento") is not None:
            entrada["orcamento"] = orcamento_para_registro(diagnostico["orcamento"])
        if episodio is not None:
            situacao_curta = "aprovado" if situacao == "aprovado" else "reprovado" if situacao.startswith("reprovado") else "falhou"
            slug = re.sub(r"\W+", "-", str(episodio.get("titulo_reescrito", "")).lower())[:40].strip("-")
            arquivo = self.pasta / f"{n:02d}_{situacao_curta}_{slug}.json"
            arquivo.write_text(json.dumps(episodio, ensure_ascii=False, indent=1), encoding="utf-8")
            entrada["arquivo"] = str(arquivo)
            entrada["titulo"] = episodio.get("titulo_reescrito")
        self.episodios.append(entrada)
        self.gravar()
        return entrada

    def entregue(self, entrada: dict) -> None:
        entrada["entregue"] = True
        self.gravar()

    def gravar(self) -> None:
        self.amostra.write_text(json.dumps(
            {"criada_em": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "incluir_vistos": False,
             "candidatos": self.candidatos}, ensure_ascii=False, indent=1), encoding="utf-8")
        self.relatorio.write_text(json.dumps(
            {"amostra": str(self.amostra), "limiar": None, "num_ctx": self.num_ctx, "episodios": self.episodios,
             "filtrados": self.filtrados, "abandonados": self.abandonados,
             **({} if self.etapa3 is None else {"etapa3": self.etapa3}),
             **({"agrupamento_falhou": self.agrupamento_falhou} if self.agrupamento_falhou else {})},
            ensure_ascii=False, indent=1, default=str), encoding="utf-8")
