"""Biblioteca comum dos modulos de cargas de desenvolvimento (7 a 11).

Cada modulo (Testes/N_dev_x/N_dev_x.py) so chama ``executar_modulo(__file__)``.
O que o modulo mede fica no ``cargas.json`` da pasta dele; esta biblioteca:

- le o ``cargas.json`` e mescla as cargas internas do ``workloads.local.json``
  (raiz do projeto, fora do git);
- confere a tomada e as ferramentas antes de medir;
- clona os repositorios na ref fixa (fora da medicao);
- roda ``preparo`` (1x), e N vezes ``setup`` -> ``command`` (cronometrado) -> ``cleanup``;
- aplica o limite de tempo (10x a mediana do ``referencia.json``), encerrando a
  arvore de processos que passar dele;
- monitora tomada e Ctrl+Q durante toda a execucao;
- grava log por carga, JSON e CSV tematico em ``HUB_EVIDENCE_DIR``;
- com ``--calibrar``, grava o ``referencia.json`` do modulo.

Passo de carga: lista de argumentos (executavel + args, sem shell) ou acao
embutida ``{"acao": "apagar" | "escrever" | "arquivos_pequenos" | "esperar_healthy"}``.
Tokens aceitos em qualquer texto: ``{work}``, ``{modulo}``, ``{evidencias}``.

Este arquivo nao e um teste: o hub o exclui do menu (Get-Scripts -Exclude).
"""

import argparse
import csv
import glob
import json
import math
import os
import queue
import re
import shutil
import stat
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - o setup do hub instala o psutil
    psutil = None

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
ARQUIVO_LOCAL = RAIZ_PROJETO / "workloads.local.json"
FATOR_LIMITE = 10
INTERVALO_MONITOR = 0.5
INTERVALO_TOMADA = 2.0
TIMEOUT_SETUP_PADRAO = 3600
TIMEOUT_CLEANUP_FALHA = 600

OK = "OK"
FALHOU = "FALHOU"
TEMPO_EXCEDIDO = "TEMPO_EXCEDIDO"
INTERROMPIDO = "INTERROMPIDO"


# =============================================================================
# Excecoes de controle
# =============================================================================
class FalhaPasso(Exception):
    """Um passo saiu com codigo != 0 ou uma acao embutida falhou."""


class TempoExcedido(Exception):
    """O command passou do limite de tempo da carga."""


class Interrompido(Exception):
    """Ctrl+Q ou tomada desconectada: para o modulo inteiro."""


# =============================================================================
# Utilitarios
# =============================================================================
def _console_seguro():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def _ler_json(caminho):
    with open(caminho, encoding="utf-8-sig") as f:
        return json.load(f)


def _expandir(valor, tokens):
    if isinstance(valor, str):
        for chave, sub in tokens.items():
            valor = valor.replace("{" + chave + "}", sub)
        return valor
    if isinstance(valor, list):
        return [_expandir(v, tokens) for v in valor]
    if isinstance(valor, dict):
        return {k: _expandir(v, tokens) for k, v in valor.items()}
    return valor


def _versao_tupla(texto):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", texto or "")
    if not m:
        return None
    return tuple(int(x) if x else 0 for x in m.groups())


def _caminho_longo(caminho):
    """Prefixo \\\\?\\ do Windows: sem ele, arquivos alem de 260 caracteres (comuns em
    repos clonados com core.longpaths, ex.: home-assistant) nao sao apagados."""
    caminho = os.path.abspath(caminho)
    if os.name == "nt" and not caminho.startswith("\\\\?\\"):
        if caminho.startswith("\\\\"):
            return "\\\\?\\UNC\\" + caminho[2:]
        return "\\\\?\\" + caminho
    return caminho


