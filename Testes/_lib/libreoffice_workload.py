"""
Carga de escritorio no LibreOffice (Writer + Calc R2) compartilhada entre testes.

Extraida das rotinas validadas no Modulo 1 (1_automacao_performance.py, que segue
intocado) para o Modulo 5 (bateria v2.0, spec 005). Importavel em qualquer SO:
psutil, pyautogui, pyperclip e ctypes.windll sao opcionais e so usados quando
presentes (Windows). Os lacos de espera aceitam `check_stop_fn` e `sleep_fn`
injetaveis, para o chamador interromper em <= 0,5 s e para testes headless.

Nao aparece no menu do hub: Get-Scripts ignora a pasta _lib.
"""

import logging
import os
import random
import shutil
import subprocess
import time
import zipfile
from xml.sax.saxutils import escape as xml_escape

try:
    import psutil
except Exception:  # pragma: no cover - depende do ambiente
    psutil = None

try:
    import pyautogui
except Exception:  # pragma: no cover - depende do ambiente
    pyautogui = None

try:
    import pyperclip
except Exception:  # pragma: no cover - depende do ambiente
    pyperclip = None

_logger = logging.getLogger("libreoffice_workload")

# =============================================================================
# CONSTANTES
# =============================================================================
LO_PROFILE_PREFIX = "wintesthub_lo_profile"
LO_COMMON_FLAGS = ["--norestore", "--nologo", "--nodefault", "--nolockcheck"]
DEFAULT_LO_PATHS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)
APP_LAUNCH_TIMEOUT = 60
CALC_LAUNCH_TIMEOUT = 180       # (s) o Calc recalcula a R2 inteira ao abrir
LO_IDLE_TIMEOUT = 60            # (s) teto da espera de ociosidade apos recalculo
LO_IDLE_CPU_PCT = 5.0           # (% de 1 nucleo) abaixo disso o soffice.bin esta ocioso
LO_IDLE_SAMPLES = 2             # leituras consecutivas abaixo do limite
LO_IDLE_INTERVAL = 0.5          # (s) intervalo entre leituras

# Planilha R2 (mesma carga do Modulo 1 e do teste do macOS)
R2_ROWS = 5000
R2_FORMULA_COLS = 20
R2_CATEGORIES = ("alpha", "beta", "gamma", "delta", "epsilon")
R2_XLSX_NAME = "workload_calc_r2.xlsx"
R2_ZIP_DATE = (1980, 1, 1, 0, 0, 0)
ODT_NAME = "workload_doc.odt"
ODT_TITLE_PADRAO = "Documento de Benchmark — WinTestHub"

TYPING_SAMPLES = [
    "O projeto continua avancando de acordo com as expectativas iniciais.",
    "A equipe mantem o monitoramento constante dos indicadores de qualidade.",
    "Os resultados parciais demonstram a eficacia da estrategia adotada.",
    "O alinhamento continuo entre as areas tem garantido o progresso fluido.",
    "As etapas de validacao estao ocorrendo sem impedimentos criticos.",
    "Todos os requisitos documentados permanecem sob analise rigorosa.",
    "A comunicacao transparente tem sido fundamental para evitar gargalos.",
    "O foco principal segue direcionado para a entrega de valor ao cliente.",
]

SHEET_DATA_POOL = [
    ["Vendas", "45230.00", "31400.00", "0.1500", "1.0"],
    ["Marketing", "12800.00", "14200.00", "0.1200", "2.0"],
    ["TI", "8500.00", "22750.00", "0.1800", "3.0"],
    ["RH", "3200.00", "9800.00", "0.0900", "4.0"],
    ["Operacoes", "67100.00", "52300.00", "0.2100", "5.0"],
    ["Financeiro", "5400.00", "7650.00", "0.1100", "6.0"],
    ["Logistica", "28900.00", "24100.00", "0.1400", "7.0"],
    ["Juridico", "1800.00", "6300.00", "0.0800", "8.0"],
    ["Suporte", "9750.00", "11200.00", "0.1000", "9.0"],
    ["Engenharia", "15600.00", "19400.00", "0.1700", "10.0"],
]
TRIGGER_MAX_ROW = 25            # linhas ciclicas 1..25 da aba Trigger


def _log(log, level, msg):
    (log or _logger).log(level, msg)


def _no_stop():
    return None


