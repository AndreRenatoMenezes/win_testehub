"""Teste de regressao: reparar_texto do teste 3.1 (fast.com).

O fast.com as vezes exibe o nome do servidor com o acento ja trocado por
U+FFFD na origem. reparar_texto restaura so nomes conhecidos e inteiros.
Extrai a lista e a funcao via ast: importar o script abriria o navegador.
Rodar: python -I -X utf8 .github/scripts/test_reparar_texto.py
"""
import ast
import re
import sys
from pathlib import Path

ALVO = Path(__file__).resolve().parents[2] / "Testes" / "3_rede_internet" / "3-1_teste_rede_internet.py"
ns = {"re": re}
for no in ast.parse(ALVO.read_text(encoding="utf-8")).body:
    if (isinstance(no, ast.Assign) and getattr(no.targets[0], "id", "") == "CIDADES_ACENTUADAS") or (
            isinstance(no, ast.FunctionDef) and no.name == "reparar_texto"):
        exec(compile(ast.Module([no], []), str(ALVO), "exec"), ns)
reparar = ns["reparar_texto"]

R = "\ufffd"
CASOS = [
    (f"S{R}o Jo{R}o de Meriti, BR | Campos dos Goytacazes, BR | Rio de Janeiro, BR",
     "S\u00e3o Jo\u00e3o de Meriti, BR | Campos dos Goytacazes, BR | Rio de Janeiro, BR"),
    (f"Bras{R}lia, BR", "Bras\u00edlia, BR"),
    (f"S{R}o Jos{R}, BR", "S\u00e3o Jos\u00e9, BR"),
    (f"S{R}o Jos{R} dos Campos, BR", "S\u00e3o Jos\u00e9 dos Campos, BR"),
    # prefixo conhecido de um nome fora da lista: corrige so o prefixo (aceitavel)
    (f"S{R}o Jos{R} dos Pinhais, BR", "S\u00e3o Jos\u00e9 dos Pinhais, BR"),
    # nao casa dentro de nomes maiores
    (f"Ita{R}na, BR", f"Ita{R}na, BR"),
    (f"Ita{R}ba, BR", f"Ita{R}ba, BR"),
    # fora da lista: fica como veio
    (f"S{R}o Jo{R}o del-Rei, BR", f"S{R}o Jo{R}o del-Rei, BR"),
    ("S\u00e3o Jo\u00e3o de Meriti, BR", "S\u00e3o Jo\u00e3o de Meriti, BR"),
    ("Rio De Janeiro, BR", "Rio De Janeiro, BR"),
    ("", ""),
    (None, None),
]

falhas = 0
for entrada, esperado in CASOS:
    obtido = reparar(entrada)
    ok = obtido == esperado
    falhas += not ok
    print(f"  {'OK    ' if ok else 'FALHOU'}  {ascii(entrada)} -> {ascii(obtido)}")
print()
if falhas:
    print(f"  {falhas} verificacao(oes) falharam.")
    sys.exit(1)
print("  Todas as verificacoes passaram.")
