"""O resumo por lote (scripts/resumo_lotes.py) com as execuções interrompidas e as que nem começaram."""
import resumo_lotes as rl

LOG = (
    "16/10 08:00:00 │ ERROR    │ techdigest.pipeline │ Execução não começou: o modelo está em uso por "
    "scripts/testar_episodio.py --amostra x (PID 1, desde 16/10 07:15, na pasta /x); espere essa execução terminar\n"
    "16/10 09:00:00 │ INFO     │ techdigest.pipeline │ === TechDigest iniciando ===\n"
    "16/10 09:05:00 │ WARNING  │ techdigest.pipeline │ Item pulado pelo QA: 'Artigo' — reprovado ↳ https://x.example\n"
    "16/10 09:20:00 │ ERROR    │ techdigest.pipeline │ Execução interrompida: memória disponível em 3.1 GiB, abaixo do "
    "mínimo de 4.0 GiB (7 notícia(s) entregue(s) antes; o que não foi entregue fica para a próxima execução).\n"
    "16/10 10:00:00 │ INFO     │ techdigest.pipeline │ === TechDigest iniciando ===\n"
    "16/10 11:10:00 │ INFO     │ techdigest.pipeline │ Execução concluída: 20 notícia(s) entregue(s) em 70 min.\n"
)


def test_o_resumo_mostra_a_execucao_interrompida_e_a_que_nao_comecou(tmp_path, capsys, monkeypatch):
    log = tmp_path / "techdigest.log"
    log.write_text(LOG, encoding="utf-8")
    nao_comecaram = []
    interrompida, concluida = rl.ler_lotes("16/10", str(log), nao_comecaram)
    assert (interrompida["fim"], interrompida["interrompida"], interrompida["qa"]) == \
        ("09:20:00", "memória disponível em 3.1 GiB, abaixo do mínimo de 4.0 GiB", 1)
    assert (concluida["entregues"], concluida["interrompida"]) == (20, "")
    assert nao_comecaram == [("08:00:00", "o modelo está em uso por scripts/testar_episodio.py --amostra x (PID 1, "
                                          "desde 16/10 07:15, na pasta /x); espere essa execução terminar")]
    monkeypatch.setattr("sys.argv", ["resumo_lotes.py", "16/10", "--log", str(log)])
    rl.main()
    saida = capsys.readouterr().out
    assert "interrompida: memória disponível em 3.1 GiB" in saida
    assert "Não começaram (a trava do modelo estava ocupada):\n  08:00:00: o modelo está em uso" in saida
