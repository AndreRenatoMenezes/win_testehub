"""Gera as versões HTML da documentação a partir dos arquivos Markdown.

Os .md em docs/ são a fonte única; os .html são gerados por este script, com
o estilo de docs/assets/estilo.css embutido (arquivo único, para leitura
offline ou impressão). Não edite os .html à mão.

Uso:
    python docs/gerar_html.py            # regenera os HTML
    python docs/gerar_html.py --check    # falha se algum HTML estiver desatualizado (CI)

Requer o pacote "markdown" (pip install markdown).
"""

import argparse
import html
import re
import sys
from pathlib import Path

import markdown

DOCS = Path(__file__).resolve().parent
CSS = DOCS / "assets" / "estilo.css"
DOCUMENTOS = ["manual-de-execucao.md", "metodologia-de-testes.md"]

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

# Rótulo em negrito no início de um blockquote -> classe de callout
CALLOUTS = {"importante": "warning", "atenção": "warning", "nota": "info", "dica": "info"}
TAGS = {"Técnico": "tecnico", "Gestão": "gestao", "Operador": "operador"}

FONTES = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500'
    '&family=Montserrat:wght@600;700&display=swap" rel="stylesheet">'
)


def slug_github(texto, separador="-"):
    """Âncora no mesmo formato do GitHub, para links do .md valerem no .html."""
    texto = re.sub(r"<[^>]+>", "", texto).strip().lower()
    texto = re.sub(r"[^\w\- ]", "", texto)
    return texto.replace(" ", separador)


def ler_cabecalho(md):
    """Extrai título, subtítulo e metadados do topo do .md e devolve o restante."""
    cabecalho, _, corpo = md.partition("\n---\n")
    titulo = re.search(r"^# (.+)$", cabecalho, re.M).group(1).strip()
    nome, _, subtitulo = titulo.partition(" — ")
    meta = dict(re.findall(r"^\*\*([^*]+):\*\*\s*(.+?)\s*$", cabecalho, re.M))
    return nome, subtitulo, meta, corpo


def data_por_extenso(iso):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return iso or ""
    ano, mes, dia = (int(g) for g in m.groups())
    return f"{dia} de {MESES[mes - 1]} de {ano}"


def remover_sumario(corpo):
    """O sumário do .md é refeito no HTML a partir dos títulos (sempre em sincronia)."""
    return re.sub(r"^## Sumário\n.*?\n---\n", "", corpo, count=1, flags=re.S | re.M)


def converter_blockquotes(conteudo):
    def placeholder(m):
        src, legenda = m.group(1), m.group(2)
        legenda = re.sub(r"^Insira aqui:\s*", "", legenda)
        return (
            '<div class="img-placeholder"><span class="icon">&#128247;</span>'
            f"<strong>Insira aqui:</strong> {legenda}<br><em>Salvar como: {src}</em></div>"
        )

    conteudo = re.sub(
        r'<blockquote>\s*<p><img alt="[^"]*" src="([^"]+)"\s*/?>(?:<br\s*/?>)?\s*<em>(.*?)</em></p>\s*</blockquote>',
        placeholder, conteudo, flags=re.S)

    def callout(m):
        interno = m.group(1).strip()
        rotulo = re.match(r"<p><strong>([^<:]+):?</strong>:?\s*", interno)
        tipo = "info"
        titulo = ""
        if rotulo:
            nome = rotulo.group(1).strip()
            tipo = CALLOUTS.get(nome.split()[0].lower(), "info")
            titulo = f"<strong>{nome}</strong>"
            interno = "<p>" + interno[rotulo.end():]
        # .callout strong vira bloco no CSS: negritos do texto usam <b>
        interno = interno.replace("<strong>", "<b>").replace("</strong>", "</b>")
        # Um único parágrafo entra direto no callout, como nos HTML originais
        unico = re.fullmatch(r"<p>(.*)</p>", interno.strip(), flags=re.S)
        if unico and "<p>" not in unico.group(1):
            interno = unico.group(1).strip()
        return f'<div class="callout callout-{tipo}">{titulo}{interno}</div>'

    return re.sub(r"<blockquote>(.*?)</blockquote>", callout, conteudo, flags=re.S)


