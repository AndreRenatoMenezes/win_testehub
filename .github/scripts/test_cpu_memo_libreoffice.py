"""Teste de regressao: Modulo 1 com workloads locais no LibreOffice
(Testes/1_cpu_memo/1_automacao_performance.py).

Valida:
1. Ausencia total de importacoes/referencias a selenium ou msedge no script.
2. Ordem de resolucao do executavel soffice.exe (HUB_LIBREOFFICE_PATH, PATH,
   caminhos padrao do Windows) e isolamento de subperfis wintesthub_lo_profile.
3. Geracao deterministica do .odt e da planilha R2 (.xlsx com as abas Data,
   Calc, Trigger e Sentinel; 100.000 formulas sem cache, texto igual ao do
   teste do macOS), semente do perfil do LibreOffice e leitura do Sentinel.
4. Consolidacao de metricas e geracao de ciclos_libreoffice.csv e
   cpu_memoria.csv (com e sem CSVs do WPA, incluindo Soma_Media).

Rodar: python -I -X utf8 .github/scripts/test_cpu_memo_libreoffice.py
"""
import csv
import importlib.util
import os
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "Testes" / "1_cpu_memo" / "1_automacao_performance.py"

spec = importlib.util.spec_from_file_location("automacao_performance", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

falhas = 0


def confere(cond, descricao):
    global falhas
    falhas += not cond
    print(f"  {'OK    ' if cond else 'FALHOU'}  {descricao}")


def perto(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


# --- 1. Ausencia de Selenium e Edge -------------------------------------------
codigo_fonte = SCRIPT_PATH.read_text(encoding="utf-8")
confere("selenium" not in codigo_fonte.lower(), "script nao importa nem referencia selenium")
confere("msedge" not in codigo_fonte.lower(), "script nao utiliza msedge")

# --- 2. Descoberta do soffice.exe e isolamento de perfil ----------------------
caminho_env = r"D:\Custom\LibreOffice\program\soffice.exe"
achado = mod.find_libreoffice_executable(
    env={"HUB_LIBREOFFICE_PATH": caminho_env},
    which_fn=lambda _: None,
    exists_fn=lambda p: p == caminho_env,
)
confere(achado == caminho_env, "prioridade 1: HUB_LIBREOFFICE_PATH valido")

achado_which = mod.find_libreoffice_executable(
    env={"HUB_LIBREOFFICE_PATH": r"C:\Inexistente\soffice.exe"},
    which_fn=lambda cmd: r"C:\Tools\soffice.exe" if cmd == "soffice.exe" else None,
    exists_fn=lambda p: p == r"C:\Tools\soffice.exe",
)
confere(achado_which == r"C:\Tools\soffice.exe", "prioridade 2: shutil.which quando HUB_LIBREOFFICE_PATH nao existe")

achado_padrao = mod.find_libreoffice_executable(
    env={},
    which_fn=lambda _: None,
    exists_fn=lambda p: p == r"C:\Program Files\LibreOffice\program\soffice.exe",
)
confere(
    achado_padrao == r"C:\Program Files\LibreOffice\program\soffice.exe",
    "prioridade 3: caminho padrao C:\\Program Files\\LibreOffice\\program\\soffice.exe",
)

achado_x86 = mod.find_libreoffice_executable(
    env={},
    which_fn=lambda _: None,
    exists_fn=lambda p: p == r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
confere(
    achado_x86 == r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "prioridade 3b: caminho padrao C:\\Program Files (x86)\\LibreOffice\\program\\soffice.exe",
)

achado_nenhum = mod.find_libreoffice_executable(
    env={},
    which_fn=lambda _: None,
    exists_fn=lambda _: False,
)
confere(achado_nenhum is None, "retorna None quando soffice.exe nao existe em nenhum local")

confere(mod.LO_PROFILE_PREFIX == "wintesthub_lo_profile", "prefixo de perfil wintesthub_lo_profile")
for flag in ("--norestore", "--nologo", "--nodefault", "--nolockcheck"):
    confere(flag in mod.LO_COMMON_FLAGS, f"flag obrigatoria {flag} presente em LO_COMMON_FLAGS")

uri_writer = mod.build_user_installation_uri("/tmp/wintesthub_lo_profile_writer")
confere(
    uri_writer.startswith("file:///") and "\\" not in uri_writer and "wintesthub_lo_profile_writer" in uri_writer,
    f"URI de UserInstallation formatada corretamente ({uri_writer})",
)
confere(
    mod._is_test_libreoffice_proc(
        "soffice.bin",
        ["soffice.bin", "-env:UserInstallation=file:///C:/Temp/wintesthub_lo_profile_calc", "--calc"],
    ),
    "identifica processo soffice.bin do teste pelo cmdline com wintesthub_lo_profile",
)
confere(
    not mod._is_test_libreoffice_proc("soffice.bin", ["soffice.bin", "--writer", "documento_usuario.odt"]),
    "ignora processo soffice.bin do usuario sem wintesthub_lo_profile",
)

# --- 3. Geracao deterministica do .odt e da planilha R2 ----------------------
NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
}
NS_X = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
    odt1, xlsx1 = mod.generate_odf_fixtures(tmp1)
    odt2, xlsx2 = mod.generate_odf_fixtures(tmp2)

    confere(Path(odt1).is_file() and Path(xlsx1).is_file(), "arquivos workload_doc.odt e workload_calc_r2.xlsx criados")
    confere(Path(xlsx1).name == "workload_calc_r2.xlsx", "planilha R2 com o nome do contrato")
    confere(not any(Path(tmp1).glob("*.ods")), "planilha .ods antiga (workload_calc_complexo.ods) nao e mais gerada")

    # Valida ODT
    with zipfile.ZipFile(odt1, "r") as zf_odt:
        names_odt = zf_odt.namelist()
        info_mime_odt = zf_odt.getinfo("mimetype")
        mime_odt = zf_odt.read("mimetype").decode("ascii")
        xml_odt = zf_odt.read("content.xml")

    confere(names_odt[0] == "mimetype", "ODT: 'mimetype' e a primeira entrada do ZIP")
    confere(info_mime_odt.compress_type == zipfile.ZIP_STORED, "ODT: 'mimetype' gravado com ZIP_STORED")
    confere(mime_odt == "application/vnd.oasis.opendocument.text", "ODT: mimetype correto")
    confere("META-INF/manifest.xml" in names_odt and "content.xml" in names_odt, "ODT: contem manifest.xml e content.xml")
    root_odt = ET.fromstring(xml_odt)
    paragrafos_odt = root_odt.findall(".//text:p", NS)
    confere(len(paragrafos_odt) == 20, f"ODT: 20 paragrafos iniciais (obtido {len(paragrafos_odt)})")

    # Valida R2
    confere(Path(xlsx1).read_bytes() == Path(xlsx2).read_bytes(), "R2: bytes identicos em duas geracoes (deterministica)")
    with zipfile.ZipFile(xlsx1, "r") as zx:
        nomes_x = set(zx.namelist())
        partes = {n: zx.read(n) for n in nomes_x}
    esperadas = {
        "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
        "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml", "xl/worksheets/sheet4.xml",
    }
    confere(esperadas <= nomes_x, "R2: pacote OOXML com workbook, rels e 4 worksheets")

    wb = ET.fromstring(partes["xl/workbook.xml"])
    abas = [sh.get("name") for sh in wb.findall(".//x:sheets/x:sheet", NS_X)]
    confere(abas == ["Data", "Calc", "Trigger", "Sentinel"], f"R2: abas na ordem Data, Calc, Trigger, Sentinel (obtido {abas})")
    view = wb.find(".//x:bookViews/x:workbookView", NS_X)
    confere(view is not None and view.get("activeTab") == "2", "R2: aba Trigger (indice 2) abre ativa")

    def _celulas(xml_bytes):
        root = ET.fromstring(xml_bytes)
        out = {}
        for c in root.iter(f"{{{NS_X['x']}}}c"):
            f = c.find("x:f", NS_X)
            v = c.find("x:v", NS_X)
            t = c.find("x:is/x:t", NS_X)
            out[c.get("r")] = {
                "f": f.text if f is not None else None,
                "v": v.text if v is not None else None,
                "t": t.text if t is not None else None,
            }
        return out

    data = _celulas(partes["xl/worksheets/sheet1.xml"])
    confere([data[f"{c}1"]["t"] for c in "ABCD"] == ["seq", "value", "category", "date"], "R2 Data: cabecalho seq, value, category, date")
    confere(len([k for k in data if k.startswith("A")]) == 5001, "R2 Data: 1 cabecalho + 5.000 linhas")
    confere(data["A2"]["v"] == "1" and perto(data["B2"]["v"], 1.000173, 1e-9) and data["C2"]["t"] == "beta", "R2 Data linha 2: seq=1, value=1.000173, category=beta")
    confere(data["D2"]["f"] == "DATE(2020, 1, 1) + MOD(1, 1825)", f"R2 Data D2: {data['D2']['f']}")
    confere(data["A5001"]["v"] == "5000" and perto(data["B5001"]["v"], (5000 * 1.000173) % 1000.0, 1e-9) and data["C5001"]["t"] == "alpha", "R2 Data linha 5001: seq=5000, value=(5000*1.000173)%1000, category=alpha")

    calc = _celulas(partes["xl/worksheets/sheet2.xml"])
    formulas_calc = [k for k, c in calc.items() if c["f"] is not None]
    confere(len(formulas_calc) == 100_000, f"R2 Calc: 5.000 x 20 = 100.000 formulas (obtido {len(formulas_calc)})")
    confere(all(calc[k]["v"] is None for k in formulas_calc), "R2 Calc: nenhuma formula com valor em cache (<v>)")
    confere([calc[f"{mod._col_letter(c)}1"]["t"] for c in range(20)] == [f"f{i}" for i in range(1, 21)], "R2 Calc: cabecalho f1..f20")
    esperadas_l2 = [
        "SUMIFS(Data!B$2:B$5001, Data!C$2:C$5001, Data!C2)",
        'COUNTIFS(Data!C$2:C$5001, Data!C2, Data!B$2:B$5001, ">"&Data!B2/2)',
        "AVERAGEIFS(Data!B$2:B$5001, Data!C$2:C$5001, Data!C2)",
        "_xlfn.MAXIFS(Data!B$2:B$5001, Data!C$2:C$5001, Data!C2)",
        "INDEX(Data!B$2:B$5001, MATCH(Data!A2, Data!A$2:A$5001, 0))",
        "VLOOKUP(MOD(Data!A2, 100), Data!A$2:B$5001, 2, FALSE)",
        "_xlfn.XLOOKUP(Data!C2, Data!C$2:C$5001, Data!B$2:B$5001)",
        'INDIRECT("Data!B" & (1 + MOD(Data!A2 * 7, 5000)))',
        "STDEV(Data!B2:B52)",
        "VAR(Data!B2:B52)",
        "PERCENTILE(Data!B2:B52, 0.95)",
        "RANK(Data!B2, Data!B2:B52, 0)",
        "NPV(0.05, Data!B2:B12)",
        "PMT(Data!B2/12000, 360, -100000)",
        "FV(Data!B2/12000, 360, -500, -10000)",
        "IPMT(0.05/12, MOD(Data!A2, 360) + 1, 360, -100000)",
        'IF(Data!B2 > 500, "high", IF(Data!B2 > 100, "mid", "low"))',
        'Data!C2 & "-" & TEXT(Data!B2, "0.00")',
        "LEN(Data!C2) * Data!B2",
        "IFERROR(SQRT(Data!B2 - 250), 0)",
    ]
    obtidas_l2 = [calc[f"{mod._col_letter(c)}2"]["f"] for c in range(20)]
    confere(obtidas_l2 == esperadas_l2, "R2 Calc linha 2: as 20 formulas com o texto exato do contrato 3")
    if obtidas_l2 != esperadas_l2:
        for k in [k for k, (o, e) in enumerate(zip(obtidas_l2, esperadas_l2)) if o != e]:
            print(f"          f{k + 1}: obtido {obtidas_l2[k]!r}")
    confere(calc["I2600"]["f"] == "STDEV(Data!B2550:B2650)" and calc["M2600"]["f"] == "NPV(0.05, Data!B2590:B2610)", "R2 Calc linha 2600: janelas +-50 e +-10 no meio da planilha")
    confere(calc["I5001"]["f"] == "STDEV(Data!B4951:B5001)" and calc["M5001"]["f"] == "NPV(0.05, Data!B4991:B5001)", "R2 Calc linha 5001: janelas truncadas no fim")
    confere(calc["T5001"]["f"] == "IFERROR(SQRT(Data!B5001 - 250), 0)", "R2 Calc T5001: ultima formula")
    sheet2_txt = partes["xl/worksheets/sheet2.xml"].decode("utf-8")
    confere("&quot;" not in sheet2_txt and '"&gt;"&amp;Data!B2/2' in sheet2_txt, "R2 Calc: aspas literais e & / > escapados no XML")

    trig = _celulas(partes["xl/worksheets/sheet3.xml"])
    confere(trig["A1"]["t"] == "seed" and trig["A2"]["v"] == "0", "R2 Trigger: A1=seed, A2=0")
    confere(b'tabSelected="1"' in partes["xl/worksheets/sheet3.xml"], "R2 Trigger: aba selecionada (tabSelected)")
    sent = _celulas(partes["xl/worksheets/sheet4.xml"])
    confere(
        sent["A1"]["t"] == "total" and sent["A2"]["f"] == "Calc!A2 + Calc!A5001 + Calc!T2 + Calc!T5001 + Trigger!A2*0" and sent["A2"]["v"] is None,
        "R2 Sentinel: A2 soma os cantos da aba Calc, sem cache",
    )
    datas_zip = {zi.date_time for zi in zipfile.ZipFile(xlsx1).infolist()}
    confere(datas_zip == {(1980, 1, 1, 0, 0, 0)}, "R2: entradas do ZIP com data fixa (sem relogio)")

# 3b. Semente do perfil e leitura do Sentinel/erros de um .ods recalculado
with tempfile.TemporaryDirectory() as tmp_prof:
    xcu = Path(mod.seed_lo_profile(str(Path(tmp_prof) / "wintesthub_lo_profile_calc")))
    confere(xcu == Path(tmp_prof) / "wintesthub_lo_profile_calc" / "user" / "registrymodifications.xcu", "semente do perfil em <perfil>/user/registrymodifications.xcu")
    rx = ET.parse(xcu).getroot()
    itens = {}
    for item in rx:
        for prop in item:
            itens[(item.get("{http://openoffice.org/2001/registry}path"), prop.get("{http://openoffice.org/2001/registry}name"))] = prop.find("value").text
    confere(itens.get(("/org.openoffice.Office.Calc/Formula/Load", "OOXMLRecalcMode")) == "0", "semente: OOXMLRecalcMode = 0 (sempre recalcular .xlsx)")
    confere(itens.get(("/org.openoffice.Office.Common/Save/Document", "WarnAlienFormat")) == "false", "semente: WarnAlienFormat = false (Ctrl+S sem dialogo de formato)")


def _ods_fake(path, sentinel_cell, calc_rows):
    """Monta um .ods minimo com as abas Calc e Sentinel."""
    def row(cells):
        return "<table:table-row>" + "".join(cells) + "</table:table-row>"
    calc_xml = row(['<table:table-cell office:value-type="string"><text:p>f1</text:p></table:table-cell>']) + "".join(row(r) for r in calc_rows)
    sent_xml = row(['<table:table-cell office:value-type="string"><text:p>total</text:p></table:table-cell>']) + row([sentinel_cell])
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<office:document-content xmlns:office="{NS["office"]}" xmlns:table="{NS["table"]}" xmlns:text="{NS["text"]}">'
        "<office:body><office:spreadsheet>"
        f'<table:table table:name="Calc">{calc_xml}</table:table>'
        f'<table:table table:name="Sentinel">{sent_xml}</table:table>'
        "</office:spreadsheet></office:body></office:document-content>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("content.xml", content)
    return path


ok_cell = '<table:table-cell office:value-type="float" office:value="12.5"><text:p>12,5</text:p></table:table-cell>'
err_cell = '<table:table-cell office:value-type="string"><text:p>#N/D</text:p></table:table-cell>'
erro_lo = '<table:table-cell office:value-type="string"><text:p>Err:502</text:p></table:table-cell>'
with tempfile.TemporaryDirectory() as tmp_ods:
    ods_ok = _ods_fake(
        str(Path(tmp_ods) / "ok.ods"),
        '<table:table-cell office:value-type="float" office:value="996865.173"><text:p>996865,17</text:p></table:table-cell>',
        [
            [ok_cell] * 5 + [err_cell] + [ok_cell] * 14,
            [ok_cell, f'<table:table-cell table:number-columns-repeated="3" office:value-type="string"><text:p>#NOME?</text:p></table:table-cell>'] + [ok_cell] * 16,
            [erro_lo] + [ok_cell] * 19,
        ],
    )
    confere(perto(mod.read_r2_sentinel(ods_ok), 996865.173, 1e-6), "read_r2_sentinel le o office:value de Sentinel.A2")
    erros = mod.count_r2_errors(ods_ok)
    confere(erros == {"f6": 1, "f2": 1, "f3": 1, "f4": 1, "f1": 1}, f"count_r2_errors conta #..., Err:... e respeita number-columns-repeated (obtido {erros})")
    ods_zero = _ods_fake(str(Path(tmp_ods) / "zero.ods"), '<table:table-cell office:value-type="float" office:value="0"><text:p>0</text:p></table:table-cell>', [[ok_cell] * 20])
    confere(mod.read_r2_sentinel(ods_zero) == 0.0, "read_r2_sentinel devolve 0 quando o Sentinel nao foi recalculado")
    ods_sem = _ods_fake(str(Path(tmp_ods) / "sem.ods"), '<table:table-cell/>', [[ok_cell] * 20])
    confere(mod.read_r2_sentinel(ods_sem) is None, "read_r2_sentinel devolve None quando Sentinel.A2 nao tem valor")
    confere(mod.R2_EXPECTED_ERRORS == {"f6": 50}, "erros esperados da propria R2: f6 = 50 (#N/A do VLOOKUP com chave 0)")

    # measure_formula_calculation: Sentinel ausente/zero reprova; .ods valido devolve (tempo, cpu)
    orig_popen = mod.subprocess.Popen

    class _FakeProc:
        pid = 424242
        returncode = 0

        def __init__(self, cmd, *a, **kw):
            self.cmd = cmd
            outdir = cmd[cmd.index("--outdir") + 1]
            base = os.path.splitext(os.path.basename(cmd[-1]))[0]
            shutil.copy(_FakeProc.fonte, os.path.join(outdir, base + ".ods"))
            _FakeProc.ultimo = cmd

        def poll(self):
            return 0

        def communicate(self):
            return "", ""

    try:
        mod.subprocess.Popen = _FakeProc
        xlsx_in = str(Path(tmp_ods) / "entrada.xlsx")
        Path(xlsx_in).write_bytes(b"x")
        _FakeProc.fonte = ods_ok
        res = mod.measure_formula_calculation("soffice.exe", xlsx_in, tmp_ods, "file:///C:/T/wintesthub_lo_profile_batch")
        confere(isinstance(res, tuple) and len(res) == 2, "measure_formula_calculation devolve (tempo_relogio_s, cpu_s)")
        cmd = _FakeProc.ultimo
        confere(cmd[cmd.index("--convert-to") + 1] == "ods" and "--headless" in cmd, "Etapa 1 converte para .ods em modo headless (nao mais PDF)")
        for fonte, desc in ((ods_zero, "Sentinel.A2 = 0"), (ods_sem, "Sentinel.A2 ausente")):
            _FakeProc.fonte = fonte
            reprovou = False
            try:
                mod.measure_formula_calculation("soffice.exe", xlsx_in, tmp_ods, "file:///C:/T/wintesthub_lo_profile_batch")
            except RuntimeError as e:
                reprovou = "recalculo nao confirmado" in str(e).lower()
            confere(reprovou, f"Etapa 1 reprova com RuntimeError quando {desc}")
    finally:
        mod.subprocess.Popen = orig_popen

# --- 4. Consolidacao e contratos de ciclos_libreoffice.csv e cpu_memoria.csv --
ciclos_fake = [
    {
        "Ciclo": i,
        "Timestamp_Inicio": f"2026-11-25 15:0{i}:00",
        "Tempo_Abertura_Writer_s": 1.20 + i * 0.10,
        "Tempo_Abertura_Calc_s": 2.00 + i * 0.20,
        "Tempo_Calculo_Formulas_s": 3.50 + i * 0.30,
        "CPU_Calculo_Formulas_s": 15.00 + i,
        "Linhas_Editadas_Calc": 6,
        "Paragrafos_Digitados_Writer": 4,
        "CPU_Sistema_Media_Pct": 20.0 + i,
        "CPU_Sistema_Pico_Pct": 45.0 + i * 2,
        "RAM_Sistema_Media_MB": 4000.0 + i * 50,
        "RAM_Sistema_Pico_MB": 4500.0 + i * 60,
        "RAM_Sistema_Media_Pct": 50.0 + i * 0.5,
        "RAM_Sistema_Pico_Pct": 58.0 + i * 0.5,
        "LibreOffice_CPU_Media_Pct": 10.0 + i * 0.5,
        "LibreOffice_CPU_Pico_Pct": 28.0 + i,
        "LibreOffice_RAM_Media_MB": 250.0 + i * 10,
        "LibreOffice_RAM_Pico_MB": 320.0 + i * 15,
        "Cooldown_Duracao_s": 30.0 if i < 5 else 0.0,
    }
    for i in range(1, 6)
]

# 4A. Sem CSVs do WPA (profile ausente / execucao avulsa)
with tempfile.TemporaryDirectory() as tmp_sem_wpa:
    mod.consolidate_results(ui=None, cycle_metrics=ciclos_fake, output_path=tmp_sem_wpa)

    p_ciclos = Path(tmp_sem_wpa) / "ciclos_libreoffice.csv"
    p_cpumemo = Path(tmp_sem_wpa) / "cpu_memoria.csv"
    p_html = Path(tmp_sem_wpa) / "Resultados_Consolidados" / "Relatorio_Resumo.html"

    confere(p_ciclos.is_file(), "sem WPA: ciclos_libreoffice.csv gerado")
    confere(p_cpumemo.is_file(), "sem WPA: cpu_memoria.csv gerado")
    confere(p_html.is_file(), "sem WPA: Relatorio_Resumo.html gerado")

    with open(p_ciclos, "r", encoding="utf-8", newline="") as f:
        linhas_ciclos = list(csv.reader(f))

    confere(linhas_ciclos[0] == mod.CICLOS_CSV_COLUMNS, "ciclos_libreoffice.csv: cabecalho identico ao contrato")
    confere(
        mod.CICLOS_CSV_COLUMNS[mod.CICLOS_CSV_COLUMNS.index("Tempo_Calculo_Formulas_s") + 1] == "CPU_Calculo_Formulas_s",
        "ciclos_libreoffice.csv: CPU_Calculo_Formulas_s logo depois de Tempo_Calculo_Formulas_s",
    )
    col_cpu = linhas_ciclos[0].index("CPU_Calculo_Formulas_s")
    confere([r[col_cpu] for r in linhas_ciclos[1:]] == ["16.00", "17.00", "18.00", "19.00", "20.00"], "ciclos_libreoffice.csv: CPU_Calculo_Formulas_s por ciclo (.2f)")
    confere(len(linhas_ciclos) == 6, "ciclos_libreoffice.csv: 1 cabecalho + 5 linhas de ciclo")
    confere(
        [r[0] for r in linhas_ciclos[1:]] == ["1", "2", "3", "4", "5"],
        "ciclos_libreoffice.csv: ciclos numerados de 1 a 5",
    )

    with open(p_cpumemo, "r", encoding="utf-8", newline="") as f:
        linhas_cm = list(csv.reader(f))

    confere(linhas_cm[0] == ["Metrica", "Valor", "Unidade"], "cpu_memoria.csv: cabecalho Metrica,Valor,Unidade")
    mapa_cm = {r[0]: (r[1], r[2]) for r in linhas_cm[1:]}

    confere(mapa_cm.get("Versao_Teste") == ("2.1", ""), "cpu_memoria.csv: Versao_Teste = 2.1")
    confere(mapa_cm.get("Ciclos_Executados") == ("5", "un"), "cpu_memoria.csv: Ciclos_Executados = 5 un")
    confere(mapa_cm.get("Duracao_Por_Ciclo") == ("300", "s"), "cpu_memoria.csv: Duracao_Por_Ciclo = 300 s")
    confere(mapa_cm.get("Tempo_Abertura_Writer_Media") == ("1.50", "s"), "Tempo_Abertura_Writer_Media = 1.50 s")
    confere(mapa_cm.get("Tempo_Abertura_Writer_Max") == ("1.70", "s"), "Tempo_Abertura_Writer_Max = 1.70 s")
    confere(mapa_cm.get("Tempo_Abertura_Calc_Media") == ("2.60", "s"), "Tempo_Abertura_Calc_Media = 2.60 s")
    confere(mapa_cm.get("Tempo_Abertura_Calc_Max") == ("3.00", "s"), "Tempo_Abertura_Calc_Max = 3.00 s")
    confere(mapa_cm.get("Tempo_Calculo_Formulas_Media") == ("4.40", "s"), "Tempo_Calculo_Formulas_Media = 4.40 s")
    confere(mapa_cm.get("Tempo_Calculo_Formulas_Max") == ("5.00", "s"), "Tempo_Calculo_Formulas_Max = 5.00 s")
    confere(mapa_cm.get("Tempo_Calculo_Formulas_Min") == ("3.80", "s"), "Tempo_Calculo_Formulas_Min = 3.80 s")
    confere(mapa_cm.get("CPU_Calculo_Formulas_Media") == ("18.00", "s"), "CPU_Calculo_Formulas_Media = 18.00 s")
    confere(mapa_cm.get("CPU_Calculo_Formulas_Max") == ("20.00", "s"), "CPU_Calculo_Formulas_Max = 20.00 s")
    confere(mapa_cm.get("CPU_Calculo_Formulas_Min") == ("16.00", "s"), "CPU_Calculo_Formulas_Min = 16.00 s")
    ordem = [r[0] for r in linhas_cm[1:]]
    confere(ordem.index("CPU_Calculo_Formulas_Media") == ordem.index("Tempo_Calculo_Formulas_Min") + 1, "CPU_Calculo_Formulas_* logo depois de Tempo_Calculo_Formulas_Min")
    confere(mapa_cm.get("CPU_Sistema_Media") == ("23.0", "%"), "CPU_Sistema_Media = 23.0 %")
    confere(mapa_cm.get("CPU_Sistema_Pico") == ("55.0", "%"), "CPU_Sistema_Pico = 55.0 %")
    confere(mapa_cm.get("RAM_Sistema_Media_MB") == ("4150.0", "MB"), "RAM_Sistema_Media_MB = 4150.0 MB")
    confere(mapa_cm.get("RAM_Sistema_Pico_MB") == ("4800.0", "MB"), "RAM_Sistema_Pico_MB = 4800.0 MB")
    confere(mapa_cm.get("RAM_Sistema_Media_Pct") == ("51.5", "%"), "RAM_Sistema_Media_Pct = 51.5 %")
    confere(mapa_cm.get("RAM_Sistema_Pico_Pct") == ("60.5", "%"), "RAM_Sistema_Pico_Pct = 60.5 %")
    confere(mapa_cm.get("LibreOffice_CPU_Media") == ("11.5", "%"), "LibreOffice_CPU_Media = 11.5 %")
    confere(mapa_cm.get("LibreOffice_CPU_Pico") == ("33.0", "%"), "LibreOffice_CPU_Pico = 33.0 %")
    confere(mapa_cm.get("LibreOffice_RAM_Media_MB") == ("280.0", "MB"), "LibreOffice_RAM_Media_MB = 280.0 MB")
    confere(mapa_cm.get("LibreOffice_RAM_Pico_MB") == ("395.0", "MB"), "LibreOffice_RAM_Pico_MB = 395.0 MB")

    metricas_legadas = [
        "CPU_Frequencia_Atual",
        "CPU_Frequencia_Max",
        "CPU_Nucleos_Fisicos",
        "CPU_Nucleos_Logicos",
        "RAM_Total_GB",
        "RAM_Disponivel_GB",
        "RAM_Uso_Percentual",
    ]
    for m_leg in metricas_legadas:
        confere(m_leg in mapa_cm, f"metrica legada preservada: {m_leg}")

# 4B. Com CSVs do WPA (valida Soma_Media, Media, Max, Min e limpeza de PID)
with tempfile.TemporaryDirectory() as tmp_com_wpa:
    run1_dir = Path(tmp_com_wpa) / "CSV_20261125_Run1"
    run2_dir = Path(tmp_com_wpa) / "CSV_20261125_Run2"
    run1_dir.mkdir()
    run2_dir.mkdir()

    # AgenteA: Run1 = 10.0, Run2 = 20.0 -> media processo = 15.0
    # AgenteB: Run1 = 30.0, Run2 = 50.0 -> media processo = 40.0
    # Soma_Media = 55.00 | Media = 27.50 | Max = 40.00 | Min = 15.00
    (run1_dir / "Agentes_CPU.csv").write_text(
        "Process Name,CPU_Weight\nAgenteA.exe (1234),\"10,00\"\nAgenteB.exe (5678),\"30,00\"\n",
        encoding="utf-8-sig",
    )
    (run2_dir / "Agentes_CPU.csv").write_text(
        "Process Name,CPU_Weight\nAgenteA.exe (9999),\"20,00\"\nAgenteB.exe (8888),\"50,00\"\n",
        encoding="utf-8-sig",
    )

    mod.consolidate_results(ui=None, cycle_metrics=ciclos_fake, output_path=tmp_com_wpa)

    with open(Path(tmp_com_wpa) / "cpu_memoria.csv", "r", encoding="utf-8", newline="") as f:
        mapa_wpa = {r[0]: (r[1], r[2]) for r in list(csv.reader(f))[1:]}

    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media") == ("55.00", ""),
        f"WPA Soma_Media = 55.00 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Soma_Media')})",
    )
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Media") == ("27.50", ""),
        f"WPA Media = 27.50 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Media')})",
    )
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Max") == ("40.00", ""),
        f"WPA Max = 40.00 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Max')})",
    )
    confere(
        mapa_wpa.get("WPA_Agentes_CPU.csv_CPU_Weight_Min") == ("15.00", ""),
        f"WPA Min = 15.00 (obtido {mapa_wpa.get('WPA_Agentes_CPU.csv_CPU_Weight_Min')})",
    )

