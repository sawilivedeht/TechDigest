"""Refaz o QA, sem o modelo, nos episódios gravados por testar_episodio.py (sem LLM e sem rede).

Serve para medir o efeito de uma mudança no QA sobre os episódios já gerados. Para cada episódio
de um relatório, remonta a entrada do QA (os veículos que entraram na geração, os lados como a
análise os deixou, com o lado fino gravado, as ressalvas e os textos completos da pauta, tirados
da amostra), roda `qa.problemas_com_campo` no episódio gravado e compara com a situação gravada.
O episódio gravado é a última versão inteira: num reprovado, a que saiu da correção.

Lista os episódios que mudam de situação, com o motivo (os problemas gravados que deixaram de
valer, ou os novos), e cruza os que passam a ser aprovados com o checar_fidelidade.py: o que ele
acha neles e o QA não pega (fato sem fonte, atribuição a veículo pela regra estrita, pergunta
aberta isenta). O que nenhum dos dois vê, como a questão escolhida pela análise de lados, fica de
fora.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/refazer_qa.py data/agrupamento/episodios_v4 data/agrupamento/episodios_amostra2_v2
    python scripts/refazer_qa.py data/agrupamento/episodios_v5/relatorio_<data-hora>.json

Uma pasta vale pelo relatorio_*.json mais recente dela. Grava data/agrupamento/refazer_qa_<data-hora>.txt.
"""
import argparse
import contextlib
import datetime
import io
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import checar_fidelidade as cf
from techdigest.ai import qa
from techdigest.ai.lados import Lado, Ressalva
from techdigest.config import Settings

settings = Settings()


@dataclass
class Refeito:
    """Um episódio gravado, com a situação de quando foi gerado e o QA de agora."""
    numero: int
    caso: str
    situacao: str                       # como o relatório a gravou
    problemas_antes: list[str]          # os do episódio gravado, quando ele foi gerado
    problemas_agora: list[str]          # os do QA de agora, no mesmo episódio
    fidelidade: "cf.Caso | None" = None  # o que o checar_fidelidade.py acha nele

    @property
    def aprovado_antes(self) -> bool:
        return self.situacao == "aprovado"

    @property
    def aprovado_agora(self) -> bool:
        return not self.problemas_agora

    @property
    def mudou(self) -> bool:
        return self.aprovado_antes != self.aprovado_agora


def _relatorio(caminho: str) -> Path:
    """O relatório de um caminho: o próprio arquivo, ou o relatorio_*.json mais recente da pasta."""
    alvo = Path(caminho)
    if alvo.is_dir():
        relatorios = sorted(alvo.glob("relatorio_*.json"))
        if not relatorios:
            sys.exit(f"{alvo}: nenhuma relatorio_<data-hora>.json nesta pasta.")
        return relatorios[-1]
    return alvo


def _amostra(relatorio: dict) -> dict[int, dict]:
    amostra = Path(relatorio["amostra"])
    if not amostra.exists():
        amostra = Path(__file__).resolve().parents[1] / relatorio["amostra"]
    return {c["id"]: c for c in json.loads(amostra.read_text(encoding="utf-8"))["candidatos"]}


def entrada_do_qa(item: dict, candidatos: dict[int, dict]) -> tuple[list[str], list[Lado], list[Ressalva], list[str]]:
    """O que o QA recebeu quando o episódio foi gerado: veículos, lados, ressalvas e textos da pauta.

    Os veículos são os dos textos que entraram na geração (os cortes com algo incluído; sem cortes,
    os artigos da pauta). O lado fino é o que o relatório gravou: pela contagem das frases, quando
    ela existe, ou pela marca "fino" dos relatórios mais antigos. Os textos são título e texto
    completo de cada artigo, como o Summarizer os passa ao QA.
    """
    cortes = item.get("cortes_na_geracao") or []
    veiculos = [c["fonte"] for c in cortes if c.get("incluido", 0) > 0] or [a["veiculo"] for a in item["artigos"]]
    analise = item.get("lados") or {}
    lados = [
        Lado(lado["posicao"], tuple(lado["atores"]), tuple(lado["veiculos"]), lado.get("resposta", ""), tuple(lado.get("trechos", [])),
             lado["frases_com_os_atores"] if "frases_com_os_atores" in lado else (1 if lado.get("fino") else None))
        for lado in analise.get("lados", [])
    ]
    ressalvas = [Ressalva(tuple(r["grupos"]), r["posicao"], tuple(r["veiculos"]), r.get("trecho", "")) for r in analise.get("ressalvas", [])]
    textos = [f"{candidatos[a['id']]['titulo']}\n{candidatos[a['id']]['texto']}" for a in item["artigos"]]
    return veiculos, lados, ressalvas, textos