def _remover_arvore(caminho):
    """rmtree que tambem apaga arquivos somente leitura (objetos do git) e caminhos longos.

    Lanca FalhaPasso se algo sobrar: um setup que nao limpa invalida a medicao seguinte.
    """
    def _forcar(func, path, _exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass
    alvo = _caminho_longo(caminho)
    if os.path.isdir(alvo) and not os.path.islink(alvo):
        shutil.rmtree(alvo, onexc=_forcar)  # Python 3.12+ (versao do setup do hub)
    elif os.path.exists(alvo):
        os.chmod(alvo, stat.S_IWRITE)
        os.remove(alvo)
    if os.path.exists(alvo):
        raise FalhaPasso(f"nao foi possivel apagar {caminho} (arquivo em uso ou sem permissao)")


def na_tomada():
    """True na tomada ou em desktop sem bateria."""
    if psutil is None:
        return True
    try:
        bat = psutil.sensors_battery()
    except Exception:
        return True
    if bat is None or bat.power_plugged is None:
        return True
    return bool(bat.power_plugged)


def encerrar_arvore(pid):
    """Encerra o processo e todos os descendentes (msbuild, go, podman...)."""
    if psutil is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        return
    try:
        pai = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    procs = pai.children(recursive=True) + [pai]
    for p in procs:
        try:
            p.terminate()
        except psutil.NoSuchProcess:
            pass
    _, vivos = psutil.wait_procs(procs, timeout=5)
    for p in vivos:
        try:
            p.kill()
        except psutil.NoSuchProcess:
            pass


def _cpu_nome():
    try:
        import winreg
        chave = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        return winreg.QueryValueEx(chave, "ProcessorNameString")[0].strip()
    except Exception:
        import platform
        return platform.processor()


def _ram_gb():
    if psutil is None:
        return None
    return round(psutil.virtual_memory().total / 1024 ** 3, 1)


def _plano_energia():
    try:
        r = subprocess.run(["powercfg", "/getactivescheme"], capture_output=True, timeout=15,
                           encoding="oem", errors="replace")
        return " ".join(r.stdout.split())
    except Exception as e:
        return f"desconhecido ({e})"


def _pasta_trabalho():
    cfg = RAIZ_PROJETO / "config.local.json"
    if cfg.exists():
        try:
            valor = _ler_json(cfg).get("DevWorkDir")
            if valor:
                return Path(os.path.expandvars(valor))
        except (OSError, ValueError):
            pass
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "wintestehub-dev-work"


# =============================================================================
# Definicao do modulo
# =============================================================================
def _mesclar_por_chave(base, extra, chave):
    resultado = list(base)
    indice = {item.get(chave): i for i, item in enumerate(resultado)}
    for item in extra:
        if item.get(chave) in indice:
            resultado[indice[item.get(chave)]] = item
        else:
            resultado.append(item)
    return resultado


def carregar_definicao(pasta_modulo):
    definicao = _ler_json(pasta_modulo / "cargas.json")
    definicao.setdefault("modulo", pasta_modulo.name)
    definicao.setdefault("ferramentas", [])
    definicao.setdefault("repos", [])
    definicao.setdefault("cargas", [])
    definicao.setdefault("registrar", [])
    definicao["cargas_locais"] = []
    if ARQUIVO_LOCAL.exists():
        local = _ler_json(ARQUIVO_LOCAL).get(definicao["modulo"], {})
        definicao["repos"] = _mesclar_por_chave(definicao["repos"], local.get("repos", []), "nome")
        definicao["cargas"] = _mesclar_por_chave(definicao["cargas"], local.get("cargas", []), "id")
        definicao["ferramentas"] = _mesclar_por_chave(definicao["ferramentas"], local.get("ferramentas", []), "cmd")
        definicao["cargas_locais"] = [c.get("id") for c in local.get("cargas", [])]
    return definicao


def carregar_referencia(pasta_modulo):
    caminho = pasta_modulo / "referencia.json"
    if not caminho.exists():
        return None
    try:
        return _ler_json(caminho)
    except (OSError, ValueError) as e:
        log(f"[!] referencia.json ilegivel ({e}); seguindo sem limite de tempo.")
        return None


# =============================================================================
# Execucao
# =============================================================================
class Contexto:
    """Estado compartilhado entre o executor, o monitor e o overlay."""

    def __init__(self, tokens, evidencias, ui):
        self.tokens = tokens
        self.evidencias = evidencias
        self.ui = ui
        self.parar = threading.Event()
        self.motivo_parada = ""
        self._ultima_tomada = 0.0

    def pedir_parada(self, motivo):
        if not self.parar.is_set():
            self.motivo_parada = motivo
            self.parar.set()

    def checar(self, deadline=None):
        """Lanca Interrompido/TempoExcedido quando for o caso."""
        agora = time.monotonic()
        if agora - self._ultima_tomada >= INTERVALO_TOMADA:
            self._ultima_tomada = agora
            if not na_tomada():
                self.pedir_parada("tomada desconectada durante a medicao")
        if self.parar.is_set():
            raise Interrompido(self.motivo_parada)
        if deadline is not None and agora > deadline:
            raise TempoExcedido()


class Executor:
    def __init__(self, ctx):
        self.ctx = ctx
        # Durante o cleanup apos falha/interrupcao: nao reagir a Ctrl+Q/tomada
        # (senao o cleanup seria abortado na hora), so ao limite de seguranca.
        self.ignorar_parada = False

    def _checar(self, deadline):
        if self.ignorar_parada:
            if deadline is not None and time.monotonic() > deadline:
                raise TempoExcedido()
            return
        self.ctx.checar(deadline)

    def _resolver_exe(self, exe, cwd, env):
        if os.sep in exe or "/" in exe:
            caminho = Path(exe)
            if not caminho.is_absolute():
                caminho = Path(cwd) / caminho
            for ext in ("", ".exe", ".cmd", ".bat"):
                if Path(str(caminho) + ext).exists():
                    return str(caminho) + ext
            return str(caminho)
        return shutil.which(exe, path=env.get("PATH")) or exe

    def rodar_passo(self, passo, cwd, env, arq_log, deadline):
        if isinstance(passo, dict):
            return self._acao(passo, cwd, env, arq_log, deadline)
        argv = list(passo)
        argv[0] = self._resolver_exe(argv[0], cwd, env)
        arq_log.write(f"$ {' '.join(argv)}\n".encode("utf-8"))
        arq_log.flush()
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=arq_log, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL)
        except OSError as e:
            raise FalhaPasso(f"nao foi possivel iniciar '{argv[0]}': {e}") from e
        try:
            while True:
                try:
                    proc.wait(timeout=INTERVALO_MONITOR / 5)
                    break
                except subprocess.TimeoutExpired:
                    self._checar(deadline)
        except (TempoExcedido, Interrompido):
            encerrar_arvore(proc.pid)
            proc.wait()
            raise
        if proc.returncode != 0:
            raise FalhaPasso(f"'{Path(argv[0]).name}' saiu com codigo {proc.returncode}")
        return None

    # ---- acoes embutidas -------------------------------------------------
    def _acao(self, passo, cwd, env, arq_log, deadline):
        nome = passo.get("acao")
        arq_log.write(f"$ [acao] {json.dumps(passo, ensure_ascii=False)}\n".encode("utf-8"))
        arq_log.flush()
        if nome == "apagar":
            for rel in passo.get("caminhos", []):
                _remover_arvore(os.path.join(cwd, rel))
            for padrao in passo.get("globs", []):
                for alvo in glob.glob(os.path.join(cwd, padrao), recursive=True):
                    _remover_arvore(alvo)
            return None
        if nome == "escrever":
            alvo = Path(cwd) / passo["arquivo"]
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_text(passo.get("conteudo", "").replace("{agora}", datetime.now().isoformat()), encoding="utf-8")
            return None
        if nome == "arquivos_pequenos":
            return self._arquivos_pequenos(passo, cwd, deadline)
        if nome == "esperar_healthy":
            return self._esperar_healthy(passo, cwd, env, arq_log, deadline)
        raise FalhaPasso(f"acao desconhecida: {nome}")

    def _arquivos_pequenos(self, passo, cwd, deadline):
        pasta = Path(cwd) / passo.get("pasta", "arquivos_pequenos")
        qtd = int(passo.get("quantidade", 20000))
        dados = os.urandom(int(passo.get("tamanho", 4096)))
        if pasta.exists():
            _remover_arvore(pasta)
        pasta.mkdir(parents=True)
        parciais = {}

        t0 = time.perf_counter()
        for i in range(qtd):
            if i % 500 == 0:
                self._checar(deadline)
            with open(pasta / f"f{i}.bin", "wb") as f:
                f.write(dados)
        parciais["criar"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        for i, entrada in enumerate(os.scandir(pasta)):
            if i % 500 == 0:
                self._checar(deadline)
            with open(entrada.path, "rb") as f:
                f.read()
        parciais["ler"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        for i, entrada in enumerate(list(os.scandir(pasta))):
            if i % 500 == 0:
                self._checar(deadline)
            os.remove(entrada.path)
        pasta.rmdir()
        parciais["apagar"] = time.perf_counter() - t0
        return parciais

    def _esperar_healthy(self, passo, cwd, env, arq_log, deadline):
        containers = passo["containers"]
        limite_proprio = time.monotonic() + float(passo.get("timeout_s", 600))
        podman = shutil.which("podman", path=env.get("PATH")) or "podman"
        estados = {}
        while True:
            for nome in containers:
                try:
                    r = subprocess.run([podman, "inspect", "--format", "{{.State.Status}}|{{.State.Health.Status}}", nome],
                                       cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
                    if r.returncode != 0:
                        estados[nome] = "ausente"
                    else:
                        execucao, _, saude = r.stdout.strip().partition("|")
                        # Container que morreu nao vai ficar healthy: reprova ja, sem esperar o timeout
                        estados[nome] = execucao if execucao in ("exited", "stopped", "dead") else saude
                except subprocess.TimeoutExpired:
                    estados[nome] = "sem resposta"
            if all(v == "healthy" for v in estados.values()):
                arq_log.write(f"healthy: {estados}\n".encode("utf-8"))
                return None
            if any(v in ("unhealthy", "exited", "stopped", "dead") for v in estados.values()):
                raise FalhaPasso(f"container parou ou ficou unhealthy (veja 'podman logs'): {estados}")
            if time.monotonic() > limite_proprio:
                raise FalhaPasso(f"timeout esperando healthy: {estados}")
            self._checar(deadline)
            time.sleep(INTERVALO_MONITOR)


def _env_carga(definicao, carga, tokens):
    env = dict(os.environ)
    for origem in (definicao.get("env", {}), carga.get("env", {})):
        for k, v in _expandir(origem, tokens).items():
            env[k] = v
    return env


def _rodar_fase(executor, passos, cwd, env, arq_log, rotulo, deadline):
    arq_log.write(f"\n### {rotulo} {datetime.now().isoformat(timespec='seconds')}\n".encode("utf-8"))
    arq_log.flush()
    parciais = {}
    for passo in passos:
        r = executor.rodar_passo(passo, cwd, env, arq_log, deadline)
        if isinstance(r, dict):
            parciais.update(r)
    return parciais


def preparar_repos(definicao, ctx, executor, pasta_logs):
    """Clona/atualiza cada repo na ref fixa. Fora da medicao."""
    if not definicao["repos"]:
        return
    work = Path(ctx.tokens["work"])
    env = dict(os.environ)
    # Repos sao publicos e clonados sem login. Se algum passar a pedir credencial (removido,
    # renomeado, limite de API), o clone falha na hora em vez de travar o hub numa janela de login.
    env["GIT_TERMINAL_PROMPT"] = "0"  # sem prompt no terminal
    env["GCM_INTERACTIVE"] = "never"  # sem janela do Git Credential Manager
    with open(pasta_logs / "_repos.log", "ab") as arq:
        for repo in definicao["repos"]:
            destino = work / repo["nome"]
            ref = repo["ref"]
            ctx.ui.status(f"Preparando repositorio {repo['nome']} @ {ref}")
            log(f"Repositorio {repo['nome']} @ {ref}")
            git = ["git", "-c", "core.longpaths=true", "-c", "credential.helper="]
            eh_hash = re.fullmatch(r"[0-9a-f]{40}", ref) is not None
            if not (destino / ".git").exists():
                if destino.exists():
                    _remover_arvore(destino)
                if eh_hash:
                    executor.rodar_passo(git + ["clone", "-q", repo["url"], str(destino)], str(work), env, arq, None)
                else:
                    prof = str(repo.get("profundidade", 1))
                    executor.rodar_passo(git + ["clone", "-q", "--depth", prof, "--branch", ref, repo["url"], str(destino)],
                                         str(work), env, arq, None)
            try:
                executor.rodar_passo(git + ["checkout", "-q", "--detach", ref], str(destino), env, arq, None)
            except FalhaPasso:
                alvo = ref if eh_hash else f"refs/tags/{ref}:refs/tags/{ref}"
                executor.rodar_passo(git + ["fetch", "-q", "origin", alvo], str(destino), env, arq, None)
                executor.rodar_passo(git + ["checkout", "-q", "--detach", ref], str(destino), env, arq, None)
            executor.rodar_passo(git + ["reset", "-q", "--hard"], str(destino), env, arq, None)
            executor.rodar_passo(git + ["clean", "-q", "-fdx"], str(destino), env, arq, None)


def checar_ferramentas(definicao, env=None):
    """Retorna (versoes, erros). Usa o env do modulo (ex.: GOTOOLCHAIN) para registrar a versao efetiva."""
    versoes, erros = {}, []
    ferramentas = list(definicao["ferramentas"])
    if definicao["repos"] and not any(f.get("cmd") == "git" for f in ferramentas):
        ferramentas.insert(0, {"cmd": "git", "versao": ["git", "--version"]})
    for f in ferramentas:
        cmd = f["cmd"]
        exe = shutil.which(cmd)
        if not exe:
            erros.append(f"'{cmd}' nao encontrado no PATH (rode o setup 7_install_devtools_dev / 10_preparar_podman)")
            continue
        argv = [exe] + list(f.get("versao", [cmd, "--version"]))[1:]
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=300, errors="replace", env=env)
            saida = (r.stdout or r.stderr).strip()
        except Exception as e:
            erros.append(f"'{cmd}' nao respondeu: {e}")
            continue
        versoes[cmd] = saida.splitlines()[0] if saida else "?"
        minima = f.get("minima")
        if minima:
            atual, exigida = _versao_tupla(saida), _versao_tupla(minima)
            if atual is None or (exigida and atual < exigida):
                erros.append(f"'{cmd}' versao {versoes[cmd]!r} abaixo da minima {minima}")
    return versoes, erros


def _registrar(definicao, ctx):
    registros = {}
    for item in definicao["registrar"]:
        item = _expandir(item, ctx.tokens)
        argv = list(item["cmd"])
        argv[0] = shutil.which(argv[0]) or argv[0]
        try:
            r = subprocess.run(argv, cwd=item.get("cwd", ctx.tokens["work"]), capture_output=True, text=True,
                               timeout=120, errors="replace", env=_env_carga(definicao, {}, ctx.tokens))
            registros[item["nome"]] = (r.stdout or r.stderr).strip()
        except Exception as e:
            registros[item["nome"]] = f"erro: {e}"
    return registros


def medir_carga(carga, definicao, ctx, executor, pasta_logs, runs, limite_s, limite_fria_s=None):
    """Executa uma carga N vezes. Retorna o dicionario de resultado.

    A 1a execucao (fria: caches do SO vazios) usa ``limite_fria_s`` (10x a fria da referencia);
    as demais, ``limite_s`` (10x a mediana). Frio se compara com frio.
    """
    limite_fria_s = limite_fria_s or limite_s
    tokens = ctx.tokens
    carga = _expandir(carga, tokens)
    cid = carga["id"]
    cwd = carga.get("cwd", tokens["work"])
    env = _env_carga(definicao, carga, tokens)
    timeout_setup = float(carga.get("timeout_setup_s", TIMEOUT_SETUP_PADRAO))
    res = {"descricao": carga.get("descricao", ""), "sensivel_rede": bool(carga.get("sensivel_rede", False)),
           "limite_s": limite_s, "limite_fria_s": limite_fria_s,
           "execucoes_s": [], "parciais": [], "status": OK, "motivo": "",
           "local": cid in definicao.get("cargas_locais", [])}
    caminho_log = pasta_logs / f"{cid}.log"
    fase = {"nome": "preparo", "medindo": False}
    limite_run = limite_s
    with open(caminho_log, "wb") as arq:
        arq.write(f"# {cid} - {os.environ.get('COMPUTERNAME', '')} - {datetime.now().isoformat(timespec='seconds')}\n"
                  .encode("utf-8"))
        try:
            Path(cwd).mkdir(parents=True, exist_ok=True)
            if carga.get("preparo"):
                ctx.ui.status(f"{cid}: preparo")
                _rodar_fase(executor, carga["preparo"], cwd, env, arq, "preparo",
                            time.monotonic() + timeout_setup)
            for i in range(1, runs + 1):
                limite_run = limite_fria_s if i == 1 else limite_s
                ctx.ui.carga(cid, i, runs, limite_run)
                fase.update(nome=f"setup run {i}", medindo=False)
                _rodar_fase(executor, carga.get("setup", []), cwd, env, arq, f"setup run {i}",
                            time.monotonic() + timeout_setup)
                ctx.ui.status(f"{cid}: medindo (run {i}/{runs})")
                t0 = time.perf_counter()
                inicio = time.monotonic()
                deadline = inicio + limite_run if limite_run else None
                ctx.ui.cronometro(inicio)
                fase.update(nome=f"command run {i}", medindo=True)
                try:
                    parciais = _rodar_fase(executor, carga["command"], cwd, env, arq, f"command run {i}", deadline)
                finally:
                    ctx.ui.cronometro(None)
                dur = time.perf_counter() - t0
                res["execucoes_s"].append(round(dur, 2))
                if parciais:
                    res["parciais"].append({k: round(v, 2) for k, v in parciais.items()})
                arq.write(f"### tempo run {i}: {dur:.2f}s\n".encode("utf-8"))
                log(f"  {cid} run {i}: {dur:.1f}s")
                ctx.ui.ultimo(f"run {i}: {dur:.1f}s")
                fase.update(nome=f"cleanup run {i}", medindo=False)
                _rodar_fase(executor, carga.get("cleanup", []), cwd, env, arq, f"cleanup run {i}",
                            time.monotonic() + timeout_setup)
        except TempoExcedido:
            if fase["medindo"]:
                res["status"], res["motivo"] = TEMPO_EXCEDIDO, f"{fase['nome']} passou do limite de {limite_run}s"
            else:
                res["status"], res["motivo"] = FALHOU, f"{fase['nome']} excedeu {int(timeout_setup)}s"
        except Interrompido as e:
            res["status"], res["motivo"] = INTERROMPIDO, str(e)
        except FalhaPasso as e:
            res["status"], res["motivo"] = FALHOU, str(e)
        except Exception as e:  # erro inesperado da propria carga (ex.: JSON incompleto)
            res["status"], res["motivo"] = FALHOU, f"{type(e).__name__}: {e}"
        if res["status"] != OK:
            arq.write(f"### {res['status']}: {res['motivo']}\n".encode("utf-8"))
            log(f"  [!] {cid} {res['status']}: {res['motivo']} (log: {caminho_log})")
            executor.ignorar_parada = True
            try:
                _rodar_fase(executor, carga.get("cleanup", []), cwd, env, arq, "cleanup apos falha",
                            time.monotonic() + TIMEOUT_CLEANUP_FALHA)
            except Exception as e:
                arq.write(f"### cleanup apos falha tambem falhou: {e}\n".encode("utf-8"))
            finally:
                executor.ignorar_parada = False
    if res["status"] == OK and res["execucoes_s"]:
        res["mediana_s"] = round(statistics.median(res["execucoes_s"]), 2)
        res["fria_s"] = res["execucoes_s"][0]
        if res["parciais"]:
            res["parciais_mediana_s"] = {k: round(statistics.median(p[k] for p in res["parciais"]), 2)
                                         for k in res["parciais"][0]}
    else:
        res["mediana_s"] = None
        res["fria_s"] = None
    return res


# =============================================================================
# Saida
# =============================================================================
def gravar_csv(caminho, cargas):
    with open(caminho, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["carga", "status", "mediana_s", "fria_s", "limite_s", "execucoes_s", "sensivel_rede", "motivo"])
        for cid, r in cargas.items():
            w.writerow([cid, r["status"], r.get("mediana_s") or "", r.get("fria_s") or "", r.get("limite_s") or "",
                        " ".join(str(x) for x in r.get("execucoes_s", [])), "sim" if r.get("sensivel_rede") else "nao",
                        r.get("motivo", "")])
            for parte, valor in (r.get("parciais_mediana_s") or {}).items():
                w.writerow([f"{cid}:{parte}", r["status"], valor, "", "", "", "", ""])


def gravar_referencia(pasta_modulo, resultado, runs):
    """Grava referencia.json. Cargas nao medidas agora (ex.: --only) mantem a referencia anterior."""
    anterior = carregar_referencia(pasta_modulo) or {}
    ref = {"gerado_em": datetime.now().isoformat(timespec="seconds"), "cpu": _cpu_nome(), "ram_gb": _ram_gb(),
           "runs": runs, "fator": FATOR_LIMITE, "versoes": resultado["versoes"],
           "cargas": dict(anterior.get("cargas", {}))}
    for cid, r in resultado["cargas"].items():
        if r["status"] == OK and r.get("mediana_s") and not r.get("local"):
            ref["cargas"][cid] = {"mediana_s": r["mediana_s"],
                                  "limite_s": int(math.ceil(r["mediana_s"] * FATOR_LIMITE)),
                                  "fria_s": r["fria_s"],
                                  "limite_fria_s": int(math.ceil(max(r["fria_s"], r["mediana_s"]) * FATOR_LIMITE))}
    caminho = pasta_modulo / "referencia.json"
    with open(caminho, "w", encoding="utf-8", newline="\n") as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return caminho


# =============================================================================
# Interface: overlay Tkinter + Ctrl+Q
# =============================================================================
class _SemUI:
    def status(self, _t): pass
    def carga(self, *_a): pass
    def ultimo(self, _t): pass
    def cronometro(self, _inicio): pass
    def aviso(self, _t): pass
    def fechar(self): pass


class Overlay:
    """Janela flutuante click-through, no padrao dos modulos 1 a 6.

    O Tkinter fica na thread principal; o trabalho manda mensagens pela fila.
    """

    def __init__(self, titulo):
        import tkinter as tk
        self.tk = tk
        self.fila = queue.Queue()
        self.inicio = None
        self.root = tk.Tk()
        self.root.title(titulo)
        largura = self.root.winfo_screenwidth()
        self.root.geometry(f"380x150+{largura - 410}+30")
        self.root.attributes("-topmost", True)
        self.root.overrideredirect(True)
        self.root.configure(bg="#1e1e1e")
        self.lbl_titulo = tk.Label(self.root, text=titulo, fg="#00ff00", bg="#1e1e1e", font=("Segoe UI", 12, "bold"))
        self.lbl_titulo.pack(pady=(8, 2))
        self.lbl_carga = tk.Label(self.root, text="Preparando...", fg="white", bg="#1e1e1e", font=("Segoe UI", 10))
        self.lbl_carga.pack()
        self.lbl_tempo = tk.Label(self.root, text="", fg="#00d2ff", bg="#1e1e1e", font=("Consolas", 11))
        self.lbl_tempo.pack(pady=2)
        self.lbl_status = tk.Label(self.root, text="", fg="#bbbbbb", bg="#1e1e1e", font=("Segoe UI", 9),
                                   wraplength=360)
        self.lbl_status.pack()
        tk.Label(self.root, text="Ctrl+Q: parada segura", fg="#777777", bg="#1e1e1e",
                 font=("Segoe UI", 8)).pack(pady=(2, 4))
        self.root.update_idletasks()
        self._click_through()
        self.root.after(200, self._processar)

    def _click_through(self):
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            estilo = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, estilo | 0x00080000 | 0x00000020)
        except Exception:
            pass

    def _processar(self):
        try:
            while True:
                tipo, valor = self.fila.get_nowait()
                if tipo == "fechar":
                    self.root.destroy()
                    return
                if tipo == "cronometro":
                    self.inicio = valor
                elif tipo == "carga":
                    self.lbl_carga.config(text=valor)
                elif tipo == "status":
                    self.lbl_status.config(text=valor, fg="#bbbbbb")
                elif tipo == "aviso":
                    self.lbl_status.config(text=valor, fg="#ff5555")
                elif tipo == "ultimo":
                    self.lbl_tempo.config(text=valor)
        except queue.Empty:
            pass
        if self.inicio is not None:
            self.lbl_tempo.config(text=f"{time.monotonic() - self.inicio:7.1f}s")
        self.root.after(200, self._processar)

    # API usada pela thread de trabalho
    def status(self, texto): self.fila.put(("status", texto))
    def aviso(self, texto): self.fila.put(("aviso", texto))
    def ultimo(self, texto): self.fila.put(("ultimo", texto))
    def cronometro(self, inicio): self.fila.put(("cronometro", inicio))
    def fechar(self): self.fila.put(("fechar", None))

    def carga(self, cid, i, n, limite):
        lim = f" | limite {limite}s" if limite else ""
        self.fila.put(("carga", f"{cid}  (run {i}/{n}{lim})"))

    def loop(self):
        self.root.mainloop()


def _iniciar_ctrl_q(ctx):
    try:
        from pynput import keyboard as kb
    except ImportError:
        log("[!] pynput indisponivel: Ctrl+Q desativado.")
        return None
    estado = {"ctrl": False}

    def on_press(key):
        if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
            estado["ctrl"] = True
        elif estado["ctrl"] and getattr(key, "char", None) in ("q", "Q", "\x11"):
            log("Parada segura solicitada (Ctrl+Q).")
            ctx.pedir_parada("parada solicitada pelo operador (Ctrl+Q)")

    def on_release(key):
        if key in (kb.Key.ctrl_l, kb.Key.ctrl_r):
            estado["ctrl"] = False

    ouvinte = kb.Listener(on_press=on_press, on_release=on_release)
    ouvinte.daemon = True
    ouvinte.start()
    return ouvinte


# =============================================================================
# Ponto de entrada dos modulos
# =============================================================================
def _args(argv):
    p = argparse.ArgumentParser(description="Modulo de cargas de desenvolvimento do WinTestHub")
    p.add_argument("--runs", type=int, default=3, help="execucoes por carga (padrao 3)")
    p.add_argument("--calibrar", action="store_true", help="mede sem limite e grava referencia.json")
    p.add_argument("--only", default="", help="so as cargas cujo id comeca com estes prefixos (separados por virgula)")
    p.add_argument("--sem-overlay", action="store_true", help="nao abre a janela flutuante")
    return p.parse_args(argv)


def _trabalho(pasta_modulo, args, ctx, resultado):
    """Corpo do modulo. Roda na thread de trabalho; preenche ``resultado``."""
    definicao = carregar_definicao(pasta_modulo)
    resultado["modulo"] = definicao["modulo"]
    resultado["csv"] = definicao.get("csv")
    referencia = None if args.calibrar else carregar_referencia(pasta_modulo)
    resultado["referencia_usada"] = (
        {"gerado_em": referencia.get("gerado_em"), "cpu": referencia.get("cpu"), "fator": referencia.get("fator")}
        if referencia else None)
    pasta_logs = ctx.evidencias / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)

    resultado["plano_energia"] = _plano_energia()
    resultado["na_tomada"] = na_tomada()
    if not resultado["na_tomada"]:
        msg = "Notebook na bateria: as cargas de dev so medem na tomada. Conecte o carregador e rode de novo."
        ctx.ui.aviso(msg)
        resultado["erros"].append(msg)
        log(f"[X] {msg}")
        time.sleep(3)
        return

    ctx.ui.status("Conferindo ferramentas...")
    resultado["versoes"], erros = checar_ferramentas(definicao, _env_carga(definicao, {}, ctx.tokens))
    for cmd, versao in resultado["versoes"].items():
        log(f"  {cmd}: {versao}")
    if erros:
        resultado["erros"].extend(erros)
        for e in erros:
            log(f"[X] {e}")
        ctx.ui.aviso("Pre-requisito ausente: " + "; ".join(erros))
        time.sleep(3)
        return

    cargas = [c for c in definicao["cargas"] if c.get("enabled", True)]
    if args.only:
        prefixos = [p.strip() for p in args.only.split(",") if p.strip()]
        cargas = [c for c in cargas if any(c["id"].startswith(p) for p in prefixos)]
    if not cargas:
        resultado["erros"].append("nenhuma carga habilitada")
        log("[X] Nenhuma carga habilitada.")
        return
    if referencia is None and not args.calibrar:
        aviso = "Modulo sem referencia.json: sem limite de tempo (rode com --calibrar no notebook de referencia)."
        resultado["avisos"].append(aviso)
        log(f"[!] {aviso}")

    executor = Executor(ctx)
    try:
        Path(ctx.tokens["work"]).mkdir(parents=True, exist_ok=True)
        preparar_repos(definicao, ctx, executor, pasta_logs)
    except Interrompido as e:
        resultado["erros"].append(f"interrompido ao preparar repositorios: {e}")
        return
    except FalhaPasso as e:
        resultado["erros"].append(f"falha ao preparar repositorios: {e} (log: {pasta_logs / '_repos.log'})")
        log(f"[X] {resultado['erros'][-1]}")
        return

    for carga in cargas:
        cid = carga["id"]
        limite = limite_fria = None
        if referencia:
            ref_carga = referencia.get("cargas", {}).get(cid) or {}
            limite, limite_fria = ref_carga.get("limite_s"), ref_carga.get("limite_fria_s")
            if limite is None:
                resultado["avisos"].append(f"{cid}: sem referencia, sem limite de tempo")
        log(f"== {cid} ==")
        r = medir_carga(carga, definicao, ctx, executor, pasta_logs, args.runs, limite, limite_fria)
        resultado["cargas"][cid] = r
        if r["status"] == INTERROMPIDO:
            resultado["erros"].append(r["motivo"])
            break

    resultado["registros"] = _registrar(definicao, ctx)