# 4C. Presenca variavel de processos entre ciclos (Ciclo 1: A=10, B=20 [soma=30]; Ciclo 2: A=10 [soma=10] -> Soma_Media = 20.00)
with tempfile.TemporaryDirectory() as tmp_wpa_var:
    r1_dir = Path(tmp_wpa_var) / "CSV_20261125_Run1"
    r2_dir = Path(tmp_wpa_var) / "CSV_20261125_Run2"
    r1_dir.mkdir()
    r2_dir.mkdir()

    csv_r1 = r1_dir / "Variavel_CPU.csv"
    csv_r2 = r2_dir / "Variavel_CPU.csv"
    csv_r1.write_text("Process Name,CPU_Weight\nProcA.exe (101),10.0\nProcB.exe (202),20.0\n", encoding="utf-8-sig")
    csv_r2.write_text("Process Name,CPU_Weight\nProcA.exe (105),10.0\n", encoding="utf-8-sig")

    # Caminho 1: com mod.pd atual (pandas se instalado, ou stdlib)
    mod.consolidate_results(ui=None, cycle_metrics=ciclos_fake, output_path=tmp_wpa_var)
    with open(Path(tmp_wpa_var) / "cpu_memoria.csv", "r", encoding="utf-8", newline="") as f:
        mapa_var1 = {r[0]: (r[1], r[2]) for r in list(csv.reader(f))[1:]}
    confere(
        mapa_var1.get("WPA_Variavel_CPU.csv_CPU_Weight_Soma_Media") == ("20.00", ""),
        f"presenca variavel (caminho padrao): Soma_Media = 20.00 (media das somas 30 e 10, obtido {mapa_var1.get('WPA_Variavel_CPU.csv_CPU_Weight_Soma_Media')})",
    )

    # Caminho 2: forcando fallback stdlib (mod.pd = None)
    orig_pd = mod.pd
    try:
        mod.pd = None
        entries_stdlib = mod._consolidate_wpa_csv_group(
            "Variavel_CPU.csv",
            [str(csv_r1), str(csv_r2)],
            str(Path(tmp_wpa_var) / "Resultados_Consolidados"),
        )
        confere(
            len(entries_stdlib) == 1 and perto(entries_stdlib[0]["Soma_Media"], 20.0),
            f"presenca variavel (fallback stdlib): Soma_Media = 20.00 (obtido {entries_stdlib[0]['Soma_Media'] if entries_stdlib else None})",
        )
    finally:
        mod.pd = orig_pd

    # Caminho 3: se pandas nao estiver instalado no host, testa tambem o ramo pandas com stub minimo de DataFrame
    if mod.pd is None:
        class _FakeSeries(list):
            def dropna(self):
                return _FakeSeries([x for x in self if x is not None])

            def head(self, n):
                return _FakeSeries(self[:n])

            def astype(self, _t):
                return _FakeSeries([str(x) for x in self])

            @property
            def str(self):
                parent = self

                class _StrOps:
                    def replace(self, pat, repl, regex=False):
                        import re as _re
                        if regex:
                            return _FakeSeries([_re.sub(pat, repl, s) for s in parent])
                        return _FakeSeries([s.replace(pat, repl) for s in parent])

                return _StrOps()

            def sum(self):
                return sum(float(x) for x in self if x is not None)

            def mean(self):
                vals = [float(x) for x in self if x is not None]
                return sum(vals) / len(vals) if vals else 0.0

            def max(self):
                return max(float(x) for x in self if x is not None)

            def min(self):
                return min(float(x) for x in self if x is not None)

        class _FakeDF:
            def __init__(self, rows, columns):
                self.rows = rows
                self.columns = list(columns)

            @property
            def empty(self):
                return len(self.rows) == 0

            def __getitem__(self, col):
                if isinstance(col, list):
                    return _FakeDF([{k: r[k] for k in col if k in r} for r in self.rows], col)
                return _FakeSeries([r.get(col) for r in self.rows])

            def __setitem__(self, col, vals):
                for r, v in zip(self.rows, vals):
                    r[col] = v

            def groupby(self, key_col, as_index=False):
                parent = self
                num_cols = [c for c in self.columns if c != key_col]

                class _GroupBy:
                    def __getitem__(self, cols):
                        return self

                    def sum(self):
                        acc = {}
                        for r in parent.rows:
                            k = r[key_col]
                            d = acc.setdefault(k, {key_col: k, **{c: 0.0 for c in num_cols}})
                            for c in num_cols:
                                if r.get(c) is not None:
                                    d[c] += float(r[c])
                        return _FakeDF(list(acc.values()), parent.columns)

                    def mean(self):
                        buckets = {}
                        for r in parent.rows:
                            k = r[key_col]
                            b = buckets.setdefault(k, {c: [] for c in num_cols})
                            for c in num_cols:
                                if r.get(c) is not None:
                                    b[c].append(float(r[c]))
                        out = []
                        for k, b in buckets.items():
                            out.append({key_col: k, **{c: sum(b[c]) / len(b[c]) for c in num_cols}})
                        return _FakeDF(out, [key_col] + num_cols)

                    def count(self):
                        buckets = {}
                        for r in parent.rows:
                            k = r[key_col]
                            b = buckets.setdefault(k, {c: 0 for c in num_cols})
                            for c in num_cols:
                                if r.get(c) is not None:
                                    b[c] += 1
                        out = [{key_col: k, **b} for k, b in buckets.items()]
                        return _FakeDF(out, [key_col] + num_cols)

                return _GroupBy()

            def rename(self, columns, inplace=False):
                self.columns = [columns.get(c, c) for c in self.columns]
                for r in self.rows:
                    for old_k, new_k in list(columns.items()):
                        if old_k in r:
                            r[new_k] = r.pop(old_k)

            def to_csv(self, path, index=False, sep=",", encoding="utf-8-sig"):
                with open(path, "w", encoding=encoding, newline="") as f:
                    w = csv.DictWriter(f, fieldnames=self.columns)
                    w.writeheader()
                    for r in self.rows:
                        w.writerow(r)

        class _FakePandas:
            @staticmethod
            def read_csv(fp, encoding="utf-8-sig"):
                with open(fp, "r", encoding=encoding, newline="") as f:
                    rd = list(csv.reader(f))
                if not rd:
                    return _FakeDF([], [])
                hdr = rd[0]
                return _FakeDF([dict(zip(hdr, row)) for row in rd[1:]], hdr)

            @staticmethod
            def to_numeric(series, errors="coerce"):
                out = []
                for v in series:
                    try:
                        out.append(float(v))
                    except Exception:
                        out.append(None)
                return _FakeSeries(out)

            @staticmethod
            def concat(dfs):
                cols = dfs[0].columns if dfs else []
                rows = [dict(r) for d in dfs for r in d.rows]
                return _FakeDF(rows, cols)

            @staticmethod
            def merge(df1, df2, on):
                by_k = {r[on]: dict(r) for r in df2.rows}
                merged = [{**r, **by_k.get(r[on], {})} for r in df1.rows]
                cols = list(df1.columns) + [c for c in df2.columns if c != on]
                return _FakeDF(merged, cols)

        try:
            mod.pd = _FakePandas
            entries_pd = mod._consolidate_wpa_csv_group(
                "Variavel_CPU.csv",
                [str(csv_r1), str(csv_r2)],
                str(Path(tmp_wpa_var) / "Resultados_Consolidados"),
            )
            confere(
                len(entries_pd) == 1 and perto(entries_pd[0]["Soma_Media"], 20.0),
                f"presenca variavel (ramo pandas): Soma_Media = 20.00 (obtido {entries_pd[0]['Soma_Media'] if entries_pd else None})",
            )
        finally:
            mod.pd = None

