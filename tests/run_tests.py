"""Batterie de tests du moteur d'anonymisation.

Usage :
    python3 tests/run_tests.py                 # fabrique les fichiers de test puis teste le moteur directement
    python3 tests/run_tests.py --http 8810     # teste un moteur déjà lancé (ex. celui de l'app, port 8810)

Le test ÉCHOUE si un fichier attendu est absent : on ne « réussit » jamais en ne testant rien.
"""
import argparse
import gzip
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

ap = argparse.ArgumentParser()
ap.add_argument("--http", type=int, default=0, help="port d'un moteur déjà lancé (sinon moteur en direct)")
ap.add_argument("--dir", default="", help="dossier des fichiers de test (sinon dossier temporaire)")
args = ap.parse_args()

FIX = args.dir or tempfile.mkdtemp(prefix="anonymiseur-tests-")
if not os.path.exists(os.path.join(FIX, "photo.jpg")):
    subprocess.run([sys.executable, os.path.join(HERE, "make_fixtures.py"), FIX], check=True)

REQUIRED = ["photo.jpg", "image.png", "image.webp", "scan.tiff", "ia.png", "simple.pdf", "riche.pdf", "simple.docx", "riche.docx",
            "contenu.docx", "classeur.xlsx", "tableur.ods", "lot.zip", "projet.tar.gz", "dump.sql.gz", "page.html", "fr.po", "logo.svg",
            "schema.drawio", "schema_clair.drawio", "schema.drawio.svg", "schema.drawio.png", "design.psd", "lettre.txt"]
OPTIONAL = ["photo.heic", "lettre.pdf", "video.mp4", "video.mkv", "son.wav", "son.flac", "son.m4a", "son.mp3"]
failures = []
for f in REQUIRED:
    if not os.path.exists(os.path.join(FIX, f)):
        failures.append(f"fichier de test manquant : {f}")
FILES = [f for f in REQUIRED + OPTIONAL if os.path.exists(os.path.join(FIX, f))]

if args.http:
    def run(name, opts):
        data = open(os.path.join(FIX, name), "rb").read()
        req = urllib.request.Request(f"http://127.0.0.1:{args.http}/clean", data=data, method="POST",
                                     headers={"X-Filename": urllib.parse.quote(name), "X-Options": urllib.parse.quote(json.dumps(opts))})
        try:
            r = urllib.request.urlopen(req, timeout=180)
            return r.status, json.loads(urllib.parse.unquote(r.headers["X-Report"])), r.read()
        except urllib.error.HTTPError as e:
            return e.code, json.loads(urllib.parse.unquote(e.headers["X-Report"])), b""
else:
    import server
    def run(name, opts):
        out, rep, st, _ = server.process(open(os.path.join(FIX, name), "rb").read(), name, server.parse_options(urllib.parse.quote(json.dumps(opts))))
        return st, rep, out

COMBOS = {
    "fichier seul": {},
    "contenu seul": {"meta": False, "content": {"on": True, "terms": ["secret"]}},
    "fichier + contenu": {"content": {"on": True}},
    "maximal": {"strong": True, "flat": True, "neutral": True, "content": {"on": True}},
    "mes valeurs": {"setmeta": {"on": True, "author": "Anne Test", "title": "Doc", "created": "2020-03-15T08:30"}},
}
NAME_IN_TEXT = {"contenu.docx", "logo.svg"}          # le nom de l'auteur est écrit dans le texte : fuite légitime si on ne masque pas
TEXT_CASES = {"lettre.txt", "lettre.pdf", "contenu.docx", "schema.drawio", "schema_clair.drawio", "logo.svg"}
SET_OK = {"photo.jpg", "image.png", "image.webp", "scan.tiff", "photo.heic", "simple.pdf", "simple.docx", "video.mp4", "son.m4a"}
counts = {"ok": 0, "ko": 0}


def check(cond, msg):
    counts["ok" if cond else "ko"] += 1
    if not cond:
        failures.append(msg)


for cname, o in COMBOS.items():
    for f in FILES:
        st, rep, out = run(f, o)
        tag = f"[{cname}] {f}"
        check(st == 200, f"{tag} : statut {st} {rep.get('error', '')}")
        if st != 200:
            continue
        meta_on = o.get("meta", True)
        if meta_on and not rep.get("passthrough"):
            check(not rep.get("unsupported"), f"{tag} : format non géré")
            if rep.get("after"):
                check(not rep["after"]["items"] or f == "design.psd", f"{tag} : métadonnées restantes {[i['tag'] for i in rep['after']['items']]}")
                oa = rep.get("origin_after") or {}
                check(not (oa.get("fields") or oa.get("ai")) or "setmeta" in o, f"{tag} : origine encore visible {oa.get('fields')}")
            found = (rep.get("leak") or {}).get("found", [])
            check(not found or (f in NAME_IN_TEXT and "content" not in o) or "setmeta" in o, f"{tag} : fuite {found}")
        if o.get("content", {}).get("on") and f in TEXT_CASES:
            red = sum((rep.get("content") or {}).get("redacted", {}).values())
            check(red > 0, f"{tag} : rien n'a été masqué")
            if not rep["content"].get("flattened"):
                left = [x["kind"] for x in rep["content"]["findings"] if x["kind"] in ("e-mail", "numéro de téléphone", "IBAN")]
                check(not left, f"{tag} : encore présent dans le texte : {left}")
        if "setmeta" in o and f in SET_OK:
            check(len(rep.get("set_items") or []) > 0, f"{tag} : vos métadonnées n'ont pas été écrites")

