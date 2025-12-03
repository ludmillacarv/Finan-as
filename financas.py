"""Utilitários simples para registrar contas, categorias e transações financeiras.

O módulo usa SQLite e mantém três tabelas:
- conta
- categoria
- transacao

Também disponibiliza uma CLI básica e um menu interativo para criar tabelas,
cadastrar dados e consultar saldos.
"""

import argparse
import calendar
import sqlite3
import sys
from datetime import datetime
from typing import Iterable, Optional

DB_NAME = "financas.db"

ALLOWED_TRANSACTION_TYPES = {"receita", "despesa", "transferencia"}
ALLOWED_CATEGORY_TYPES = {"receita", "despesa"}


def conectar() -> sqlite3.Connection:
    """Abre conexão com o banco e garante suporte a chaves estrangeiras."""
    con = sqlite3.connect(DB_NAME)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def criar_tabelas() -> None:
    """Cria as tabelas necessárias, caso ainda não existam."""
    with conectar() as con:
        cur = con.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS conta (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              nome TEXT NOT NULL,
              saldo_inicial REAL NOT NULL DEFAULT 0
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS categoria (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              nome TEXT NOT NULL,
              tipo TEXT NOT NULL CHECK(tipo IN ('receita','despesa')),
              UNIQUE(nome, tipo)
            );
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transacao (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tipo TEXT NOT NULL CHECK(tipo IN ('receita','despesa','transferencia')),
              data TEXT NOT NULL,
              valor REAL NOT NULL CHECK(valor >= 0),
              categoria_id INTEGER,
              conta_origem_id INTEGER NOT NULL,
              conta_destino_id INTEGER,
              descricao TEXT,
              FOREIGN KEY(categoria_id) REFERENCES categoria(id),
              FOREIGN KEY(conta_origem_id) REFERENCES conta(id),
              FOREIGN KEY(conta_destino_id) REFERENCES conta(id)
            );
            """
        )

        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_transacao_data
                ON transacao(data);
            """
        )


def seed_basico() -> None:
    """Cria conta e categorias padrão quando o banco ainda está vazio."""
    with conectar() as con:
        (contas_existentes,) = con.execute("SELECT COUNT(1) FROM conta").fetchone()
        if contas_existentes == 0:
            con.execute("INSERT INTO conta (nome, saldo_inicial) VALUES (?, ?)", ("Carteira", 0))

        (categorias_existentes,) = con.execute("SELECT COUNT(1) FROM categoria").fetchone()
        if categorias_existentes == 0:
            con.executemany(
                "INSERT INTO categoria (nome, tipo) VALUES (?, ?)",
                (
                    ("Salário", "receita"),
                    ("Alimentação", "despesa"),
                    ("Transporte", "despesa"),
                    ("Lazer", "despesa"),
                ),
            )


def _registro_existente(con: sqlite3.Connection, table: str, record_id: int) -> bool:
    (count,) = con.execute(f"SELECT COUNT(1) FROM {table} WHERE id = ?", (record_id,)).fetchone()
    return count > 0


def criar_conta(nome: str, saldo_inicial: float = 0) -> int:
    with conectar() as con:
        cur = con.execute(
            "INSERT INTO conta (nome, saldo_inicial) VALUES (?, ?)",
            (nome, saldo_inicial),
        )
        return cur.lastrowid


def criar_categoria(nome: str, tipo: str) -> int:
    if tipo not in ALLOWED_CATEGORY_TYPES:
        raise ValueError(f"Tipo de categoria inválido: {tipo}")

    with conectar() as con:
        cur = con.execute(
            "INSERT OR IGNORE INTO categoria (nome, tipo) VALUES (?, ?)",
            (nome, tipo),
        )
        if cur.lastrowid == 0:
            # Consulta id existente para manter idempotência.
            (cat_id,) = con.execute(
                "SELECT id FROM categoria WHERE nome = ? AND tipo = ?",
                (nome, tipo),
            ).fetchone()
            return cat_id
        return cur.lastrowid


def _validar_transacao(
    con: sqlite3.Connection,
    tipo: str,
    valor: float,
    conta_origem_id: int,
    categoria_id: Optional[int],
    conta_destino_id: Optional[int],
) -> None:
    if tipo not in ALLOWED_TRANSACTION_TYPES:
        raise ValueError("Tipo de transação inválido")
    if valor < 0:
        raise ValueError("Valor da transação não pode ser negativo")
    if not _registro_existente(con, "conta", conta_origem_id):
        raise ValueError("Conta de origem inexistente")
    if conta_destino_id is not None and not _registro_existente(con, "conta", conta_destino_id):
        raise ValueError("Conta de destino inexistente")

    if tipo == "transferencia":
        if conta_destino_id is None:
            raise ValueError("Transferência requer conta de destino")
    else:
        if categoria_id is None:
            raise ValueError("Transações de receita e despesa precisam de categoria")
        row = con.execute("SELECT tipo FROM categoria WHERE id = ?", (categoria_id,)).fetchone()
        if row is None:
            raise ValueError("Categoria informada não existe")
        if row[0] != tipo:
            raise ValueError("Categoria incompatível com o tipo de transação")


