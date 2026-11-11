"""Fabrique des fichiers de test avec des métadonnées et un contenu FICTIFS (« Jean Martin », etc.).

Usage : python3 tests/make_fixtures.py DOSSIER_DE_SORTIE
Nécessite Pillow et pypdf (déjà dans l'app autonome). Les fichiers audio/vidéo ne sont créés que si un FFmpeg complet
(avec encodeurs) est trouvé : variable FFMPEG_FULL, ou /opt/homebrew/bin/ffmpeg, ou ffmpeg dans le PATH.
"""
import base64
import gzip
import io
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import urllib.parse
import zipfile
import zlib

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo

OUT = sys.argv[1] if len(sys.argv) > 1 else "fixtures"
os.makedirs(OUT, exist_ok=True)
P = lambda n: os.path.join(OUT, n)  # noqa: E731
made = []


def put(name, data, mode="wb"):
    with open(P(name), mode) as f:
        f.write(data)
    made.append(name)


# ── Images ───────────────────────────────────────────────────────────────────
im = Image.new("RGB", (400, 300), (30, 60, 160))
d = ImageDraw.Draw(im)
for i in range(0, 400, 20):
    d.line([(i, 0), (400 - i, 300)], fill=(240, 200, 40), width=3)
ex = Image.Exif()
ex[0x010F], ex[0x0110], ex[0x0112] = "MarqueTest", "ModeleX1", 6
ex[0x0132], ex[0x013B], ex[0x0131] = "2024:05:01 10:00:00", "Jean Martin", "Logiciel Photo 9"
gps = ex.get_ifd(0x8825)
gps[1], gps[2], gps[3], gps[4] = "N", (48.0, 51.0, 30.0), "E", (2.0, 17.0, 40.0)
im.save(P("photo.jpg"), quality=61, subsampling=0, exif=ex, progressive=True); made.append("photo.jpg")
pi = PngInfo()
pi.add_text("Author", "Jean Martin")
im.save(P("image.png"), pnginfo=pi, exif=ex); made.append("image.png")
im.save(P("image.webp"), exif=ex); made.append("image.webp")
im.save(P("scan.tiff"), exif=ex); made.append("scan.tiff")
pi = PngInfo()
pi.add_text("parameters", "a cat, masterpiece\nNegative prompt: blurry\nSteps: 20, Sampler: Euler a, CFG scale: 7, Seed: 123")
pi.add_text("Software", "ComfyUI")
Image.new("RGB", (32, 32), (9, 9, 9)).save(P("ia.png"), pnginfo=pi); made.append("ia.png")
if shutil.which("sips"):
    subprocess.run(["sips", "-s", "format", "heic", P("photo.jpg"), "--out", P("photo.heic")], capture_output=True)
    if os.path.exists(P("photo.heic")):
        made.append("photo.heic")

if not os.path.exists(P("photo.heic")):                    # sans sips (Windows) : pillow-heif sait écrire du HEIC
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        Image.open(P("photo.jpg")).convert("RGB").save(P("photo.heic"), exif=ex.tobytes())
        made.append("photo.heic")
    except Exception:  # noqa: BLE001
        data = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "photo.heic")   # HEIC fictif fourni avec le dépôt
        if os.path.exists(data):
            shutil.copy(data, P("photo.heic"))
            made.append("photo.heic")

# ── PDF ──────────────────────────────────────────────────────────────────────
from pypdf import PdfWriter  # noqa: E402

w = PdfWriter()
w.add_blank_page(200, 200)
w.add_metadata({"/Author": "Jean Martin", "/Title": "Secret", "/Creator": "Logiciel PDF 4"})
buf = io.BytesIO(); w.write(buf); put("simple.pdf", buf.getvalue())

letter = ("Bonjour,\nContactez Jean Martin au 06 12 34 56 78 ou +33 6 12 34 56 78, ou par mail à jean.martin@exemple.fr.\n"
          "Virement sur FR76 3000 6000 0112 3456 7890 189 (IBAN). Carte 4539 1488 0343 6467. Dossier : /home/jean/Documents/secret.\n"
          "Serveur 192.168.1.42. Version 1.2.3.4. Date 12/05/2024. Tel faux: 12345.\n")
put("lettre.txt", letter, "w")
if shutil.which("cupsfilter"):
    r = subprocess.run(["cupsfilter", "-m", "application/pdf", P("lettre.txt")], capture_output=True)
    if r.stdout[:5] == b"%PDF-":
        put("lettre.pdf", r.stdout)

