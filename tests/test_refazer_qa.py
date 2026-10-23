"""Testes de scripts/refazer_qa.py: a entrada do QA remontada do relatório e a comparação com a situação gravada."""
import json
from pathlib import Path

import refazer_qa
from techdigest.ai import qa

TEXTO = "A prefeitura de Curitiba multou a Construtora Alfa por atrasar a entrega da ponte. A empresa vai recorrer da multa."


def _episodio() -> dict:
    """Um episódio que passa no QA de agora: um lado, um analista e as palavras na faixa."""
    fala = " ".join(["palavra"] * max(qa.MIN_POR_PERSONAGEM, qa.MIN_TOTAL // 2))
    return {
        "titulo_reescrito": "Prefeitura multa construtora", "resumo_didatico": "Uma frase. " * qa.MIN_FRASES_RESUMO,
        "pontos_chave": ["a", "b"], "por_que_importa": "Importa.",
        "personagens": [{"nome": "Helena", "papel": "apresentadora"}, {"nome": "Ramos", "papel": "analista de obras"}],
        "roteiro_podcast": [{"personagem": "Helena", "fala": fala}, {"personagem": "Ramos", "fala": fala}],
        "houve_divergencia": False, "fontes_citadas": ["Jornal do Vale"],
    }


RESSALVA = {"grupos": ["engenheiros"], "posicao": "Há risco.", "veiculos": ["Jornal do Vale"], "trecho": "A empresa vai recorrer da multa"}


def _gravar(pasta, situacao: str, problemas: list[str], lado: dict, ressalvas=()) -> str:
    amostra = pasta / "amostra.json"
    amostra.write_text(json.dumps({"candidatos": [{"id": 7, "veiculo": "Jornal do Vale", "titulo": "Prefeitura multa construtora",
                                                    "texto": TEXTO}]}), encoding="utf-8")
    episodio = pasta / "episodio.json"
    episodio.write_text(json.dumps(_episodio(), ensure_ascii=False), encoding="utf-8")
    relatorio = pasta / "relatorio_20261014-210000.json"
    relatorio.write_text(json.dumps({"amostra": str(amostra), "episodios": [{
        "episodio": 1, "caso": "controle", "situacao": situacao, "problemas_depois_da_revisao": problemas, "arquivo": str(episodio),
        "artigos": [{"id": 7, "veiculo": "Jornal do Vale", "titulo": "Prefeitura multa construtora"}],
        "cortes_na_geracao": [{"fonte": "Jornal do Vale", "texto": len(TEXTO), "incluido": len(TEXTO)}],
        "lados": {"lados": [lado], "ressalvas": list(ressalvas)},
    }]}, ensure_ascii=False), encoding="utf-8")
    return relatorio


NEUTRO = {"posicao": "relato dos fatos, sem lados definidos", "atores": [], "veiculos": ["Jornal do Vale"], "resposta": "",
          "trechos": [], "fino": False}


def test_a_entrada_do_qa_e_remontada_do_relatorio_e_da_amostra(tmp_path):
    relatorio = json.loads(_gravar(tmp_path, "aprovado", [], NEUTRO, [RESSALVA]).read_text(encoding="utf-8"))
    candidatos = refazer_qa._amostra(relatorio)
    veiculos, lados, ressalvas, textos, orc = refazer_qa.entrada_do_qa(relatorio["episodios"][0], candidatos)
    assert veiculos == ["Jornal do Vale"] and textos == [f"Prefeitura multa construtora\n{TEXTO}"]
    assert orc is None                      # relatório sem os parágrafos que entraram: sem orçamento, valem os mínimos de antes
    assert lados[0].posicao == "relato dos fatos, sem lados definidos" and lados[0].mencoes is None
    assert [(r.grupos, r.trecho) for r in ressalvas] == [(("engenheiros",), "A empresa vai recorrer da multa")]
    # o lado fino vem da contagem das frases, quando o relatório a tem, ou da marca "fino" dos relatórios mais antigos
    item = relatorio["episodios"][0]
    item["lados"]["lados"] = [{**NEUTRO, "atores": ["Construtora Alfa"], "fino": True}]
    assert refazer_qa.entrada_do_qa(item, candidatos)[1][0].mencoes == 1
    item["lados"]["lados"] = [{**NEUTRO, "atores": ["Construtora Alfa"], "fino": True, "frases_com_os_atores": 4}]
    assert refazer_qa.entrada_do_qa(item, candidatos)[1][0].mencoes == 4


def test_o_orcamento_e_o_gravado_ou_o_recalculado_dos_paragrafos_que_entraram(tmp_path):
    from techdigest.ai.orcamento import Orcamento, orcamento
    relatorio = json.loads(_gravar(tmp_path, "aprovado", [], NEUTRO).read_text(encoding="utf-8"))
    candidatos = refazer_qa._amostra(relatorio)
    item = relatorio["episodios"][0]
    # o recorte gravado: o parágrafo único, com os 40 primeiros caracteres (7 palavras)
    item["cortes_na_geracao"][0]["paragrafos_que_entraram"] = [{"paragrafo": 1, "motivo": "lide", "caracteres": 40}]
    assert refazer_qa.palavras_recebidas(item, candidatos) == len(TEXTO[:40].split()) == 7
    lados = refazer_qa.entrada_do_qa(item, candidatos)[1]
    assert refazer_qa.entrada_do_qa(item, candidatos)[4] == orcamento(lados, 7)
    # o relatório que já grava o orçamento vale como está
    item["orcamento"] = {"helena": 200, "analistas": [250], "total": 450, "palavras_do_texto": 256, "reduzido": True}
    assert refazer_qa.entrada_do_qa(item, candidatos)[4] == Orcamento(200, (250,), 256, True)


def test_episodio_reprovado_que_o_qa_de_agora_aprova_aparece_como_mudanca(tmp_path):
    relatorio = _gravar(tmp_path, "reprovado pelo QA (revisão ainda reprovada)", ["Helena com 230 palavras (alvo 240-650)"], NEUTRO)
    [refeito] = refazer_qa.refazer(relatorio)
    assert (refeito.aprovado_antes, refeito.aprovado_agora, refeito.mudou) == (False, True, True)
    texto = refazer_qa.montar({relatorio: [refeito]}, "14/10/2026 21:00:00")
    assert "  ep1 (controle): REPROVADO -> aprovado   <- MUDA" in texto
    assert "      deixou de valer: Helena com 230 palavras (alvo 240-650)" in texto
    assert "o checar_fidelidade não acha nada que o QA deixe passar" in texto
    # aprovado quando gerado e aprovado agora: não muda
    [igual] = refazer_qa.refazer(_gravar(tmp_path, "aprovado", [], NEUTRO))
    assert not igual.mudou and igual.problemas_agora == []
    # e o que passa a reprovar mostra o problema do QA de agora: a ressalva que a Helena não traz
    [piorou] = refazer_qa.refazer(_gravar(tmp_path, "aprovado", [], NEUTRO, [RESSALVA]))
    assert (piorou.aprovado_antes, piorou.aprovado_agora, piorou.mudou) == (True, False, True)
    assert piorou.problemas_agora[0].startswith("ressalva 1 (engenheiros; Jornal do Vale): não aparece numa frase da Helena")
    assert "      problema do QA de agora: ressalva 1 (engenheiros" in refazer_qa.montar({Path("r.json"): [piorou]}, "agora")
