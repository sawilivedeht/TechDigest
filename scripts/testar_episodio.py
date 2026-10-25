"""Diagnóstico da geração de episódios a partir de pautas (Fase 3 do agrupamento).

Com uma amostra fixa, gera com Summarizer.process os episódios de algumas pautas. Não gera áudio,
não envia nada ao Telegram, não chama mark_seen e não abre o digest.db.

Uso (da raiz do projeto, com o venv ativo, o Ollama no ar pela unit, com systemctl --user start
techdigest-teste.target, e nenhum pipeline rodando):
    python scripts/testar_episodio.py --amostra data/agrupamento/amostra_<data-hora>.json
    python scripts/testar_episodio.py --repetir data/agrupamento/episodios/relatorio_<data-hora>.json --pasta episodios_v2
    python scripts/testar_episodio.py --repetir <relatório> --pautas "86+71" --so-lados

Sem --repetir nem --pautas, refaz as etapas 1 a 3 do agrupamento e escolhe até 4 pautas com várias
fontes e 1 de fonte única, como controle. --repetir usa as pautas de um relatório anterior, na
mesma ordem, e --pautas acrescenta pautas montadas pelos ids da amostra; nos dois casos a etapa 3
não roda. --so-lados faz só a análise de lados de cada pauta, sem gerar episódio.

A análise de lados lê os textos inteiros, e a geração e as revisões recebem de cada texto um recorte
por relevância: o relatório diz, por fonte, que parágrafos entraram em cada chamada e por quê (lide,
trecho do lado N, ordem do texto) e quais ficaram de fora tendo trecho de evidência. Nas pautas com
disputa mostra também, para cada trecho de evidência, a fala de analista que mais palavras dele
repete (é uma medida de palavras em comum, não uma regra).

Antes de tudo confere a GPU (ver `ai/gpu.py`): o driver da NVIDIA tem de responder e o log do
ollama serve (o da unit ollama.service, OLLAMA_LOG, ou o de --log-ollama) tem de mostrar que o
servidor achou a GPU ao subir; senão para antes de carregar o modelo. Depois da primeira chamada,
confere no mesmo log que o modelo principal carregou com camadas na GPU; senão descarrega o modelo e para.

Antes de cada chamada ao LLM mostra memória disponível, swap e temperaturas. Para se a memória
disponível estiver abaixo de --min-memoria (GiB) ou se o Ollama sair do ar ou descarregar o modelo
no meio da rodada. Se a CPU passar de --max-cpu (°C) antes de uma chamada, espera até ela baixar de
--retomar-cpu e continua. Essas travas e as da GPU são as do pipeline (`ai/maquina.py`). A rodada
pega a trava do modelo (`trava.py`): com outra execução usando o modelo, para antes de começar. Grava em data/agrupamento/<pasta>/ o JSON de cada episódio e um
relatorio_<data-hora>.json (ou lados_<data-hora>.json) com tudo o que foi medido.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

import testar_agrupamento as diag
from techdigest import trava
from techdigest.ai import maquina, qa
from techdigest.ai.llm import get_provider
from techdigest.ai.elenco import nomes_dos_analistas
from techdigest.ai.lados import lados_finos
from techdigest.ai.prompt import PROMPT_LADOS, PROMPT_RESUMO, PROMPT_REVISOR, PROMPT_ROTEIRO, PROMPT_SISTEMA, PROMPT_TITULO
from techdigest.ai.summarizer import CORRECOES, TETO_PRINCIPAL, TETO_RELACIONADO, QAReprovado, Summarizer
from techdigest.config import Settings
from techdigest.processing import agrupamento as ag

settings = Settings()

ALERTA_DA_JANELA = 0.9   # avisa quando entrada + saída passam desta fração de num_ctx
FALAS_NO_RELATORIO = 3
MIN_LETRAS_DA_PALAVRA = 4   # na medida dos trechos nas falas, só contam as palavras com pelo menos isto


def _argumentos() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Gera episódios de pautas com várias fontes, sem entregar nada.")
    p.add_argument("--amostra", metavar="ARQUIVO",
                   help="amostra gravada por testar_agrupamento.py --salvar-amostra (padrão: a do relatório de --repetir)")
    p.add_argument("--repetir", metavar="RELATORIO",
                   help="usa as pautas de um relatório anterior deste script, na mesma ordem, sem refazer a etapa 3")
    p.add_argument("--pautas", metavar="IDS", default="",
                   help='pautas a mais, pelos ids da amostra: "86+71;12" (o texto mais longo é o principal)')
    p.add_argument("--so-lados", action="store_true", help="faz só a análise de lados de cada pauta, sem gerar episódio")
    p.add_argument("--pasta", default="episodios", metavar="NOME",
                   help="subpasta de data/agrupamento/ para os arquivos (padrão: %(default)s)")
    p.add_argument("--limiar", type=float, default=settings.agrup_limiar,
                   help="score mínimo da pauta provisória (padrão: AGRUP_LIMIAR = %(default)s)")
    p.add_argument("--max-pautas", type=int, default=4, metavar="N",
                   help="quantas pautas com várias fontes gerar (padrão: %(default)s)")
    p.add_argument("--min-memoria", type=float, default=4.0, metavar="GIB",
                   help="para se a memória disponível cair abaixo disto, em GiB (padrão: %(default)s)")
    p.add_argument("--max-cpu", type=float, default=95.0, metavar="°C",
                   help="com a CPU acima disto antes de uma chamada, a rodada espera esfriar (padrão: %(default)s)")
    p.add_argument("--retomar-cpu", type=float, default=85.0, metavar="°C",
                   help="a rodada continua quando a CPU baixa disto (padrão: %(default)s)")
    p.add_argument("--log-ollama", metavar="ARQUIVO", default=settings.ollama_log,
                   help="arquivo em que o ollama serve grava a saída: a conferência da GPU lê nele a linha "
                        "\"inference compute\" (padrão: o da unit ollama.service, OLLAMA_LOG: %(default)s)")
    args = p.parse_args()
    if not args.amostra and not args.repetir:
        p.error("informe --amostra ou --repetir")
    if settings.llm_provider == "ollama" and not args.log_ollama:
        p.error("informe --log-ollama: sem o log do ollama serve não dá para saber se o servidor achou a GPU")
    return args


def _memoria_do_processo(pid) -> dict[str, float] | None:
    """Memória de um processo, em GiB: residente (rss), a parte anônima dela e o que está na swap."""
    try:
        with open(f"/proc/{pid}/status") as arquivo:
            campos = {linha.split(":")[0]: linha.split()[1] for linha in arquivo if linha.startswith(("VmRSS", "RssAnon", "VmSwap"))}
    except (OSError, IndexError):
        return None   # o processo acabou, ou é uma thread do kernel
    if "VmRSS" not in campos:
        return None
    return {"rss": int(campos["VmRSS"]) / 1048576, "anonima": int(campos.get("RssAnon", 0)) / 1048576,
            "swap": int(campos.get("VmSwap", 0)) / 1048576}


def _processos_do_ollama() -> dict[str, str]:
    """PID e nome do servidor do Ollama e de tudo o que ele abriu (o llama-server, que executa o modelo)."""
    nomes, pais = {}, {}
    for entrada in os.listdir("/proc"):
        if not entrada.isdigit():
            continue
        try:
            with open(f"/proc/{entrada}/stat") as arquivo:
                conteudo = arquivo.read()
            nomes[entrada] = conteudo[conteudo.index("(") + 1:conteudo.rindex(")")]
            pais[entrada] = conteudo[conteudo.rindex(")") + 2:].split()[1]
        except (OSError, ValueError, IndexError):
            continue
    do_ollama = {pid for pid, nome in nomes.items() if nome.startswith("ollama")}
    while novos := {pid for pid, pai in pais.items() if pai in do_ollama} - do_ollama:
        do_ollama |= novos
    return {pid: nomes[pid] for pid in sorted(do_ollama, key=int)}


def _memoria_por_processo() -> dict[str, dict[str, float]]:
    """Memória do processo deste script e dos processos do Ollama, somados e por nome.

    O Ollama são dois processos: o servidor ("ollama") e o executor do modelo ("llama-server"),
    que o servidor abre. A parte do modelo que fica na GPU não aparece aqui. Traz também, quando
    existe, a RAM ocupada pela swap comprimida (zram): com ela, o que vai para a swap continua
    ocupando memória.
    """
    soma = {"rss": 0.0, "anonima": 0.0, "swap": 0.0, "processos": 0}
    medidas = {"script": _memoria_do_processo(os.getpid()) or {}, "ollama": soma}
    for pid, nome in _processos_do_ollama().items():
        if memoria := _memoria_do_processo(pid):
            por_nome = medidas.setdefault(f"ollama:{nome}", {"rss": 0.0, "anonima": 0.0, "swap": 0.0})
            for chave, valor in memoria.items():
                soma[chave] += valor
                por_nome[chave] += valor
            soma["processos"] += 1
    try:
        with open("/sys/block/zram0/mm_stat") as arquivo:
            medidas["zram"] = {"ram": int(arquivo.read().split()[2]) / 1073741824}   # mem_used_total, em bytes
    except (OSError, IndexError, ValueError):
        pass
    return {nome: {chave: round(valor, 2) for chave, valor in medida.items()} for nome, medida in medidas.items()}


def _resumo_da_memoria(medidas: dict) -> str:
    script, ollama = medidas.get("script", {}), medidas.get("ollama", {})
    partes = [
        f"script {script.get('rss', 0):.2f} GB (swap {script.get('swap', 0):.2f})",
        f"ollama {ollama.get('rss', 0):.2f} GB (anônima {ollama.get('anonima', 0):.2f}, swap {ollama.get('swap', 0):.2f}, "
        f"{ollama.get('processos', 0):.0f} processo(s))",
    ]
    if "zram" in medidas:
        partes.append(f"zram ocupa {medidas['zram']['ram']:.2f} GB de RAM")
    return " · ".join(partes)


# Como cada chamada aparece no relatório, pelo prompt de sistema.
ROTULOS = {PROMPT_SISTEMA: "geração", PROMPT_LADOS: "lados", PROMPT_REVISOR: CORRECOES["completa"],
           PROMPT_RESUMO: CORRECOES["resumo"], PROMPT_ROTEIRO: CORRECOES["roteiro"], PROMPT_TITULO: CORRECOES["titulo"]}
# Primeira pessoa do plural na fala de um analista: pronomes e verbos em -amos, -emos e -imos. É só diagnóstico.
_NOS = re.compile(r"\b(?:nós|conosco|noss[oa]s?|[^\W\d_]{2,}(?:[aeií]mos))\b", re.IGNORECASE)
_NAO_E_NOS = {"mesmos", "termos", "extremos", "supremos", "ramos", "remos", "próximos", "últimos", "mínimos", "máximos",
              "ótimos", "íntimos", "legítimos", "empréstimos", "primos", "péssimos", "altíssimos", "muitíssimos"}


class ProviderMonitorado(maquina.ProviderVigiado):
    """O provider com as travas da máquina do pipeline (`ai/maquina.py`) e o registro de cada chamada.

    Antes de cada chamada mostra a memória, a swap, as temperaturas e a memória por processo; guarda
    o tempo, os tokens e a resposta. As travas são as mesmas do pipeline, com os limites da linha de
    comando.
    """

    def __init__(self, provider, min_memoria: float, max_cpu: float, retomar_cpu: float, log_ollama: str | None):
        super().__init__(provider, log_ollama=log_ollama, min_memoria=min_memoria, max_cpu=max_cpu,
                         retomar_cpu=retomar_cpu)
        self.chamadas: list[dict] = []

    def chat_json(self, system: str, user: str, **opcoes) -> dict:
        esperou = self.esperar_a_cpu()
        disponivel, resumo = maquina.estado_da_maquina()
        chamada = {
            "prompt": ROTULOS.get(system, "outro"), "espera_pela_cpu": round(esperou, 1),
            "chars_sistema": len(system), "chars_entrada": len(user), "maquina_antes": resumo,
            "memoria_disponivel": None if disponivel is None else round(disponivel, 2),
            "memoria_por_processo": (memoria := _memoria_por_processo()),
        }
        print(f"      {chamada['prompt']}: {len(system) + len(user)} caracteres · antes: {resumo}", flush=True)
        print(f"        memória por processo: {_resumo_da_memoria(memoria)}", flush=True)
        self.conferir_memoria(disponivel)
        self.conferir_antes_de_carregar()
        self.conferir_ollama()
        self.chamadas.append(chamada)
        inicio = time.perf_counter()
        try:
            resposta = self.provider.chat_json(system, user, **opcoes)
        except Exception as e:
            chamada.update(segundos=time.perf_counter() - inicio, erro=f"{type(e).__name__}: {str(e)[:300]}")
            self.depois_da_falha()   # se foi o servidor que caiu, a rodada para aqui em vez de seguir falhando
            raise
        self.conferir_depois_da_carga()
        tokens = dict(self.provider.ultimo_uso)
        chamada.update(segundos=time.perf_counter() - inicio, tokens_entrada=tokens.get("prompt", 0),
                       tokens_saida=tokens.get("saida", 0), resposta=resposta)
        return resposta


def _pautas_dadas(args: argparse.Namespace, ids: dict[ag.Candidato, int]) -> list[tuple[str, ag.Pauta]]:
    """As pautas de --repetir (como estavam no relatório) e as de --pautas (montadas pelos ids), com o nome do caso."""
    por_id = {n: c for c, n in ids.items()}
    escolhidas: list[tuple[str, ag.Pauta]] = []
    try:
        if args.repetir:
            for item in json.loads(Path(args.repetir).read_text(encoding="utf-8"))["episodios"]:
                principal, *demais = [(por_id[a["id"]], a.get("relacao")) for a in item["artigos"]]
                escolhidas.append((item["caso"], ag.Pauta(
                    principal=principal[0], relacionados=tuple(c for c, _ in demais),
                    relacoes={c: relacao for c, relacao in demais if relacao in ag.RELACOES},
                )))
        for grupo in filter(None, (g.strip() for g in args.pautas.split(";"))):
            artigos = [por_id[int(n)] for n in grupo.split("+")]
            principal = max(artigos, key=lambda c: len(c.texto))        # a regra do projeto: o texto extraído mais longo
            escolhidas.append((f"ids_{grupo}", ag.Pauta(principal=principal, relacionados=tuple(c for c in artigos if c is not principal))))
    except (OSError, ValueError, KeyError, TypeError) as e:
        sys.exit(f"Pautas ilegíveis ({type(e).__name__}: {e}): confira --repetir e --pautas.")
    return escolhidas


def _pautas_finais(args: argparse.Namespace, provider, candidatos: list[ag.Candidato],
                   ids: dict[ag.Candidato, int]) -> list[ag.Pauta]:
    """Etapas 1 a 3 sobre a amostra: as pautas finais."""
    titulos = ag.comparar_titulos(candidatos, settings.agrup_chars_texto)
    textos = ag.comparar_textos(candidatos, settings.agrup_chars_texto)
    pares = ag.pontuar_pares(candidatos, titulos, textos, settings.agrup_peso_titulo, settings.agrup_limiar_duplicata)
    provisorias, _ = ag.formar_pautas(candidatos, pares, args.limiar, settings.agrup_max_artigos)
    com_varios = [p for p in provisorias if p.relacionados]
    finais = [p for p in provisorias if not p.relacionados]
    print(f"\n== Etapa 3: o LLM confirma {len(com_varios)} pauta(s) provisória(s) (limiar {args.limiar:.2f}) ==", flush=True)
    for n, pauta in enumerate(com_varios, 1):
        chamada = diag._consultar_llm(provider, pauta, 1)
        finais += chamada.finais
        print(f"  pauta {n}/{len(com_varios)} (ids {', '.join(str(ids[c]) for c in pauta.artigos)}) · "
              f"{chamada.segundos:.1f} s · {chamada.erro or diag._resumo_do_veredito(chamada, ids)}", flush=True)
    return finais


def _escolher(finais: list[ag.Pauta], ids: dict[ag.Candidato, int], quantas: int) -> list[tuple[str, ag.Pauta]]:
    """Até `quantas` pautas com várias fontes e uma de fonte única, cada uma com o nome do caso.

    A preferência cobre os casos diferentes: mesmo acontecimento entre veículos diferentes,
    desdobramento entre veículos diferentes e textos do mesmo veículo; depois, as pautas com mais
    textos. O controle é a primeira pauta de um artigo só, na ordem da amostra.
    """
    varias = [p for p in finais if p.relacionados]

    def caso(p: ag.Pauta) -> str:
        if len(p.veiculos) == 1:
            return "mesmo_veiculo"
        return "desdobramento" if "desdobramento" in p.relacoes.values() else "mesmo_acontecimento"

    escolhidas: list[tuple[str, ag.Pauta]] = []
    for nome in ("mesmo_acontecimento", "desdobramento", "mesmo_veiculo"):
        primeira = next((p for p in varias if caso(p) == nome), None)
        if primeira:
            escolhidas.append((nome, primeira))
    for p in sorted(varias, key=lambda p: -len(p.artigos)):
        if all(p is not escolhida for _, escolhida in escolhidas):
            escolhidas.append((caso(p), p))
    escolhidas = escolhidas[:quantas]
    sozinhas = sorted((p for p in finais if not p.relacionados), key=lambda p: ids[p.principal])
    return ([("controle_fonte_unica", sozinhas[0])] if sozinhas else []) + escolhidas


def _como_fonte(c: ag.Candidato, relacao: str | None = None) -> dict:
    fonte = {"source": c.veiculo, "title": c.titulo, "text": c.texto, "data": c.data}
    return {**fonte, "relacao": relacao} if relacao else fonte


def _apresentar(rotulo: str, n: int, caso: str, pauta: ag.Pauta, ids: dict) -> dict:
    """Mostra a pauta e devolve o começo do relatório dela."""
    print(f"\n== {rotulo} {n}: {caso} · {len(pauta.artigos)} texto(s) de {len(pauta.veiculos)} veículo(s) ==")
    print(f"  principal:   [id {ids[pauta.principal]}] {diag._rotulo(pauta.principal)} ({len(pauta.principal.texto)} caracteres)")
    for c in pauta.relacionados:
        print(f"  relacionado: [id {ids[c]}] {diag._rotulo(c)} ({len(c.texto)} caracteres, {pauta.relacoes.get(c, '?')})")
    return {
        "episodio": n, "caso": caso,
        "artigos": [{"id": ids[c], "veiculo": c.veiculo, "titulo": c.titulo, "caracteres": len(c.texto),
                     "relacao": pauta.relacoes.get(c, "principal")} for c in pauta.artigos],
        "veiculos_da_pauta": list(pauta.veiculos),
    }


def _fontes(pauta: ag.Pauta) -> tuple[dict, list[dict]]:
    return _como_fonte(pauta.principal), [_como_fonte(c, pauta.relacoes.get(c)) for c in pauta.relacionados]


def _lados(analise, chamadas: list[dict]) -> dict:
    """Mostra o resultado da análise de lados e devolve o que vai para o relatório."""
    feitas = [ch for ch in chamadas if ch["prompt"] == "lados"]
    registro = {
        "quantos": len(analise.lados), "questao": analise.questao, "motivo": analise.motivo,
        "tentativas": len(feitas), "lado_de_emergencia": bool(analise.problemas), "invalida_porque": analise.problemas,
        "ajustes": analise.ajustes, "atores_sem_entrada": analise.faltam, "textos_cortados_na_analise": analise.cortes,
        "sem_sim_e_nao": analise.sem_sim_e_nao,
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
    print(f"  lados: {registro['quantos']} · {registro['tentativas']} tentativa(s) · {registro['segundos']:.1f} s · "
          f"tokens {registro['tokens_entrada']} + {registro['tokens_saida']}")
    for corte in analise.cortes:
        print(f"    TEXTO CORTADO NA ANÁLISE: {corte['fonte']} · lidos {corte['lido']} de {corte['texto']} caracteres")
    print(f"    questão: {registro['questao'] or '(sem disputa)'}")
    for e in registro["respostas_por_ator"]:
        quase = f" (quase literal, {e['diferencas']} palavra(s) diferente(s); o LLM escreveu: \"{e['trecho_do_llm']}\")" if e["trecho_do_llm"] else ""
        conferencia = (f"comprovada ({e['prova']})" if e["prova"] else "SEM A RESPOSTA DO ATOR") if e["comprovada"] else "TRECHO NÃO ENCONTRADO"
        print(f"    resposta de {e['ator']}: {e['resposta'] or '-'} · {conferencia} "
              f"em {e['veiculo'] or '-'}: \"{e['trecho']}\"{quase}")
    for i, lado in enumerate(registro["lados"], 1):
        resposta = f"[{lado['resposta']}] " if lado["resposta"] else ""
        print(f"    lado {i}{' (FINO)' if lado['fino'] else ''}: {resposta}{lado['posicao']}")
        print(f"            atores: {', '.join(lado['atores']) or '-'} · veículos: {', '.join(lado['veiculos'])} · "
              f"frases dos textos com os atores: {lado['frases_com_os_atores']}")
    for i, ressalva in enumerate(registro["ressalvas"], 1):
        print(f"    ressalva {i}: {ressalva['posicao']}")
        print(f"            grupos: {', '.join(ressalva['grupos']) or '-'} · veículos: {', '.join(ressalva['veiculos'])} · "
              f"trecho: \"{ressalva['trecho']}\"")
    for ressalva in registro["ressalvas_descartadas"]:
        print(f"    ressalva descartada ({ressalva['motivo']}): {ressalva['posicao']} · grupos: {', '.join(ressalva['grupos']) or '-'} · "
              f"trecho: \"{ressalva['trecho']}\"")
    print(f"    motivo: {registro['motivo'] or '-'}")
    for ajuste in analise.ajustes:
        print(f"    ajuste: {ajuste}")
    if analise.primeira is not None and analise.primeira.problemas:
        print(f"    PRIMEIRA TENTATIVA RECUSADA: {'; '.join(analise.primeira.problemas)}")
        print(f"    resposta recusada: {json.dumps(analise.primeira.resposta, ensure_ascii=False)}")
    elif analise.primeira is not None:
        if analise.primeira.faltam:
            print(f"    PRIMEIRA TENTATIVA SEM A ENTRADA DE: {'; '.join(analise.primeira.faltam)} (a nova tentativa pediu a entrada)")
        for r in analise.primeira.recusados:
            print(f"    PRIMEIRA TENTATIVA COM TRECHO RECUSADO: {r.ator}: \"{r.trecho}\" ({r.motivo}; a nova tentativa pediu o trecho)")
        if analise.primeira.sem_sim_e_nao:
            print(f"    PRIMEIRA TENTATIVA SEM \"SIM\" E \"NÃO\": {analise.primeira.sem_sim_e_nao} (a nova tentativa pediu as duas)")
        print(f"    primeira resposta: {json.dumps(analise.primeira.resposta, ensure_ascii=False)}")
    if analise.segunda is not None:
        sem = "; ".join([*analise.faltam, *(r.ator for r in analise.recusados)])
        motivo = "; ".join(analise.segunda.problemas) or analise.segunda.sem_sim_e_nao or f"{len(analise.segunda.lados)} lado(s)"
        print(f"    NOVA TENTATIVA RECUSADA (fica a primeira{f', sem {sem}' if sem else ''}): {motivo}")
        print(f"    resposta recusada: {json.dumps(analise.segunda.resposta, ensure_ascii=False)}")
    if analise.sem_sim_e_nao:
        print(f"    FICOU SEM \"SIM\" E \"NÃO\" (a regra não derruba a análise): {analise.sem_sim_e_nao}")
    elif analise.faltam:
        print(f"    A ENTRADA NÃO VEIO NA NOVA TENTATIVA, o ator saiu: {'; '.join(analise.faltam)}")
    for r in analise.recusados if analise.segunda is None else ():
        print(f"    TRECHO SEM VALER{' NA NOVA TENTATIVA' if analise.primeira is not None else ''}, o ator saiu: {r.ator}: "
              f"\"{r.trecho}\" ({r.motivo})")
    if analise.problemas:
        print(f"    AS DUAS TENTATIVAS FALHARAM, a pauta ficou com o lado de emergência: {'; '.join(analise.problemas)}")
        print(f"    resposta do LLM: {json.dumps(analise.resposta, ensure_ascii=False)}")
    return registro


def _primeira_pessoa(episodio: dict) -> list[dict]:
    """As frases dos analistas com primeira pessoa do plural ("nós", "precisamos"). Só diagnóstico: pega também
    o "vamos" de quem conduz a conversa."""
    achadas = []
    for turno in episodio.get("roteiro_podcast") or []:
        if not isinstance(turno, dict) or qa._palavras_do_nome(turno.get("personagem")) == [qa.HELENA]:
            continue
        for frase in qa.frases(turno.get("fala", "")):
            marcas = [m.group() for m in _NOS.finditer(frase) if m.group().lower() not in _NAO_E_NOS]
            if marcas:
                achadas.append({"personagem": turno.get("personagem"), "marcas": marcas, "frase": frase})
    return achadas


def _cortes(entrada) -> list[dict]:
    """Por artigo da pauta: quanto do texto entrou na mensagem, que parágrafos entraram, por quê, e os que ficaram de fora
    tendo trecho de evidência."""
    recortes = {i: recorte for i, recorte in enumerate(entrada.recortes)}   # na mesma ordem dos cortes, só os que a análise leu
    return [
        {**corte, "teto": TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO,
         "cortado_pelo_orcamento": max(min(corte["texto"], TETO_PRINCIPAL if i == 0 else TETO_RELACIONADO) - corte["incluido"], 0),
         "paragrafos_do_texto": recortes.get(i, {}).get("paragrafos"),
         "paragrafos_que_entraram": recortes.get(i, {}).get("entraram", []),
         "paragrafos_com_trecho_fora": recortes.get(i, {}).get("fora", [])}
        for i, corte in enumerate(entrada.cortes)
    ]


def _faixas(entraram: list[dict]) -> str:
    """Os parágrafos que entraram, agrupados pelo motivo: "§2-3 lide · §4-9 ordem do texto · §14 trecho do lado 1"."""
    grupos: list[list] = []   # [primeiro, último, motivo, cortado]
    for item in entraram:
        motivo = item["motivo"] + (" (cortado)" if item.get("cortado") else "")
        if grupos and grupos[-1][2] == motivo and grupos[-1][1] == item["paragrafo"] - 1:
            grupos[-1][1] = item["paragrafo"]
        else:
            grupos.append([item["paragrafo"], item["paragrafo"], motivo])
    return " · ".join(f"§{a}{'' if a == b else f'-{b}'} {motivo}" for a, b, motivo in grupos) or "nada"


def _mostrar_cortes(cortes: list[dict], rotulo: str) -> None:
    for corte in cortes:
        print(f"  texto na {rotulo}: {corte['fonte']} · {corte['incluido']} de {corte['texto']} caracteres "
              f"(teto {corte['teto']}; ficaram fora {corte['cortado_pelo_orcamento']} do que o teto deixaria)")
        if corte["paragrafos_do_texto"] is not None:
            print(f"    parágrafos ({len(corte['paragrafos_que_entraram'])} de {corte['paragrafos_do_texto']}): "
                  f"{_faixas(corte['paragrafos_que_entraram'])}")
        for fora in corte["paragrafos_com_trecho_fora"]:
            print(f"    FICOU DE FORA na {rotulo}: §{fora['paragrafo']} ({fora['motivo']}, {fora['caracteres']} caracteres)")


def _palavras_que_contam(texto) -> set[str]:
    return {palavra for palavra in qa._palavras_do_nome(texto) if len(palavra) >= MIN_LETRAS_DA_PALAVRA}


def _trechos_nas_falas(episodio: dict, analise) -> list[dict]:
    """Para cada trecho de evidência de cada lado, a fala de analista que mais palavras dele repete.

    Só diagnóstico: conta as palavras de MIN_LETRAS_DA_PALAVRA letras ou mais do trecho que estão
    na fala, sem acento nem caixa. Não diz se a fala é fiel ao trecho, só onde olhar.
    """
    try:
        do_lado = qa.lado_de_cada_analista(episodio, analise.lados)
        falas = [(n, str(t["personagem"]), str(t["fala"])) for n, t in enumerate(episodio["roteiro_podcast"], 1)
                 if qa._palavras_do_nome(t.get("personagem")) != [qa.HELENA]]
    except (KeyError, TypeError, AttributeError):
        return []
    achados = []
    for i, lado in enumerate(analise.lados):
        analista = next((nome for nome, indice in do_lado.items() if indice == i), None)
        for trecho in lado.trechos:
            do_trecho = _palavras_que_contam(trecho)
            melhor = max(falas, key=lambda fala: len(do_trecho & _palavras_que_contam(fala[2])), default=None)
            do_analista = max((fala for fala in falas if fala[1] == analista),
                              key=lambda fala: len(do_trecho & _palavras_que_contam(fala[2])), default=None)

            def medida(fala):
                return None if fala is None else {
                    "turno": fala[0], "personagem": fala[1], "fala": fala[2],
                    "palavras_em_comum": sorted(do_trecho & _palavras_que_contam(fala[2])),
                    "proporcao": round(len(do_trecho & _palavras_que_contam(fala[2])) / max(len(do_trecho), 1), 2),
                }
            achados.append({"lado": i + 1, "atores": list(lado.atores), "analista_do_lado": analista, "trecho": trecho,
                            "palavras_do_trecho": len(do_trecho), "melhor_fala_do_analista": medida(do_analista),
                            "melhor_fala_de_qualquer_analista": medida(melhor)})
    return achados


def _plano_seguido(episodio: dict, analise, orc) -> dict:
    """Se o roteiro seguiu o plano das falas do bloco, quem fecha o episódio e, de cada analista, as palavras, o alvo e
    as frases do lado dele no recorte (só diagnóstico; o QA não cobra o plano nem quem fecha).

    O analista de cada lado vem da correspondência um a um do QA; com um lado só, é o único analista. Na ordem, 0 é a
    Helena, i é o analista do lado i e "?" é quem não tem lado.
    """
    roteiro = episodio["roteiro_podcast"]
    nomes = list(dict.fromkeys(str(t["personagem"]) for t in roteiro))
    analistas = [nome for nome in nomes if qa._palavras_do_nome(nome) != [qa.HELENA]]
    if len(analise.lados) == 1:
        do_lado = {nome: 0 for nome in analistas[:1]} if len(analistas) == 1 else {}
    else:
        do_lado = qa.lado_de_cada_analista(episodio, analise.lados)

    def codigo(nome: str):
        return 0 if qa._palavras_do_nome(nome) == [qa.HELENA] else (do_lado[nome] + 1 if nome in do_lado else "?")

    plano = orc.plano
    ordem = [codigo(str(t["personagem"])) for t in roteiro]
    palavras = qa.palavras_por_personagem(roteiro)
    por_personagem = {}
    for nome in nomes:
        i = codigo(nome)
        falas = [len(str(t["fala"]).split()) for t in roteiro if str(t["personagem"]) == nome]
        por_personagem[nome] = {
            "falas": len(falas), "media": round(sum(falas) / len(falas)), "falas_do_plano": plano.falas[i] if i != "?" else None,
            "tamanho_do_plano": plano.tamanhos[i] if i != "?" else None,
        }
    analistas_por_lado = [
        {"personagem": nome, "lado": do_lado[nome] + 1, "palavras": palavras[nome], "alvo": orc.analistas[do_lado[nome]],
         "frases_do_lado": analise.lados[do_lado[nome]].mencoes,
         "fino": len(analise.lados) >= 2 and analise.lados[do_lado[nome]].fino}
        for nome in analistas if nome in do_lado
    ]
    ultimo = str(roteiro[-1]["personagem"])
    return {
        "plano": {"falas": list(plano.falas), "tamanhos": list(plano.tamanhos), "ordem": list(plano.ordem)},
        "ordem_do_roteiro": ordem, "ordem_igual_ao_plano": ordem == list(plano.ordem), "por_personagem": por_personagem,
        "termina_com": ultimo, "termina_com_analista": qa._palavras_do_nome(ultimo) != [qa.HELENA],
        "analistas": analistas_por_lado,
    }


def _analisar(n: int, caso: str, pauta: ag.Pauta, ids: dict, summarizer: Summarizer, monitor: ProviderMonitorado) -> dict:
    """Só a análise de lados de uma pauta, sobre os textos inteiros, e o recorte que a geração receberia."""
    relatorio = _apresentar("Pauta", n, caso, pauta, ids)
    primeira = len(monitor.chamadas)
    entrada, analise = summarizer.preparar(*_fontes(pauta))
    relatorio["lados"] = _lados(analise, monitor.chamadas[primeira:])
    relatorio["cortes_na_geracao"] = _cortes(entrada)
    relatorio["chars_da_entrada_do_episodio"] = len(entrada.texto)
    _mostrar_cortes(relatorio["cortes_na_geracao"], "geração")
    return relatorio


def _gerar(n: int, caso: str, pauta: ag.Pauta, ids: dict, summarizer: Summarizer, monitor: ProviderMonitorado,
           pasta: Path, carimbo: str) -> dict:
    """Gera o episódio de uma pauta e devolve o relatório dela."""
    relatorio = _apresentar("Episódio", n, caso, pauta, ids)
    proporcao = summarizer.chars_por_token
    primeira = len(monitor.chamadas)
    inicio = time.perf_counter()
    try:
        episodio = summarizer.process(*_fontes(pauta))
        situacao = "aprovado"
    except QAReprovado as e:
        situacao = f"reprovado pelo QA ({e})"
        episodio = summarizer.ultimo_diagnostico.get("episodio")   # a última versão inteira, com a correção já aplicada
    except Exception as e:
        situacao = f"falhou ({type(e).__name__}: {str(e)[:300]})"
        episodio = None
    segundos = time.perf_counter() - inicio
    chamadas = [{k: v for k, v in ch.items() if k != "resposta"} for ch in monitor.chamadas[primeira:]]
    diagnostico = summarizer.ultimo_diagnostico

    relatorio.update({
        "situacao": situacao, "segundos": round(segundos, 1), "chars_por_token_no_inicio": round(proporcao, 2),
        "chamadas": chamadas,
        "problemas_antes_da_revisao": diagnostico.get("problemas"),
        "tipo_de_correcao": diagnostico.get("correcao"),
        "titulos_reprovados": diagnostico.get("titulos_reprovados") or [],
        "problemas_depois_da_revisao": diagnostico.get("problemas_da_revisao"),
    })
    primeira_versao = diagnostico.get("primeira_versao")
    if isinstance(primeira_versao, dict) and diagnostico.get("correcao"):
        relatorio["primeira_versao"] = {
            "titulo": primeira_versao.get("titulo_reescrito"), "resumo_didatico": primeira_versao.get("resumo_didatico"),
        }
        try:   # para medir quanto a correção acrescentou a cada personagem (só diagnóstico)
            roteiro = primeira_versao["roteiro_podcast"]
            relatorio["primeira_versao"]["palavras_por_personagem"] = qa.palavras_por_personagem(roteiro)
            relatorio["primeira_versao"]["falas_por_personagem"] = {
                nome: sum(1 for t in roteiro if t["personagem"] == nome) for nome in qa.palavras_por_personagem(roteiro)}
        except (KeyError, TypeError, AttributeError):   # roteiro fora do formato
            pass
    if diagnostico.get("lados") is not None:
        relatorio["lados"] = _lados(diagnostico["lados"], chamadas)
    for nome, entrada in (("cortes_na_geracao", diagnostico.get("entrada")), ("cortes_na_revisao", diagnostico.get("revisao"))):
        if entrada is not None:
            relatorio[nome] = _cortes(entrada)

    for ch in chamadas:
        if "erro" in ch:
            print(f"  {ch['prompt']}: FALHOU em {ch['segundos']:.0f} s — {ch['erro']}")
            continue
        total = ch["tokens_entrada"] + ch["tokens_saida"]
        ch["fracao_da_janela"] = round(total / settings.ollama_num_ctx, 2)
        alerta = "  ALERTA: perto do limite de num_ctx" if total >= ALERTA_DA_JANELA * settings.ollama_num_ctx else ""
        print(f"  {ch['prompt']}: {ch['tokens_entrada']} + {ch['tokens_saida']} tokens = {total} de {settings.ollama_num_ctx} "
              f"({total / settings.ollama_num_ctx:.0%}) · {ch['segundos']:.0f} s{alerta}")
    for nome, rotulo in (("cortes_na_geracao", "geração"), ("cortes_na_revisao", CORRECOES.get(relatorio["tipo_de_correcao"], "revisão"))):
        _mostrar_cortes(relatorio.get(nome, []), rotulo)
    print(f"  QA antes da correção: {relatorio['problemas_antes_da_revisao'] or 'sem problemas'}")
    if relatorio["tipo_de_correcao"]:
        print(f"  correção usada: {CORRECOES[relatorio['tipo_de_correcao']]}")
    for recusado in relatorio["titulos_reprovados"]:
        print(f"  título reprovado: {recusado['titulo']}")
    if relatorio["problemas_depois_da_revisao"] is not None:
        print(f"  QA depois da correção: {relatorio['problemas_depois_da_revisao'] or 'sem problemas'}")
    print(f"  situação: {situacao} · {segundos:.0f} s no total")

    if episodio is not None:
        citadas = episodio.get("fontes_citadas") if isinstance(episodio.get("fontes_citadas"), list) else []
        relatorio.update(
            houve_divergencia=episodio.get("houve_divergencia"), fontes_citadas=citadas,
            titulo=episodio.get("titulo_reescrito"),
            analistas=list(dict.fromkeys(
                str(t.get("personagem")) for t in episodio.get("roteiro_podcast") or []
                if isinstance(t, dict) and qa._palavras_do_nome(t.get("personagem")) != [qa.HELENA]
            )),
            veiculos_sem_citacao=[v for v in pauta.veiculos if not any(qa.mesmo_veiculo(v, f) for f in citadas)],
            fontes_fora_da_pauta=[f for f in citadas if not any(qa.mesmo_veiculo(v, f) for v in pauta.veiculos)],
            resumo_didatico=episodio.get("resumo_didatico"),
            primeiras_falas=(episodio.get("roteiro_podcast") or [])[:FALAS_NO_RELATORIO],
            personagens=episodio.get("personagens"),
            turnos=len(episodio.get("roteiro_podcast") or []),
            frases_na_primeira_pessoa=_primeira_pessoa(episodio),
        )
        analise = diagnostico.get("lados")
        orc = diagnostico.get("orcamento")
        if orc is not None:
            relatorio["orcamento"] = {"helena": orc.helena, "analistas": list(orc.analistas), "total": orc.total,
                                      "palavras_do_texto": orc.palavras_do_texto, "reduzido": orc.reduzido,
                                      "turnos": orc.turnos, "falas": list(orc.plano.falas),
                                      "tamanhos": list(orc.plano.tamanhos), "ordem": list(orc.plano.ordem)}
        try:
            relatorio["palavras_por_personagem"] = qa.palavras_por_personagem(episodio["roteiro_podcast"])
            antes = (relatorio.get("primeira_versao") or {}).get("palavras_por_personagem")
            if antes is not None:   # quanto a correção acrescentou (ou tirou) de cada personagem e do total
                relatorio["acrescimo_da_correcao"] = {
                    **{nome: n - antes.get(nome, 0) for nome, n in relatorio["palavras_por_personagem"].items()},
                    "total": sum(relatorio["palavras_por_personagem"].values()) - sum(antes.values())}
            relatorio["limites_por_personagem"] = qa.limites_de_cada_personagem(episodio, analise.lados, orc) if analise else None
            if analise and orc is not None:   # quanto cada personagem fica do alvo que o bloco pediu: só diagnóstico
                def medida(palavras: int, alvo: int) -> dict:
                    return {"alvo": alvo, "palavras": palavras, "proporcao": round(palavras / alvo, 2),
                            "acima_do_alvo": max(palavras - alvo, 0)}
                alvos = qa.alvo_de_cada_personagem(episodio, analise.lados, orc)
                relatorio["alvo_por_personagem"] = {nome: medida(relatorio["palavras_por_personagem"][nome], alvo)
                                                    for nome, alvo in alvos.items()}
                relatorio["alvo_do_total"] = medida(sum(relatorio["palavras_por_personagem"].values()), orc.total)
            relatorio["lado_de_cada_analista"] = qa.lado_de_cada_analista(episodio, analise.lados) if analise else None
            if analise and orc is not None:
                relatorio["plano_seguido"] = _plano_seguido(episodio, analise, orc)
            relatorio["lado_fino_acima_do_teto"] = {   # o teto do analista de lado fino é só diagnóstico: o QA não cobra
                nome: relatorio["palavras_por_personagem"][nome] for nome in qa.analistas_de_lado_fino(episodio, analise.lados)
                if relatorio["palavras_por_personagem"][nome] > qa.MAX_LADO_FINO
            } if analise else {}
        except (KeyError, TypeError, AttributeError):   # episódio fora do formato
            pass
        print(f"  turnos: {relatorio['turnos']} · palavras: {relatorio.get('palavras_por_personagem')} · "
              f"limites: {relatorio.get('limites_por_personagem')}")
        if relatorio.get("acrescimo_da_correcao") is not None:
            print(f"  a correção acrescentou: {relatorio['acrescimo_da_correcao']} (primeira versão: "
                  f"{relatorio['primeira_versao']['palavras_por_personagem']}, falas {relatorio['primeira_versao']['falas_por_personagem']})")
        if "orcamento" in relatorio:
            o = relatorio["orcamento"]
            print(f"  orçamento: {o['palavras_do_texto']} palavras de texto → Helena {o['helena']}, analistas {o['analistas']}, "
                  f"total {o['total']}{' (reduzido)' if o['reduzido'] else ''}; plano: "
                  + ", ".join(f"{'Helena' if i == 0 else f'lado {i}'} {n}×{tam}" for i, (n, tam) in enumerate(zip(o['falas'], o['tamanhos'])))
                  + f"; {o['turnos']} turnos ({' '.join('H' if i == 0 else str(i) for i in o['ordem'])})")
            for nome, a in [*(relatorio.get("alvo_por_personagem") or {}).items(), ("total", relatorio.get("alvo_do_total"))]:
                if a:
                    print(f"  diagnóstico: {nome} com {a['palavras']} palavras para o alvo de {a['alvo']} ({a['proporcao']:.0%})"
                          + (f", {a['acima_do_alvo']} acima" if a["acima_do_alvo"] else ""))
        if seguido := relatorio.get("plano_seguido"):
            print("  plano seguido: " + "; ".join(
                f"{nome} {d['falas']} falas (plano {d['falas_do_plano']}) de {d['media']} palavras em média (plano {d['tamanho_do_plano']})"
                for nome, d in seguido["por_personagem"].items())
                + f" · ordem {'igual ao' if seguido['ordem_igual_ao_plano'] else 'DIFERENTE do'} plano "
                  f"({' '.join('H' if i == 0 else str(i) for i in seguido['ordem_do_roteiro'])})")
            print(f"  fecha o episódio: {seguido['termina_com']}" + (" (ANALISTA: o plano termina com a Helena)" if seguido["termina_com_analista"] else ""))
            for a in seguido["analistas"]:
                print(f"  analista {a['personagem']}: lado {a['lado']}{' (FINO)' if a['fino'] else ''}, {a['palavras']} palavras para o alvo "
                      f"de {a['alvo']}, {a['frases_do_lado']} frases do lado no recorte")
        for nome, palavras in (relatorio.get("lado_fino_acima_do_teto") or {}).items():
            print(f"  diagnóstico: {nome}, analista de lado fino, com {palavras} palavras (o prompt pede até {qa.MAX_LADO_FINO})")
        if analise is not None:
            relatorio["nomes_do_bloco"] = nomes_dos_analistas(analise.lados)
            print(f"  nomes que o bloco deu aos analistas: {', '.join(relatorio['nomes_do_bloco'])}")
        print(f"  papéis: {[(p.get('nome'), p.get('papel')) for p in relatorio['personagens'] or [] if isinstance(p, dict)]}")
        for item in relatorio["frases_na_primeira_pessoa"]:
            print(f"  primeira pessoa ({item['personagem']}; {', '.join(item['marcas'])}): {item['frase']}")
        print(f"  título: {relatorio['titulo']}")
        print(f"  analistas: {', '.join(relatorio['analistas']) or 'nenhum'} · houve_divergencia: {relatorio['houve_divergencia']} · "
              f"fontes_citadas: {citadas} · veículos da pauta: {list(pauta.veiculos)}")
        print(f"  veículos sem citação: {relatorio['veiculos_sem_citacao'] or 'nenhum'} · "
              f"fontes fora da pauta: {relatorio['fontes_fora_da_pauta'] or 'nenhuma'}")
        print(f"  resumo_didatico: {relatorio['resumo_didatico']}")
        for fala in relatorio["primeiras_falas"]:
            print(f"  [{fala.get('personagem')}] {fala.get('fala')}")
        analise = diagnostico.get("lados")
        if analise is not None and analise.ressalvas:
            try:
                achadas = qa.perguntas_das_ressalvas(episodio, analise.ressalvas)
            except (KeyError, TypeError, AttributeError):   # episódio fora do formato: não há falas para conferir
                achadas = [[] for _ in analise.ressalvas]
            relatorio["perguntas_das_ressalvas"] = [
                [{"frase": frase, "fala_com_pergunta": com_pergunta} for frase, com_pergunta in da_ressalva] for da_ressalva in achadas
            ]
            for i, da_ressalva in enumerate(achadas, 1):
                if not da_ressalva:
                    print(f"  ressalva {i}: NENHUMA frase da Helena com veículo, grupo e verbo de posição")
                for frase, com_pergunta in da_ressalva:
                    print(f"  ressalva {i}, na fala da Helena ({'com' if com_pergunta else 'SEM'} pergunta): {frase}")
        if analise is not None and len(analise.lados) >= 2:
            relatorio["trechos_nas_falas"] = _trechos_nas_falas(episodio, analise)
            for item in relatorio["trechos_nas_falas"]:
                fala = item["melhor_fala_do_analista"]
                onde = (f"turno {fala['turno']} de {fala['personagem']}, {fala['proporcao']:.0%} das {item['palavras_do_trecho']} palavras "
                        f"({', '.join(fala['palavras_em_comum']) or 'nenhuma'})") if fala else "SEM ANALISTA PARA O LADO"
                outra = item["melhor_fala_de_qualquer_analista"]
                if outra and fala and outra["personagem"] != fala["personagem"] and outra["proporcao"] > fala["proporcao"]:
                    onde += f" · mais palavras na fala de {outra['personagem']} (turno {outra['turno']}, {outra['proporcao']:.0%})"
                print(f"  trecho do lado {item['lado']} nas falas: \"{item['trecho']}\" → {onde}")
        slug = re.sub(r"\W+", "-", str(episodio.get("titulo_reescrito", "")).lower())[:40].strip("-")
        arquivo = pasta / f"{carimbo}_{n}_{caso}{'' if situacao == 'aprovado' else '_reprovado'}_{slug}.json"
        arquivo.write_text(json.dumps(episodio, ensure_ascii=False, indent=1), encoding="utf-8")
        relatorio["arquivo"] = str(arquivo)
        print(f"  episódio gravado em {arquivo}")
    return relatorio


def main() -> None:
    args = _argumentos()
    diag._log_no_console()
    carimbo = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    pasta = diag._pasta() / args.pasta
    pasta.mkdir(parents=True, exist_ok=True)
    if not args.amostra:
        args.amostra = json.loads(Path(args.repetir).read_text(encoding="utf-8"))["amostra"]

    with trava.trava_do_modelo():
        _rodar(args, pasta, carimbo)


def _rodar(args: argparse.Namespace, pasta: Path, carimbo: str) -> None:
    """A rodada, com a trava do modelo já presa."""
    disponivel, resumo = maquina.estado_da_maquina()
    print(f"== Máquina: {resumo} · num_ctx {settings.ollama_num_ctx} (reserva de saída "
          f"{min(settings.ollama_num_predict, settings.llm_reserva_saida)} tokens) ==")
    monitor = ProviderMonitorado(get_provider(settings), args.min_memoria, args.max_cpu, args.retomar_cpu,
                                 args.log_ollama)
    monitor.conferir_memoria(disponivel)        # antes de começar
    monitor.conferir_antes_de_carregar()        # a GPU, antes de carregar o modelo (só com o Ollama)
    summarizer = Summarizer(provider=monitor)
    candidatos, ids = diag._carregar_amostra(args.amostra)
    if args.repetir or args.pautas:
        escolhidas = _pautas_dadas(args, ids)
    else:
        finais = _pautas_finais(args, monitor, candidatos, ids)   # a etapa 3 também passa pelas travas
        escolhidas = _escolher(finais, ids, args.max_pautas)
        print(f"\n{sum(1 for p in finais if p.relacionados)} pauta(s) final(is) com várias fontes")
    print(f"\n{len(escolhidas)} pauta(s) para {'analisar os lados' if args.so_lados else 'gerar'}: "
          f"{', '.join(caso for caso, _ in escolhidas)}")

    relatorios = []
    caminho = pasta / f"{'lados' if args.so_lados else 'relatorio'}_{carimbo}.json"

    def gravar() -> None:
        caminho.write_text(json.dumps(
            {"amostra": args.amostra, "limiar": None if args.repetir or args.pautas else args.limiar,   # sem etapa 3, não há limiar
             "num_ctx": settings.ollama_num_ctx,
             "gpu": {"antes_da_carga": monitor.gpu_antes_da_carga or [], "depois_da_carga": monitor.gpu_depois_da_carga},
             "episodios": relatorios},
            ensure_ascii=False, indent=1, default=str,
        ), encoding="utf-8")

    try:
        for n, (caso, pauta) in enumerate(escolhidas, 1):
            if args.so_lados:
                relatorios.append(_analisar(n, caso, pauta, ids, summarizer, monitor))
            else:
                relatorios.append(_gerar(n, caso, pauta, ids, summarizer, monitor, pasta, carimbo))
            gravar()  # a cada pauta: se a máquina cair no meio, fica o que já foi medido
    finally:
        gravar()
        print(f"\nRelatório: {caminho} ({len(relatorios)} de {len(escolhidas)} pauta(s))")


if __name__ == "__main__":
    try:
        main()
    except trava.TravaOcupada as e:
        sys.exit(f"PAREI antes de começar: {e}.")
    except maquina.ExecucaoInterrompida as e:
        sys.exit(f"\nPAREI: {e}.")