# --- 5. Testes de runtime simulados (ciclo 300s com erro GUI, wpaexporter e cleanup) ---
import time
from types import SimpleNamespace


class _DummyUI:
    def __init__(self, on_update=None):
        self.on_update = on_update

    def atualizar(self, ciclo, status, tempo="--"):
        if self.on_update:
            self.on_update(ciclo, status, tempo)

    def fechar(self):
        pass


with tempfile.TemporaryDirectory() as tmp_rt:
    odt_rt, ods_rt = mod.generate_odf_fixtures(tmp_rt)  # ods_rt = planilha R2 (.xlsx)

    orig_stabilize = mod.STABILIZE_SECONDS
    orig_duration = mod.DURATION_SECONDS
    orig_base_dir = mod.BASE_DIR
    orig_output_path = mod.OUTPUT_PATH
    orig_subproc_run = mod.subprocess.run
    orig_calc_fn = mod.measure_formula_calculation
    orig_launch_fn = mod.measure_app_launch
    orig_writer_fn = mod.simulate_writer_editing
    orig_calc_gui_fn = mod.simulate_calc_editing
    orig_mkdtemp = mod.tempfile.mkdtemp
    orig_check_prereq = mod.check_prerequisites

    try:
        mod.OUTPUT_PATH = tmp_rt
        mod.BASE_DIR = tmp_rt

        # 5A. Falha de GUI e efetivamente invocada, propaga excecao e resulta em FAIL (_exit_code = 1),
        #     e tempo expirado antes de completar edicoes no Writer e no Calc tambem reprova o ciclo.
        mod.STABILIZE_SECONDS = 0
        mod.DURATION_SECONDS = 5.0
        mod.subprocess.run = lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")
        mod.measure_formula_calculation = lambda *a, **kw: (0.01, 0.02)
        mod.measure_app_launch = lambda *a, **kw: (0.01, 100, 200)

        gui_calls = {"writer": 0, "calc": 0}

        def _fail_gui(*_a, **_kw):
            gui_calls["writer"] += 1
            raise RuntimeError("erro simulado de GUI no Writer")

        mod.simulate_writer_editing = _fail_gui
        mod.simulate_calc_editing = lambda *_a, **_kw: 2

        gui_propagou = False
        try:
            mod.run_test_cycle(1, _DummyUI(), "soffice.exe", odt_rt, ods_rt)
        except RuntimeError as e:
            gui_propagou = "erro simulado de GUI no Writer" in str(e)

        confere(
            gui_calls["writer"] == 1 and gui_propagou,
            f"funcao de edicao GUI com falha foi chamada ({gui_calls['writer']}x) e propagou RuntimeError",
        )

        mod.check_prerequisites = lambda: "soffice.exe"
        mod._exit_code = 0
        gui_calls["writer"] = 0
        mod.worker_thread(_DummyUI())
        confere(
            gui_calls["writer"] == 1 and mod._exit_code == 1,
            "falha de GUI em worker_thread chama a funcao de edicao e resulta em _exit_code = 1 (FAIL)",
        )

        # Tempo expirado antes de qualquer edicao GUI (zero edicoes no Writer e Calc) -> RuntimeError (FAIL)
        mod.DURATION_SECONDS = 0.0
        gui_calls = {"writer": 0, "calc": 0}

        def _writer_ok(*_a, **_kw):
            gui_calls["writer"] += 1
            return 1

        def _calc_ok(*_a, **_kw):
            gui_calls["calc"] += 1
            return 2

        mod.simulate_writer_editing = _writer_ok
        mod.simulate_calc_editing = _calc_ok
        expirou_sem_edicao = False
        try:
            mod.run_test_cycle(1, _DummyUI(), "soffice.exe", odt_rt, ods_rt)
        except RuntimeError as e:
            expirou_sem_edicao = "sem edicoes GUI completas" in str(e)

        confere(
            gui_calls["writer"] == 0 and gui_calls["calc"] == 0 and expirou_sem_edicao,
            "tempo expirado antes das edicoes GUI (0 edicoes) rejeita o ciclo com RuntimeError",
        )

        # Tempo expirado apos editar apenas o Writer (0 edicoes no Calc) -> RuntimeError e _exit_code = 1 (FAIL)
        mod.DURATION_SECONDS = 0.15

        def _writer_slow(*_a, **_kw):
            gui_calls["writer"] += 1
            time.sleep(0.20)
            return 1

        mod.simulate_writer_editing = _writer_slow
        mod.simulate_calc_editing = _calc_ok
        gui_calls = {"writer": 0, "calc": 0}
        expirou_sem_calc = False
        try:
            mod.run_test_cycle(1, _DummyUI(), "soffice.exe", odt_rt, ods_rt)
        except RuntimeError as e:
            expirou_sem_calc = "sem edicoes GUI completas" in str(e)

        confere(
            gui_calls["writer"] == 1 and gui_calls["calc"] == 0 and expirou_sem_calc,
            "tempo expirado apos Writer mas sem edicao no Calc rejeita o ciclo com RuntimeError",
        )

        mod._exit_code = 0
        mod.worker_thread(_DummyUI())
        confere(
            mod._exit_code == 1,
            "ciclo sem edicoes completas no Writer e Calc resulta em _exit_code = 1 (FAIL) no worker_thread",
        )

        # 5B. Falha do wpaexporter.exe aborta o ciclo com RuntimeError e define _exit_code = 1
        (Path(tmp_rt) / mod.PROFILE_NAME).write_text("<Profile/>", encoding="utf-8")
        mod.DURATION_SECONDS = 0.30
        mod.simulate_writer_editing = lambda *_a, **_kw: 1
        mod.simulate_calc_editing = lambda *_a, **_kw: 2

        def _run_wpa_fail(cmd, *a, **kw):
            if "wpaexporter.exe" in str(cmd):
                return SimpleNamespace(returncode=1, stdout="", stderr="wpaexporter falhou no trace")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        mod.subprocess.run = _run_wpa_fail
        wpa_falhou = False
        try:
            mod.run_test_cycle(1, _DummyUI(), "soffice.exe", odt_rt, ods_rt)
        except RuntimeError as e:
            wpa_falhou = "wpaexporter" in str(e).lower()
        confere(wpa_falhou, "falha do wpaexporter.exe levanta RuntimeError no ciclo")

        mod.check_prerequisites = lambda: "soffice.exe"
        mod._exit_code = 0
        mod.worker_thread(_DummyUI())
        confere(mod._exit_code == 1, "falha do wpaexporter.exe em worker_thread resulta em _exit_code = 1 (FAIL)")
        (Path(tmp_rt) / mod.PROFILE_NAME).unlink(missing_ok=True)

        # 5C. Parada durante estabilizacao ou excecao antes do WPR remove cycle_dir e subperfis
        created_cycle_dirs = []

        def _tracking_mkdtemp(*a, **kw):
            d = orig_mkdtemp(*a, **kw)
            if "wintesthub_lo_cycle" in os.path.basename(d):
                created_cycle_dirs.append(d)
            return d

        mod.tempfile.mkdtemp = _tracking_mkdtemp
        mod.STABILIZE_SECONDS = 3

        def _stop_on_stabilize(ciclo, status, tempo="--"):
            if "Estabilizando" in str(status):
                mod._stop_requested.set()

        parou_estab = False
        try:
            mod.run_test_cycle(1, _DummyUI(on_update=_stop_on_stabilize), "soffice.exe", odt_rt, ods_rt)
        except KeyboardInterrupt:
            parou_estab = True
        finally:
            mod._stop_requested.clear()

        confere(parou_estab, "parada segura durante estabilizacao interrompe o ciclo com KeyboardInterrupt")
        confere(
            len(created_cycle_dirs) == 1 and not os.path.exists(created_cycle_dirs[0]),
            "diretorio temporario e subperfis removidos quando parada ocorre durante estabilizacao",
        )

        created_cycle_dirs.clear()
        mod.STABILIZE_SECONDS = 0

        def _run_wpr_start_fail(cmd, *a, **kw):
            if "wpr.exe -start" in str(cmd):
                return SimpleNamespace(returncode=1, stdout="", stderr="erro wpr start")
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        mod.subprocess.run = _run_wpr_start_fail
        wpr_start_falhou = False
        try:
            mod.run_test_cycle(1, _DummyUI(), "soffice.exe", odt_rt, ods_rt)
        except RuntimeError:
            wpr_start_falhou = True

        confere(
            wpr_start_falhou and len(created_cycle_dirs) == 1 and not os.path.exists(created_cycle_dirs[0]),
            "diretorio temporario e subperfis removidos quando wpr.exe -start falha",
        )

        # 5D. Verificacao de foco GUI (_focus_window / simulate_writer_editing / simulate_calc_editing)
        mod.simulate_writer_editing = orig_writer_fn
        mod.simulate_calc_editing = orig_calc_gui_fn
        orig_get_u32 = mod._get_user32
        orig_pyautogui = mod.pyautogui
        orig_pyperclip = mod.pyperclip
        try:
            class _FakePyAutoGUI:
                FailSafeException = RuntimeError
                @staticmethod
                def hotkey(*_a): pass
                @staticmethod
                def press(*_a): pass
                @staticmethod
                def click(*_a): pass
                @staticmethod
                def size(): return (1920, 1080)

            class _FakePyperclip:
                @staticmethod
                def copy(_t): pass

            mod.pyautogui = _FakePyAutoGUI
            mod.pyperclip = _FakePyperclip

            class _FakeUser32Unfocused:
                @staticmethod
                def IsWindow(_h): return 1
                @staticmethod
                def IsWindowVisible(_h): return 1
                @staticmethod
                def IsIconic(_h): return 0
                @staticmethod
                def ShowWindow(_h, _c): return 1
                @staticmethod
                def SetForegroundWindow(_h): return 0
                @staticmethod
                def GetForegroundWindow(): return 999  # Foco permaneceu em outra janela

            mod._get_user32 = lambda: _FakeUser32Unfocused
            foco_writer_rejeitado = False
            try:
                mod.simulate_writer_editing(200)
            except RuntimeError as e:
                foco_writer_rejeitado = "foco gui nao confirmado" in str(e).lower()

            foco_calc_rejeitado = False
            try:
                mod.simulate_calc_editing(201)
            except RuntimeError as e:
                foco_calc_rejeitado = "foco gui nao confirmado" in str(e).lower()

            confere(
                foco_writer_rejeitado and foco_calc_rejeitado,
                "SetForegroundWindow nao confirmado (GetForegroundWindow != hwnd) impede contabilizar edicao no Writer e no Calc",
            )

            class _FakeUser32Focused:
                current_fg = 0
                @staticmethod
                def IsWindow(_h): return 1
                @staticmethod
                def IsWindowVisible(_h): return 1
                @staticmethod
                def IsIconic(_h): return 0
                @staticmethod
                def ShowWindow(_h, _c): return 1
                @classmethod
                def SetForegroundWindow(cls, h):
                    cls.current_fg = h
                    return 1
                @classmethod
                def GetForegroundWindow(cls):
                    return cls.current_fg

            mod._get_user32 = lambda: _FakeUser32Focused
            ed_w = mod.simulate_writer_editing(200)
            ed_c = mod.simulate_calc_editing(201)
            confere(
                ed_w == 1 and ed_c == 2,
                "quando GetForegroundWindow confirma o HWND alvo, edicoes no Writer (1) e Calc (2) sao contabilizadas",
            )
        finally:
            mod._get_user32 = orig_get_u32
            mod.pyautogui = orig_pyautogui
            mod.pyperclip = orig_pyperclip
    finally:
        mod.STABILIZE_SECONDS = orig_stabilize
        mod.DURATION_SECONDS = orig_duration
        mod.BASE_DIR = orig_base_dir
        mod.OUTPUT_PATH = orig_output_path
        mod.subprocess.run = orig_subproc_run
        mod.measure_formula_calculation = orig_calc_fn
        mod.measure_app_launch = orig_launch_fn
        mod.simulate_writer_editing = orig_writer_fn
        mod.simulate_calc_editing = orig_calc_gui_fn
        mod.tempfile.mkdtemp = orig_mkdtemp
        mod.check_prerequisites = orig_check_prereq
        mod._stop_requested.clear()