def converter_destaques(conteudo):
    # Tags [Técnico] / [Gestão] dos títulos
    for nome, classe in TAGS.items():
        conteudo = conteudo.replace(f"<code>[{nome}]</code>", f'<span class="tag tag-{classe}">{nome}</span>')

    # PASS/FAIL em negrito dentro de tabelas viram selos
    def celula(m):
        texto = m.group(2)
        texto = texto.replace("<strong>PASS</strong>", '<span class="badge badge-pass">PASS</span>')
        texto = texto.replace("<strong>FAIL</strong>", '<span class="badge badge-fail">FAIL</span>')
        return f"<{m.group(1)}>{texto}</td>"

    return re.sub(r"<(td[^>]*)>(.*?)</td>", celula, conteudo, flags=re.S)


def em_secoes(conteudo):
    """Agrupa cada <h2> e seu conteúdo num <div class="section"> (sem as linhas ---)."""
    conteudo = re.sub(r"\s*<hr\s*/?>\s*", "\n", conteudo)
    partes = re.split(r"(?=<h2[ >])", conteudo)
    saida = [p for p in partes[:1] if p.strip()]
    for parte in partes[1:]:
        saida.append(f'<div class="section">\n{parte.strip()}\n</div>')
    return "\n\n".join(saida)


def sumario(conteudo):
    itens = []
    for ident, titulo in re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', conteudo, flags=re.S):
        texto = re.sub(r"<[^>]+>", "", titulo)
        texto = re.sub(r"^\d+\.\s*", "", texto).strip()
        itens.append(f'<li><a href="#{ident}">{texto}</a></li>')
    return '<div class="toc">\n<h2>Sumário</h2>\n<ol>\n' + "\n".join(itens) + "\n</ol>\n</div>"


def gerar(origem: Path) -> str:
    md = origem.read_text(encoding="utf-8").replace("\r\n", "\n")
    nome, subtitulo, meta, corpo = ler_cabecalho(md)
    corpo = remover_sumario(corpo)

    conteudo = markdown.markdown(
        corpo,
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": slug_github}},
        output_format="html",
    )
    conteudo = converter_blockquotes(conteudo)
    conteudo = converter_destaques(conteudo)
    conteudo = em_secoes(conteudo)

    versao = meta.get("Versão", "")
    data = data_por_extenso(meta.get("Data"))
    publico = meta.get("Público-alvo", "")
    meta_html = " <span>|</span> ".join(
        f"<span>{html.escape(v)}</span>" for v in (f"Versão {versao}" if versao else "", data, publico) if v)
    titulo_pagina = f"{nome} - {subtitulo}" if subtitulo else nome
    rodape_mes = data.split(" de ", 1)[-1].capitalize() if data else ""

    css = CSS.read_text(encoding="utf-8").strip()
    return f"""<!DOCTYPE html>
<!-- Gerado a partir de {origem.name} por docs/gerar_html.py. Não edite à mão. -->
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(titulo_pagina)}</title>
{FONTES}
<style>
{css}
</style>
</head>
<body>
<div class="container">

<div class="doc-header">
<h1>{html.escape(nome)}</h1>
<div class="subtitle">{html.escape(subtitulo)}</div>
<div class="doc-meta">{meta_html}</div>
</div>

{sumario(conteudo)}

{conteudo}

<div style="text-align: center; padding: 24px; color: var(--cinza-neutro); font-size: 12px;">
<p>{html.escape(subtitulo or nome)} &mdash; {html.escape(nome)} v{html.escape(versao)} &mdash; {html.escape(rodape_mes)}</p>
<p style="margin-top: 8px;">Gerado a partir de <code>docs/{origem.name}</code>.</p>
</div>

</div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="não grava; falha se algum HTML estiver desatualizado")
    args = parser.parse_args()

    desatualizados = []
    for nome in DOCUMENTOS:
        origem = DOCS / nome
        destino = origem.with_suffix(".html")
        novo = gerar(origem)
        atual = destino.read_text(encoding="utf-8").replace("\r\n", "\n") if destino.exists() else None
        if args.check:
            if atual != novo:
                desatualizados.append(destino.name)
        elif atual != novo:
            destino.write_text(novo, encoding="utf-8", newline="\n")
            print(f"gerado: docs/{destino.name}")
        else:
            print(f"sem mudanças: docs/{destino.name}")

    if desatualizados:
        for nome in desatualizados:
            print(f"::error file=docs/{nome}::{nome} está desatualizado. Rode: python docs/gerar_html.py")
        sys.exit(1)
    if args.check:
        print("HTML da documentação em sincronia com o Markdown.")


if __name__ == "__main__":
    main()