if not os.path.exists(P("lettre.pdf")):                    # sans cupsfilter (Windows) : PDF écrit à la main, texte extractible
    def esc(t):
        return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    body = "BT /F1 9 Tf 36 770 Td 11 TL " + " ".join("(%s) Tj T*" % esc(l) for l in letter.splitlines()) + " ET"
    body = body.encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
    pdf = b"%PDF-1.4\n"; offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(pdf)); pdf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
    put("lettre.pdf", pdf)

# PDF « riche » : annotation signée + photo JPEG (avec EXIF/GPS) embarquée, écrit à la main
jpg = open(P("photo.jpg"), "rb").read()
objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /XObject << /Im0 5 0 R >> >> /Annots [6 0 R] >>"]
c = b"q 100 0 0 100 10 10 cm /Im0 Do Q"
objs.append(b"<< /Length %d >>\nstream\n" % len(c) + c + b"\nendstream")
objs.append(b"<< /Type /XObject /Subtype /Image /Width 400 /Height 300 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n" % len(jpg) + jpg + b"\nendstream")
objs.append(b"<< /Type /Annot /Subtype /Text /Rect [10 10 30 30] /Contents (note) /T (Jean Martin) /M (D:20240501100000Z) /Subj (Revue) >>")
pdf = b"%PDF-1.7\n"; offs = []
for i, o in enumerate(objs, 1):
    offs.append(len(pdf)); pdf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
x = len(pdf)
pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
pdf += b"trailer\n<< /Size %d /Root 1 0 R /Info << /Author (Jean Martin) /Producer (Distiller 23) >> >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)
put("riche.pdf", pdf)

# ── Office / OpenDocument ────────────────────────────────────────────────────
CORE = "<cp:coreProperties xmlns:cp='x' xmlns:dc='y'><dc:creator>Jean Martin</dc:creator></cp:coreProperties>"
W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
with zipfile.ZipFile(P("simple.docx"), "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>"); z.writestr("word/document.xml", "<d/>"); z.writestr("docProps/core.xml", CORE)
made.append("simple.docx")
with zipfile.ZipFile(P("riche.docx"), "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>")
    z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body><w:p w:rsidR="00A1B2C3"><w:ins w:id="1" w:author="Jean Martin" w:date="2024-05-01T10:00:00Z"><w:r><w:t>Bonjour</w:t></w:r></w:ins></w:p></w:body></w:document>')
    z.writestr("word/comments.xml", f'<?xml version="1.0"?><w:comments {W}><w:comment w:id="0" w:author="Marie Dupont" w:date="2024-05-02T09:00:00Z" w:initials="MD"><w:p><w:r><w:t>ok</w:t></w:r></w:p></w:comment></w:comments>')
    z.writestr("word/people.xml", '<?xml version="1.0"?><w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"><w15:person w15:author="Marie Dupont"><w15:presenceInfo w15:providerId="AD" w15:userId="S-1-5-21-123"/></w15:person></w15:people>')
    z.writestr("word/settings.xml", f'<?xml version="1.0"?><w:settings {W}><w:rsids><w:rsidRoot w:val="00A1B2C3"/></w:rsids></w:settings>')
    z.writestr("docProps/core.xml", CORE)
made.append("riche.docx")
with zipfile.ZipFile(P("contenu.docx"), "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>")
    z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body><w:p><w:r><w:t>Contact : jean.martin@exemple.fr, tél 06 12 34 56 78, par Jean Martin.</w:t></w:r></w:p></w:body></w:document>')
    z.writestr("docProps/core.xml", CORE)
made.append("contenu.docx")
with zipfile.ZipFile(P("classeur.xlsx"), "w") as z:
    z.writestr("[Content_Types].xml", "<Types/>")
    z.writestr("xl/workbook.xml", '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:x15ac="http://schemas.microsoft.com/office/spreadsheetml/2010/11/ac"><mc:AlternateContent><mc:Choice Requires="x15"><x15ac:absPath url="/home/jean/Documents/Secret"/></mc:Choice></mc:AlternateContent><sheets/></workbook>')
    z.writestr("xl/comments1.xml", "<comments><authors><author>Jean Martin</author></authors></comments>")