# =============================================================================
# 1. DESCOBERTA E PERFIL
# =============================================================================
def find_libreoffice_executable(env=None, which_fn=shutil.which, exists_fn=os.path.exists):
    """
    Localiza soffice.exe nesta ordem: HUB_LIBREOFFICE_PATH, PATH
    (soffice.exe / soffice) e caminhos padrao do Windows. None se ausente.
    """
    environ = os.environ if env is None else env
    env_path = (environ.get("HUB_LIBREOFFICE_PATH", "") or "").strip()
    if env_path and exists_fn(env_path):
        return env_path
    for cmd in ("soffice.exe", "soffice"):
        found = which_fn(cmd)
        if found and exists_fn(found):
            return found
    for candidate in DEFAULT_LO_PATHS:
        if exists_fn(candidate):
            return candidate
    return None


def build_user_installation_uri(profile_dir):
    """Caminho local do perfil -> URI file:/// com barras normais."""
    norm = os.path.abspath(profile_dir).replace("\\", "/").lstrip("/")
    return f"file:///{norm}"


_LO_REGISTRY_SEED = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    '<item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
    '<item oor:path="/org.openoffice.Office.Common/Save/Document">'
    '<prop oor:name="WarnAlienFormat" oor:op="fuse"><value>false</value></prop></item>\n'
    '</oor:items>\n'
)


def seed_lo_profile(profile_dir):
    """
    Cria <profile_dir>/user/registrymodifications.xcu: recalcula sempre ao abrir
    .xlsx (OOXMLRecalcMode=0) e salva sem aviso de formato (WarnAlienFormat=false).
    """
    user_dir = os.path.join(profile_dir, "user")
    os.makedirs(user_dir, exist_ok=True)
    xcu_path = os.path.join(user_dir, "registrymodifications.xcu")
    with open(xcu_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_LO_REGISTRY_SEED)
    return xcu_path


# =============================================================================
# 2. FIXTURES DETERMINISTICAS (ODT + R2 XLSX)
# =============================================================================
def _write_odf_zip(target_path, mimetype_str, content_xml_str):
    """Pacote ODF 1.2: mimetype (STORED) primeiro, manifest e content.xml."""
    manifest_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.2">\n'
        f'  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" '
        f'manifest:media-type="{mimetype_str}"/>\n'
        '  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>\n'
        '</manifest:manifest>\n'
    )
    with zipfile.ZipFile(target_path, "w") as zf:
        zf.writestr(zipfile.ZipInfo("mimetype", date_time=R2_ZIP_DATE),
                    mimetype_str.encode("ascii"), compress_type=zipfile.ZIP_STORED)
        zf.writestr(zipfile.ZipInfo("META-INF/manifest.xml", date_time=R2_ZIP_DATE),
                    manifest_xml.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(zipfile.ZipInfo("content.xml", date_time=R2_ZIP_DATE),
                    content_xml_str.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)


def build_odt_content_xml(title=ODT_TITLE_PADRAO, paragraphs=20):
    """content.xml do documento base: titulo + `paragraphs` paragrafos."""
    body = "\n".join(
        f"      <text:p>Paragrafo {i + 1}: {xml_escape(TYPING_SAMPLES[i % len(TYPING_SAMPLES)])}</text:p>"
        for i in range(paragraphs)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<office:document-content '
        'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
        'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
        'office:version="1.2">\n'
        '  <office:body>\n'
        '    <office:text>\n'
        f'      <text:h text:outline-level="1">{xml_escape(title)}</text:h>\n'
        f'{body}\n'
        '    </office:text>\n'
        '  </office:body>\n'
        '</office:document-content>\n'
    )


def generate_odt_fixture(target_path, title=ODT_TITLE_PADRAO):
    """Grava o .odt base (bytes identicos a cada chamada)."""
    _write_odf_zip(target_path, "application/vnd.oasis.opendocument.text", build_odt_content_xml(title))
    return target_path


def _r2_formula(col_index, row):
    """Formula Calc!<col><row> da R2 (sem '='); MAXIFS/XLOOKUP com prefixo _xlfn."""
    R = row
    last = R2_ROWS + 1
    win_lo = max(2, R - 50)
    win_hi = min(last, R + 50)
    formulas = (
        f"SUMIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f'COUNTIFS(Data!C$2:C${last}, Data!C{R}, Data!B$2:B${last}, ">"&Data!B{R}/2)',
        f"AVERAGEIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f"_xlfn.MAXIFS(Data!B$2:B${last}, Data!C$2:C${last}, Data!C{R})",
        f"INDEX(Data!B$2:B${last}, MATCH(Data!A{R}, Data!A$2:A${last}, 0))",
        f"VLOOKUP(MOD(Data!A{R}, 100), Data!A$2:B${last}, 2, FALSE)",
        f"_xlfn.XLOOKUP(Data!C{R}, Data!C$2:C${last}, Data!B$2:B${last})",
        f'INDIRECT("Data!B" & (1 + MOD(Data!A{R} * 7, {R2_ROWS})))',
        f"STDEV(Data!B{win_lo}:B{win_hi})",
        f"VAR(Data!B{win_lo}:B{win_hi})",
        f"PERCENTILE(Data!B{win_lo}:B{win_hi}, 0.95)",
        f"RANK(Data!B{R}, Data!B{win_lo}:B{win_hi}, 0)",
        f"NPV(0.05, Data!B{max(2, R - 10)}:B{min(last, R + 10)})",
        f"PMT(Data!B{R}/12000, 360, -100000)",
        f"FV(Data!B{R}/12000, 360, -500, -10000)",
        f"IPMT(0.05/12, MOD(Data!A{R}, 360) + 1, 360, -100000)",
        f'IF(Data!B{R} > 500, "high", IF(Data!B{R} > 100, "mid", "low"))',
        f'Data!C{R} & "-" & TEXT(Data!B{R}, "0.00")',
        f"LEN(Data!C{R}) * Data!B{R}",
        f"IFERROR(SQRT(Data!B{R} - 250), 0)",
    )
    return formulas[col_index]


def _col_letter(index):
    """0 -> A, 19 -> T, 26 -> AA."""
    letters = ""
    n = index + 1
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xlsx_cell_str(ref, text):
    return f'<c r="{ref}" t="inlineStr"><is><t>{xml_escape(text)}</t></is></c>'


def _xlsx_cell_num(ref, value):
    return f'<c r="{ref}"><v>{value!r}</v></c>'


def _xlsx_cell_formula(ref, formula):
    # Sem <v>: nenhum valor em cache, o LibreOffice tem de calcular tudo
    return f'<c r="{ref}"><f>{xml_escape(formula)}</f></c>'


def _xlsx_sheet_xml(rows_xml, selected=False):
    view = '<sheetViews><sheetView tabSelected="1" workbookViewId="0"/></sheetViews>' if selected else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"{view}<sheetData>{''.join(rows_xml)}</sheetData></worksheet>"
    )