def registrar_transacao(
    tipo: str,
    valor: float,
    conta_origem_id: int,
    *,
    data: Optional[str] = None,
    categoria_id: Optional[int] = None,
    conta_destino_id: Optional[int] = None,
    descricao: Optional[str] = None,
) -> int:
    """Insere uma transação de receita, despesa ou transferência.

    A data é gravada em ISO 8601; quando não informada, usa o momento atual.
    """
    momento = data or datetime.now().isoformat(timespec="seconds")

    with conectar() as con:
        _validar_transacao(con, tipo, valor, conta_origem_id, categoria_id, conta_destino_id)
        cur = con.execute(
            """
            INSERT INTO transacao (tipo, data, valor, categoria_id, conta_origem_id, conta_destino_id, descricao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tipo, momento, valor, categoria_id, conta_origem_id, conta_destino_id, descricao),
        )
        return cur.lastrowid


def _total_por_tipo(con: sqlite3.Connection, conta_id: int, tipo: str) -> float:
    (soma,) = con.execute(
        "SELECT COALESCE(SUM(valor), 0) FROM transacao WHERE conta_origem_id = ? AND tipo = ?",
        (conta_id, tipo),
    ).fetchone()
    return soma


def _total_transferencias_entrando(con: sqlite3.Connection, conta_id: int) -> float:
    (soma,) = con.execute(
        "SELECT COALESCE(SUM(valor), 0) FROM transacao WHERE conta_destino_id = ? AND tipo = 'transferencia'",
        (conta_id,),
    ).fetchone()
    return soma


def saldo_atual(con: sqlite3.Connection, conta_id: int) -> float:
    """Calcula o saldo atual somando o saldo inicial e os lançamentos."""
    row = con.execute("SELECT saldo_inicial FROM conta WHERE id = ?", (conta_id,)).fetchone()
    if row is None:
        raise ValueError("Conta não encontrada")

    saldo = row[0]
    saldo += _total_por_tipo(con, conta_id, "receita")
    saldo -= _total_por_tipo(con, conta_id, "despesa")
    saldo -= _total_por_tipo(con, conta_id, "transferencia")
    saldo += _total_transferencias_entrando(con, conta_id)
    return saldo


def listar_contas() -> Iterable[dict]:
    with conectar() as con:
        contas = con.execute("SELECT id, nome, saldo_inicial FROM conta ORDER BY nome").fetchall()
        for conta_id, nome, saldo_inicial in contas:
            yield {
                "id": conta_id,
                "nome": nome,
                "saldo_inicial": saldo_inicial,
                "saldo_atual": saldo_atual(con, conta_id),
            }


def listar_categorias(tipo: Optional[str] = None) -> list[dict]:
    """Lista categorias opcionalmente filtradas por tipo."""
    query = "SELECT id, nome, tipo FROM categoria"
    params: tuple[object, ...] = ()
    if tipo:
        query += " WHERE tipo = ?"
        params = (tipo,)
    query += " ORDER BY nome"

    with conectar() as con:
        return [
            {"id": row[0], "nome": row[1], "tipo": row[2]}
            for row in con.execute(query, params).fetchall()
        ]


def listar_transacoes(conta_id: Optional[int] = None) -> list[dict]:
    query = "SELECT id, tipo, data, valor, categoria_id, conta_origem_id, conta_destino_id, descricao FROM transacao"
    params: tuple[object, ...] = ()
    if conta_id is not None:
        query += " WHERE conta_origem_id = ? OR conta_destino_id = ?"
        params = (conta_id, conta_id)
    query += " ORDER BY datetime(data) DESC, id DESC"

    with conectar() as con:
        rows = con.execute(query, params).fetchall()
        return [
            {
                "id": row[0],
                "tipo": row[1],
                "data": row[2],
                "valor": row[3],
                "categoria_id": row[4],
                "conta_origem_id": row[5],
                "conta_destino_id": row[6],
                "descricao": row[7],
            }
            for row in rows
        ]


def listar_transacoes_mes(ano: int, mes: int) -> list[dict]:
    """Lista transações ocorridas em um mês específico."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    inicio = f"{ano:04d}-{mes:02d}-01"
    fim = f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}"

    with conectar() as con:
        rows = con.execute(
            """
            SELECT t.id, t.data, t.tipo, t.valor, c.nome, t.descricao
            FROM transacao t
            LEFT JOIN categoria c ON c.id = t.categoria_id
            WHERE t.data BETWEEN ? AND ?
            ORDER BY datetime(t.data) DESC, t.id DESC
            """,
            (inicio, fim),
        ).fetchall()
    return [
        {
            "id": row[0],
            "data": row[1],
            "tipo": row[2],
            "valor": row[3],
            "categoria_nome": row[4],
            "descricao": row[5],
        }
        for row in rows
    ]


