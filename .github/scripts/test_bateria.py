"""Teste de regressao: Modulo 5 — Bateria v2.0 (spec 005).

Valida, sem hardware de bateria e sem enviar teclas (pyautogui/pyperclip
substituidos por fakes), em Linux (CI) e Windows:
1. Testes/_lib/libreoffice_workload.py: descoberta do soffice, URI de perfil,
   semente do perfil, ODT + R2 XLSX deterministicos e integros, filtro de
   processos do teste, launch_app/wait_lo_idle/is_window_alive headless.
2. Testes/5_bateria/5_teste_bateria.py: constantes v2.0 e ausencia de Edge/Google.
3. calcular_metricas_fase e calcular_metricas_globais (tempo real, normalizacao
   100%->0%, fallback por %, 1a hora).
4. decidir_exit_code (PASS com fase ativa < 30 min ate 10%; FAILs).
5. linhas_bateria_csv (schema v2.0) e concluir_resultado gravando bateria.csv.
6. Checkpoint atomico e detector de hibernacao.
7. Fase ativa: anti-bloat do Writer, recalculo da R2, WPR so na 1a hora,
   recuperacao de erro pontual.
8. Ordem do encerramento: bateria.csv + restaurar_tudo() antes da janela de
   reconexao e da pos-medicao pesada.

Rodar: python -I -X utf8 .github/scripts/test_bateria.py
"""
import csv
import hashlib
import importlib.util
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
LIB_DIR = ROOT_DIR / "Testes" / "_lib"
SCRIPT_PATH = ROOT_DIR / "Testes" / "5_bateria" / "5_teste_bateria.py"

EVID_DIR = tempfile.mkdtemp(prefix="test_bateria_")
os.environ["HUB_EVIDENCE_DIR"] = EVID_DIR      # log e evidencias do import vao para o temporario
os.environ.pop("HUB_MONITOR_PID", None)

sys.path.insert(0, str(LIB_DIR))
import libreoffice_workload as lw  # noqa: E402