def _r2_sheets():
    """[(nome, xml)] das 4 abas da R2: Data, Calc, Trigger (ativa), Sentinel."""
    last = R2_ROWS + 1
    data_rows = ['<row r="1">' + "".join(
        _xlsx_cell_str(f"{c}1", t) for c, t in zip("ABCD", ("seq", "value", "category", "date"))
    ) + "</row>"]
    for seq in range(1, R2_ROWS + 1):
        r = seq + 1
        data_rows.append(
            f'<row r="{r}">'
            + _xlsx_cell_num(f"A{r}", seq)
            + _xlsx_cell_num(f"B{r}", (seq * 1.000173) % 1000.0)
            + _xlsx_cell_str(f"C{r}", R2_CATEGORIES[seq % len(R2_CATEGORIES)])
            + _xlsx_cell_formula(f"D{r}", f"DATE(2020, 1, 1) + MOD({seq}, 1825)")
            + "</row>"
        )
    cols = [_col_letter(c) for c in range(R2_FORMULA_COLS)]
    calc_rows = ['<row r="1">' + "".join(
        _xlsx_cell_str(f"{cols[c]}1", f"f{c + 1}") for c in range(R2_FORMULA_COLS)
    ) + "</row>"]
    for r in range(2, last + 1):
        calc_rows.append(
            f'<row r="{r}">'
            + "".join(_xlsx_cell_formula(f"{cols[c]}{r}", _r2_formula(c, r)) for c in range(R2_FORMULA_COLS))
            + "</row>"
        )
    trigger_rows = [
        '<row r="1">' + _xlsx_cell_str("A1", "seed") + "</row>",
        '<row r="2">' + _xlsx_cell_num("A2", 0) + "</row>",
    ]
    sentinel_rows = [
        '<row r="1">' + _xlsx_cell_str("A1", "total") + "</row>",
        '<row r="2">' + _xlsx_cell_formula(
            "A2", f"Calc!A2 + Calc!A{last} + Calc!T2 + Calc!T{last} + Trigger!A2*0"
        ) + "</row>",
    ]
    return [
        ("Data", _xlsx_sheet_xml(data_rows)),
        ("Calc", _xlsx_sheet_xml(calc_rows)),
        ("Trigger", _xlsx_sheet_xml(trigger_rows, selected=True)),
        ("Sentinel", _xlsx_sheet_xml(sentinel_rows)),
    ]