def executar_modulo(arquivo_modulo, argv=None):
    """Executa o modulo e encerra o processo com o exit code do hub."""
    _console_seguro()
    args = _args(sys.argv[1:] if argv is None else argv)
    pasta_modulo = Path(arquivo_modulo).resolve().parent
    hub_dir = os.environ.get("HUB_EVIDENCE_DIR")
    evidencias = Path(hub_dir) if hub_dir else pasta_modulo / "_saida"
    evidencias.mkdir(parents=True, exist_ok=True)
    work = _pasta_trabalho()
    tokens = {"work": str(work), "modulo": str(pasta_modulo), "evidencias": str(evidencias)}

    resultado = {"modulo": pasta_modulo.name, "host": os.environ.get("COMPUTERNAME", ""),
                 "data": datetime.now().isoformat(timespec="seconds"), "runs": args.runs,
                 "calibracao": args.calibrar, "cpu": _cpu_nome(), "ram_gb": _ram_gb(), "pasta_trabalho": str(work),
                 "versoes": {}, "cargas": {}, "erros": [], "avisos": [], "registros": {}}

    ui = _SemUI()
    overlay = None
    if not args.sem_overlay:
        try:
            overlay = Overlay(f"Cargas dev - {pasta_modulo.name}")
            ui = overlay
        except Exception as e:  # sem display (CI) ou Tk indisponivel
            log(f"[!] Overlay indisponivel ({e}); seguindo sem janela.")
    ctx = Contexto(tokens, evidencias, ui)
    ouvinte = _iniciar_ctrl_q(ctx)

    log(f"Modulo {pasta_modulo.name} | runs={args.runs} | calibrar={args.calibrar} | trabalho={work}")

    def alvo():
        try:
            _trabalho(pasta_modulo, args, ctx, resultado)
        except Exception as e:  # nunca deixar a thread morrer sem registrar
            resultado["erros"].append(f"erro inesperado: {type(e).__name__}: {e}")
            log(f"[X] {resultado['erros'][-1]}")
        finally:
            ui.fechar()

    if overlay:
        t = threading.Thread(target=alvo, daemon=True)
        t.start()
        overlay.loop()
        t.join()
    else:
        alvo()
    if ouvinte:
        ouvinte.stop()

    todas_ok = bool(resultado["cargas"]) and all(r["status"] == OK for r in resultado["cargas"].values())
    passou = todas_ok and not resultado["erros"]
    resultado["resultado"] = "PASS" if passou else "FAIL"

    nome_csv = resultado.get("csv") or f"dev_{pasta_modulo.name.split('_', 1)[-1]}.csv"
    with open(evidencias / f"{Path(nome_csv).stem}.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    gravar_csv(evidencias / nome_csv, resultado["cargas"])

    if args.calibrar:
        if passou:
            caminho = gravar_referencia(pasta_modulo, resultado, args.runs)
            log(f"Referencia gravada: {caminho}")
        else:
            log("[X] Calibracao NAO gravada: nem todas as cargas terminaram OK.")

    log("Resumo:")
    for cid, r in resultado["cargas"].items():
        log(f"  {cid:<40} {r['status']:<15} mediana={r.get('mediana_s')}  fria={r.get('fria_s')}"
            f"  limite={r.get('limite_fria_s')}/{r.get('limite_s')} (1a/demais)")
    for e in resultado["erros"]:
        log(f"  erro: {e}")
    log(f"Resultado: {resultado['resultado']} | evidencias: {evidencias}")
    sys.exit(0 if passou else 1)
