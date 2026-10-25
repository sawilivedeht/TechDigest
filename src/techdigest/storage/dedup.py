import sqlite3, hashlib

import logging
logger = logging.getLogger("techdigest.storage.dedup")


def _hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class SeenStore:
    """O que já foi entregue (`seen`) e quantas execuções reprovaram cada item no QA (`reprovacoes`).

    `seen` só tem o que foi entregue. As reprovações ficam numa tabela à parte, criada aqui se não existir (decisão do
    dono de 16/10/2026: a mudança no banco é aditiva, e a `master` antiga continua lendo e escrevendo `seen` como antes,
    sem saber da tabela nova). O item que chega a MAX_REPROVACOES não é mais tentado, e continua fora de `seen`.
    """

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS seen "
            "(hash TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS reprovacoes "
            "(hash TEXT PRIMARY KEY, vezes INTEGER NOT NULL, primeira_em TEXT DEFAULT CURRENT_TIMESTAMP, "
            "ultima_em TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        self.conn.commit()

    def is_new(self, url: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE hash = ?", (_hash(url),)).fetchone()
        return row is None

    def mark_seen(self, url: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO seen (hash) VALUES (?)", (_hash(url),))
        self.conn.commit()

    def marcar_vistos(self, urls) -> None:
        """Marca vários links como entregues numa transação só: a pauta inteira (os artigos gerados, as duplicatas e os
        excedentes) entra junta, ou nada entra."""
        with self.conn:
            self.conn.executemany("INSERT OR IGNORE INTO seen (hash) VALUES (?)", [(_hash(url),) for url in dict.fromkeys(urls)])

    def reprovacoes(self, url: str) -> int:
        """Em quantas execuções o QA reprovou o item (0 se nunca)."""
        row = self.conn.execute("SELECT vezes FROM reprovacoes WHERE hash = ?", (_hash(url),)).fetchone()
        return row[0] if row else 0

    def registrar_reprovacao(self, url: str) -> int:
        """Conta mais uma execução em que o QA reprovou o item e devolve o total."""
        self.conn.execute(
            "INSERT INTO reprovacoes (hash, vezes) VALUES (?, 1) "
            "ON CONFLICT(hash) DO UPDATE SET vezes = vezes + 1, ultima_em = CURRENT_TIMESTAMP",
            (_hash(url),),
        )
        self.conn.commit()
        return self.reprovacoes(url)