def generate_r2_xlsx(target_path):
    """
    Planilha R2 como OOXML minimo: 4 abas, 5.000 linhas e 100.000 formulas sem
    valor em cache, aba Trigger ativa. Bytes identicos a cada chamada.
    """
    sheets = _r2_sheets()
    ns_rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="{ns_rel}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="{ns_rel}">'
        '<bookViews><workbookView activeTab="2"/></bookViews><sheets>'
        + "".join(
            f'<sheet name="{name}" sheetId="{i}" r:id="rId{i}"/>'
            for i, (name, _) in enumerate(sheets, start=1)
        )
        + "</sheets></workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i}" Type="{ns_rel}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Relationships>"
    )
    parts = [
        ("[Content_Types].xml", content_types),
        ("_rels/.rels", root_rels),
        ("xl/workbook.xml", workbook),
        ("xl/_rels/workbook.xml.rels", workbook_rels),
    ] + [(f"xl/worksheets/sheet{i}.xml", xml) for i, (_, xml) in enumerate(sheets, start=1)]
    with zipfile.ZipFile(target_path, "w") as zf:
        for name, xml in parts:
            info = zipfile.ZipInfo(name, date_time=R2_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, xml.encode("utf-8"))
    return target_path


def generate_odf_fixtures(work_dir, title=ODT_TITLE_PADRAO):
    """Gera workload_doc.odt e workload_calc_r2.xlsx em work_dir -> (odt, xlsx)."""
    os.makedirs(work_dir, exist_ok=True)
    odt_path = os.path.join(work_dir, ODT_NAME)
    xlsx_path = os.path.join(work_dir, R2_XLSX_NAME)
    generate_odt_fixture(odt_path, title=title)
    generate_r2_xlsx(xlsx_path)
    return odt_path, xlsx_path


# =============================================================================
# 3. PROCESSOS DO LIBREOFFICE DO TESTE
# =============================================================================
def is_test_libreoffice_proc(name, cmdline_list, profile_marker=LO_PROFILE_PREFIX):
    """soffice.exe/.bin cujo cmdline contem o marcador do perfil do teste."""
    if not name:
        return False
    if name.lower() not in ("soffice.exe", "soffice.bin", "soffice"):
        return False
    cmd_str = " ".join(cmdline_list or []).lower()
    return profile_marker.lower() in cmd_str


def lo_tree_procs(roots, known):
    """
    Atualiza e devolve `known` ({pid: psutil.Process}) com as raizes vivas e
    seus descendentes; remove os que ja terminaram.
    """
    if psutil is None:
        return known
    for r in list(roots):
        try:
            rp = known.get(r)
            if rp is None:
                rp = psutil.Process(r)
                known[r] = rp
            for child in rp.children(recursive=True):
                known.setdefault(child.pid, child)
        except psutil.Error:
            continue
    for pid, pr in list(known.items()):
        try:
            if not pr.is_running():
                known.pop(pid, None)
        except psutil.Error:
            known.pop(pid, None)
    return known


