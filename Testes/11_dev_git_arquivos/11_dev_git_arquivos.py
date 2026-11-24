"""Modulo 11_dev_git_arquivos - Git e arquivos: arquivos pequenos (overhead de EDR) e git clone local + status.

Cronometra cargas reais de desenvolvimento (origem: homologacao de notebooks para desenvolvimento). O que e medido
esta em cargas.json; a execucao, o limite de tempo (10x a referencia), a
tomada, o Ctrl+Q e as evidencias ficam na biblioteca comum Testes/_lib/dev_cargas.py.

Uso avulso:  python 11_dev_git_arquivos.py [--runs 3] [--only PREFIXO] [--calibrar] [--sem-overlay]
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))

from dev_cargas import executar_modulo  # noqa: E402

if __name__ == "__main__":
    executar_modulo(__file__)
