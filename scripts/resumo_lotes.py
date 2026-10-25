"""Resumo por lote do log do TechDigest.

Uso (da raiz do projeto, com o venv ativo):
    python scripts/resumo_lotes.py          # lotes de hoje
    python scripts/resumo_lotes.py 07/10    # lotes de um dia (DD/MM)
    python scripts/resumo_lotes.py 07/10 --log <pasta da simulação>/logs/techdigest.log

Lê data/logs/techdigest.log (ou o log de --log) e os arquivos rotacionados (.1 a .7), do mais
antigo ao mais novo. Uma execução interrompida por uma trava da máquina aparece com o motivo, e
as que nem começaram porque a trava do modelo estava ocupada vêm listadas depois da tabela. Os itens
que o filtro tirou (esporte, ofertas, site de partido) e os abandonados pelo limite de tentativas
têm colunas próprias, e o aviso de parada aparece nas observações (enviado ou não).
"""
import datetime
import re
import sys
from pathlib import Path

from techdigest.config import Settings

settings = Settings()

RE_LINHA = re.compile(r"^(\d\d/\d\d) (\d\d:\d\d:\d\d) │ (\w+)\s*│ (\S+)\s*│ (.*)$")
RE_TOKS = re.compile(r"\(([\d.]+) tok/s\)")
RE_RAM = re.compile(r"RAM disp\.=([\d.]+) GB")
RE_SWAP = re.compile(r"swap usado=([\d.]+) GB")
RE_CPU = re.compile(r"CPU=(\d+)°C")
RE_GPU = re.compile(r"GPU=(\d+)°C/(\d+) MHz")
RE_FIM = re.compile(r"Execução concluída: (\d+) notícia")


def _arquivos_de_log(log: str | None = None) -> list[Path]:
    base = Path(log) if log else Path(settings.log_dir) / "techdigest.log"
    rotacionados = [Path(f"{base}.{i}") for i in range(7, 0, -1)]
    return [p for p in rotacionados + [base] if p.exists()]


def _novo_lote(hora: str) -> dict:
    return {"inicio": hora, "fim": None, "entregues": None, "qa": 0, "descartados": 0, "filtrados": 0, "abandonados": 0,
            "erros": 0, "falhas_entrega": 0, "orcamento": False, "fatal": False, "interrompida": "", "aviso": "",
            "toks": [], "ram": [], "swap": [], "cpu": [], "gpu": [], "gpu_mhz": []}


def ler_lotes(dia: str, log: str | None = None, nao_comecaram: list | None = None) -> list[dict]:
    lotes: list[dict] = []
    atual = None
    ultimo_evento = None
    for arquivo in _arquivos_de_log(log):
        for linha in arquivo.read_text(encoding="utf-8", errors="replace").splitlines():
            m = RE_LINHA.match(linha)
            if not m:
                # linha de traceback: um "Item pulado:" antigo que era rejeição do QA
                if atual and ultimo_evento == "erro" and "QAReprovado:" in linha:
                    atual["erros"] -= 1
                    atual["qa"] += 1
                    ultimo_evento = None
                continue
            data, hora, _nivel, _origem, msg = m.groups()
            if data != dia:
                continue
            ultimo_evento = None
            if msg.startswith("Execução não começou:"):
                if nao_comecaram is not None:
                    nao_comecaram.append((hora, msg.removeprefix("Execução não começou:").strip()))
                continue
            if "=== TechDigest iniciando ===" in msg:
                atual = _novo_lote(hora)
                lotes.append(atual)
                continue
            if atual is None:
                continue
            if (f := RE_FIM.search(msg)):
                atual["fim"], atual["entregues"] = hora, int(f.group(1))
            elif "Nenhuma notícia entregue" in msg:
                atual["fim"], atual["entregues"] = hora, 0
            elif "Orçamento de tempo" in msg:
                atual["orcamento"] = True
            elif "Falha fatal" in msg:
                atual["fim"], atual["fatal"] = hora, True
            elif msg.startswith("Execução interrompida:"):
                atual["fim"] = hora
                atual["interrompida"] = msg.removeprefix("Execução interrompida:").split(" (")[0].strip()
            elif "Item pulado pelo QA" in msg:
                atual["qa"] += 1
            elif msg.startswith("Item pulado:"):
                atual["erros"] += 1
                ultimo_evento = "erro"
            elif msg.startswith("Item descartado"):
                atual["descartados"] += 1
            elif msg.startswith("Item filtrado"):
                atual["filtrados"] += 1
            elif msg.startswith("Item abandonado"):
                atual["abandonados"] += 1
            elif msg.startswith("Aviso de parada não enviado"):
                atual["aviso"] = "aviso não enviado"
            elif msg.startswith("Aviso de parada:"):
                atual["aviso"] = "aviso enviado"
            elif msg.startswith("Falha ao entregar"):
                atual["falhas_entrega"] += 1
            elif "tok/s" in msg and msg.startswith("Ollama"):
                for chave, regex in (("toks", RE_TOKS), ("ram", RE_RAM), ("swap", RE_SWAP), ("cpu", RE_CPU)):
                    if (v := regex.search(msg)):
                        atual[chave].append(float(v.group(1)))
                if (g := RE_GPU.search(msg)):
                    atual["gpu"].append(float(g.group(1)))
                    atual["gpu_mhz"].append(float(g.group(2)))
    return lotes