def kill_test_libreoffice(roots=None, profile_marker=LO_PROFILE_PREFIX, log=None):
    """
    Encerra apenas soffice do teste (arvore de `roots` + cmdline com o marcador),
    preservando instancias do usuario. Retorna quantos processos foram alvo.
    """
    if psutil is None:
        return 0
    by_pid = dict(lo_tree_procs(set(roots or ()), {}))
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            info = proc.info
            if is_test_libreoffice_proc(info.get("name"), info.get("cmdline"), profile_marker):
                by_pid.setdefault(proc.pid, proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    targets = list(by_pid.values())
    if not targets:
        return 0
    _log(log, logging.INFO, f"Encerrando {len(targets)} processo(s) do LibreOffice do teste.")
    for proc in targets:
        try:
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(targets, timeout=3.0)
    for proc in alive:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return len(targets)


# =============================================================================
# 4. JANELAS WIN32
# =============================================================================
def get_user32():
    """ctypes.windll.user32 no Windows; None nas demais plataformas."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        return ctypes.windll.user32
    except Exception:
        return None


def find_visible_window_for_pids(target_pids):
    """HWND da 1a janela visivel com titulo pertencente a um dos PIDs (Windows)."""
    if not target_pids or os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in target_pids and user32.GetWindowTextLengthW(hwnd) > 0:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        return found[0] if found else None
    except Exception as e:
        _logger.debug(f"Erro ao enumerar janelas Win32: {e}")
        return None


def launch_app(soffice_path, mode, file_path, profile_uri, roots, timeout=APP_LAUNCH_TIMEOUT,
               check_stop_fn=None, sleep_fn=time.sleep, log=None,
               popen_fn=subprocess.Popen, find_window_fn=None):
    """
    Abre soffice (--writer/--calc) com subperfil isolado e cronometra ate haver
    janela visivel estavel por 0,5 s. Adiciona o PID raiz a `roots`.
    Retorna (elapsed_s, pid, hwnd). Estourar `timeout` levanta TimeoutError.
    """
    check_stop = check_stop_fn or _no_stop
    find_window = find_window_fn or find_visible_window_for_pids
    cmd = [soffice_path, f"-env:UserInstallation={profile_uri}", mode, *LO_COMMON_FLAGS, file_path]
    marker = profile_uri.rstrip("/").split("/")[-1]
    _log(log, logging.INFO, f"Iniciando LibreOffice ({mode}) com perfil {marker}...")
    t0 = time.perf_counter()
    proc = popen_fn(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    roots.add(proc.pid)
    known = {}
    headless = (os.name != "nt") and (find_window_fn is None)
    while True:
        check_stop()
        if (time.perf_counter() - t0) > timeout:
            kill_test_libreoffice(roots, log=log)
            raise TimeoutError(f"Timeout de {timeout}s ao aguardar abertura do LibreOffice ({mode}).")
        pids = {proc.pid} | set(lo_tree_procs({proc.pid}, known))
        hwnd = 1 if headless else find_window(pids)
        if hwnd is not None:
            sleep_fn(0.5)
            pids_after = {proc.pid} | set(lo_tree_procs({proc.pid}, known))
            hwnd_after = 1 if headless else find_window(pids_after)
            if hwnd_after is not None:
                elapsed = time.perf_counter() - t0
                chosen = sorted(pids_after)[-1]
                _log(log, logging.INFO,
                     f"LibreOffice ({mode}) aberto em {elapsed:.2f}s (PID={chosen}, HWND={hwnd_after}).")
                return elapsed, chosen, hwnd_after
        sleep_fn(0.1)


def wait_lo_idle(hwnd, timeout=LO_IDLE_TIMEOUT, idle_cpu_pct=LO_IDLE_CPU_PCT,
                 idle_samples=LO_IDLE_SAMPLES, idle_interval=LO_IDLE_INTERVAL,
                 check_stop_fn=None, sleep_fn=time.sleep, user32=None, log=None):
    """
    Espera o soffice.bin dono de `hwnd` ficar ocioso (CPU < idle_cpu_pct por
    idle_samples leituras). Retorna segundos esperados; sem user32/psutil
    (CI) retorna 0. Estourar `timeout` levanta RuntimeError.
    """
    check_stop = check_stop_fn or _no_stop
    u32 = get_user32() if user32 is None else user32
    if u32 is None or psutil is None or not hasattr(u32, "GetWindowThreadProcessId") or not hwnd:
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return 0.0
        proc = psutil.Process(int(pid.value))
        proc.cpu_percent(interval=None)
    except Exception as e:
        _log(log, logging.DEBUG, f"Espera de ociosidade ignorada (HWND={hwnd}): {e}")
        return 0.0
    t0 = time.perf_counter()
    quietas = 0
    while True:
        check_stop()
        sleep_fn(idle_interval)
        try:
            cpu = float(proc.cpu_percent(interval=None))
        except Exception:
            return time.perf_counter() - t0
        quietas = quietas + 1 if cpu < idle_cpu_pct else 0
        elapsed = time.perf_counter() - t0
        if quietas >= idle_samples:
            return elapsed
        if elapsed > timeout:
            raise RuntimeError(
                f"LibreOffice nao ficou ocioso em {timeout}s (CPU={cpu:.0f}% de 1 nucleo, HWND={hwnd})."
            )


def is_window_alive(hwnd, user32=None):
    """True se a janela ainda existe. Fora do Windows, qualquer hwnd conta como viva."""
    if not hwnd:
        return False
    u32 = get_user32() if user32 is None else user32
    if u32 is None or not hasattr(u32, "IsWindow"):
        return True
    try:
        return bool(u32.IsWindow(hwnd))
    except Exception:
        return False


def verify_window_focused(hwnd, user32=None):
    """Confirma que `hwnd` existe, esta visivel e em primeiro plano; senao RuntimeError."""
    if not hwnd:
        raise RuntimeError("Janela do LibreOffice invalida (HWND ausente).")
    u32 = get_user32() if user32 is None else user32
    if u32 is None:
        return True
    if hasattr(u32, "IsWindow") and not u32.IsWindow(hwnd):
        raise RuntimeError(f"Janela do LibreOffice (HWND={hwnd}) nao existe mais.")
    if hasattr(u32, "IsWindowVisible") and not u32.IsWindowVisible(hwnd):
        raise RuntimeError(f"Janela do LibreOffice (HWND={hwnd}) nao esta visivel.")
    fg = u32.GetForegroundWindow()
    if fg != hwnd:
        raise RuntimeError(f"Foco GUI nao confirmado (esperado HWND={hwnd}, atual={fg}).")
    return True


def focus_window(hwnd, sleep_fn=time.sleep, log=None, user32=None):
    """
    Traz `hwnd` ao primeiro plano (SetForegroundWindow, fallback Alt+Tab) e
    confirma o foco; levanta RuntimeError se nao conseguir.
    """
    if not hwnd:
        raise RuntimeError("Janela do LibreOffice invalida (HWND ausente).")
    u32 = get_user32() if user32 is None else user32
    if u32 is None:
        if pyautogui is not None and os.name == "nt":
            pyautogui.hotkey("alt", "tab")
            sleep_fn(0.5)
        return
    try:
        if hasattr(u32, "IsIconic") and u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        u32.SetForegroundWindow(hwnd)
        sleep_fn(0.3)
    except Exception as e:
        _log(log, logging.DEBUG, f"SetForegroundWindow falhou ({e}); tentando Alt+Tab.")
    if u32.GetForegroundWindow() != hwnd:
        if pyautogui is not None:
            pyautogui.hotkey("alt", "tab")
            sleep_fn(0.4)
        try:
            u32.SetForegroundWindow(hwnd)
            sleep_fn(0.2)
        except Exception:
            pass
    verify_window_focused(hwnd, user32=u32)


# =============================================================================
# 5. ENTRADA SIMULADA (pyautogui + clipboard)
# =============================================================================
def type_text_safely(text, sleep_fn=time.sleep):
    """Cola o texto via clipboard (suporta acentos)."""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    sleep_fn(0.3)


def click_safe_content_area(rng=random):
    """Clica num ponto aleatorio da zona segura de conteudo da janela maximizada."""
    w, h = pyautogui.size()
    x = rng.randint(int(w * 0.12), int(w * 0.80))
    y = rng.randint(int(h * 0.22), int(h * 0.85))
    pyautogui.click(x, y)
    return x, y


def ensure_grid_focus(sleep_fn=time.sleep):
    """Esc + clique no centro da grade do Calc."""
    pyautogui.press("escape")
    sleep_fn(0.3)
    w, h = pyautogui.size()
    pyautogui.click(w // 2, int(h * 0.55))
    sleep_fn(0.5)


def navigate_to_row(target_row, sleep_fn=time.sleep):
    """Vai para a coluna A da linha `target_row` (1..25) a partir de A1."""
    pyautogui.hotkey("ctrl", "home")
    sleep_fn(0.3)
    for _ in range(min(max(1, target_row), TRIGGER_MAX_ROW)):
        pyautogui.press("down")
        sleep_fn(0.05)
    sleep_fn(0.2)


def write_row(values, sleep_fn=time.sleep):
    """Preenche as colunas de uma linha e volta para o inicio da proxima."""
    for idx, val in enumerate(values):
        type_text_safely(val, sleep_fn=sleep_fn)
        if idx < len(values) - 1:
            pyautogui.press("tab")
            sleep_fn(0.15)
        else:
            pyautogui.press("enter")
            sleep_fn(0.2)
            pyautogui.press("home")
            sleep_fn(0.2)
