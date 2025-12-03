import sqlite3
from datetime import datetime, date

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

DB_NAME = "financas.db"


# ---------------------------
# Banco / Helpers
# ---------------------------
def conectar():
    return sqlite3.connect(DB_NAME, check_same_thread=False)


def tabelas_existem():
    with conectar() as con:
        r = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('conta','categoria','transacao')"
        ).fetchall()
    nomes = {x[0] for x in r}
    return "conta" in nomes and "categoria" in nomes and "transacao" in nomes


def criar_tabelas_se_precisar():
    if tabelas_existem():
        return
    with conectar() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS conta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                saldo_inicial REAL NOT NULL DEFAULT 0
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS categoria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                tipo TEXT NOT NULL CHECK(tipo IN ('receita','despesa'))
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS transacao (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL CHECK(tipo IN ('receita','despesa','transferencia')),
                valor REAL NOT NULL,
                data TEXT NOT NULL,
                conta_origem_id INTEGER NOT NULL,
                conta_destino_id INTEGER,
                categoria_id INTEGER,
                descricao TEXT,
                FOREIGN KEY(conta_origem_id) REFERENCES conta(id),
                FOREIGN KEY(conta_destino_id) REFERENCES conta(id),
                FOREIGN KEY(categoria_id) REFERENCES categoria(id)
            );
            """
        )
        con.commit()


def listar_contas():
    with conectar() as con:
        rows = con.execute("SELECT id, nome, saldo_inicial FROM conta ORDER BY nome").fetchall()
    return pd.DataFrame(rows, columns=["id", "nome", "saldo_inicial"])


def listar_categorias(tipo=None):
    with conectar() as con:
        if tipo:
            rows = con.execute(
                "SELECT id, nome, tipo FROM categoria WHERE tipo=? ORDER BY nome", (tipo,)
            ).fetchall()
        else:
            rows = con.execute("SELECT id, nome, tipo FROM categoria ORDER BY tipo, nome").fetchall()
    return pd.DataFrame(rows, columns=["id", "nome", "tipo"])


def inserir_conta(nome, saldo_inicial):
    with conectar() as con:
        con.execute("INSERT INTO conta(nome, saldo_inicial) VALUES (?,?)", (nome, saldo_inicial))
        con.commit()


def inserir_categoria(nome, tipo):
    with conectar() as con:
        con.execute("INSERT INTO categoria(nome, tipo) VALUES (?,?)", (nome, tipo))
        con.commit()


def inserir_transacao(tipo, valor, data_str, conta_origem_id, categoria_id=None, descricao=None, conta_destino_id=None):
    with conectar() as con:
        con.execute(
            """
            INSERT INTO transacao(tipo, valor, data, conta_origem_id, conta_destino_id, categoria_id, descricao)
            VALUES (?,?,?,?,?,?,?)
            """,
            (tipo, valor, data_str, conta_origem_id, conta_destino_id, categoria_id, descricao),
        )
        con.commit()


def buscar_transacoes(ano=None, mes=None, conta_id=None):
    query = """
        SELECT 
            t.id, t.data, t.tipo, t.valor,
            co.nome AS conta_origem,
            cd.nome AS conta_destino,
            c.nome AS categoria,
            t.descricao
        FROM transacao t
        LEFT JOIN conta co ON co.id = t.conta_origem_id
        LEFT JOIN conta cd ON cd.id = t.conta_destino_id
        LEFT JOIN categoria c ON c.id = t.categoria_id
        WHERE 1=1
    """
    params = []

    if conta_id:
        query += " AND (t.conta_origem_id = ? OR t.conta_destino_id = ?)"
        params += [conta_id, conta_id]

    if ano and mes:
        inicio = f"{ano:04d}-{mes:02d}-01T00:00:00"
        # fim do mês (23:59:59)
        if mes == 12:
            fim = f"{ano+1:04d}-01-01T00:00:00"
        else:
            fim = f"{ano:04d}-{mes+1:02d}-01T00:00:00"
        query += " AND t.data >= ? AND t.data < ?"
        params += [inicio, fim]

    query += " ORDER BY t.data DESC, t.id DESC"

    with conectar() as con:
        rows = con.execute(query, params).fetchall()

    return pd.DataFrame(
        rows,
        columns=["id", "data", "tipo", "valor", "conta_origem", "conta_destino", "categoria", "descricao"],
    )


def resumo_mes(ano, mes):
    df = buscar_transacoes(ano, mes)
    receitas = df[df["tipo"] == "receita"]["valor"].sum()
    despesas = df[df["tipo"] == "despesa"]["valor"].sum()
    saldo = receitas - despesas
    return receitas, despesas, saldo, df


# ---------------------------
# UI
# ---------------------------
st.set_page_config(page_title="Meu App de Finanças", page_icon="💰", layout="wide")
st.title("💰 Meu App de Finanças")

criar_tabelas_se_precisar()

# Sidebar navegação
aba = st.sidebar.radio(
    "Navegação",
    ["Dashboard", "Lançar Transação", "Contas", "Categorias", "Transações"],
)

# Carrega dados base
contas_df = listar_contas()
categorias_df = listar_categorias()


if aba == "Dashboard":
    st.subheader("📊 Resumo do mês")

    col1, col2 = st.columns(2)
    with col1:
        ano = st.number_input("Ano", min_value=2000, max_value=2100, value=date.today().year, step=1)
    with col2:
        mes = st.number_input("Mês", min_value=1, max_value=12, value=date.today().month, step=1)

    receitas, despesas, saldo, df_mes = resumo_mes(int(ano), int(mes))

    c1, c2, c3 = st.columns(3)
    c1.metric("Receitas", f"R$ {receitas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Despesas", f"R$ {despesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Saldo", f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))

    st.divider()

    if df_mes.empty:
        st.info("Nenhuma transação no mês selecionado.")
    else:
        st.write("Últimas transações do mês:")
        st.dataframe(df_mes, use_container_width=True)

        # Gráfico por categoria (despesas)
        despesas_cat = df_mes[df_mes["tipo"] == "despesa"].groupby("categoria")["valor"].sum().sort_values(ascending=False)
        if not despesas_cat.empty:
            st.subheader("🍕 Despesas por categoria")
            fig, ax = plt.subplots()
            despesas_cat.plot(kind="pie", ax=ax, autopct="%1.1f%%")
            ax.set_ylabel("")
            st.pyplot(fig)

        # Linha de saldo acumulado no mês
        st.subheader("📈 Evolução do saldo no mês")
        df_plot = df_mes.copy()
        df_plot["data_dt"] = pd.to_datetime(df_plot["data"])
        df_plot = df_plot.sort_values("data_dt")
        df_plot["delta"] = df_plot.apply(
            lambda r: r["valor"] if r["tipo"] == "receita" else (-r["valor"] if r["tipo"] == "despesa" else 0),
            axis=1
        )
        df_plot["saldo_acum"] = df_plot["delta"].cumsum()

        fig2, ax2 = plt.subplots()
        ax2.plot(df_plot["data_dt"], df_plot["saldo_acum"])
        ax2.set_xlabel("Data")
        ax2.set_ylabel("Saldo acumulado")
        st.pyplot(fig2)


elif aba == "Lançar Transação":
    st.subheader("➕ Nova transação")

    if contas_df.empty:
        st.warning("Crie uma conta primeiro.")
        st.stop()

    tipo = st.selectbox("Tipo", ["receita", "despesa", "transferencia"])

    valor = st.number_input("Valor (R$)", min_value=0.01, value=10.00, step=1.0)
    data_tx = st.date_input("Data", value=date.today())
    hora_tx = st.time_input("Hora", value=datetime.now().time())

    conta_origem = st.selectbox(
        "Conta origem",
        contas_df["nome"].tolist()
    )
    conta_origem_id = int(contas_df.loc[contas_df["nome"] == conta_origem, "id"].iloc[0])

    categoria_id = None
    conta_destino_id = None

    if tipo in ("receita", "despesa"):
        cats_do_tipo = categorias_df[categorias_df["tipo"] == tipo]
        if cats_do_tipo.empty:
            st.warning(f"Crie uma categoria do tipo {tipo} primeiro.")
            st.stop()
        categoria_nome = st.selectbox("Categoria", cats_do_tipo["nome"].tolist())
        categoria_id = int(cats_do_tipo.loc[cats_do_tipo["nome"] == categoria_nome, "id"].iloc[0])

    if tipo == "transferencia":
        contas_dest = contas_df[contas_df["id"] != conta_origem_id]
        if contas_dest.empty:
            st.warning("Você precisa de pelo menos 2 contas para transferir.")
            st.stop()
        conta_destino = st.selectbox("Conta destino", contas_dest["nome"].tolist())
        conta_destino_id = int(contas_dest.loc[contas_dest["nome"] == conta_destino, "id"].iloc[0])

    descricao = st.text_input("Descrição (opcional)", value="")

    if st.button("Salvar transação", type="primary"):
        data_str = datetime.combine(data_tx, hora_tx).isoformat(timespec="seconds")
        inserir_transacao(
            tipo=tipo,
            valor=float(valor),
            data_str=data_str,
            conta_origem_id=conta_origem_id,
            categoria_id=categoria_id,
            descricao=descricao if descricao else None,
            conta_destino_id=conta_destino_id
        )
        st.success("Transação registrada! ✅")
        st.rerun()


elif aba == "Contas":
    st.subheader("🏦 Contas")

    st.dataframe(contas_df, use_container_width=True)

    st.divider()
    st.write("Criar nova conta")
    nome = st.text_input("Nome da conta")
    saldo_inicial = st.number_input("Saldo inicial", value=0.0, step=10.0)

    if st.button("Criar conta"):
        try:
            inserir_conta(nome.strip(), float(saldo_inicial))
            st.success("Conta criada! ✅")
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")


elif aba == "Categorias":
    st.subheader("🏷️ Categorias")

    st.dataframe(categorias_df, use_container_width=True)

    st.divider()
    st.write("Criar nova categoria")
    nome = st.text_input("Nome da categoria")
    tipo = st.selectbox("Tipo", ["receita", "despesa"])

    if st.button("Criar categoria"):
        try:
            inserir_categoria(nome.strip(), tipo)
            st.success("Categoria criada! ✅")
            st.rerun()
        except Exception as e:
            st.error(f"Erro: {e}")


elif aba == "Transações":
    st.subheader("📜 Transações")

    col1, col2, col3 = st.columns(3)

    with col1:
        conta_filtro = st.selectbox("Filtrar por conta (opcional)", ["Todas"] + contas_df["nome"].tolist())
    with col2:
        ano = st.number_input("Ano (opcional)", min_value=2000, max_value=2100, value=date.today().year, step=1)
    with col3:
        mes = st.number_input("Mês (opcional)", min_value=1, max_value=12, value=date.today().month, step=1)

    conta_id = None if conta_filtro == "Todas" else int(contas_df.loc[contas_df["nome"] == conta_filtro, "id"].iloc[0])

    df = buscar_transacoes(int(ano), int(mes), conta_id=conta_id)

    if df.empty:
        st.info("Nenhuma transação encontrada.")
    else:
        st.dataframe(df, use_container_width=True)
