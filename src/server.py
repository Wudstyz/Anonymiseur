"""Serveur local d'anonymisation : écoute uniquement sur 127.0.0.1, rien ne sort de la machine."""
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from cleaners import (CONTENT_CATS, author_names, clean_fields, set_metadata, tags_for, clean_bytes, inspect, leak_check, origin, scan_content,
                      set_progress)

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("PORT", 8765))
MAX_BYTES = 2 * 1024 ** 3


last_ping = [0.0]


def watchdog(srv):
    """Quitte quand la page est fermée (plus de ping depuis 20 s)."""
    while True:
        time.sleep(3)
        if last_ping[0] and time.time() - last_ping[0] > 20:
            srv.shutdown()
            return


TOKEN = os.environ.get("TOKEN", "")          # fourni par l'app native ; protège les routes qui lisent le disque
RESULTS = {}                                   # résultats gardés en mémoire pour « Télécharger » / « Tout enregistrer »
JOBS = {}                                      # progression des traitements en cours
LOCK = threading.Lock()
NEUTRAL_TS = 946684800                         # 1er janvier 2000, 00:00 UTC
MAX_FILES = 5000
SKIP_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def parse_options(header):
    """Options envoyées par l'interface (JSON encodé dans X-Options), avec valeurs par défaut sûres."""
    try:
        o = json.loads(urllib.parse.unquote(header or "") or "{}")
    except ValueError:
        o = {}
    c = o.get("content") or {}
    return {
        "meta": o.get("meta", True) is not False,
        "rename": bool(o.get("rename")),
        "strong": bool(o.get("strong")),
        "flat": bool(o.get("flat")),
        "beside": bool(o.get("beside")),
        "neutral": bool(o.get("neutral")),
        "content": {"cats": c.get("cats") or list(CONTENT_CATS), "terms": c.get("terms") or []} if c.get("on") else None,
        "setmeta": {k: str(v) for k, v in (o.get("setmeta") or {}).items() if k != "on" and v not in (None, "")}
        if (o.get("setmeta") or {}).get("on") else None,
        "job": str(o.get("job") or ""),
    }


def _job(job, pct, stage=None):
    if job:
        with LOCK:
            j = JOBS.setdefault(job, {})
            j["pct"] = round(pct)
            if stage:
                j["stage"] = stage


def process(data, name, o):
    """Nettoie `data` selon les options `o` et renvoie (octets, rapport complet, statut HTTP, nom final)."""
    job = o.get("job")
    set_progress(lambda pct, stage=None: _job(job, pct, stage))
    _job(job, 5, "Lecture et analyse")
    before = inspect(data, name)
    content = None
    if o["content"]:
        content = {"cats": o["content"]["cats"], "terms": o["content"]["terms"], "names": author_names(before)}
    _job(job, 10, "Nettoyage")
    try:
        out, rep = clean_bytes(data, name, strong=o["strong"], flat=o["flat"], content=content, meta=o["meta"])
        status = 200
    except Exception as e:  # noqa: BLE001
        out, rep, status = b"", {"removed": [], "notes": [], "error": str(e)}, 422
    written, mine = {}, set()
    if status == 200 and o["setmeta"] and not rep.get("unsupported"):
        _job(job, 70, "Écriture de vos métadonnées")
        out2, srep, written = set_metadata(out, name, o["setmeta"])
        if written:
            out, mine = out2, tags_for(written)
        rep["removed"] = rep["removed"] + srep["removed"]
        rep["notes"] = rep["notes"] + srep["notes"]
    if status == 200 and rep.get("new_ext"):
        name = os.path.splitext(name)[0] + rep["new_ext"]
    if o["rename"] and status == 200:
        name = secrets.token_hex(6) + os.path.splitext(name)[1].lower()
        rep["notes"].append("Nom de fichier remplacé par un nom aléatoire.")
    rep["before"] = rep["after"] = None
    if status == 200 and not rep.get("unsupported"):
        _job(job, 85, "Vérification")
        rep["before"], rep["after"] = before, inspect(out, name)
        # ce que VOUS avez défini n'est pas une « trace restante » : on le sépare
        rep["set_items"] = [i for i in rep["after"]["items"] if i["tag"] in mine] if mine else []
        if mine:
            is_mine = lambda tag: tag in mine or ("gps" in written and tag.startswith("GPS"))  # noqa: E731
            rep["set_items"] = [i for i in rep["after"]["items"] if is_mine(i["tag"])]
            rep["after"]["items"] = [i for i in rep["after"]["items"] if not is_mine(i["tag"])]
            rep["after"]["all"] = [t for t in rep["after"]["all"] if not is_mine(t[1])]
        rep["origin_before"] = origin(rep["before"], data)
        rep["origin_after"] = origin(rep["after"], out)
        rep["leak"] = leak_check(rep["before"], out, name) if o["meta"] else None
        if rep["leak"] and written:
            mine_vals = {str(v).lower() for v in o["setmeta"].values()}
            rep["leak"]["found"] = [x for x in rep["leak"]["found"] if x["value"].lower() not in mine_vals]
        rep["content"] = scan_content(out, name, author_names(before))
        rep["content"]["redacted"] = rep.get("redacted") or {}
        rep["content"]["flattened"] = bool(rep.get("flattened"))
        for k in ("before", "after"):
            if rep[k]:
                rep[k].pop("all", None)
    elif status == 200:
        rep["content"] = scan_content(out, name, [])
        rep["content"]["redacted"] = rep.get("redacted") or {}
    rep["meta_kept"] = not o["meta"]
    rep["name"] = name
    rep["size_before"], rep["size_after"] = len(data), len(out)
    _job(job, 100, "Terminé")
    return out, rep, status, name