# --- 6. Espera de ociosidade do Calc apos recalculo da R2 (_wait_lo_idle) -------
class _FakeU32Pid:
    @staticmethod
    def GetWindowThreadProcessId(_h, ref):
        ref._obj.value = 777
        return 1


def _fake_psutil(leituras):
    class _P:
        def __init__(self, pid):
            assert pid == 777
            self.seq = list(leituras)

        def cpu_percent(self, interval=None):
            return self.seq.pop(0) if self.seq else 0.0

    return SimpleNamespace(Process=_P)


orig_psutil = mod.psutil
orig_interval = mod.LO_IDLE_INTERVAL
try:
    mod.LO_IDLE_INTERVAL = 0.01
    # 1a leitura (priming) + 120% (recalculando) + 90% + 2 leituras ociosas
    mod.psutil = _fake_psutil([0.0, 120.0, 90.0, 1.0, 0.5])
    esperou = mod._wait_lo_idle(555, timeout=5, user32=_FakeU32Pid)
    confere(0.03 <= esperou < 1.0, f"_wait_lo_idle sai depois de {mod.LO_IDLE_SAMPLES} leituras ociosas seguidas ({esperou:.2f}s)")

    mod.psutil = _fake_psutil([0.0, 1.0, 80.0, 2.0, 3.0])
    t_ini = time.perf_counter()
    mod._wait_lo_idle(555, timeout=5, user32=_FakeU32Pid)
    confere(time.perf_counter() - t_ini >= 0.04, "_wait_lo_idle exige leituras ociosas consecutivas (pico no meio zera a contagem)")

    mod.psutil = _fake_psutil([0.0] + [150.0] * 1000)
    estourou = False
    try:
        mod._wait_lo_idle(555, timeout=0.05, user32=_FakeU32Pid)
    except RuntimeError as e:
        estourou = "nao ficou ocioso" in str(e)
    confere(estourou, "_wait_lo_idle levanta RuntimeError quando o Calc nao fica ocioso no teto")

    confere(mod._wait_lo_idle(555, user32=SimpleNamespace()) == 0.0, "_wait_lo_idle sem GetWindowThreadProcessId (CI/fake) retorna 0 sem esperar")
    mod.psutil = _fake_psutil([150.0] * 1000)
    sem_dono = SimpleNamespace(GetWindowThreadProcessId=lambda _h, ref: 0)
    t_ini = time.perf_counter()
    confere(mod._wait_lo_idle(555, timeout=5, user32=sem_dono) == 0.0 and time.perf_counter() - t_ini < 0.5, "_wait_lo_idle com HWND sem processo dono (pid 0 = Idle do sistema) retorna na hora")
    confere(mod.CALC_LAUNCH_TIMEOUT == 180 and mod.APP_LAUNCH_TIMEOUT == 60, "timeouts: Calc 180 s (recalcula a R2 ao abrir), Writer 60 s")
