"""Lanceur d'Anonymiseur pour Windows.

Démarre le moteur local (127.0.0.1) puis ouvre l'interface dans une fenêtre Edge sans barre d'adresse (mode « application »).
Quand la fenêtre est fermée, le moteur s'arrête tout seul. Les fichiers passés en argument (menu « Envoyer vers »,
glisser sur le raccourci) sont mis en attente dans la fenêtre ; si l'app est déjà ouverte, ils lui sont transmis.
"""
import ctypes
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request

APP = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.environ.get("LOCALAPPDATA") or APP, "Anonymiseur")
os.makedirs(DATA, exist_ok=True)
PORT = int(os.environ.get("ANONYMISEUR_PORT", "48765"))
PATHS = [os.path.abspath(a) for a in sys.argv[1:] if os.path.exists(a)]


def log(msg):
    with open(os.path.join(DATA, "lanceur.log"), "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def alert(text):
    ctypes.windll.user32.MessageBoxW(0, text, "Anonymiseur", 0x10 | 0x40000)


def ping(port, timeout=1.5):
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=timeout).status == 204
    except Exception:  # noqa: BLE001
        return False


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def port_busy(port):
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def find_browser():
    """Edge (présent sur Windows 10 et 11), sinon Chrome."""
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData"):
        base = os.environ.get(env)
        if base:
            for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
                p = os.path.join(base, rel)
                if os.path.exists(p):
                    return p
    try:
        import winreg
        for exe in ("msedge.exe", "chrome.exe"):
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                p = winreg.QueryValue(k, None)
                if p and os.path.exists(p):
                    return p
    except OSError:
        pass
    return None


def forward_to_running_instance():
    """L'app est déjà ouverte : on lui transmet les fichiers et on s'arrête."""
    try:
        token = open(os.path.join(DATA, "jeton"), encoding="utf-8").read().strip()
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/enqueue", data=json.dumps({"paths": PATHS}).encode(),
                                     method="POST", headers={"X-Token": token})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:  # noqa: BLE001
        log("transmission impossible : " + traceback.format_exc())


def main():
    global PORT
    if ping(PORT):
        forward_to_running_instance()
        return
    if port_busy(PORT):
        PORT = free_port()           # un autre programme occupe le port habituel (les réglages mémorisés seront perdus)
    token = secrets.token_hex(16)
    with open(os.path.join(DATA, "jeton"), "w", encoding="utf-8") as f:
        f.write(token)
    os.environ.update({"PORT": str(PORT), "TOKEN": token, "WINAPP": "1", "PYTHONNOUSERSITE": "1",
                       "PYTHONDONTWRITEBYTECODE": "1"})
    os.environ["PATH"] = os.path.join(APP, "bin") + os.pathsep + os.environ.get("PATH", "")
    sys.path.insert(0, os.path.join(APP, "app"))
    import server                    # lit PORT, TOKEN et WINAPP au chargement : l'environnement doit être prêt avant

    url = f"http://127.0.0.1:{PORT}/"

    def open_window():
        for _ in range(100):
            if ping(PORT, 0.5):
                break
            time.sleep(0.1)
        with server.LOCK:
            server.PENDING.extend(PATHS)
        exe = find_browser()
        if not exe:
            os.startfile(url)        # aucun Edge/Chrome trouvé : navigateur par défaut
            return
        subprocess.Popen([exe, f"--app={url}", "--window-size=840,920", f"--user-data-dir={os.path.join(DATA, 'navigateur')}",
                          "--no-first-run", "--no-default-browser-check", "--disable-sync", "--disable-features=Translate"])

    threading.Thread(target=open_window, daemon=True).start()
    sys.argv = [sys.argv[0], "--no-browser", "--watch"]
    server.main()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        alert("Anonymiseur n'a pas pu démarrer.\n\nDétails : " + os.path.join(DATA, "lanceur.log"))