def refazer(caminho: Path) -> list[Refeito]:
    """Refaz o QA nos episódios gravados de um relatório e junta o que o checar_fidelidade.py acha em cada um."""
    relatorio = json.loads(caminho.read_text(encoding="utf-8"))
    candidatos = _amostra(relatorio)
    with contextlib.redirect_stdout(io.StringIO()):   # os avisos de episódio sem arquivo já saem abaixo
        fidelidade = {caso.numero: caso for caso in cf._carregar(caminho)}
    refeitos = []
    for item in relatorio["episodios"]:
        if not item.get("arquivo"):
            continue
        episodio = json.loads(Path(item["arquivo"]).read_text(encoding="utf-8"))
        veiculos, lados, ressalvas, textos = entrada_do_qa(item, candidatos)
        try:
            agora = [p.texto for p in qa.problemas_com_campo(episodio, veiculos, lados, ressalvas, textos)]
        except (KeyError, TypeError, AttributeError) as e:
            agora = [f"estrutura inválida para o QA ({type(e).__name__}: {e})"]
        antes = [] if item["situacao"] == "aprovado" else (item.get("problemas_depois_da_revisao") or item.get("problemas_antes_da_revisao") or [])
        refeitos.append(Refeito(item["episodio"], item["caso"], item["situacao"], antes, agora, fidelidade.get(item["episodio"])))
    return refeitos


def _encurtar(texto: str, limite: int = 220) -> str:
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


def o_que_o_qa_nao_pega(caso: "cf.Caso | None") -> list[str]:
    """O que o checar_fidelidade.py acha num episódio e o QA não cobra: fato sem fonte, atribuição a veículo pela
    regra estrita, pergunta aberta isenta e problema de divergência."""
    if caso is None:
        return []
    r = caso.resultado
    achados = [f"sem fonte ({a.tipo}, {a.local}): {a.rotulo}" for a in r.sem_fonte]
    achados += [f"atribuição a veículo pela regra estrita ({a.local}): {a.veiculo} com {a.medida.no_citado:.0%} das palavras, "
                f"{a.medida.outro} com {a.medida.no_outro:.0%} · \"{_encurtar(a.frase, 140)}\""
                for a in caso.atribuicoes if cf.pela_regra_estrita(a.medida)]
    achados += [f"pergunta aberta isenta ({a.local}): \"{_encurtar(a.frase, 140)}\"" for a in r.perguntas_abertas]
    achados += [f"divergência ({a.local}): {a.tipo}" for a in r.divergencia]
    return achados


def montar(por_relatorio: dict[Path, list[Refeito]], gerado_em: str) -> str:
    linhas = [f"QA refeito sem o modelo · gerado em {gerado_em}"]
    for caminho, refeitos in por_relatorio.items():
        mudaram = [r for r in refeitos if r.mudou]
        linhas += ["", f"== {caminho} · {len(refeitos)} episódio(s): {sum(r.aprovado_antes for r in refeitos)} aprovado(s) "
                       f"quando gerados, {sum(r.aprovado_agora for r in refeitos)} pelo QA de agora · {len(mudaram)} mudam =="]
        for r in refeitos:
            antes, agora = ("aprovado" if r.aprovado_antes else "REPROVADO"), ("aprovado" if r.aprovado_agora else "REPROVADO")
            linhas.append(f"  ep{r.numero} ({r.caso}): {antes} -> {agora}" + ("   <- MUDA" if r.mudou else ""))
            if r.mudou and r.aprovado_agora:
                linhas += [f"      deixou de valer: {_encurtar(p)}" for p in r.problemas_antes] or ["      (o relatório não gravou os problemas)"]
                nao_pega = o_que_o_qa_nao_pega(r.fidelidade)
                linhas += [f"      o checar_fidelidade acha e o QA não pega: {item}" for item in nao_pega] or [
                    "      o checar_fidelidade não acha nada que o QA deixe passar"]
            elif not r.aprovado_agora:
                novos = [p for p in r.problemas_agora if p not in r.problemas_antes]
                linhas += [f"      problema do QA de agora: {_encurtar(p)}" for p in r.problemas_agora]
                if r.mudou:
                    linhas.append(f"      {len(novos)} problema(s) novo(s) em relação a quando foi gerado")
    return "\n".join(linhas) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Refaz o QA, sem o modelo, nos episódios gravados por testar_episodio.py.")
    p.add_argument("caminhos", nargs="+", metavar="PASTA_OU_RELATORIO",
                   help="pastas de episódios (vale o relatorio_*.json mais recente de cada) ou relatórios")
    args = p.parse_args()
    por_relatorio = {}
    for caminho in args.caminhos:
        relatorio = _relatorio(caminho)
        por_relatorio[relatorio] = refazer(relatorio)
    agora = datetime.datetime.now()
    texto = montar(por_relatorio, f"{agora:%d/%m/%Y %H:%M:%S}")
    destino = Path(settings.db_path).parent / "agrupamento" / f"refazer_qa_{agora:%Y%m%d-%H%M%S}.txt"
    destino.write_text(texto, encoding="utf-8")
    print(texto)
    print(f"Relatório: {destino}")


if __name__ == "__main__":
    main()