def resumo_mes(ano: int, mes: int) -> dict:
    """Calcula receitas, despesas e saldo do mês informado."""
    ultimo_dia = calendar.monthrange(ano, mes)[1]
    inicio = f"{ano:04d}-{mes:02d}-01"
    fim = f"{ano:04d}-{mes:02d}-{ultimo_dia:02d}"

    with conectar() as con:
        receitas, despesas = con.execute(
            """
            SELECT 
              COALESCE(SUM(CASE WHEN tipo='receita' THEN valor END), 0) as receitas,
              COALESCE(SUM(CASE WHEN tipo='despesa' THEN valor END), 0) as despesas
            FROM transacao
            WHERE data BETWEEN ? AND ?
            """,
            (inicio, fim),
        ).fetchone()

    saldo = receitas - despesas
    return {"receitas": receitas, "despesas": despesas, "saldo": saldo}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ferramentas para gerenciar finanças pessoais")
    sub = parser.add_subparsers(dest="comando", required=True)

    sub.add_parser("criar-tabelas", help="Criar tabelas do banco de dados")

    parser_conta = sub.add_parser("criar-conta", help="Cadastrar uma nova conta")
    parser_conta.add_argument("nome")
    parser_conta.add_argument("saldo_inicial", type=float, nargs="?", default=0)

    parser_categoria = sub.add_parser("criar-categoria", help="Cadastrar uma nova categoria")
    parser_categoria.add_argument("nome")
    parser_categoria.add_argument("tipo", choices=sorted(ALLOWED_CATEGORY_TYPES))

    parser_transacao = sub.add_parser("transacao", help="Registrar uma transação")
    parser_transacao.add_argument("tipo", choices=sorted(ALLOWED_TRANSACTION_TYPES))
    parser_transacao.add_argument("valor", type=float)
    parser_transacao.add_argument("conta_origem_id", type=int)
    parser_transacao.add_argument(
        "categoria_id",
        nargs="?",
        help="Use _ ou omita para ignorar em transferências",
    )
    parser_transacao.add_argument("conta_destino_id", nargs="?")
    parser_transacao.add_argument("descricao", nargs="*")

    parser_saldo = sub.add_parser("saldo", help="Consultar saldo de uma conta")
    parser_saldo.add_argument("conta_id", type=int)

    sub.add_parser("listar-contas", help="Listar contas com saldos")

    parser_listar = sub.add_parser("listar-transacoes", help="Listar transações")
    parser_listar.add_argument("conta_id", type=int, nargs="?")

    parser_resumo = sub.add_parser("resumo-mes", help="Mostrar resumo de receitas e despesas do mês")
    parser_resumo.add_argument("ano", type=int)
    parser_resumo.add_argument("mes", type=int)

    parser_listar_categorias = sub.add_parser("listar-categorias", help="Listar categorias")
    parser_listar_categorias.add_argument("tipo", nargs="?", choices=sorted(ALLOWED_CATEGORY_TYPES))

    sub.add_parser("menu", help="Abrir menu interativo")

    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.comando == "criar-tabelas":
        criar_tabelas()
        seed_basico()
        print("Tabelas criadas/garantidas e dados básicos populados.")
        return

    if args.comando == "criar-conta":
        criar_tabelas()
        conta_id = criar_conta(args.nome, args.saldo_inicial)
        print(f"Conta criada com id {conta_id}.")
        return

    if args.comando == "criar-categoria":
        criar_tabelas()
        cat_id = criar_categoria(args.nome, args.tipo)
        print(f"Categoria pronta com id {cat_id}.")
        return

    if args.comando == "transacao":
        criar_tabelas()
        categoria_id = None
        if args.categoria_id not in (None, "_"):
            categoria_id = int(args.categoria_id)

        conta_destino_id: Optional[int] = None
        if args.tipo == "transferencia":
            if args.conta_destino_id is not None:
                try:
                    conta_destino_id = int(args.conta_destino_id)
                except ValueError as exc:
                    raise ValueError("Conta de destino deve ser um número inteiro") from exc
        else:
            if args.conta_destino_id is not None:
                args.descricao.insert(0, args.conta_destino_id)

        descricao = " ".join(args.descricao) if args.descricao else None

        transacao_id = registrar_transacao(
            args.tipo,
            args.valor,
            args.conta_origem_id,
            categoria_id=categoria_id,
            conta_destino_id=conta_destino_id,
            descricao=descricao,
        )
        print(f"Transação registrada com id {transacao_id}.")
        return

    if args.comando == "saldo":
        criar_tabelas()
        seed_basico()
        with conectar() as con:
            row = con.execute("SELECT nome FROM conta WHERE id = ?", (args.conta_id,)).fetchone()
            if row is None:
                raise ValueError("Conta não encontrada")

            nome = row[0]
            saldo = saldo_atual(con, args.conta_id)

        print(f"Saldo atual de '{nome}': R$ {saldo:.2f}")
        return

    if args.comando == "listar-contas":
        criar_tabelas()
        seed_basico()
        for conta in listar_contas():
            print(
                f"[{conta['id']}] {conta['nome']} - "
                f"Saldo inicial: {conta['saldo_inicial']:.2f} | "
                f"Saldo atual: {conta['saldo_atual']:.2f}"
            )
        return

    if args.comando == "listar-transacoes":
        criar_tabelas()
        seed_basico()
        for tx in listar_transacoes(args.conta_id):
            destino = f" -> conta {tx['conta_destino_id']}" if tx["conta_destino_id"] else ""
            print(
                f"[{tx['id']}] {tx['tipo']} de {tx['valor']:.2f} em {tx['data']} "
                f"(conta origem {tx['conta_origem_id']}{destino})"
            )
        return

    if args.comando == "listar-categorias":
        criar_tabelas()
        seed_basico()
        for categoria in listar_categorias(args.tipo):
            print(f"[{categoria['id']}] {categoria['nome']} ({categoria['tipo']})")
        return

    if args.comando == "resumo-mes":
        criar_tabelas()
        seed_basico()
        res = resumo_mes(args.ano, args.mes)
        print(f"Receitas: R$ {res['receitas']:.2f}")
        print(f"Despesas: R$ {res['despesas']:.2f}")
        print(f"Saldo:    R$ {res['saldo']:.2f}")
        return

    if args.comando == "menu":
        criar_tabelas()
        seed_basico()
        menu_interativo()
        return