def _min(valores, fmt="{:.0f}"):
    return fmt.format(min(valores)) if valores else "-"


def _max(valores, fmt="{:.0f}"):
    return fmt.format(max(valores)) if valores else "-"


def _duracao(inicio: str, fim: str | None) -> str:
    if not fim:
        return "em andamento"
    t0 = datetime.datetime.strptime(inicio, "%H:%M:%S")
    t1 = datetime.datetime.strptime(fim, "%H:%M:%S")
    minutos = ((t1 - t0).total_seconds() % 86400) / 60
    return f"{minutos:.0f} min"


def main() -> None:
    argumentos = sys.argv[1:]
    log = None
    if "--log" in argumentos:
        i = argumentos.index("--log")
        if i + 1 >= len(argumentos):
            sys.exit("--log precisa do caminho do arquivo de log")
        log = argumentos[i + 1]
        del argumentos[i:i + 2]
    dia = argumentos[0] if argumentos else datetime.date.today().strftime("%d/%m")
    nao_comecaram: list[tuple[str, str]] = []
    lotes = ler_lotes(dia, log, nao_comecaram)
    if not lotes:
        print(f"Nenhum lote encontrado em {dia} (arquivos lidos: {[str(p) for p in _arquivos_de_log(log)]})")
        _listar_nao_comecaram(nao_comecaram)
        return
    cab = ("Início", "Duração", "Entreg.", "QA", "Desc.", "Filt.", "Aband.", "Erros", "F.entr.",
           "tok/s méd", "tok/s mín", "RAM mín GB", "swap máx GB", "CPU máx °C", "GPU máx °C", "GPU mín MHz", "Obs.")
    linhas = []
    for l in lotes:
        obs = []
        if l["orcamento"]:
            obs.append("orçamento esgotado")
        if l["fatal"]:
            obs.append("falha fatal")
        if l["interrompida"]:
            obs.append(f"interrompida: {l['interrompida']}")
        if l["aviso"]:
            obs.append(l["aviso"])
        toks = l["toks"]
        linhas.append((
            l["inicio"], _duracao(l["inicio"], l["fim"]),
            "-" if l["entregues"] is None else str(l["entregues"]),
            str(l["qa"]), str(l["descartados"]), str(l["filtrados"]), str(l["abandonados"]), str(l["erros"]),
            str(l["falhas_entrega"]),
            f"{sum(toks) / len(toks):.1f}" if toks else "-", _min(toks, "{:.1f}"),
            _min(l["ram"], "{:.1f}"), _max(l["swap"], "{:.1f}"),
            _max(l["cpu"]), _max(l["gpu"]), _min(l["gpu_mhz"]),
            ", ".join(obs),
        ))
    larguras = [max(len(c), *(len(x[i]) for x in linhas)) for i, c in enumerate(cab)]
    print(f"Lotes de {dia}:")
    print(" | ".join(c.ljust(w) for c, w in zip(cab, larguras)))
    print("-+-".join("-" * w for w in larguras))
    for x in linhas:
        print(" | ".join(v.ljust(w) for v, w in zip(x, larguras)))
    _listar_nao_comecaram(nao_comecaram)


def _listar_nao_comecaram(nao_comecaram: list[tuple[str, str]]) -> None:
    """As execuções que nem começaram, porque a trava do modelo estava ocupada."""
    if nao_comecaram:
        print("\nNão começaram (a trava do modelo estava ocupada):")
        for hora, motivo in nao_comecaram:
            print(f"  {hora}: {motivo}")


if __name__ == "__main__":
    main()