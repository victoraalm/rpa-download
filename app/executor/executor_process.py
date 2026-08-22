"""Subprocesso de execução de um robô.

Roda o manifesto em Chromium headless ("execução invisível"). Se detectar sessão
expirada (campo de senha visível ao abrir o site), abre o navegador na tela para
o usuário logar manualmente, recaptura/salva a sessão e retoma a execução.

Comunicação com o app (stdout, uma linha JSON por evento):
    {"type":"log","msg":...}
    {"type":"login_required"}
    {"type":"done","ok":true|false,"downloads":[...],"error":""}

Códigos de saída: 0 = sucesso, 2 = cancelado, 3 = erro.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from playwright.sync_api import sync_playwright  # noqa: E402

from app.executor.browser import ensure_chromium  # noqa: E402
from app.executor.executor_core import ExecutionEngine, is_login_page  # noqa: E402
from app.robot_manifest import RobotManifest  # noqa: E402
from app.services import crypto  # noqa: E402

EXIT_OK = 0
EXIT_CANCEL = 2
EXIT_ERROR = 3

_LOGIN_OVERLAY_JS = r"""
(() => {
  if (window.__rpa_login_installed || window.top !== window.self) return;
  window.__rpa_login_installed = true;
  function build() {
    if (document.getElementById('__rpa_login_bar')) return;
    const bar = document.createElement('div');
    bar.id = '__rpa_login_bar';
    bar.style.cssText = 'position:fixed;top:12px;left:50%;transform:translateX(-50%);' +
      'z-index:2147483647;background:#161619;color:#F2E9CE;border:1px solid #D4AF37;' +
      'border-radius:10px;padding:10px 14px;font-family:Segoe UI,Arial,sans-serif;' +
      'font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.4);display:flex;gap:10px;align-items:center;';
    const msg = document.createElement('span');
    msg.textContent = 'Sessão expirada — faça login normalmente. Ao terminar, clique:';
    const btn = document.createElement('button');
    btn.textContent = '✔ Já fiz login, continuar';
    btn.style.cssText = 'background:#D4AF37;color:#161619;border:none;border-radius:8px;' +
      'padding:6px 12px;font-weight:700;cursor:pointer;';
    btn.onclick = () => { if (window.__rpa_login_done) window.__rpa_login_done(); };
    bar.appendChild(msg); bar.appendChild(btn);
    (document.body || document.documentElement).appendChild(bar);
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', build);
  else build();
  setInterval(build, 1000);
})();
"""


def _emit(obj):
    try:
        if sys.stdout is not None:
            sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    except (OSError, ValueError):
        pass


def _make_context(browser, session_path, headed=False):
    kwargs = {"accept_downloads": True}
    if headed:
        kwargs["no_viewport"] = True  # site ocupa a janela toda (sem margem cinza)
    if session_path and os.path.isfile(session_path):
        try:
            kwargs["storage_state"] = json.loads(crypto.load_text_encrypted(session_path))
        except (OSError, ValueError):
            pass
    return browser.new_context(**kwargs)


def _wait_login_done(context, page, session_path, log):
    """Mostra o overlay 'Já fiz login' na página atual e espera o usuário logar."""
    done = {"v": False}
    try:
        context.expose_binding("__rpa_login_done", lambda *_: done.__setitem__("v", True))
    except Exception:
        pass  # já exposto neste contexto
    context.add_init_script(_LOGIN_OVERLAY_JS)
    try:
        page.evaluate(_LOGIN_OVERLAY_JS)  # injeta também na página já carregada
    except Exception:
        pass
    page.on("close", lambda *_: done.__setitem__("v", "closed"))
    log("Faça login na janela do navegador e clique em “Já fiz login”…")
    while done["v"] is False:
        try:
            page.wait_for_timeout(200)
        except Exception:
            done["v"] = "closed"
    if done["v"] == "closed":
        return False
    try:
        crypto.save_text_encrypted(session_path, json.dumps(context.storage_state()))
        log("Sessão recapturada e salva.")
    except Exception as e:  # noqa: BLE001
        log(f"Aviso: não foi possível salvar a sessão: {e}")
    return True


def _run(pw, manifest, start_url, download_dir, session_path, log, headed):
    launch_args = ["--start-maximized"] if headed else []
    browser = pw.chromium.launch(headless=not headed, args=launch_args)
    try:
        ctx = _make_context(browser, session_path, headed)
        page = ctx.new_page()
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
        if is_login_page(page):
            if not headed:
                return "needs_login", [], []
            # Visível: o usuário loga na própria janela (sem abrir outra).
            if not _wait_login_done(ctx, page, session_path, log):
                return "cancel", [], []
            try:
                page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
        engine = ExecutionEngine(page, manifest, download_dir, log=log)
        res = engine.execute()
        return ("ok" if res.ok else "error"), res.downloads, engine.step_results
    finally:
        browser.close()


def _manual_login(pw, start_url, session_path, log):
    log("Abrindo navegador para login manual…")
    browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
    try:
        ctx = _make_context(browser, session_path, headed=True)
        page = ctx.new_page()
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
        except Exception:
            pass
        return _wait_login_done(ctx, page, session_path, log)
    finally:
        browser.close()


def _parse(argv):
    p = argparse.ArgumentParser(description="Executor de robô (Playwright).")
    p.add_argument("--manifest", required=True)
    p.add_argument("--download-dir", required=True)
    p.add_argument("--session-in", default="")
    p.add_argument("--start-url", default="")
    p.add_argument("--log", default="")
    p.add_argument("--headed", action="store_true", help="navegador visível")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse(argv if argv is not None else sys.argv[1:])
    manifest = RobotManifest.load(args.manifest)
    start_url = args.start_url or manifest.start_url
    session_path = args.session_in

    logf = open(args.log, "a", encoding="utf-8") if args.log else None

    def log(msg):
        _emit({"type": "log", "msg": msg})
        if logf:
            logf.write(msg + "\n")
            logf.flush()

    rc = EXIT_ERROR
    downloads = []
    error = ""
    results = []
    try:
        ensure_chromium(log)  # baixa o navegador no 1º uso, se necessário
        with sync_playwright() as pw:
            status, downloads, results = _run(pw, manifest, start_url,
                                              args.download_dir, session_path, log, args.headed)
            if status == "needs_login":  # só ocorre no modo invisível (headless)
                _emit({"type": "login_required"})
                if _manual_login(pw, start_url, session_path, log):
                    status, downloads, r2 = _run(pw, manifest, start_url,
                                                 args.download_dir, session_path, log, args.headed)
                    results = results + r2
                else:
                    status = "cancel"

            if status == "ok":
                rc = EXIT_OK
            elif status == "cancel":
                rc = EXIT_CANCEL
            else:
                rc = EXIT_ERROR
                error = "Falha na execução (ver log)."
    except Exception as e:  # nunca derruba sem reportar
        error = f"{type(e).__name__}: {e}"
        log("ERRO: " + error)
        rc = EXIT_ERROR
    finally:
        if logf:
            logf.close()
        _write_csv(args.log, results)

    _emit({"type": "done", "ok": rc == EXIT_OK, "downloads": downloads, "error": error})
    return rc


def _write_csv(log_path, rows):
    """Grava o log detalhado por passo em .csv (separador ';' p/ Excel BR)."""
    if not log_path:
        return
    csv_path = (log_path[:-4] + ".csv") if log_path.lower().endswith(".log") else log_path + ".csv"
    cols = ["data_hora", "periodo", "passo", "acao", "campo", "seletor",
            "seletor_tipo", "seletor_rank", "seletor_total", "tentativas",
            "duracao_ms", "valor", "status", "erro"]
    try:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=cols, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