def unique_path(folder, filename):
    stem, ext = os.path.splitext(filename)
    path, i = os.path.join(folder, filename), 2
    while os.path.exists(path):
        path = os.path.join(folder, f"{stem} {i}{ext}")
        i += 1
    return path


def set_neutral_date(path):
    try:
        os.utime(path, (NEUTRAL_TS, NEUTRAL_TS))
    except OSError:
        pass


def write_result(folder, filename, out, neutral):
    dest = unique_path(folder, filename)
    with open(dest, "xb") as f:
        f.write(out)
    if neutral:
        set_neutral_date(dest)
    return dest


def process_folder(src, o):
    """Nettoie tous les fichiers d'un dossier vers « <dossier> (anonymisé) », en gardant l'arborescence."""
    job = o.get("job")
    files = []
    for root, dirs, names in os.walk(src):
        dirs[:] = sorted(d for d in dirs if not os.path.islink(os.path.join(root, d)))
        for n in sorted(names):
            p = os.path.join(root, n)
            if n in SKIP_NAMES or n.startswith("._") or os.path.islink(p):
                continue
            files.append(p)
    if not files:
        return {"removed": [], "notes": [], "error": "Le dossier ne contient aucun fichier."}, 422
    if len(files) > MAX_FILES:
        return {"removed": [], "notes": [], "error": f"Trop de fichiers ({len(files)}, maximum {MAX_FILES})."}, 422
    dest_root = unique_path(os.path.dirname(src), os.path.basename(src.rstrip("/")) + " (anonymisé)")
    os.makedirs(dest_root)
    fo = dict(o, rename=False, job="")             # les noms sont conservés pour garder l'arborescence
    rows, tot = [], {"files": len(files), "ok": 0, "skipped": 0, "passthrough": 0, "partial": 0, "before": 0, "after": 0, "leaks": 0, "findings": 0}
    size_b = size_a = 0
    for i, path in enumerate(files):
        rel = os.path.relpath(path, src)
        _job(job, 100 * i / len(files), f"Fichier {i + 1}/{len(files)} : {rel}")
        row = {"path": rel}
        try:
            with open(path, "rb") as f:
                data = f.read()
            out, rep, status, name = process(data, os.path.basename(path), fo)
        except Exception as e:  # noqa: BLE001
            row.update(status="error", reason=str(e))
            rows.append(row); tot["skipped"] += 1
            continue
        if status != 200 or rep.get("unsupported"):
            row.update(status="skipped", reason=rep.get("error") or "format non géré")
            rows.append(row); tot["skipped"] += 1
            continue
        folder = os.path.join(dest_root, os.path.dirname(rel))
        os.makedirs(folder, exist_ok=True)
        write_result(folder, name, out, o["neutral"])
        nb = len(rep["before"]["items"]) if rep.get("before") else 0
        na = len(rep["after"]["items"]) if rep.get("after") else 0
        leak = len((rep.get("leak") or {}).get("found", []))
        fnd = sum(x["count"] for x in (rep.get("content") or {}).get("findings", []))
        row.update(status="ok", before=nb, after=na, leak=leak, findings=fnd, name=name,
                   removed=sum((rep.get("redacted") or {}).values()), passthrough=bool(rep.get("passthrough")))
        tot["passthrough"] += bool(rep.get("passthrough"))
        tot["partial"] += bool(na and o["meta"])
        rows.append(row)
        tot["ok"] += 1; tot["before"] += nb; tot["after"] += na; tot["leaks"] += leak; tot["findings"] += fnd
        size_b += len(data); size_a += len(out)
    if o["neutral"]:
        for root, dirs, _n in os.walk(dest_root, topdown=False):
            for d in dirs:
                set_neutral_date(os.path.join(root, d))
        set_neutral_date(dest_root)
    notes = ["Noms des fichiers et des dossiers conservés pour garder l'arborescence."]
    if tot["skipped"]:
        notes.append(f"{tot['skipped']} fichier(s) non traités (format non géré ou erreur) : ils n'ont PAS été copiés.")
    rep = {"folder": True, "name": os.path.basename(dest_root), "source_name": os.path.basename(src.rstrip("/")),
           "saved_path": dest_root, "files": rows, "totals": tot, "removed": [], "notes": notes,
           "size_before": size_b, "size_after": size_a, "meta_kept": not o["meta"]}
    _job(job, 100, "Terminé")
    return rep, 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _local_only(self):
        # Refuse les requêtes venant d'un autre site web (protection contre le DNS rebinding / CSRF).
        if self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            self.send_error(403)
            return False
        return True

    def _authorized(self, token):
        if TOKEN and secrets.compare_digest(token or "", TOKEN):
            return True
        self.send_error(403)
        return False

    def _reply(self, status, body, rep):
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Report", urllib.parse.quote(json.dumps(rep, ensure_ascii=False)))
        self.send_header("Access-Control-Expose-Headers", "X-Report")
        self.end_headers()
        self.wfile.write(body)

    def _clean_path(self, src, o):
        err = None
        if not os.path.isabs(src) or not os.path.exists(src):
            err = "Fichier introuvable."
        elif os.path.isfile(src) and os.path.getsize(src) > MAX_BYTES:
            err = "Fichier trop volumineux (2 Go maximum)."
        if err:
            self._reply(422, b"", {"removed": [], "notes": [], "error": err, "name": os.path.basename(src)})
            return
        if os.path.isdir(src):
            rep, status = process_folder(src, o)
            rep.setdefault("name", os.path.basename(src))
            self._reply(status, b"", rep)
            return
        with open(src, "rb") as f:
            data = f.read()
        orig_name = os.path.basename(src)
        out, rep, status, name = process(data, orig_name, o)
        rep["source_name"] = orig_name
        if status == 200 and not rep.get("unsupported") or (status == 200 and rep.get("redacted")):
            if o["beside"]:
                folder = os.path.dirname(src)
                final = name if o["rename"] else f"{os.path.splitext(name)[0]} (anonymisé){os.path.splitext(name)[1]}"
                try:
                    rep["saved_path"] = write_result(folder, final, out, o["neutral"])
                except OSError as e:
                    rep["notes"].append(f"Enregistrement à côté de l'original impossible : {e.strerror}")
            if "saved_path" not in rep:
                rid = secrets.token_hex(8)
                with LOCK:
                    RESULTS[rid] = (name, out)
                rep["id"] = rid
        self._reply(status, b"", rep)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/ping":
            last_ping[0] = time.time()
            self.send_response(204)
            self.end_headers()
            return
        if url.path == "/progress":
            q = urllib.parse.parse_qs(url.query)
            with LOCK:
                j = dict(JOBS.get((q.get("job") or [""])[0], {}))
            body = json.dumps(j).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/result":
            if not self._local_only():
                return
            q = urllib.parse.parse_qs(url.query)
            if not self._authorized((q.get("token") or [""])[0]):
                return
            with LOCK:
                item = RESULTS.get((q.get("id") or [""])[0])
            if not item:
                self.send_error(404)
                return
            name, body = item
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(name))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path not in ("/", "/index.html"):
            self.send_error(404)
            return
        with open(os.path.join(HERE, "index.html"), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path not in ("/clean", "/clean-path", "/forget", "/stat") or not self._local_only():
            self.send_error(404)
            return
        n = int(self.headers.get("Content-Length", 0))
        if n > MAX_BYTES:
            self.send_error(413)
            return
        body = self.rfile.read(n)
        o = parse_options(self.headers.get("X-Options"))

        if path == "/forget":
            if self._authorized(self.headers.get("X-Token")):
                with LOCK:
                    RESULTS.clear()
                self.send_response(204)
                self.end_headers()
            return

        if path == "/stat":
            if not self._authorized(self.headers.get("X-Token")):
                return
            src = urllib.parse.unquote(self.headers.get("X-Path", ""))
            info = {"name": os.path.basename(src.rstrip("/"))}
            try:
                if os.path.isdir(src):
                    n = 0
                    for _r, _d, fs in os.walk(src):
                        n += sum(1 for f in fs if f not in SKIP_NAMES and not f.startswith("._"))
                        if n > 20000:
                            break
                    info.update(dir=True, count=n)
                elif os.path.isfile(src):
                    info.update(dir=False, size=os.path.getsize(src))
            except OSError:
                pass
            body = json.dumps(info).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if path == "/clean-path":
            if not self._authorized(self.headers.get("X-Token")):
                return
            src = urllib.parse.unquote(self.headers.get("X-Path", ""))
            try:
                self._clean_path(src, o)
            finally:
                with LOCK:
                    JOBS.pop(o["job"], None)
            return

        # /clean : le contenu est envoyé dans la requête (utilisé hors de l'app native)
        name = os.path.basename(urllib.parse.unquote(self.headers.get("X-Filename", "fichier"))) or "fichier"
        try:
            out, rep, status, name = process(body, name, o)
        finally:
            with LOCK:
                JOBS.pop(o["job"], None)
        self._reply(status, out, rep)


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}"
    print(f"Anonymiseur de métadonnées prêt : {url}  (Ctrl+C pour quitter)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    if "--watch" in sys.argv:
        threading.Thread(target=watchdog, args=(srv,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