# ── contrôles précis sur les sorties
st, rep, out = run("lot.zip", {})
check(st == 200 and {i.date_time for i in zipfile.ZipFile(io.BytesIO(out)).infolist()} == {(1980, 1, 1, 0, 0, 0)}, "lot.zip : dates internes non remises à zéro")
st, rep, out = run("projet.tar.gz", {})
if st == 200:
    m = tarfile.open(fileobj=io.BytesIO(out)).getmembers()[0]
    check((m.uid, m.uname, m.mtime) == (0, "", 946684800), f"projet.tar.gz : en-tête tar non neutralisé {(m.uid, m.uname, m.mtime)}")
    check(int.from_bytes(out[4:8], "little") == 0, "projet.tar.gz : date de l'en-tête gzip conservée")
st, rep, out = run("dump.sql.gz", {})
check(st == 200 and b"dump_jean" not in out[:60] and gzip.decompress(out) == b"SELECT 1;\n", "dump.sql.gz : nom d'origine conservé ou contenu altéré")
st, rep, out = run("photo.jpg", {"strong": True})
if st == 200:
    from PIL import Image
    im = Image.open(io.BytesIO(out))
    check(im.size == (300, 400) and not im.getexif(), f"photo.jpg renforcé : orientation/EXIF {im.size} {dict(im.getexif())}")
st, rep, out = run("design.psd", {})
check(st == 200 and b"Jean Martin" not in out and b"Adobe Photoshop" not in out and out[:4] == b"8BPS", "design.psd : ressources non retirées ou fichier abîmé")
st, rep, out = run("schema.drawio", {})
check(st == 200 and b"Electron" not in out and b"Qx7b2LmN9" not in out and b"<mxfile" in out, "schema.drawio : identité de l'éditeur conservée")
st, rep, out = run("schema.drawio.png", {})
check(st == 200 and b"mxfile" not in out, "schema.drawio.png : diagramme intégré conservé")
st, rep, out = run("fr.po", {})
check(st == 200 and b"Jean Martin" not in out and b'msgid "Hello"' in out, "fr.po : en-tête non nettoyé ou traductions altérées")

# ── dossier entier (moteur en direct uniquement) : arborescence conservée, fichier inconnu non copié, dates neutres
if not args.http:
    import shutil
    base = tempfile.mkdtemp(prefix="anonymiseur-dossier-")
    src = os.path.join(base, "Projet")
    for rel, name in (("photos", "photo.jpg"), ("docs", "contenu.docx"), ("docs", "lettre.txt"), (".", "schema.drawio")):
        os.makedirs(os.path.join(src, rel), exist_ok=True)
        shutil.copy(os.path.join(FIX, name), os.path.join(src, rel, name))
    with open(os.path.join(src, "inconnu.xyz"), "wb") as fh:
        fh.write(os.urandom(300))
    opts = server.parse_options(urllib.parse.quote(json.dumps({"neutral": True, "content": {"on": True}})))
    rep, status = server.process_folder(src, opts)
    dest = rep.get("saved_path", "")
    tree = sorted(os.path.relpath(os.path.join(r, f), dest) for r, _d, fs in os.walk(dest) for f in fs) if dest else []
    check(status == 200 and tree == ["docs/contenu.docx", "docs/lettre.txt", "photos/photo.jpg", "schema.drawio"], f"dossier : arborescence inattendue {tree}")
    check(rep["totals"]["skipped"] == 1 and rep["totals"]["after"] == 0, f"dossier : totaux inattendus {rep['totals']}")
    check(dest and abs(os.path.getmtime(os.path.join(dest, "photos", "photo.jpg")) - 946684800) < 2, "dossier : date du fichier non neutralisée")
    check(os.path.exists(os.path.join(src, "photos", "photo.jpg")) and b"Exif" in open(os.path.join(src, "photos", "photo.jpg"), "rb").read(), "dossier : l'original a été modifié")
    shutil.rmtree(base, ignore_errors=True)

print()
print(f"{counts['ok']} vérifications réussies, {counts['ko']} échec(s), sur {len(FILES)} fichiers × {len(COMBOS)} combinaisons")
if len(FILES) < len(REQUIRED):
    print("⚠ des fichiers obligatoires manquent")
for m in failures:
    print("  ✗", m)
sys.exit(1 if failures else 0)