spec = importlib.util.spec_from_file_location("teste_bateria", SCRIPT_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
lo = mod.lo   # a mesma instancia usada pelo script

falhas = 0


def confere(cond, descricao):
    global falhas
    falhas += not cond
    print(f"  {'OK    ' if cond else 'FALHOU'}  {descricao}")


def perto(a, b, tol=0.01):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def sha(caminho):
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


# --- Fakes de GUI (nenhuma tecla real e enviada) ------------------------------
class FakeGui:
    class FailSafeException(Exception):
        pass

    def __init__(self):
        self.eventos = []

    def hotkey(self, *teclas):
        self.eventos.append(("hotkey",) + teclas)

    def press(self, tecla):
        self.eventos.append(("press", tecla))

    def click(self, x, y):
        self.eventos.append(("click", x, y))

    def scroll(self, n):
        self.eventos.append(("scroll", n))

    def size(self):
        return 1920, 1080

    def conta(self, *evento):
        return sum(1 for e in self.eventos if e == evento)


class FakeClip:
    def __init__(self):
        self.textos = []

    def copy(self, texto):
        self.textos.append(texto)


gui, clip = FakeGui(), FakeClip()
mod.pyautogui = gui
lo.pyautogui = gui
lo.pyperclip = clip


class FakeUi:
    def __init__(self):
        self.textos = []

    def atualizar(self, *args):
        self.textos.append(args)

    def mostrar(self):
        pass

    def ocultar(self):
        pass


# =============================================================================
print("1. Testes/_lib/libreoffice_workload.py")
# =============================================================================
env_path = r"D:\LO\program\soffice.exe"
confere(lw.find_libreoffice_executable(env={"HUB_LIBREOFFICE_PATH": env_path}, which_fn=lambda _: None,
                                       exists_fn=lambda p: p == env_path) == env_path,
        "descoberta: HUB_LIBREOFFICE_PATH tem prioridade")
confere(lw.find_libreoffice_executable(env={"HUB_LIBREOFFICE_PATH": r"C:\nao\existe.exe"},
                                       which_fn=lambda c: r"C:\T\soffice.exe" if c == "soffice.exe" else None,
                                       exists_fn=lambda p: p == r"C:\T\soffice.exe") == r"C:\T\soffice.exe",
        "descoberta: PATH quando HUB_LIBREOFFICE_PATH nao existe")
confere(lw.find_libreoffice_executable(env={}, which_fn=lambda _: None,
                                       exists_fn=lambda p: p == lw.DEFAULT_LO_PATHS[1]) == lw.DEFAULT_LO_PATHS[1],
        "descoberta: caminho padrao (x86)")
confere(lw.find_libreoffice_executable(env={}, which_fn=lambda _: None, exists_fn=lambda _: False) is None,
        "descoberta: None quando ausente")

with tempfile.TemporaryDirectory() as tmp:
    perfil = os.path.join(tmp, f"{lw.LO_PROFILE_PREFIX}_calc")
    uri = lw.build_user_installation_uri(perfil)
    confere(uri.startswith("file:///") and "\\" not in uri and uri.endswith(f"{lw.LO_PROFILE_PREFIX}_calc"),
            f"URI do perfil com barras normais ({uri[:40]}...)")
    xcu = Path(lw.seed_lo_profile(perfil)).read_text(encoding="utf-8")
    confere('oor:name="OOXMLRecalcMode"' in xcu and "<value>0</value>" in xcu
            and 'oor:name="WarnAlienFormat"' in xcu and "<value>false</value>" in xcu,
            "seed_lo_profile: OOXMLRecalcMode=0 e WarnAlienFormat=false")

    odt1, xlsx1 = lw.generate_odf_fixtures(os.path.join(tmp, "a"))
    odt2, xlsx2 = lw.generate_odf_fixtures(os.path.join(tmp, "b"))
    confere(os.path.basename(odt1) == "workload_doc.odt" and os.path.basename(xlsx1) == "workload_calc_r2.xlsx",
            "generate_odf_fixtures: nomes workload_doc.odt e workload_calc_r2.xlsx")
    confere(sha(odt1) == sha(odt2) and sha(xlsx1) == sha(xlsx2), "fixtures deterministicas (bytes identicos)")
    with zipfile.ZipFile(odt1) as zf:
        primeiro = zf.infolist()[0]
        conteudo = zf.read("content.xml").decode("utf-8")
        confere(primeiro.filename == "mimetype" and primeiro.compress_type == zipfile.ZIP_STORED
                and zf.read("mimetype") == b"application/vnd.oasis.opendocument.text",
                "ODT: mimetype primeiro e sem compressao")
        confere(conteudo.count("<text:p>") == 20 and "WinTestHub" in conteudo, "ODT: titulo + 20 paragrafos")
    with zipfile.ZipFile(xlsx1) as zf:
        nomes = zf.namelist()
        wb = zf.read("xl/workbook.xml").decode("utf-8")
        calc = zf.read("xl/worksheets/sheet2.xml").decode("utf-8")
        trig = zf.read("xl/worksheets/sheet3.xml").decode("utf-8")
    abas = re.findall(r'<sheet name="([^"]+)"', wb)
    confere(abas == ["Data", "Calc", "Trigger", "Sentinel"], f"R2: abas {abas}")
    confere(calc.count("<f>") == lw.R2_ROWS * lw.R2_FORMULA_COLS == 100000 and "<v>" not in calc,
            "R2: 100.000 formulas sem valor em cache")
    confere('tabSelected="1"' in trig and 'activeTab="2"' in wb, "R2: aba Trigger ativa")
    confere("xl/worksheets/sheet4.xml" in nomes, "R2: pacote OOXML completo")

confere(lw.is_test_libreoffice_proc("soffice.bin", ["soffice.bin", "-env:UserInstallation=file:///C:/T/wintesthub_lo_profile_writer"]),
        "filtro: soffice.bin com marcador = do teste")
confere(not lw.is_test_libreoffice_proc("soffice.bin", ["soffice.bin", "--writer", "C:/doc.odt"]),
        "filtro: soffice do usuario (sem marcador) preservado")
confere(not lw.is_test_libreoffice_proc("python.exe", ["wintesthub_lo_profile"]), "filtro: outro processo ignorado")


class FakeProc:
    pid = os.getpid()


comandos = []
roots = set()
elapsed, pid, hwnd = lw.launch_app(
    "soffice.exe", "--calc", "x.xlsx", "file:///C:/T/wintesthub_lo_profile_calc", roots,
    timeout=5, sleep_fn=lambda _s: None, popen_fn=lambda cmd, **_k: comandos.append(cmd) or FakeProc(),
    find_window_fn=lambda _pids: 4242,
)
confere(hwnd == 4242 and os.getpid() in roots and elapsed >= 0, "launch_app: devolve HWND do find_window_fn e registra o PID raiz")
confere(comandos and comandos[0][1] == "-env:UserInstallation=file:///C:/T/wintesthub_lo_profile_calc"
        and comandos[0][2] == "--calc" and comandos[0][-1] == "x.xlsx" and "--norestore" in comandos[0],
        "launch_app: linha de comando com subperfil isolado e flags comuns")
paradas = []


def para_no_launch():
    paradas.append(1)
    raise KeyboardInterrupt


try:
    lw.launch_app("soffice.exe", "--writer", "d.odt", "file:///C:/T/wintesthub_lo_profile_writer", set(),
                  check_stop_fn=para_no_launch, sleep_fn=lambda _s: None,
                  popen_fn=lambda cmd, **_k: FakeProc(), find_window_fn=lambda _p: None)
    confere(False, "launch_app: check_stop_fn interrompe")
except KeyboardInterrupt:
    confere(paradas == [1], "launch_app: check_stop_fn interrompe a espera")
confere(lw.wait_lo_idle(123, user32=object()) == 0.0, "wait_lo_idle: sem user32 utilizavel retorna 0 sem esperar")
confere(not lw.is_window_alive(None) and not lw.is_window_alive(0), "is_window_alive: HWND ausente = fechada")


class FakeUser32:
    def __init__(self, vivo):
        self.vivo = vivo

    def IsWindow(self, _h):
        return self.vivo


confere(lw.is_window_alive(7, user32=FakeUser32(True)) and not lw.is_window_alive(7, user32=FakeUser32(False)),
        "is_window_alive: consulta IsWindow")

# =============================================================================
print("2. Modulo 5 v2.0: constantes e ausencia de Edge/Google")
# =============================================================================
confere(mod.VERSAO_TESTE == "2.0", "VERSAO_TESTE = 2.0")
confere(mod.PROTECAO_BATERIA_PCT == 10, "PROTECAO_BATERIA_PCT = 10")
confere(mod.DURACAO_OCIOSA_S == 3600 and mod.DURACAO_WPR_ESCRITORIO_S == 3600, "ociosa 60 min e WPR ativo 60 min")
confere(mod.CARGA_INICIAL_MIN_PCT == 95 and mod.ESTABILIZACAO_S == 300, "carga minima 95% e estabilizacao 5 min")
confere(mod.MODO_ENERGIA_ALVO == "00000000-0000-0000-0000-000000000000" == mod.MODO_EQUILIBRADO,
        "MODO_ENERGIA_ALVO = Equilibrado")
confere(mod.INTERVALO_RECALC_CALC_S == 300 and mod.WRITER_MAX_PARAGRAFOS == 60, "recalculo 5 min e anti-bloat 60")
confere(mod.MOTIVOS_PASS == ("protecao_bateria",), "MOTIVOS_PASS = ('protecao_bateria',)")
fonte = SCRIPT_PATH.read_text(encoding="utf-8")
residuos = [p for p in (r"\bedge\b", r"msedge", r"google", r"docs\.google", r"dell\.com", r"login_exigido",
                        r"DURACAO_ESCRITORIO_S", r"ESCRITORIO_MINIMO_PASS_S", r"PrazoDaFase")
            if re.search(p, fonte, re.I)]
confere(not residuos, f"script sem referencias ao Edge/Google/v1.0 ({residuos or 'nenhuma'})")
confere(not re.search(r"^\s*(import|from)\s+\S*automacao_performance", fonte, re.M)
        and "spec_from_file_location" not in fonte, "script nao importa o Modulo 1 (usa _lib/libreoffice_workload)")

# =============================================================================
print("3. Metricas de fase e globais")
# =============================================================================
H = 3600


def amostra(t, pct, mwh):
    return {"t": t, "carga_pct": pct, "energia_mwh": mwh}


ini_ociosa = amostra(0, 100, 50000)
fim_ociosa = amostra(H, 95, 47500)
fim_ativa = amostra(5 * H, 10, 5000)
m = mod.calcular_metricas_fase(ini_ociosa, fim_ociosa, 50000)
confere(perto(m["duracao_min"], 60) and perto(m["energia_mwh"], 2500) and perto(m["taxa_w"], 2.5)
        and perto(m["queda_pp"], 5) and perto(m["autonomia_h"], 20) and not m["estimada"],
        "fase: energia, taxa, queda e autonomia projetada com mWh real")
g = mod.calcular_metricas_globais(ini_ociosa, fim_ativa, 50000)
confere(perto(g["tempo_total_min"], 300) and perto(g["tempo_total_h"], 5), "global: tempo real 300 min = 5 h")
confere(perto(g["energia_total_mwh"], 45000) and perto(g["taxa_global_w"], 9.0), "global: 45.000 mWh e 9 W")
confere(perto(g["autonomia_equiv_100pct_h"], 5 * 50000 / 45000) and not g["estimada"],
        "global: autonomia equivalente 100%->0% = h x (cheia / energia)")
g_rel = mod.calcular_metricas_globais(amostra(0, 96, 96), amostra(4 * H, 10, 10), 100)
confere(g_rel["estimada"] and perto(g_rel["energia_total_mwh"], 86)
        and perto(g_rel["autonomia_equiv_100pct_h"], 4 * 100 / 86), "global: capacidade relativa (<=100) -> estimada por %")
g_sem = mod.calcular_metricas_globais(amostra(0, 98, None), amostra(3 * H, 10, None), None)
confere(g_sem["energia_total_mwh"] is None and g_sem["taxa_global_w"] is None
        and perto(g_sem["autonomia_equiv_100pct_h"], 3 * 100 / 88), "global: sem mWh nem carga cheia -> fallback via %")
g_est = mod.calcular_metricas_globais(amostra(0, 100, None), amostra(2 * H, 10, None), 40000)
confere(g_est["estimada"] and perto(g_est["energia_total_mwh"], 36000), "global: sem mWh com carga cheia -> estimada")
confere(mod.calcular_metricas_globais(None, fim_ativa, 50000)["tempo_total_min"] is None, "global: sem marco -> N/A")
um_h = mod.calcular_metricas_fase(amostra(H, 95, 47500), amostra(2 * H, 80, 40000), 50000)
confere(perto(um_h["taxa_w"], 7.5), "1a hora da fase ativa: taxa 7,5 W")
confere(mod.calcular_metricas_fase(amostra(H, 95, 47500), None, 50000)["taxa_w"] is None,
        "1a hora incompleta (sem fim_wpr) -> N/A")

# =============================================================================
print("4. decidir_exit_code")
# =============================================================================
base = {"preflight_ok": True, "conferencia_ok": True, "ociosa_completa": True, "escritorio_iniciada": True,
        "escritorio_s": 12 * 60, "motivo": "protecao_bateria", "energia_ok": True,
        "bateria_csv": True, "amostras_csv": True}
confere(mod.decidir_exit_code(base) == 0, "PASS: bateria desgastada, fase ativa de 12 min ate 10%")
for chave, valor, descricao in (
    ("ociosa_completa", False, "10% ainda na fase ociosa"),
    ("escritorio_iniciada", False, "fase ativa nao iniciada"),
    ("escritorio_s", 0, "fase ativa sem duracao"),
    ("motivo", "carregador_reconectado", "carregador reconectado"),
    ("motivo", "parada_segura", "parada segura"),
    ("motivo", "hibernacao_inesperada", "hibernacao inesperada"),
    ("motivo", "padronizacao_na_bateria", "padronizacao na bateria"),
    ("motivo", "concluido", "motivo da v1.0 (concluido)"),
    ("preflight_ok", False, "falha de pre-voo"),
    ("conferencia_ok", False, "falha na conferencia"),
    ("energia_ok", False, "sem energia"),
    ("bateria_csv", False, "bateria.csv nao gravado"),
    ("amostras_csv", False, "bateria_amostras.csv nao gravado"),
):
    confere(mod.decidir_exit_code(dict(base, **{chave: valor})) == 1, f"FAIL: {descricao}")

# =============================================================================
print("5. linhas_bateria_csv e concluir_resultado")
# =============================================================================
esc = mod.calcular_metricas_fase(amostra(H + 300, 94, 47000), fim_ativa, 50000)
linhas = mod.linhas_bateria_csv(
    coleta_valida=True, motivo="protecao_bateria", globais=g, ociosa=m, escritorio=esc,
    escritorio_1h=mod.calcular_metricas_fase(None, None, 50000),
    contadores={"tempo_abertura_writer_s": 2.345, "tempo_abertura_calc_s": 31.0, "paragrafos_writer": 120,
                "linhas_calc": 240, "recalculos_calc": 44},
    estaticos={"carga_cheia_mwh": 50000, "projeto_mwh": 56000, "ciclos": 87}, carga_inicial=100, carga_final=10,
    plano="Equilibrado", modo="Equilibrado", brilho=50, bluetooth="desligado", desvios=0)
chaves = [l[0] for l in linhas]
esperadas = [
    "Versao_Teste", "Coleta_Valida", "Motivo_Encerramento", "Protecao_Bateria_Limite",
    "Tempo_Total_Bateria_Real_min", "Tempo_Total_Bateria_Real_h", "Energia_Total_Consumida", "Taxa_Media_Global",
    "Autonomia_Real_Equivalente_100pct",
    "Ociosa_Duracao_Medida", "Ociosa_Energia_Consumida", "Ociosa_Taxa_Media_Descarga", "Ociosa_Queda_Carga",
    "Ociosa_Queda_Carga_Hora", "Ociosa_Autonomia_Projetada",
    "Escritorio_Duracao_Medida", "Escritorio_Duracao_Medida_h", "Escritorio_Energia_Consumida",
    "Escritorio_Taxa_Media_Descarga", "Escritorio_1h_Taxa_Media_Descarga", "Escritorio_Queda_Carga",
    "Escritorio_Queda_Carga_Hora", "Escritorio_Autonomia_Projetada",
    "Tempo_Abertura_Writer", "Tempo_Abertura_Calc", "Paragrafos_Digitados_Writer", "Linhas_Editadas_Calc",
    "Recalculos_Calc_R2",
    "Energia_Estimada", "Carga_Bateria_Inicial", "Carga_Bateria_Final", "Capacidade_Carga_Cheia",
    "Capacidade_Projeto", "Ciclos_Carga", "Plano_Energia", "Modo_Energia", "Brilho", "Bluetooth",
    "Desvios_Padronizacao",
]
confere(chaves == esperadas, f"schema v2.0: {len(esperadas)} metricas na ordem da spec")
v = {l[0]: (l[1], l[2]) for l in linhas}
confere(v["Versao_Teste"] == ("2.0", "texto") and v["Protecao_Bateria_Limite"] == ("10", "%"), "Versao 2.0 e limite 10%")
confere(v["Tempo_Total_Bateria_Real_min"] == ("300.00", "min") and v["Tempo_Total_Bateria_Real_h"] == ("5.00", "h"),
        "tempo real com ponto e 2 casas")
confere(v["Autonomia_Real_Equivalente_100pct"] == ("5.56", "h") and v["Taxa_Media_Global"] == ("9.00", "W"),
        "autonomia equivalente 5.56 h e taxa global 9.00 W")
confere(v["Escritorio_1h_Taxa_Media_Descarga"] == ("N/A", "W"), "1a hora incompleta -> N/A")
confere(v["Escritorio_Duracao_Medida_h"][0] == f"{esc['duracao_min'] / 60:.2f}", "Escritorio_Duracao_Medida_h")
confere(v["Tempo_Abertura_Writer"] == ("2.35", "s") and v["Recalculos_Calc_R2"] == ("44", "un"),
        "metricas do LibreOffice")
confere(v["Modo_Energia"] == ("Equilibrado", "texto") and v["Desvios_Padronizacao"] == ("0", "un"), "modo Equilibrado")

# concluir_resultado de ponta a ponta (bateria.csv real em HUB_EVIDENCE_DIR)
mod._preflight[:] = [{"Item": "Plano de energia", "Situacao": "ok", "Depois": "Equilibrado"}]
mod._medicao["conferencia_ok"] = True
mod._medicao["motivo"] = "protecao_bateria"
mod._marcos.clear()
mod._marcos.update({
    "ociosa": {"inicio": ini_ociosa, "fim": fim_ociosa, "completa": True},
    "escritorio": {"inicio": amostra(H + 300, 94, 47000), "fim_wpr": amostra(2 * H + 300, 80, 40000),
                   "fim": fim_ativa, "completa": True},
})
mod._amostra_final["valor"] = fim_ativa
mod._amostras_medidas[:] = [("ociosa", 50, "Equilibrado"), ("escritorio", 50, "Equilibrado")]
Path(EVID_DIR, mod.ARQ_AMOSTRAS).write_text("cab\nlinha\n", encoding="utf-8-sig")
codigo = mod.concluir_resultado(FakeUi(), {"carga_cheia_mwh": 50000, "projeto_mwh": 56000, "ciclos": 87})
with open(os.path.join(EVID_DIR, "bateria.csv"), encoding="utf-8") as f:
    gravado = {r[0]: r[1] for r in csv.reader(f)}
confere(codigo == 0 and gravado.get("Coleta_Valida") == "sim", "concluir_resultado: PASS e bateria.csv gravado")
confere(gravado.get("Escritorio_1h_Taxa_Media_Descarga") == "7.00" and gravado.get("Tempo_Total_Bateria_Real_min") == "300.00",
        "concluir_resultado: taxa da 1a hora e tempo real total")
confere(json.loads(Path(EVID_DIR, mod.ARQ_CHECKPOINT).read_text(encoding="utf-8"))["versao"] == "2.0",
        "concluir_resultado: checkpoint final gravado")
mod._marcos["ociosa"]["completa"] = False
mod._marcos.pop("escritorio")
codigo = mod.concluir_resultado(FakeUi(), {"carga_cheia_mwh": 50000})
with open(os.path.join(EVID_DIR, "bateria.csv"), encoding="utf-8") as f:
    gravado = {r[0]: r[1] for r in csv.reader(f)}
confere(codigo == 1 and gravado.get("Coleta_Valida") == "nao", "10% ainda na ociosa -> FAIL (Coleta_Valida = nao)")
mod._medicao["motivo"] = None

# =============================================================================
print("6. Checkpoint atomico e detector de hibernacao")
# =============================================================================
ck = os.path.join(EVID_DIR, "ck_teste.json")
ok = mod.gravar_checkpoint({"data_hora": "2026-11-27 10:00:00", "fase": "escritorio", "carga_pct": 42, "t": 1.0},
                           caminho=ck)
dados = json.loads(Path(ck).read_text(encoding="utf-8"))
confere(ok and not os.path.exists(ck + ".tmp"), "checkpoint gravado sem sobra de .tmp")
confere(dados["versao"] == "2.0" and dados["ultima_amostra"]["carga_pct"] == 42
        and {"marcos", "contadores_lo", "desvios", "motivo", "fase"} <= set(dados), "checkpoint com o estado esperado")
Path(ck).write_text("lixo", encoding="utf-8")
mod.gravar_checkpoint({"carga_pct": 41}, caminho=ck)
confere(json.loads(Path(ck).read_text(encoding="utf-8"))["ultima_amostra"]["carga_pct"] == 41,
        "checkpoint substitui o anterior por inteiro")
confere(not mod.gravar_checkpoint({}, caminho=os.path.join(EVID_DIR, "nao", "existe", "ck.json")),
        "checkpoint em pasta inexistente: falha vira aviso (False)")
confere(not mod.detectar_salto_hibernacao(1000, 50, 1005, 55), "tique normal de 5 s -> sem salto")
confere(not mod.detectar_salto_hibernacao(1000, 50, 1060, 110), "tique lento de 60 s (coletor) -> sem salto")
confere(mod.detectar_salto_hibernacao(1000, 50, 1900, 900), "900 s de parede e de monotonico -> hibernacao")
confere(mod.detectar_salto_hibernacao(1000, 50, 1900, 55), "parede salta 900 s com monotonico parado -> hibernacao")

# =============================================================================
print("7. Fase ativa no LibreOffice")
# =============================================================================
mod.pausa = lambda _s: None
lo.focus_window = lambda *_a, **_k: None
lo.verify_window_focused = lambda *_a, **_k: True
lo.wait_lo_idle = lambda *_a, **_k: 0.0
mod._lo_state.update(mod._novo_estado_lo())
mod._lo_state.update({"hwnd_writer": 11, "hwnd_calc": 22})
for _ in range(mod.WRITER_MAX_PARAGRAFOS):
    mod.simular_writer()
confere(mod._lo_state["paragrafos_writer"] == 60 and gui.conta("hotkey", "ctrl", "s") == 60,
        "Writer: 1 paragrafo e Ctrl+S por turno")
antes = len(clip.textos)
mod.simular_writer()
confere(mod._lo_state["paragrafos_desde_reset"] == 1 and any("texto reiniciado" in t for t in clip.textos[antes:]),
        "Writer: anti-bloat reinicia o texto apos 60 paragrafos")
gui.eventos.clear()
for _ in range(13):
    mod.simular_calc(False)
confere(mod._lo_state["linhas_calc"] == 26 and mod._lo_state["proxima_linha"] == 2,
        "Calc: 2 linhas por turno, linha ciclica 1-25 da Trigger")
confere(gui.conta("hotkey", "ctrl", "shift", "f9") == 0, "Calc: sem recalculo completo fora do intervalo")
mod.simular_calc(True)
confere(mod._lo_state["recalculos_calc"] == 1 and gui.conta("hotkey", "ctrl", "shift", "f9") == 1,
        "Calc: Ctrl+Shift+F9 no intervalo de recalculo")

# Laco da fase ativa: WPR so na 1a hora, erro pontual nao derruba, sai pela protecao de bateria
registro = []
reais = {n: getattr(mod, n) for n in ("simular_writer", "simular_calc", "amostra_marco", "parar_wpr_ativo",
                                      "recuperar_app_se_fechou", "emit_progress")}
estado = {"turnos": 0, "erro": False}


def writer_fake():
    estado["turnos"] += 1
    if not estado["erro"]:
        estado["erro"] = True
        raise RuntimeError("foco perdido")
    registro.append("writer")
    if estado["turnos"] >= 6:
        mod.registrar_encerramento("protecao_bateria", "carga em 10%")


mod.simular_writer = writer_fake
mod.simular_calc = lambda forcar: registro.append(("calc", forcar))
mod.amostra_marco = lambda tipo: registro.append(("marco", tipo))
mod.parar_wpr_ativo = lambda fase: registro.append(("wpr_stop", fase))
mod.recuperar_app_se_fechou = lambda app: (_ for _ in ()).throw(TimeoutError("relancamento lento")) if registro.append(("recuperar", app)) is None else None
mod.emit_progress = lambda *_a, **_k: None
mod.DURACAO_WPR_ESCRITORIO_S = 0
mod.INTERVALO_RECALC_CALC_S = 0
mod._wpr["escritorio_1h_salvo"] = False
mod._encerrar.clear()
try:
    mod.executar_fase_escritorio(FakeUi())
    saiu = "normal"
except KeyboardInterrupt:
    saiu = "interrupcao"
confere(saiu == "interrupcao" and mod.motivo_encerramento() == "protecao_bateria",
        "fase ativa sem teto: so sai quando a vigia registra protecao_bateria")
confere(registro.count(("marco", "fim_wpr_escritorio")) == 1 and registro.count(("wpr_stop", "Escritorio")) == 1
        and mod._wpr["escritorio_1h_salvo"], "WPR: amostra-marco e trace salvos uma unica vez na marca de 1 h")
confere(("recuperar", "writer") in registro and registro.count("writer") >= 1,
        "erro pontual (inclusive falha no relancamento): tenta recuperar e continua a descarga")
confere(("calc", True) in registro, "Calc recebe pedido de recalculo no intervalo")

# FailSafeException do pyautogui -> interrompe via KeyboardInterrupt
mod._encerrar.clear()
mod._stop_requested.clear()
mod._medicao["motivo"] = None
mod.simular_writer = lambda: (_ for _ in ()).throw(FakeGui.FailSafeException("canto"))
try:
    mod.executar_fase_escritorio(FakeUi())
    fs_ok = False
except KeyboardInterrupt:
    fs_ok = True
confere(fs_ok, "FailSafeException do pyautogui interrompe a fase ativa com KeyboardInterrupt")

for nome, funcao in reais.items():
    setattr(mod, nome, funcao)

# =============================================================================
print("8. Ordem do encerramento")
# =============================================================================
# encerrar_fase_medida: fecha LibreOffice e coleta amostra final ANTES do wpr -stop
ordem_fase = []
reais_enc = {n: getattr(mod, n) for n in ("coletar_amostra", "fechar_libreoffice_teste", "parar_wpr_ativo")}
mod._amostra_final["valor"] = None
mod._lo_state["ativo"] = True
mod._wpr["ativo"], mod._wpr["fase"] = True, "Escritorio"
mod.coletar_amostra = lambda *a, **k: ordem_fase.append("amostra_final") or {"carga_pct": 10}
mod.fechar_libreoffice_teste = lambda: ordem_fase.append("fechar_lo")
mod.parar_wpr_ativo = lambda fase: ordem_fase.append(f"wpr_stop({fase})")
mod.encerrar_fase_medida()
confere(ordem_fase == ["amostra_final", "fechar_lo", "wpr_stop(Escritorio)"],
        "encerrar_fase_medida: amostra final e LibreOffice fechados ANTES do wpr -stop")
for nome, funcao in reais_enc.items():
    setattr(mod, nome, funcao)
mod._wpr["ativo"] = False
mod._lo_state["ativo"] = False

# Ctrl+Q / parada_segura mesmo na tomada -> pula janela de reconexao e exportacao pesada
real_status_energia = mod.status_energia
mod.status_energia = lambda: {"fonte": "tomada", "bateria_flag": 0, "carga_pct": 10, "economia_ligada": False}
mod._stop_requested.set()
confere(mod.aguardar_reconexao_para_pos_medicao(FakeUi(), 1) == "pular",
        "parada segura (Ctrl+Q) na tomada: pula pos-medicao pesada")
mod._stop_requested.clear()
mod._medicao["motivo"] = "parada_segura"
confere(mod.aguardar_reconexao_para_pos_medicao(FakeUi(), 1) == "pular",
        "motivo parada_segura na tomada: pula pos-medicao pesada")
mod._medicao["motivo"] = None
mod.status_energia = real_status_energia

ordem = []
stubs = {
    "encerrar_fase_medida": lambda: ordem.append("encerrar_fase_medida"),
    "restaurar_na_bateria": lambda: ordem.append("restaurar_na_bateria"),
    "gerar_relatorio_bateria": lambda *a, **k: ordem.append("relatorio_depois"),
    "concluir_resultado": lambda ui, est: ordem.append("bateria.csv") or 0,
    "restaurar_tudo": lambda: ordem.append("restaurar_tudo"),
    "manter_tela_ligada": lambda ligar: ordem.append(f"tela_{ligar}"),
    "pos_medicao_pesada": lambda ui: ordem.append("pos_medicao_pesada"),
}
for nome, funcao in stubs.items():
    setattr(mod, nome, funcao)
for escolha, pesada in (("tomada", True), ("bateria", True), ("pular", False)):
    ordem.clear()
    mod.aguardar_reconexao_para_pos_medicao = lambda ui, c, e=escolha: ordem.append(f"reconexao(c={c})") or e
    codigo = mod.encerramento_e_pos_medicao(FakeUi(), {})
    esperado = ["encerrar_fase_medida", "restaurar_na_bateria", "relatorio_depois", "bateria.csv",
                "restaurar_tudo", "tela_False", "reconexao(c=0)"] + (["pos_medicao_pesada"] if pesada else [])
    confere(ordem == esperado and codigo == 0,
            f"'{escolha}': bateria.csv e restaurar_tudo antes da reconexao"
            + (" e da pos-medicao pesada" if pesada else "; exportacao pulada"))
ordem.clear()
mod.concluir_resultado = lambda ui, est: (_ for _ in ()).throw(RuntimeError("x"))
mod.aguardar_reconexao_para_pos_medicao = lambda ui, c: ordem.append(f"reconexao(c={c})") or "pular"
codigo = mod.encerramento_e_pos_medicao(FakeUi(), {})
confere(codigo == 1 and "restaurar_tudo" in ordem and ordem.index("restaurar_tudo") < ordem.index("reconexao(c=1)"),
        "falha no calculo do resultado: FAIL, mas a maquina ainda e restaurada antes da reconexao")

print()
logging.shutdown()   # solta o log do script antes de remover a pasta (Windows)
shutil.rmtree(EVID_DIR, ignore_errors=True)
if falhas:
    print(f"{falhas} verificacao(oes) falharam.")
    sys.exit(1)
print("Todas as verificacoes passaram.")