made.append("classeur.xlsx")
META = '<?xml version="1.0"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta><meta:generator>LibreOffice/7.4$MacOSX_AARCH64</meta:generator><dc:creator>Jean Martin</dc:creator></office:meta></office:document-meta>'
with zipfile.ZipFile(P("tableur.ods"), "w") as z:
    z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", zipfile.ZIP_STORED)
    z.writestr("meta.xml", META); z.writestr("content.xml", "<office:document-content xmlns:office='urn:oasis:names:tc:opendocument:xmlns:office:1.0'/>")
    z.writestr("Object 1/meta.xml", META)            # graphique embarqué : il a ses propres métadonnées
made.append("tableur.ods")

# ── Archives ─────────────────────────────────────────────────────────────────
with zipfile.ZipFile(P("lot.zip"), "w") as z:
    z.write(P("photo.jpg"), "photos/photo.jpg"); z.write(P("lettre.txt"), "lettre.txt"); z.write(P("contenu.docx"), "contrat.docx")
made.append("lot.zip")
with tarfile.open(P("projet.tar.gz"), "w:gz") as t:
    ti = t.gettarinfo(P("lettre.txt"), "dossier/lettre.txt"); ti.uname, ti.gname, ti.uid, ti.gid, ti.mtime = "jeanmartin", "staff", 501, 20, 1714557600
    t.addfile(ti, open(P("lettre.txt"), "rb"))
made.append("projet.tar.gz")
with open(P("dump.sql.gz"), "wb") as raw:
    with gzip.GzipFile(filename="dump_jean_2024.sql", mode="wb", fileobj=raw, mtime=1714557600) as g:
        g.write(b"SELECT 1;\n")
made.append("dump.sql.gz")

# ── Web : HTML, traduction, SVG, draw.io ─────────────────────────────────────
put("page.html", '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="author" content="Jean Martin"><meta name="generator" content="WordPress 6.4"><title>Accueil</title><!-- Created with Mobirise 5 --></head><body>Bonjour</body></html>', "w")
put("fr.po", '# Traduction francaise.\n# Jean Martin <jean@exemple.fr>, 2024.\nmsgid ""\nmsgstr ""\n"Project-Id-Version: Appli 1.0\\n"\n"Last-Translator: Jean Martin <jean@exemple.fr>\\n"\n"Language-Team: French\\n"\n"PO-Revision-Date: 2024-05-01 10:00+0200\\n"\n"X-Generator: Poedit 3.4\\n"\n\nmsgid "Hello"\nmsgstr "Bonjour"\n', "w")
put("logo.svg", '''<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!-- Created with Inkscape (http://www.inkscape.org/) -->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" xmlns:sodipodi="http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" width="100" height="100" viewBox="0 0 100 100" inkscape:version="1.3 (0e150ed, 2023-07-21)" sodipodi:docname="/home/jean/Documents/logo_perso.svg" inkscape:export-filename="/home/jean/Desktop/logo.png">
  <sodipodi:namedview id="namedview1" pagecolor="#ffffff" inkscape:current-layer="layer1"/>
  <metadata id="metadata1"><rdf:RDF><cc:Work xmlns:cc="http://creativecommons.org/ns#" rdf:about=""><dc:creator><cc:Agent><dc:title>Jean Martin</dc:title></cc:Agent></dc:creator><dc:date>2024-05-01</dc:date></cc:Work></rdf:RDF></metadata>
  <title>Logo de Jean Martin</title>
  <circle cx="50" cy="50" r="40" fill="#1f6f50"/>
  <text x="10" y="90">contact: jean.martin@exemple.fr</text>
</svg>''', "w")

img_b64 = base64.b64encode(jpg).decode()
model = ('<mxGraphModel dx="1000" dy="600" grid="1" gridSize="10" page="1" pageWidth="827" pageHeight="1169"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
         '<mxCell id="2" value="Contact : jean.martin@exemple.fr, 06 12 34 56 78 (Jean Martin)" style="rounded=0;whiteSpace=wrap;html=1;" vertex="1" parent="1"><mxGeometry x="10" y="10" width="260" height="60" as="geometry"/></mxCell>'
         '<mxCell id="3" value="" style="shape=image;aspect=fixed;image=data:image/jpeg,' + img_b64 + ';" vertex="1" parent="1"><mxGeometry x="10" y="100" width="80" height="60" as="geometry"/></mxCell>'
         '<UserObject label="Serveur 192.168.1.42" link="https://intranet.exemple.fr/jean" id="4"><mxCell style="rounded=1;" vertex="1" parent="1"><mxGeometry x="300" y="10" width="120" height="40" as="geometry"/></mxCell></UserObject>'
         '</root></mxGraphModel>')


