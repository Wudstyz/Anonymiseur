"""Tests de bout en bout de l'app Windows INSTALLÉE : jeton, file « Envoyer vers », traitement par chemin (espaces et accents),
« à côté de l'original », date de création neutre, « Tout enregistrer », corbeille.
Usage : python tests/e2e_windows.py <fixtures> <dossier de travail> [port]
Le moteur doit tourner avec ANONYMISEUR_TEST_DIALOG (dossier de sortie) et ANONYMISEUR_ASSUME_YES=1."""
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

FIX, WORK = sys.argv[1], sys.argv[2]
PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 48765
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = open(os.path.join(os.environ["LOCALAPPDATA"], "Anonymiseur", "jeton"), encoding="utf-8").read().strip()
fails = []


def check(cond, msg):
    print(("  ok  " if cond else "  ÉCHEC ") + msg)
    if not cond:
        fails.append(msg)


def call(path, body=None, headers=None, method=None):
    req = urllib.request.Request(BASE + path, data=body, headers={"X-Token": TOKEN, **(headers or {})}, method=method or ("POST" if body is not None else "GET"))
    try:
        r = urllib.request.urlopen(req, timeout=180)
        return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


html = call("/")[2].decode("utf-8")
check("window.WINAPP=true" in html and TOKEN in html, "la page contient le mode Windows et le jeton")
check(call("/native", b'{"type":"pick"}', {"X-Token": "mauvais"})[0] == 403, "/native refuse un mauvais jeton")

# « Envoyer vers » : un second lancement dépose des chemins, la fenêtre les récupère
src = os.path.join(WORK, "Dossier é test")
os.makedirs(src, exist_ok=True)
photo = os.path.join(src, "Photo d'été.jpg")
shutil.copy(os.path.join(FIX, "photo.jpg"), photo)
check(call("/enqueue", json.dumps({"paths": [photo]}).encode())[0] == 200, "/enqueue accepte un chemin")
st, _, body = call("/pending?token=" + TOKEN)
check(json.loads(body)["paths"] == [photo], "/pending rend le chemin (accents et espaces conservés)")
check(json.loads(call("/pending?token=" + TOKEN)[2])["paths"] == [], "/pending se vide après lecture")

# Traitement par chemin, à côté de l'original, date neutre
opts = urllib.parse.quote(json.dumps({"beside": True, "neutral": True}))
st, hdr, _ = call("/clean-path", b"", {"X-Path": urllib.parse.quote(photo), "X-Options": opts})
rep = json.loads(urllib.parse.unquote(hdr["X-Report"]))
check(st == 200 and rep.get("saved_path") and os.path.exists(rep["saved_path"]), f"copie « (anonymisé) » créée à côté de l'original : {rep.get('saved_path')}")
if rep.get("saved_path") and os.path.exists(rep["saved_path"]):
    stt = os.stat(rep["saved_path"])
    check(time.gmtime(stt.st_mtime).tm_year == 2000 and time.gmtime(stt.st_ctime).tm_year == 2000, "dates de modification ET de création au 1er janvier 2000")
    check(rep["after"]["items"] == [] and not (rep["leak"] or {}).get("found"), "plus aucune métadonnée ni fuite")
check(os.path.exists(photo), "l'original est intact")

# Dossier entier
dossier = os.path.join(WORK, "Mon Projet")
for rel, name in (("photos", "photo.jpg"), ("docs", "contenu.docx")):
    os.makedirs(os.path.join(dossier, rel), exist_ok=True)
    shutil.copy(os.path.join(FIX, name), os.path.join(dossier, rel, name))
st, hdr, _ = call("/clean-path", b"", {"X-Path": urllib.parse.quote(dossier), "X-Options": urllib.parse.quote("{}")})
rep = json.loads(urllib.parse.unquote(hdr["X-Report"]))
check(st == 200 and rep["totals"]["ok"] == 2 and os.path.isdir(rep["saved_path"]), "dossier : 2 fichiers traités, « (anonymisé) » créé")

# « Tout enregistrer » vers le dossier choisi (boîte de dialogue simulée)
st, hdr, _ = call("/clean-path", b"", {"X-Path": urllib.parse.quote(os.path.join(FIX, "photo.jpg")), "X-Options": urllib.parse.quote("{}")})
rid = json.loads(urllib.parse.unquote(hdr["X-Report"]))["id"]
before = set(os.listdir(os.environ["ANONYMISEUR_E2E_OUT"]))
out = json.loads(call("/native", json.dumps({"type": "saveAll", "items": [{"id": rid, "name": "x"}]}).encode())[2])
check(out.get("saved") == 1 and len(set(os.listdir(os.environ["ANONYMISEUR_E2E_OUT"])) - before) == 1, "« Tout enregistrer » écrit le fichier dans le dossier choisi")

# Corbeille : l'original disparaît (récupérable), la copie reste
orig = os.path.join(WORK, "a_supprimer.jpg"); copie = os.path.join(WORK, "a_supprimer (anonymisé).jpg")
shutil.copy(os.path.join(FIX, "photo.jpg"), orig); shutil.copy(os.path.join(FIX, "photo.jpg"), copie)
out = json.loads(call("/native", json.dumps({"type": "trash", "items": [{"src": orig, "copy": copie}]}).encode())[2])
check(out.get("trashed") == 1 and not os.path.exists(orig) and os.path.exists(copie), "corbeille : original déplacé, copie conservée")

print()
print("ÉCHECS :", len(fails))
sys.exit(1 if fails else 0)
