# Contribuindo com o WinTestHub

Obrigado por ajudar a melhorar o projeto. Este guia cobre o fluxo de trabalho e, principalmente, o **contrato** que todo script precisa seguir para funcionar dentro do hub.

## Fluxo de trabalho

1. Abra uma issue descrevendo a falha ou a proposta (use os modelos disponíveis).
2. Crie um branch a partir de `main`: `feat/modulo-7-gpu`, `fix/rede-exit-code`, `docs/manual-bateria`.
3. Faça commits pequenos no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/v1.0.0/):
   `feat(bateria): ...`, `fix(hub): ...`, `docs: ...`, `ci: ...`.
4. **Teste em uma máquina Windows real.** O CI só valida sintaxe e conteúdo sensível; ele não executa os testes.
5. Abra o pull request preenchendo o checklist e atualize o `CHANGELOG.md` na seção **Não lançado**.

## Como o hub encontra os scripts

O `hub.ps1` procura **recursivamente** por arquivos `*.ps1` e `*.py` em duas pastas, definidas no `config.json`:

| Pasta | Fase | Uso |
|-------|------|-----|
| `Setup/` | Fase 1 — Preparação | Configura a máquina antes dos testes |
| `Testes/` | Fase 2 — Testes | Mede o hardware e decide PASS/FAIL |

- Os scripts aparecem no menu ordenados pelo nome do arquivo e agrupados pela pasta-mãe.
- O rótulo do grupo vem do nome da pasta, sem o prefixo numérico: `5_bateria` → **Bateria**.
- **Todo** `.ps1`/`.py` dessas pastas vira item do menu. Um script auxiliar (chamado por outro, e não pelo operador) precisa entrar na lista `-Exclude` da função `Get-Scripts` no `hub.ps1`, como já acontece com `boot_shutdown_duration.ps1`.

## Contrato de um script

### 1. Exit code define o resultado

| Código | Status no hub |
|--------|---------------|
| `0` | **PASS** |
| `≠ 0` | **FAIL** |
| exceção no próprio hub | **ERROR** |

Saia com `0` **somente** quando o teste realmente passou.

> **Atenção (Python com overlay/threads):** `sys.exit()` chamado dentro de uma `threading.Thread` encerra só a thread e **não** altera o exit code do processo. Na thread de trabalho, lance uma exceção ou defina a variável global de exit code; chame `sys.exit(_exit_code)` apenas na thread principal.

### 2. Evidências vão para a pasta indicada pelo hub

O hub injeta estas variáveis de ambiente antes de cada script:

| Variável | Conteúdo |
|----------|----------|
| `HUB_EVIDENCE_DIR` | Pasta de evidências do teste atual (`Execucoes/<cenário>/Traces/<pasta-do-teste>`) |
| `HUB_TRACE_DIR` | Igual a `HUB_EVIDENCE_DIR` |
| `HUB_TRACE_ROOT` | Pasta `Traces` do cenário |

Nunca grave arquivos na raiz do projeto. Para permitir execução avulsa (fora do hub), use a pasta do próprio script como fallback:

```python
OUTPUT_PATH = os.environ.get("HUB_EVIDENCE_DIR", os.path.dirname(os.path.abspath(__file__)))
```

### 3. CSV temático (opcional)

Se o teste gerar um CSV-resumo, registre-o no mapa `$expectedCSVs` da função `Copy-ThematicCSVs` no `hub.ps1`. Ao final da execução, o hub copia esse arquivo para `Resultados/<cenário>/`.

```powershell
"7_gpu" = "gpu.csv"
```

### 4. Variantes na mesma pasta

O hub dá a todos os scripts de uma pasta o mesmo `HUB_EVIDENCE_DIR`. Uma variante que divide a pasta com o módulo principal, como a `1-1` dentro de `1_cpu_memo`, deve:

- gravar numa **subpasta própria** de `HUB_EVIDENCE_DIR` (a `1-1` usa `dlp_usb/`). Caso contrário, os dois testes sobrescrevem os arquivos um do outro, e globs como `CSV_*` misturam os resultados;
- usar um nome de CSV temático próprio e registrá-lo no mapa `$variantCSVs` da `Copy-ThematicCSVs`, que copia esses CSVs para `Resultados/` só quando eles existem.

O teste `.github/scripts/Test-CopyThematicCSVs.ps1`, executado no CI, cobre esse comportamento.

### 5. Execução não interativa

Scripts `.ps1` rodam com `-NonInteractive`, e a saída de todos é capturada para o log. Quando o teste precisar do operador, use uma janela própria (Tkinter, por exemplo), como fazem os módulos 5 e 6.

## Checklist para um novo módulo

- [ ] Pasta `Testes/N_categoria/` e script `N_nome.py` (ou `.ps1`)
- [ ] Exit code `0` somente em PASS
- [ ] Evidências em `HUB_EVIDENCE_DIR`
- [ ] Parada segura (`Ctrl+Q`) em testes longos
- [ ] CSV temático registrado em `Copy-ThematicCSVs` (se houver)
- [ ] Dependências Python novas adicionadas a `Setup/environment/5_install_py_dependencies.ps1`
- [ ] Seção nova em `docs/metodologia-de-testes.md` (objetivo, procedimento, métricas e critério de aprovação) e passo a passo no `docs/manual-de-execucao.md`
- [ ] HTML da documentação regenerado com `python docs/gerar_html.py`

## Documentação

Os `.md` de `docs/` são a fonte única. Os `.html` são gerados a partir deles pelo `docs/gerar_html.py`, com o estilo de `docs/assets/estilo.css`, e **não devem ser editados à mão**:

```bash
pip install markdown
python docs/gerar_html.py          # regenera os HTML
python docs/gerar_html.py --check  # o mesmo teste que o CI roda
```

Para destacar um texto, use as convenções que o gerador converte nos componentes visuais:

| No Markdown | No HTML |
|-------------|---------|
| `> **Importante:** ...` ou `> **Atenção:** ...` | Caixa de alerta (amarela) |
| `> **Nota:** ...` ou `> **Dica:** ...` | Caixa informativa (azul) |
| `> ![Legenda](img/placeholder-x.png)` + `> *Insira aqui: ...*` | Espaço reservado para screenshot |
| `` `[Técnico]` `` / `` `[Gestão]` `` num título | Etiqueta de público |
| `**PASS**` / `**FAIL**` numa célula de tabela | Selo verde ou vermelho |

## Dados sensíveis

Este repositório é **público**. Nunca versione:

- IPs, URLs ou hostnames internos: coloque-os no `config.local.json`, que não é versionado;
- perfis `*.wpaProfile`, que listam os processos dos agentes monitorados;
- credenciais, tokens, números de série ou logs de execução reais;
- binários de terceiros cuja licença não permita redistribuição, como o `msedgedriver.exe`.

O job **Conteúdo sensível** do CI bloqueia esses arquivos e qualquer IPv4 fixo fora da lista permitida (`127.0.0.1`, `0.0.0.0`, `8.8.8.8`).

## Estilo

- Indentação de 4 espaços; scripts Windows (`.ps1`, `.bat`) com CRLF. O `.editorconfig` e o `.gitattributes` já cuidam disso.
- Mantenha compatibilidade com o **Windows PowerShell 5.1**, que é o runtime do hub. Evite sintaxe exclusiva do PowerShell 7, como `??`, `?.` e o operador ternário.
- Python 3.12, a versão instalada pelo setup.
