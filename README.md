# Meu app de finanças

Ferramentas simples em Python para registrar contas, categorias e transações usando SQLite.
Há dois modos de uso: menu interativo (sem argumentos) ou linha de comando.

## Pré-requisitos
- Python 3.11+

## Como usar
1. Abra o menu interativo:
   ```bash
   python financas.py
   ```
   O menu cria o banco automaticamente, inclui uma conta "Carteira" e categorias
   básicas (Salário, Alimentação, Transporte, Lazer) e permite lançar receitas,
   despesas, além de ver resumo ou transações do mês.

2. Ou use os comandos diretos:
   1. Crie o banco e tabelas:
   ```bash
   python financas.py criar-tabelas
   ```
   2. Cadastre contas e categorias:
   ```bash
   python financas.py criar-conta "Carteira" 100
   python financas.py criar-categoria "Salário" receita
   python financas.py criar-categoria "Mercado" despesa
   ```
   3. Registre transações:
   ```bash
   # Receita (exige categoria do tipo receita)
   python financas.py transacao receita 2500 1 1

   # Despesa (exige categoria do tipo despesa)
   python financas.py transacao despesa 300 1 3 "Supermercado"

   # Transferência entre contas (categoria é ignorada)
   python financas.py transacao transferencia 200 1 _ 2 "Transferência para poupança"
   ```
   Para transferências, passe `_` ou omita o parâmetro de categoria.

   4. Consulte saldos e transações:
   ```bash
   python financas.py saldo 1
   python financas.py listar-contas
   python financas.py listar-transacoes 1
   # Menu interativo via subcomando
   python financas.py menu
   ```

As datas são gravadas automaticamente em formato ISO 8601, mas você pode sobrescrever passando o parâmetro `data` diretamente ao
 chamar `registrar_transacao` via código.

## Interface web (Streamlit)
Uma interface gráfica simples está disponível em `app.py`. Ela reutiliza o mesmo banco `financas.db` e permite cadastrar contas, categorias e transações via navegador.

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   # ou
   pip install streamlit pandas matplotlib
   ```

2. Inicie a interface:
   ```bash
   streamlit run app.py
   ```

3. Acesse o endereço exibido pelo Streamlit (por padrão, http://localhost:8501) e use o menu lateral para navegar entre dashboard, lançamentos, contas, categorias e transações.