finally:
    mod.psutil = orig_psutil
    mod.LO_IDLE_INTERVAL = orig_interval

# --- 7. Rastreamento pela arvore do soffice.exe lancado (_lo_tree_procs) ---------
# Com o hub elevado, varrer o cmdline de todos os processos leva segundos e perde o
# soffice.bin; o teste segue a arvore (pid/ppid) dos processos que ele mesmo lanca.
if mod.psutil is not None:
    import subprocess as _sp

    neto_code = "import time; time.sleep(30)"
    filho_code = (
        "import subprocess, sys, time; "
        f"p = subprocess.Popen([sys.executable, '-c', {neto_code!r}]); "
        "print(p.pid, flush=True); time.sleep(30)"
    )
    raiz = _sp.Popen([sys.executable, "-c", filho_code], stdout=_sp.PIPE, text=True)
    try:
        neto_pid = int(raiz.stdout.readline().strip())
        known = mod._lo_tree_procs({raiz.pid}, {})
        confere(raiz.pid in known and neto_pid in known, "_lo_tree_procs acompanha a raiz e o neto (arvore recursiva por ppid)")
        mod.psutil.Process(raiz.pid).kill()
        raiz.wait(timeout=10)
        known = mod._lo_tree_procs({raiz.pid}, known)
        confere(raiz.pid not in known and neto_pid in known, "_lo_tree_procs remove a raiz morta e segue acompanhando o neto ja visto")
        mod.psutil.Process(neto_pid).kill()
        mod.psutil.wait_procs([mod.psutil.Process(neto_pid)], timeout=10) if mod.psutil.pid_exists(neto_pid) else None
        known = mod._lo_tree_procs({raiz.pid}, known)
        confere(neto_pid not in known, "_lo_tree_procs remove processos que terminaram")
    finally:
        for pid in (raiz.pid,):
            try:
                mod.psutil.Process(pid).kill()
            except Exception:
                pass
        try:
            mod.psutil.Process(neto_pid).kill()
        except Exception:
            pass
    fonte = SCRIPT_PATH.read_text(encoding="utf-8")
    corpo_e1 = fonte[fonte.index("def measure_formula_calculation("):fonte.index("def _find_visible_window_for_pids(")]
    corpo_al = fonte[fonte.index("def measure_app_launch("):fonte.index("def _wait_lo_idle(")]
    confere("process_iter" not in corpo_e1 and "process_iter" not in corpo_al, "Etapas 1-3 nao varrem o cmdline de todos os processos (process_iter) nos lacos cronometrados")
else:
    print("  (psutil ausente: testes de arvore de processos pulados)")

print()
if falhas:
    print(f"  {falhas} verificacao(oes) falharam.")
    sys.exit(1)
print("  Todas as verificacoes passaram.")