def _solicitar_int(mensagem: str) -> int:
    while True:
        try:
            return int(input(mensagem).strip())
        except ValueError:
            print("Por favor, informe um número inteiro.")


def menu_interativo() -> None:
    while True:
        print("\n=== FINANÇAS PESSOAIS ===")
        print("1) Lançar receita")
        print("2) Lançar despesa")
        print("3) Ver transações do mês")
        print("4) Ver resumo do mês")
        print("0) Sair")

        op = input("Escolha: ").strip()

        if op == "0":
            print("Até logo!")
            break

        if op not in {"1", "2", "3", "4"}:
            print("Opção inválida.")
            continue

        try:
            if op in {"1", "2"}:
                tipo = "receita" if op == "1" else "despesa"
                valor = float(input("Valor (ex 12.50): ").replace(",", "."))
                data = input("Data (YYYY-MM-DD) [enter para hoje]: ").strip() or datetime.now().strftime("%Y-%m-%d")
                descricao = input("Descrição: ").strip() or None

                print("\nContas:")
                contas = list(listar_contas())
                for conta in contas:
                    print(f"{conta['id']} - {conta['nome']}")
                conta_id = _solicitar_int("Conta: ")

                print(f"\nCategorias de {tipo}:")
                categorias = listar_categorias(tipo)
                for cat in categorias:
                    print(f"{cat['id']} - {cat['nome']}")
                categoria_id = _solicitar_int("Categoria: ")

                registrar_transacao(
                    tipo,
                    valor,
                    conta_id,
                    data=data,
                    categoria_id=categoria_id,
                    descricao=descricao,
                )
                print("✅ Lançamento registrado!")

            elif op == "3":
                ano = _solicitar_int("Ano (ex 2025): ")
                mes = _solicitar_int("Mês (1-12): ")
                transacoes = listar_transacoes_mes(ano, mes)
                if not transacoes:
                    print("Nada por aqui.")
                else:
                    print("\nID | Data | Tipo | Valor | Categoria | Descrição")
                    for tx in transacoes:
                        categoria = tx["categoria_nome"] or "-"
                        descricao = tx["descricao"] or ""
                        print(f"{tx['id']} | {tx['data']} | {tx['tipo']} | {tx['valor']:.2f} | {categoria} | {descricao}")

            elif op == "4":
                ano = _solicitar_int("Ano (ex 2025): ")
                mes = _solicitar_int("Mês (1-12): ")
                resumo = resumo_mes(ano, mes)
                print(f"\nReceitas: R$ {resumo['receitas']:.2f}")
                print(f"Despesas: R$ {resumo['despesas']:.2f}")
                print(f"Saldo:    R$ {resumo['saldo']:.2f}")

        except Exception as exc:  # noqa: BLE001 - feedback direto no menu
            print(f"Erro: {exc}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        criar_tabelas()
        seed_basico()
        menu_interativo()
    else:
        main()