def compress(x):
    q = urllib.parse.quote(x, safe="~()*!.'"); c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return base64.b64encode(c.compress(q.encode()) + c.flush()).decode()


agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) draw.io/24.2.5 Chrome/120.0.6099.109 Electron/28.1.0 Safari/537.36"
head = f'<mxfile host="Electron" modified="2024-05-01T10:00:00.000Z" agent="{agent}" etag="Qx7b2LmN9" version="24.2.5" type="device">'
drawio = head + '<diagram id="p1abc" name="Architecture">' + compress(model) + '</diagram></mxfile>'
put("schema.drawio", drawio, "w")
put("schema_clair.drawio", '<?xml version="1.0" encoding="UTF-8"?>\n' + head + '<diagram id="p1abc" name="Architecture">' + model + '</diagram></mxfile>', "w")
import html  # noqa: E402
put("schema.drawio.svg", '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Do not edit this file with editors other than draw.io -->\n<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="300px" height="170px" viewBox="-0.5 -0.5 300 170" content="%s"><defs/><g><text x="10" y="30">Contact : jean.martin@exemple.fr</text></g></svg>' % html.escape(drawio, quote=True), "w")
pi = PngInfo(); pi.add_text("mxfile", urllib.parse.quote(drawio))
Image.new("RGB", (120, 80), (250, 250, 250)).save(P("schema.drawio.png"), pnginfo=pi); made.append("schema.drawio.png")

# ── Photoshop (PSD minimal avec ressources EXIF, XMP, IPTC, miniature, version) ─────────────────
def res(rid, payload):
    pad = b"\0" if len(payload) % 2 else b""
    return b"8BIM" + struct.pack(">H", rid) + b"\0\0" + struct.pack(">I", len(payload)) + payload + pad
resources = (res(1058, b"Exif\0\0MM\0*\0\0\0\x08\0\0\0\0\0\0")
             + res(1060, b"<x:xmpmeta xmlns:x='adobe:ns:meta/'><rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'><rdf:Description xmlns:dc='http://purl.org/dc/elements/1.1/'><dc:creator>Jean Martin</dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>")
             + res(1028, b"\x1c\x02\x50\x00\x0bJean Martin") + res(1036, b"\0" * 28) + res(1057, b"\0\0\0\x01\x01\0\0\0\0Adobe Photoshop") + res(1005, b"\0" * 16))
psd = (b"8BPS" + struct.pack(">H", 1) + b"\0" * 6 + struct.pack(">HIIHH", 3, 2, 2, 8, 3) + struct.pack(">I", 0)
       + struct.pack(">I", len(resources)) + resources + struct.pack(">I", 0) + struct.pack(">H", 0) + bytes(range(12)))
put("design.psd", psd)

# ── Audio / vidéo (seulement avec un FFmpeg complet) ──────────────────────────
full = os.environ.get("FFMPEG_FULL") or ("/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else shutil.which("ffmpeg"))
if full:
    def ff(*args):
        subprocess.run([full, "-loglevel", "error", "-y", *args], capture_output=True)
    v = ["-f", "lavfi", "-i", "testsrc=d=1:s=64x64", "-f", "lavfi", "-i", "sine=d=1"]
    ff(*v, "-metadata", "artist=Jean Martin", "-metadata", "title=Secret", "-metadata", "location=+48.85+002.35/", P("video.mp4"))
    ff(*v, "-metadata", "artist=Jean Martin", P("video.mkv"))
    ff("-f", "lavfi", "-i", "sine=d=1", "-metadata", "artist=Jean Martin", "-metadata", "title=Secret", P("son.wav"))
    ff("-f", "lavfi", "-i", "sine=d=1", "-metadata", "artist=Jean Martin", P("son.flac"))
    ff("-f", "lavfi", "-i", "sine=d=1", "-c:a", "aac", "-metadata", "artist=Jean Martin", P("son.m4a"))
    ff("-f", "lavfi", "-i", "sine=d=1", "-c:a", "libmp3lame", "-metadata", "artist=Jean Martin", P("son.mp3"))
    made += [n for n in ("video.mp4", "video.mkv", "son.wav", "son.flac", "son.m4a", "son.mp3") if os.path.exists(P(n))]
else:
    print("(aucun FFmpeg complet trouvé : fichiers audio/vidéo non créés)")

print(f"{len(made)} fichiers de test créés dans {OUT}")
