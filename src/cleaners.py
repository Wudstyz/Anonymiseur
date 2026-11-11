"""Suppression des métadonnées, sans perte de contenu quand c'est possible.

Chaque nettoyeur reçoit les octets du fichier et renvoie (octets_nettoyés, rapport),
où rapport = {"removed": [...], "notes": [...]}.
"""
import base64
import gzip
import tarfile
import html as _html_mod
import io
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import urllib.parse
import zlib
import zipfile

MEDIA_EXT = {
    ".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".mpg", ".mpeg", ".3gp", ".flv", ".wmv",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".oga", ".opus", ".wma", ".aiff", ".aif",
}
ZIP_DOC_EXT = {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm", ".dotx", ".potx", ".xltx",
               ".odt", ".ods", ".odp", ".odg", ".epub"}


_tl = threading.local()


def set_progress(cb):
    """Fonction appelée avec (pourcentage, étape) pendant le traitement du fichier courant."""
    _tl.cb = cb


def _progress(pct, stage=None):
    cb = getattr(_tl, "cb", None)
    if cb:
        cb(pct, stage)


def new_report():
    return {"removed": [], "notes": []}


# ───────────────────────── JPEG ─────────────────────────

def _jpeg_orientation(exif):
    """Lit l'orientation dans un segment EXIF (après 'Exif\\0\\0'). 1 si absent."""
    t = exif[6:]
    if len(t) < 8 or t[:2] not in (b"II", b"MM"):
        return 1, False
    e = "<" if t[:2] == b"II" else ">"
    try:
        off = struct.unpack(e + "I", t[4:8])[0]
        n = struct.unpack(e + "H", t[off:off + 2])[0]
        orient, gps = 1, False
        for i in range(n):
            tag, _typ, _cnt, val = struct.unpack(e + "HHI4s", t[off + 2 + 12 * i: off + 14 + 12 * i])
            if tag == 0x0112:
                orient = struct.unpack(e + "H", val[:2])[0]
            elif tag == 0x8825:
                gps = True
        return orient, gps
    except struct.error:
        return 1, False


def clean_jpeg(data):
    rep = new_report()
    if data[:2] != b"\xff\xd8":
        raise ValueError("JPEG invalide")
    out = bytearray(b"\xff\xd8")
    i, orient, gps = 2, 1, False
    removed = {}
    # Pré-lecture : nombre de composantes (SOF) et transformation Adobe, pour savoir si l'APP14 est superflu.
    ncomp, adobe_tf, j = None, None, 2
    while j + 4 <= len(data) and data[j] == 0xFF:
        mk = data[j + 1]
        if mk == 0xFF:
            j += 1
            continue
        if mk == 0xDA or mk == 0xD9:
            break
        if mk in (0x01, *range(0xD0, 0xD8)):
            j += 2
            continue
        ln_ = struct.unpack(">H", data[j + 2:j + 4])[0]
        if 0xC0 <= mk <= 0xCF and mk not in (0xC4, 0xC8, 0xCC) and ncomp is None:
            ncomp = data[j + 9] if j + 9 < len(data) else None
        if mk == 0xEE and data[j + 4:j + 9] == b"Adobe" and ln_ >= 14:
            adobe_tf = data[j + 15] if j + 15 < len(data) else None
        j += 2 + ln_
    drop_adobe = ncomp == 3 and adobe_tf == 1       # YCbCr par défaut : l'APP14 n'apporte rien, sauf « fait avec Adobe »
    while i < len(data):
        if data[i] != 0xFF:
            raise ValueError("JPEG corrompu")
        m = data[i + 1]
        if m == 0xFF:
            i += 1
            continue
        if m == 0xDA:  # début des données image : on recopie tout le reste tel quel
            out += data[i:]
            break
        if m in (0x01, *range(0xD0, 0xD8)):
            out += data[i:i + 2]
            i += 2
            continue
        ln = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i + 4:i + 2 + ln]
        keep = False
        if m == 0xE0:                       # JFIF
            keep = True
        elif m == 0xE2 and seg.startswith(b"ICC_PROFILE"):  # profil colorimétrique
            keep = True
        elif m == 0xEE and seg.startswith(b"Adobe"):        # transform couleur (gardée si nécessaire aux couleurs)
            keep = not drop_adobe
        elif 0xC0 <= m <= 0xFE and m not in (0xE1, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA,
                                              0xEB, 0xEC, 0xED, 0xEF, 0xFE):
            keep = True                     # tables / cadre image
        if m == 0xE1 and seg.startswith(b"Exif\0\0"):
            orient, gps = _jpeg_orientation(seg)
        if keep:
            out += data[i:i + 2 + ln]
        else:
            name = {0xE1: "EXIF/XMP", 0xFE: "Commentaire", 0xED: "IPTC/Photoshop"}.get(m, f"APP{m - 0xE0}")
            removed[name] = removed.get(name, 0) + ln
        i += 2 + ln
    if orient not in (1, 0):
        # Sans l'orientation l'image s'afficherait couchée : on garde un EXIF minimal avec ce seul champ.
        tiff = b"MM\0*\0\0\0\x08\0\x01\x01\x12\0\x03\0\0\0\x01" + struct.pack(">H", orient) + b"\0\0\0\0\0\0"
        seg = b"Exif\0\0" + tiff
        pos = 2
        if out[2:4] == b"\xff\xe0":
            pos = 4 + struct.unpack(">H", bytes(out[4:6]))[0]
        out[pos:pos] = b"\xff\xe1" + struct.pack(">H", len(seg) + 2) + seg
        rep["notes"].append(f"Orientation ({orient}) conservée pour que l'image reste droite.")
    for k, v in removed.items():
        rep["removed"].append(f"{k} ({v} octets)")
    if gps:
        rep["removed"].insert(0, "Coordonnées GPS")
    return bytes(out), rep


# ───────────────────────── PNG ─────────────────────────

_PNG_KEEP = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP",
             b"sBIT", b"pHYs", b"bKGD", b"acTL", b"fcTL", b"fdAT"}


def clean_png(data):
    rep = new_report()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("PNG invalide")
    out, i = bytearray(data[:8]), 8
    while i < len(data):
        ln, typ = struct.unpack(">I4s", data[i:i + 8])
        end = i + 12 + ln
        if typ in _PNG_KEEP:
            out += data[i:end]
        else:
            label = {b"tEXt": "Texte", b"zTXt": "Texte", b"iTXt": "Texte/XMP", b"tIME": "Date de modification",
                     b"eXIf": "EXIF"}.get(typ, typ.decode("latin1"))
            if typ in (b"tEXt", b"zTXt", b"iTXt") and data[i + 8:i + 14] == b"mxfile":
                label = "Diagramme draw.io modifiable intégré (tout le contenu du schéma)"
                rep["notes"].append("Le diagramme draw.io intégré à ce PNG a été retiré : l'image n'est plus modifiable dans draw.io.")
            rep["removed"].append(label)
        i = end
    rep["removed"] = sorted(set(rep["removed"]))
    return bytes(out), rep


# ───────────────────────── WebP ─────────────────────────

def clean_webp(data):
    rep = new_report()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("WebP invalide")
    body, i = bytearray(), 12
    while i + 8 <= len(data):
        fourcc, ln = data[i:i + 4], struct.unpack("<I", data[i + 4:i + 8])[0]
        chunk = data[i:i + 8 + ln + (ln & 1)]
        if fourcc in (b"EXIF", b"XMP "):
            rep["removed"].append("EXIF" if fourcc == b"EXIF" else "XMP")
        else:
            if fourcc == b"VP8X":
                c = bytearray(chunk)
                c[8] &= ~(0x08 | 0x04)  # drapeaux EXIF + XMP
                chunk = bytes(c)
            body += chunk
        i += 8 + ln + (ln & 1)
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + bytes(body), rep


# ───────────────────────── GIF ─────────────────────────

def clean_gif(data):
    rep = new_report()
    if data[:3] != b"GIF":
        raise ValueError("GIF invalide")
    flags = data[10]
    i = 13 + (3 * (2 << (flags & 7)) if flags & 0x80 else 0)
    out = bytearray(data[:i])

    def blocks(j):
        k = j
        while data[k] != 0:
            k += data[k] + 1
        return k + 1

    while i < len(data):
        b = data[i]
        if b == 0x3B:
            out.append(b)
            break
        if b == 0x21:
            label, end = data[i + 1], blocks(i + 2)
            keep = label in (0xF9, 0x01)
            if label == 0xFF:
                keep = data[i + 3:i + 14] in (b"NETSCAPE2.0", b"ANIMEXTS1.0")
                if not keep:
                    rep["removed"].append("Extension d'application (XMP...)")
            elif label == 0xFE:
                rep["removed"].append("Commentaire")
            if keep:
                out += data[i:end]
            i = end
        elif b == 0x2C:
            lf = data[i + 9]
            j = i + 10 + (3 * (2 << (lf & 7)) if lf & 0x80 else 0) + 1
            end = blocks(j)
            out += data[i:end]
            i = end
        else:
            raise ValueError("GIF corrompu")
    return bytes(out), rep


# ───────────────────────── ZIP (Office, OpenDocument, EPUB) ─────────────────────────

_EMPTY_CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
               'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
               'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>')
_EMPTY_APP = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>')
_EMPTY_CUSTOM = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"/>')
_EMPTY_ODF_META = ('<?xml version="1.0" encoding="UTF-8"?>'
                   '<office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
                   'office:version="1.2"><office:meta/></office:document-meta>')
_ZIP_REPLACE = {
    "docProps/core.xml": (_EMPTY_CORE, "Auteur, dates, titre (core.xml)"),
    "docProps/app.xml": (_EMPTY_APP, "Société, application, durée d'édition (app.xml)"),
    "docProps/custom.xml": (_EMPTY_CUSTOM, "Propriétés personnalisées"),
    "meta.xml": (_EMPTY_ODF_META, "Métadonnées OpenDocument"),
}
_ZIP_DROP = {"docProps/thumbnail.jpeg", "docProps/thumbnail.png", "Thumbnails/thumbnail.png"}


_RSID_ATTR = re.compile(r'\s+w:rsid[A-Za-z]*="[^"]*"')
_RSIDS_BLOCK = re.compile(r"<w:rsids>.*?</w:rsids>", re.S)
_W_AUTHOR = re.compile(r'(\bw:author=")[^"]*(")')
_W_INITIALS = re.compile(r'\s+w:initials="[^"]*"')
_W_DATE = re.compile(r'\s+w:date="[^"]*"')
_DATE_UTC = re.compile(r'\s+w16cex:dateUtc="[^"]*"')
_ABSPATH = re.compile(r"<mc:AlternateContent[^>]*>\s*<mc:Choice[^>]*>\s*<x15ac:absPath[^>]*/>\s*</mc:Choice>\s*"
                      r"</mc:AlternateContent>", re.S)
_XL_AUTHOR = re.compile(r"<author>[^<]*</author>")
_PERSON_ATTR = re.compile(r'\b(displayName|userId|providerId)="[^"]*"')
_PPT_AUTHOR = re.compile(r'(<p:cmAuthor\b[^>]*?\b)(name|initials)="[^"]*"')
_ODF_TAGS = [re.compile(p) for p in (r"<dc:creator>[^<]*</dc:creator>", r"<dc:date>[^<]*</dc:date>",
                                      r"<meta:creator-initials>[^<]*</meta:creator-initials>")]
_OFFICE_XML = re.compile(r"^(word|xl|ppt)/.*\.xml$|^(?:.+/)?(content|styles)\.xml$")


def deep_office_xml(name, raw):
    """Retire d'un XML Office/ODF les traces d'édition. Renvoie (octets, étiquettes de ce qui a été retiré)."""
    if not _OFFICE_XML.match(name):
        return raw, set()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, set()
    found, new = set(), text

    def sub(rx, repl, label):
        nonlocal new
        new2, n = rx.subn(repl, new)
        if n:
            new, _ = new2, found.add(label)

    sub(_RSID_ATTR, "", "Identifiants de session d'édition (rsid)")
    sub(_RSIDS_BLOCK, "", "Identifiants de session d'édition (rsid)")
    sub(_W_AUTHOR, r"\1Auteur\2", "Noms des auteurs de commentaires et modifications")
    sub(_W_INITIALS, "", "Initiales des auteurs")
    sub(_W_DATE, "", "Dates des commentaires et modifications")
    sub(_DATE_UTC, "", "Dates des commentaires et modifications")
    sub(_ABSPATH, "", "Chemin du fichier sur votre disque (absPath)")
    if name.startswith("xl/"):
        sub(_XL_AUTHOR, "<author>Auteur</author>", "Noms des auteurs de commentaires")
        if "person" in name:
            sub(_PERSON_ATTR, lambda m: f'{m.group(1)}="Auteur"', "Identités des collaborateurs")
    if name.startswith("ppt/"):
        sub(_PPT_AUTHOR, lambda m: f'{m.group(1)}{m.group(2)}="Auteur"', "Noms des auteurs de commentaires")
    if name == "word/people.xml":
        new = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml"/>')
        found.add("Identités des collaborateurs")
    if name.rsplit("/", 1)[-1] in ("content.xml", "styles.xml"):
        for rx in _ODF_TAGS:
            sub(rx, "", "Auteurs et dates des annotations")
    if new == text:
        return raw, set()
    try:  # on ne garde la modification que si le XML reste valide
        import xml.etree.ElementTree as ET
        ET.fromstring(new.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return raw, set()
    return new.encode("utf-8"), found


def clean_zip(data, depth=0):
    rep = new_report()
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            name = info.filename
            if name in _ZIP_DROP:
                rep["removed"].append("Miniature d'aperçu")
                continue
            content = src.read(name)
            key = name if name in _ZIP_REPLACE else ("meta.xml" if name.endswith("/meta.xml") else None)
            if key:
                content = _ZIP_REPLACE[key][0].encode()
                lab = _ZIP_REPLACE[key][1] + (" d'un objet embarqué" if "/" in name else "")
                if lab not in rep["removed"]:
                    rep["removed"].append(lab)
            elif depth == 0 and not info.is_dir() and os.path.splitext(name)[1].lower() in (".docx", ".xlsx", ".pptx") \
                    and "/embeddings/" in name:
                try:                      # classeur / document Office embarqué : il a ses propres propriétés
                    sub, sub_rep = clean_zip(content, depth=1)
                    content = sub
                    rep["removed"].append("Propriétés d'un document Office embarqué (" + os.path.basename(name) + ")")
                except Exception:  # noqa: BLE001
                    pass
            elif depth == 0 and not info.is_dir():
                content, found = deep_office_xml(name, content)
                for label in sorted(found):
                    if label not in rep["removed"]:
                        rep["removed"].append(label)
                # nettoie aussi les images embarquées (photos collées dans un document)
                try:
                    sub, sub_rep = clean_bytes(content, name, depth + 1, embedded=True)
                    if sub_rep["removed"]:
                        rep["removed"].append(f"{os.path.basename(name)} : " + ", ".join(sub_rep["removed"]))
                    content = sub
                except Exception:
                    pass
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr & 0xFFFF0000
            dst.writestr(zi, content)
    rep["notes"].append("Les noms écrits dans le texte du document, et les polices embarquées éventuelles, ne sont pas modifiés.")
    return buf.getvalue(), rep


# ───────────────────────── PDF ─────────────────────────

def clean_pdf(data, flat=False):
    rep = new_report()
    if flat:
        res = flatten_pdf(data)
        if res:
            data = res[0]
            rep["removed"].append("Pages redessinées en images (polices, calques et structure interne supprimés)")
            rep["notes"].append("PDF aplati : le texte n'est plus sélectionnable.")
        else:
            rep["notes"].append("Aplatissement du PDF indisponible (outil absent) : PDF nettoyé normalement.")
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        raise RuntimeError("pypdf manquant (lancez ./lancer.command)")
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("PDF chiffré : déverrouillez-le d'abord")
    info = reader.metadata or {}
    if info:
        rep["removed"].append("Infos document (" + ", ".join(k.lstrip("/") for k in info.keys()) + ")")
    if reader.trailer["/Root"].get("/Metadata") is not None:
        rep["removed"].append("XMP")
    writer = PdfWriter()
    n_annots = n_images = 0
    for page in reader.pages:
        page.pop("/Metadata", None)
        page.pop("/PieceInfo", None)
        try:
            for ref in page.get("/Annots") or []:
                a = ref.get_object()
                if a.get("/Subtype") != "/Widget":
                    for k in ("/T", "/M", "/CreationDate", "/Subj", "/RC"):
                        if a.pop(k, None) is not None:
                            n_annots += 1
            xobj = (page.get("/Resources") or {}).get("/XObject") or {}
            for ref in xobj.values():
                x = ref.get_object()
                x.pop("/Metadata", None)
                x.pop("/PieceInfo", None)
                f = x.get("/Filter")
                f = f[0] if isinstance(f, list) and f else f
                if x.get("/Subtype") == "/Image" and f == "/DCTDecode" and hasattr(x, "_data"):
                    cleaned, jrep = clean_jpeg(bytes(x._data))
                    if jrep["removed"]:
                        x._data = cleaned
                        n_images += 1
        except Exception:  # noqa: BLE001
            pass
        writer.add_page(page)
    if n_annots:
        rep["removed"].append("Auteurs et dates des annotations")
    if n_images:
        rep["removed"].append(f"EXIF/GPS de {n_images} image(s) embarquée(s)")
    writer.add_metadata({})
    writer._info = None  # aucun dictionnaire /Info
    buf = io.BytesIO()
    writer.write(buf)
    out = buf.getvalue()
    # Le moteur d'écriture ajoute /Producer : on retire toute trace restante.
    out = re.sub(rb"/Producer\s*\((?:[^()\\]|\\.)*\)", b"", out)
    out = re.sub(rb"/(Creator|Author|Title|Subject|Keywords|CreationDate|ModDate)\s*\((?:[^()\\]|\\.)*\)", b"", out)
    rep["notes"].append("Le texte visible du document (noms, adresses, dates écrites dedans) n'est pas modifié.")
    return out, rep


# ───────────────────────── Audio / vidéo (ffmpeg) ─────────────────────────

def clean_media(data, ext):
    rep = new_report()
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg manquant (brew install ffmpeg)")
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in" + ext), os.path.join(d, "out" + ext)
        with open(src, "wb") as f:
            f.write(data)
        codec = ""
        fp = shutil.which("ffprobe")
        if fp:
            codec = subprocess.run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name",
                                    "-of", "csv=p=0", src], capture_output=True, text=True).stdout.strip()
        bsf = {"h264": "filter_units=remove_types=6", "hevc": "filter_units=remove_types=39|40"}.get(codec)
        cmd = [ff, "-y", "-loglevel", "error", "-i", src,
               "-map", "0:v?", "-map", "0:a?", "-map", "0:s?",
               "-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1",
               "-map_chapters", "-1", "-c", "copy",
               "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
        if bsf:
            cmd += ["-bsf:v", bsf]
            rep["removed"].append("Signature de l'encodeur vidéo dans le flux (x264/x265 et ses réglages)")
        if ext in (".mp3",):
            cmd += ["-write_id3v2", "0", "-write_xing", "0"]
        cmd.append(dst)
        duration = 0.0
        if fp:
            try:
                duration = float(subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                                                capture_output=True, text=True).stdout.strip() or 0)
            except ValueError:
                pass
        proc = subprocess.Popen(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        tail = []
        for line in proc.stdout:
            if line.startswith("out_time_us=") and duration:
                try:
                    _progress(10 + 70 * min(1.0, int(line.split("=")[1]) / 1e6 / duration), "Nettoyage de la vidéo")
                except ValueError:
                    pass
            elif "=" not in line:
                tail.append(line)
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg : " + "".join(tail).strip()[-300:])
        with open(dst, "rb") as f:
            out = f.read()
    rep["removed"] = ["Tags globaux et par piste (date, GPS, appareil, logiciel…)", "Chapitres"] + rep["removed"]
    return out, rep


# ───────────────────────── Autres formats via exiftool (si installé) ─────────────────────────

_ET_EXTRA = ["-Make=", "-Model=", "-Software=", "-ModifyDate=", "-CreateDate=", "-DateTimeOriginal=", "-Artist=",
             "-Copyright=", "-ImageDescription=", "-HostComputer=", "-DocumentName=", "-GPS:all="]
_ET_SENSITIVE = ("Make", "Model", "Software", "DateTime", "Artist", "Copyright", "GPSLatitude", "GPSLongitude",
                 "SerialNumber", "CreateDate", "ModifyDate", "DateTimeOriginal", "Creator", "Author", "OwnerName")


def clean_with_exiftool(data, ext):
    rep = new_report()
    et = shutil.which("exiftool")
    if not et:
        return None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f" + ext)
        with open(p, "wb") as f:
            f.write(data)
        kind = subprocess.run([et, "-s3", "-FileType", p], capture_output=True, text=True).stdout.strip()
        if not kind:
            return None          # exiftool ne reconnaît pas ce format
        # -all= ne peut pas vider l'IFD0 des formats basés sur TIFF (TIFF, DNG, RAW) : on y efface les champs à la main.
        subprocess.run([et, "-m", "-all=", *_ET_EXTRA, "-overwrite_original", "-q", "-q", p],
                       capture_output=True, text=True)
        chk = subprocess.run([et, "-j", "-a", "-G0:1", p], capture_output=True, text=True)
        try:
            import json as _json
            tags = _json.loads(chk.stdout)[0]
        except Exception:  # noqa: BLE001
            return None
        left = sorted({k.split(":")[-1] for k in tags if k.split(":")[-1] in _ET_SENSITIVE})
        with open(p, "rb") as f:
            out = f.read()
    rep["removed"] = ["Métadonnées (exiftool)"]
    if left:
        rep["notes"].append("Champs qui n'ont pas pu être effacés : " + ", ".join(left))
    return out, rep


# ───────────────────────── Routage ─────────────────────────

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis")


def _sips_to_png(data):
    """Décode un HEIC/HEIF avec l'outil intégré à macOS (sips) et renvoie du PNG."""
    sips = shutil.which("sips")
    if not sips:
        raise RuntimeError("sips introuvable")
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.heic"), os.path.join(d, "out.png")
        with open(src, "wb") as f:
            f.write(data)
        r = subprocess.run([sips, "-s", "format", "png", src, "--out", dst], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(dst):
            raise RuntimeError("Conversion HEIC impossible : " + r.stderr.strip()[-200:])
        with open(dst, "rb") as f:
            return f.read()


def clean_image_strong(data, filename=""):
    """Mode renforcé : décode puis ré-encode les pixels. Efface aussi la structure d'origine du fichier
    (tables de quantification, profil, ordre des blocs) qui peut trahir l'appareil ou le logiciel.
    HEIC/HEIF → JPEG, TIFF → PNG (sans perte)."""
    rep = new_report()
    from PIL import Image, ImageCms, ImageOps
    ext = os.path.splitext(filename)[1].lower()
    target, converted = None, False
    if data[4:8] == b"ftyp" and data[8:12] in _HEIF_BRANDS:
        data, target, converted = _sips_to_png(data), "JPEG", True
    im = Image.open(io.BytesIO(data))
    fmt = im.format
    if fmt == "TIFF" and ext in (".tif", ".tiff"):
        target, converted = "PNG", True
    elif target is None and fmt not in ("JPEG", "PNG", "WEBP"):
        return None
    if getattr(im, "is_animated", False):
        return None
    icc = im.info.get("icc_profile")
    im.load()
    im = ImageOps.exif_transpose(im)  # l'orientation est appliquée aux pixels : plus besoin d'EXIF
    if icc:
        try:  # conserve l'apparence des couleurs en passant en sRGB
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            im = ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"),
                                           outputMode=im.mode if im.mode in ("RGB", "RGBA") else "RGB")
        except Exception:  # noqa: BLE001
            pass
    out_fmt = target or fmt
    buf = io.BytesIO()
    if out_fmt == "JPEG":
        im.convert("RGB").save(buf, "JPEG", quality=92, optimize=True, subsampling=2)
    elif out_fmt == "PNG":
        try:
            im.save(buf, "PNG", optimize=True)
        except Exception:  # noqa: BLE001
            buf, out_fmt = io.BytesIO(), "JPEG"
            im.convert("RGB").save(buf, "JPEG", quality=92, optimize=True, subsampling=2)
    else:
        im.save(buf, "WEBP", quality=92, method=4)
    if converted:
        rep["new_ext"] = ".jpg" if out_fmt == "JPEG" else ".png"
        rep["notes"].append(f"Format converti en {out_fmt} pour repartir d'un fichier entièrement neuf.")
    rep["removed"].append("Image entièrement ré-encodée : structure d'origine, tables de compression et profil effacés")
    rep["notes"].append("Mode renforcé : l'image est redessinée, donc légèrement recompressée. Le bruit du capteur et un "
                        "éventuel filigrane invisible d'IA restent.")
    rep["strong"] = True
    return buf.getvalue(), rep


_CONTENT_NOTE = ("Traces dans le contenu lui-même, non effaçables par un simple nettoyage : bruit propre au capteur de "
                 "l'appareil, filigrane invisible d'IA (ex. SynthID), réglages de compression.")


def clean_bytes(data, filename, depth=0, embedded=False, strong=False, flat=False, content=None, meta=True):
    """Point d'entrée. `meta` : effacer les métadonnées ; `content` : masquer le contenu
    ({"cats": [...], "terms": [...], "names": [...]}) ; `strong` / `flat` : modes renforcés images / PDF."""
    opts = {"strong": strong, "flat": flat, "content": content, "meta": meta}
    pre = new_report()
    work = data
    if content and not embedded and depth <= 1 and os.path.splitext(filename)[1].lower() != ".zip":
        _progress(20, "Masquage du contenu")
        work, pre = redact_file(data, filename, content)
        if pre.get("flattened"):
            opts["flat"] = False
    if not meta:
        pre["notes"].append("Métadonnées conservées (option désactivée).")
        pre["metadata_kept"] = True
        return work, pre
    _progress(30, "Nettoyage des métadonnées")
    if strong and not embedded:
        try:
            res = clean_image_strong(work, filename)
        except Exception:  # noqa: BLE001
            res = None
        if res:
            return _merge(res, pre)
    out, rep = _route(work, filename, depth, embedded, opts)
    if not embedded and not rep.get("unsupported") and depth == 0 and \
            (data[:2] == b"\xff\xd8" or data[:8] == b"\x89PNG\r\n\x1a\n" or data[8:12] == b"WEBP"
             or os.path.splitext(filename)[1].lower() in MEDIA_EXT):
        rep["notes"].append(_CONTENT_NOTE)
    return _merge((out, rep), pre)


def _merge(res, pre):
    out, rep = res
    rep["removed"] = pre.get("removed", []) + rep["removed"]
    notes = rep["notes"]
    if pre.get("redacted"):
        notes = [n for n in notes if not n.startswith("Le texte visible du document")]
    rep["notes"] = pre.get("notes", []) + notes
    for k in ("redacted", "flattened", "content_unsupported"):
        if pre.get(k):
            rep[k] = pre[k]
    if pre.get("redacted") and rep.get("unsupported"):
        rep["unsupported"] = False
    return out, rep


def _route(data, filename, depth=0, embedded=False, opts=None):
    opts = opts or {}
    ext = os.path.splitext(filename)[1].lower()
    if data[:2] == b"\xff\xd8":
        return clean_jpeg(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return clean_png(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return clean_webp(data)
    if data[:3] == b"GIF":
        return clean_gif(data)
    if embedded:
        return data, new_report()
    if data[:5] == b"%PDF-":
        return clean_pdf(data, opts.get("flat", False))
    if ext in ZIP_DOC_EXT and zipfile.is_zipfile(io.BytesIO(data)):
        return clean_zip(data)
    if ext == ".zip" and zipfile.is_zipfile(io.BytesIO(data)):
        return clean_archive(data, depth, opts)
    if is_drawio(data):
        return clean_drawio(data)
    if is_svg(data, ext):
        return clean_svg(data)
    if data[:4] == b"8BPS":
        return clean_psd(data)
    if data[:2] == b"\x1f\x8b":
        return clean_gzip(data, filename, depth, opts)
    if ext == ".tar" or _is_tar(data):
        return clean_tar(data, depth, opts)
    if ext in (".html", ".htm", ".xhtml"):
        return clean_html(data)
    if ext in (".po", ".pot"):
        return clean_po(data)
    av = ext if ext in MEDIA_EXT else sniff_av(data)
    if av:
        return clean_media(data, av)
    if ext in PASSTHROUGH_EXT:
        rep = new_report()
        rep["passthrough"] = True
        rep["notes"].append("Ce type de fichier (code, texte, police, traduction…) ne contient pas de métadonnées personnelles : "
                            "copié tel quel. Son texte peut en revanche contenir des noms ou e-mails (bouton « Masquer »).")
        return data, rep
    if ext in UNSUPPORTED_MSG:
        rep = new_report()
        rep["unsupported"] = True
        rep["notes"].append(UNSUPPORTED_MSG[ext])
        return data, rep
    res = clean_with_exiftool(data, ext)
    if res:
        return res
    rep = new_report()
    rep["notes"].append(
        "Format non géré en natif : le contenu n'a pas été modifié. Installez exiftool "
        "(brew install exiftool) pour couvrir TIFF, HEIC, RAW, etc.")
    rep["unsupported"] = True
    return data, rep


def clean_archive(data, depth, opts):
    """ZIP quelconque : nettoie chaque fichier qu'il contient, remet à zéro les dates internes."""
    rep = new_report()
    cleaned, kept = 0, []
    buf = io.BytesIO()
    try:
        if any(i.flag_bits & 0x1 for i in zipfile.ZipFile(io.BytesIO(data)).infolist()):
            raise ValueError("Archive ZIP protégée par un mot de passe : extrayez-la d'abord, puis anonymisez son contenu.")
    except zipfile.BadZipFile as e:
        raise ValueError(f"Archive ZIP inhabituelle ou abîmée, non traitée ({str(e)[:60]}).")
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            try:
                name, content = info.filename, b"" if info.is_dir() else src.read(info.filename)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as e:
                raise ValueError(f"Archive ZIP inhabituelle ou protégée, non traitée ({str(e)[:60]}).")
            if not info.is_dir():
                if depth >= 2:
                    kept.append(name)
                else:
                    try:
                        out_c, r = clean_bytes(content, name, depth=depth + 1, **opts)
                        if r.get("unsupported"):
                            kept.append(name)
                        else:
                            content, cleaned = out_c, cleaned + 1
                            if r.get("new_ext"):
                                name = os.path.splitext(name)[0] + r["new_ext"]
                    except Exception:  # noqa: BLE001
                        kept.append(name)
            zi = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_STORED if info.is_dir() else zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr & 0xFFFF0000
            dst.writestr(zi, content)
    rep["removed"] = [f"{cleaned} fichier(s) de l'archive nettoyé(s)", "Dates internes de l'archive remises à zéro"]
    if kept:
        rep["notes"].append(f"{len(kept)} fichier(s) de l'archive n'ont pas pu être nettoyés et restent tels quels : "
                            + ", ".join(kept[:5]) + ("…" if len(kept) > 5 else ""))
    return buf.getvalue(), rep


# ───────────────────────── Inspection (avant / après) ─────────────────────────

_SENSITIVE_GROUPS = ("GPS", "XMP", "IPTC", "MakerNotes", "Ducky", "Apple", "Canon", "Nikon",
                     "Sony", "Samsung", "Pentax", "Olympus", "Panasonic", "FujiFilm", "Leica", "Google")
_SENSITIVE_RE = re.compile(
    r"(date|gps|make|model|software|author|artist|creator|producer|title|subject|keyword|description|comment|"
    r"copyright|serial|owner|lens|location|latitude|longitude|altitude|encoder|application|company|manager|"
    r"lastmodifiedby|lastsavedby|revision|thumbnail|preview|credit|byline|caption|userid|uuid|documentid|"
    r"instanceid|originaldocument|hostcomputer|camera|device|lastprinted|template|totaltime|edittime|category|"
    r"photographer|imageuniqueid|timezone|offsettime|history|derivedfrom|toolkit|lensid|firmware|writername|readername|"
    r"iptcdigest|copyrightflag|photoshopthumbnail)", re.I)
_IGNORED_GROUPS = {"System", "ExifTool", "File", "Composite", "ICC_Profile", "JFIF", "Photoshop_Thumb"}


def _ignored(group):
    return group in _IGNORED_GROUPS or group.startswith("ICC")
# Dates « vides » ou neutres laissées par les formats eux-mêmes : ne révèlent rien.
_TECHNICAL_TAGS = {"GlobalAltitude", "GlobalAngle", "CopyrightFlag", "TitlesOfParts", "HeadingPairs", "User-definedValue-type", "DCTEncodeVersion", "APP14Flags0",
                   "APP14Flags1", "ColorTransform", "DocSecurity", "ScaleCrop", "LinksUpToDate", "SharedDoc",
                   "HyperlinksChanged", "PreviewTime", "PreviewDuration", "HandlerDescription", "SampleGroupDescription", "TimeScale",
                   "MediaTimeScale", "SelectionTime", "SelectionDuration", "PosterTime", "CurrentTime"}
_NEUTRAL_DATE = re.compile(r"^(0000:00:00|1980:01:01|1904:01:01|1970:01:01|0000-00-00)")


def inspect(data, filename):
    """Liste les métadonnées d'un fichier via exiftool.

    Renvoie {"items": [{"group","tag","value"}...], "technical": n} ou None si exiftool est absent.
    "items" = métadonnées pouvant identifier ou situer quelqu'un ; "technical" = dimensions, codec, etc.
    """
    ext = os.path.splitext(filename)[1].lower()
    if is_drawio(data) or is_svg(data, ext):
        return inspect_xml_doc(data, ext)
    if data[:2] == b"\x1f\x8b" or ext == ".tar" or _is_tar(data):
        return inspect_archive(data)
    if ext in (".html", ".htm", ".xhtml") or ext in (".po", ".pot"):
        return inspect_text_meta(data, ext)
    if ext in PASSTHROUGH_EXT and ext not in (".html", ".htm"):
        return {"items": [], "technical": 0, "all": []}
    et = shutil.which("exiftool")
    if not et:
        return None
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f" + ext)
        with open(p, "wb") as f:
            f.write(data)
        r = subprocess.run([et, "-j", "-a", "-u", "-G1", "-m", p], capture_output=True, text=True)
    try:
        import json as _json
        raw = _json.loads(r.stdout)[0]
    except Exception:  # noqa: BLE001
        return {"items": [], "technical": 0, "all": []}
    items, technical, every = [], 0, []
    for key, val in raw.items():
        if key == "SourceFile" or ":" not in key:
            continue
        group, tag = key.split(":", 1)
        if _ignored(group):
            continue
        if isinstance(val, list):
            val = ", ".join(str(v) for v in val)
        val = re.sub(r"\(Binary data (\d+) bytes.*\)", r"(données binaires, \1 octets)", str(val))
        if len(val) > 140:
            val = val[:137] + "…"
        every.append((group, tag, val))
        sensitive = group.startswith(_SENSITIVE_GROUPS) or bool(_SENSITIVE_RE.search(tag))
        if tag in _TECHNICAL_TAGS:
            sensitive = False
        if sensitive and _NEUTRAL_DATE.match(val):
            sensitive = False
        if sensitive and val.strip() in ("", "0", "und", "unknown"):
            sensitive = False
        if sensitive:
            items.append({"group": group, "tag": tag, "value": val})
        else:
            technical += 1
    if data[:8] == b"\x89PNG\r\n\x1a\n" and re.search(rb"(?:tEXt|iTXt|zTXt)mxfile\x00", data):
        items.append({"group": "PNG", "tag": "Diagramme draw.io intégré", "value": "tout le contenu du schéma est embarqué dans l'image"})
    return {"items": items, "technical": technical, "all": every}


# ───────────────────────── Origine : appareil, logiciel, auteur, IA ─────────────────────────

_AI_NAMES = re.compile(
    r"(stable[ \-_]?diffusion|midjourney|dall[\-·. _]?e|firefly|openai|chat-?gpt|gemini|imagen|comfy-?ui|"
    r"automatic1111|a1111|invoke-?ai|leonardo\.?ai|dreamstudio|sdxl|novelai|flux\b|runway|sora\b|kling|"
    r"synthid|ideogram|copilot designer|bing image creator|made with ai|ai[- ]generated|generative (ai|fill))", re.I)
_AI_FIELDS = {"parameters", "prompt", "negativeprompt", "workflow", "sampler", "cfgscale", "seed", "aisystemused",
              "aipromptinformation", "aipromptwriterName".lower(), "generationparameters"}
_PICK = [  # (libellé, tags, groupes exclus)
    ("Appareil", ("Make", "Model", "HostComputer", "LensModel", "LensMake", "DeviceManufacturer", "DeviceModelName"), ()),
    ("N° de série", ("SerialNumber", "BodySerialNumber", "InternalSerialNumber", "LensSerialNumber", "CameraSerialNumber"), ()),
    ("Logiciel", ("Software", "CreatorTool", "Producer", "Application", "Encoder", "ClaimGenerator", "Generator",
                  "ProgramName", "WriterName", "Host", "Agent", "AppVersion"), ()),
    ("Auteur", ("Artist", "Author", "LastModifiedBy", "OwnerName", "Photographer", "Byline", "Copyright", "Publisher",
                "Rights", "Company", "Manager", "Credit"), ()),
    ("Date de création", ("CreateDate", "DateTimeOriginal", "DateCreated", "CreationDate", "MediaCreateDate",
                          "TrackCreateDate"), ()),
    ("Dernière modification", ("ModifyDate", "MetadataDate", "LastModifiedDate", "MediaModifyDate"), ()),
    ("Lieu", ("GPSPosition", "GPSLatitude", "GPSLongitude", "LocationInformation", "City", "Country", "Location"), ()),
]


def origin(info, data):
    """Résume ce que les métadonnées disent sur l'origine du fichier. `info` = résultat de inspect()."""
    out = {"fields": [], "ai": [], "ai_checked": bool(info)}
    if not info:
        return out
    seen = set()
    for label, tags, _ in _PICK:
        vals = []
        for group, tag, val in info["all"]:
            if tag in tags and val and not _NEUTRAL_DATE.match(val) and str(val).strip() not in ("0", "und"):
                if tag == "Creator" and not group.startswith("XMP"):
                    continue
                vals.append(f"{val}" if label != "Appareil" else f"{tag} : {val}")
        vals = [v for v in dict.fromkeys(vals)][:4]
        if vals:
            out["fields"].append({"label": label, "value": " · ".join(vals)})
    # Creator : logiciel dans un PDF, auteur dans un document XMP/Office
    for group, tag, val in info["all"]:
        if tag == "Creator" and val and not _NEUTRAL_DATE.match(val):
            lab = "Logiciel" if group == "PDF" else "Auteur"
            for f in out["fields"]:
                if f["label"] == lab:
                    if val not in f["value"]:
                        f["value"] += " · " + val
                    break
            else:
                out["fields"].append({"label": lab, "value": val})
    # IA
    reasons = []
    if b"c2pa" in data[:4_000_000] or b"jumb" in data[:4_000_000]:
        reasons.append("Signature numérique C2PA (« Content Credentials ») présente")
    for group, tag, val in info["all"]:
        v = str(val)
        if "algorithmicmedia" in v.replace(" ", "").lower():
            reasons.append(f"Mention « média généré par algorithme » ({tag})")
        elif tag.lower() in _AI_FIELDS and len(v) > 2:
            reasons.append(f"Paramètres de génération stockés dans le champ {tag}")
        elif len(v) < 3000 and _AI_NAMES.search(v) and tag not in ("FileName",):
            m = _AI_NAMES.search(v).group(1)
            reasons.append(f"Nom d'outil d'IA « {m} » dans {tag}")
    out["ai"] = list(dict.fromkeys(reasons))
    return out


# ───────────────────────── Contrôle de fuite ─────────────────────────

_LEAK_SKIP_TAGS = re.compile(r"(date|time|gps|latitude|longitude|altitude|ref$|orientation|rating|revision|"
                             r"thumbnail|preview|version)", re.I)
_LEAK_STOP = {"apple", "canon", "sony", "nikon", "north", "south", "east", "west", "none", "unknown", "adobe",
              "google", "samsung", "microsoft", "windows", "macintosh", "yes", "true", "false", "auteur"}


def _haystack(data, filename):
    """Octets dans lesquels chercher : le fichier tel quel + le contenu décompressé (zip, flux PDF)."""
    limit = 64 * 1024 * 1024
    parts = [data if len(data) <= limit else data[:limit // 2] + data[-limit // 2:]]
    try:
        if is_drawio(data) or is_svg(data, os.path.splitext(filename)[1].lower()):
            t = data.decode("utf-8-sig", "replace")
            m = re.search(r'\scontent="([^"]*)"', t)
            if m:
                t += "\n" + _html_mod.unescape(m.group(1))
            parts.append(_inline_pages(t).encode("utf-8"))
        elif zipfile.is_zipfile(io.BytesIO(data)):
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist()[:2000]:
                    if not n.endswith("/"):
                        parts.append(z.read(n)[:limit])
        elif data[:5] == b"%PDF-":
            import zlib
            for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
                try:
                    parts.append(zlib.decompress(m.group(1)))
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass
    return b"\n".join(parts)


def leak_check(info_before, cleaned, filename):
    """Cherche dans le fichier nettoyé chaque valeur textuelle identifiante qu'il contenait avant."""
    if not info_before:
        return None
    wanted = {}
    for group, tag, val in info_before.get("all", []):
        if _LEAK_SKIP_TAGS.search(tag) or _ignored(group) or tag in _TECHNICAL_TAGS:
            continue
        sensitive = group.startswith(_SENSITIVE_GROUPS) or _SENSITIVE_RE.search(tag)
        if not sensitive:
            continue
        v = str(val).strip()
        candidates = [v] + [p.strip() for p in re.split(r"[;,]", v) if len(p.strip()) >= 5]
        for c in candidates:
            if len(c) >= 4 and c.lower() not in _LEAK_STOP and not _NEUTRAL_DATE.match(c) \
                    and not c.startswith("(") and not re.fullmatch(r"[\d .:+\-/]+", c):
                wanted.setdefault(c, tag)
    hay = _haystack(cleaned, filename)
    hay_l = hay.lower()
    found = []
    for value, tag in wanted.items():
        needles = {value.lower().encode("utf-8"), value.lower().encode("utf-16-le"), value.lower().encode("utf-16-be")}
        if any(n and n in hay_l for n in needles):
            found.append({"tag": tag, "value": value if len(value) <= 80 else value[:77] + "…"})
    return {"checked": len(wanted), "found": found}


# ───────────────────────── Identifiants dans le contenu visible ─────────────────────────

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE_FR = re.compile(r"(?<![\d.])(?:\+33|0033|0)[ .\-]?[1-9](?:[ .\-]?\d{2}){4}(?!\d)")
_PHONE_INT = re.compile(r"(?<![\w+])\+\d{1,3}[ .\-]?\(?\d{1,4}\)?(?:[ .\-]?\d{2,4}){2,4}(?!\d)")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_PATH = re.compile(r"(?:/Users/|/home/)[A-Za-z0-9._\-]+|[A-Za-z]:\\Users\\[^\\\s]+|/Volumes/[^\s/]+")
_IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d|\.\d)")
_NIR = re.compile(r"(?<!\d)[12] ?\d{2} ?(?:0[1-9]|1[0-2]) ?\d{2} ?\d{3} ?\d{3} ?\d{2}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){13,16}(?!\d)")
_TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm", ".rtf", ".log", ".tex", ".yml", ".yaml",
             ".ini", ".cfg", ".eml", ".srt", ".vtt", ".py", ".js", ".sql", ".php", ".css", ".scss", ".ts", ".tsx", ".jsx",
             ".vue", ".sh", ".conf", ".c", ".h", ".ejs", ".twig", ".po", ".pot", ".markdown", ".mjs", ".java", ".rb", ".go"}
_NAME_TAGS = ("Artist", "Author", "Creator", "LastModifiedBy", "OwnerName", "Photographer", "Company", "Manager",
              "Byline", "Credit")


def _iban_ok(s):
    s = s.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    n = int("".join(str(int(c, 36)) for c in s[4:] + s[:4]))
    return n % 97 == 1


def _luhn_ok(digits):
    if not 13 <= len(digits) <= 16:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def extract_text(data, filename):
    """Texte visible du fichier, ou None si le format n'est pas analysé."""
    ext = os.path.splitext(filename)[1].lower()
    try:
        if is_drawio(data) or is_svg(data, ext):
            return _xml_doc_text(data)
        if data[:5] == b"%PDF-":
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            if r.is_encrypted:
                return None
            return "\n".join((p.extract_text() or "") for p in r.pages[:200])[:3_000_000]
        if ext in ZIP_DOC_EXT and zipfile.is_zipfile(io.BytesIO(data)):
            out = []
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if re.match(r"^(word/(document|header\d*|footer\d*|footnotes|endnotes|comments)|ppt/(slides|notesSlides)/[^/]+|"
                                r"xl/(sharedStrings|comments\d*)|content|OEBPS/.+)\.(x?html|xml)$", n) or n == "content.xml":
                        raw = z.read(n)[:5_000_000].decode("utf-8", "ignore")
                        out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)))
            import html as _html
            return _html.unescape("\n".join(out))[:3_000_000]
        if ext in _TEXT_EXT:
            return data[:5_000_000].decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return None
    return None


def scan_content(data, filename, names=()):
    """Repère e-mails, téléphones, IBAN, chemins, noms… écrits dans le texte du fichier."""
    text = extract_text(data, filename)
    if text is None:
        return {"supported": False, "findings": [], "names": []}
    found = {}

    def add(kind, vals):
        vals = list(dict.fromkeys(v.strip() for v in vals))
        if vals:
            found[kind] = vals

    add("e-mail", _EMAIL.findall(text))
    add("numéro de téléphone", _PHONE_FR.findall(text) + _PHONE_INT.findall(text))
    add("IBAN", [m for m in _IBAN.findall(text) if _iban_ok(m)])
    add("chemin sur un disque", _PATH.findall(text))
    add("adresse IP", [m for m in _IPV4.findall(text) if not m.startswith(("0.", "127.")) and max(map(int, m.split("."))) > 20])
    add("n° de sécurité sociale", _NIR.findall(text))
    add("carte bancaire", [m for m in _CARD.findall(text) if _luhn_ok(re.sub(r"\D", "", m))])
    low = text.lower()
    hits = []
    for n in dict.fromkeys(names):
        if len(n) >= 4 and n.lower() in low:
            hits.append({"name": n, "count": low.count(n.lower())})
    return {"supported": True, "names": hits,
            "findings": [{"kind": k, "count": len(v), "examples": v[:3]} for k, v in found.items()]}


def author_names(info):
    """Noms de personnes / sociétés trouvés dans les métadonnées d'avant (pour les chercher dans le texte)."""
    out = []
    for _g, tag, val in (info or {}).get("all", []):
        if tag in _NAME_TAGS and isinstance(val, str) and 3 < len(val.strip()) < 80 and not val.strip().startswith("("):
            out.append(val.strip())
    return list(dict.fromkeys(out))


# ───────────────────────── Masquage du contenu ─────────────────────────

CONTENT_CATS = ("email", "phone", "bank", "path", "ip", "names")
_CONTENT_MEMBER = re.compile(r"^(word/(document|header\d*|footer\d*|footnotes|endnotes|comments)|ppt/(slides|notesSlides)/[^/]+|"
                             r"xl/(sharedStrings|comments\d*)|OEBPS/.+)\.(x?html|xml)$")
_XML_TEXT = re.compile(r">([^<>]+)<")
_NAME_STOP = {"microsoft", "corporation", "windows", "office", "adobe", "apple", "google", "libreoffice", "word",
              "excel", "inc.", "ltd.", "gmbh", "auteur"}


def _expand_names(names):
    out = []
    for n in names:
        out.append(n)
        out += [w for w in re.split(r"[\s,;]+", n) if len(w) >= 4 and w.lower() not in _NAME_STOP]
    return sorted(dict.fromkeys(out), key=len, reverse=True)


def _matches(text, content):
    """Renvoie [(genre, texte trouvé)] pour les catégories demandées."""
    cats = set(content.get("cats") or CONTENT_CATS)
    out = []
    if "bank" in cats:
        out += [("IBAN", m) for m in _IBAN.findall(text) if _iban_ok(m)]
        out += [("carte bancaire", m) for m in _CARD.findall(text) if _luhn_ok(re.sub(r"\D", "", m))]
        out += [("n° de sécurité sociale", m) for m in _NIR.findall(text)]
    if "email" in cats:
        out += [("e-mail", m) for m in _EMAIL.findall(text)]
    if "phone" in cats:
        out += [("numéro de téléphone", m) for m in _PHONE_FR.findall(text) + _PHONE_INT.findall(text)]
    if "path" in cats:
        out += [("chemin sur un disque", m) for m in _PATH.findall(text)]
    if "ip" in cats:
        out += [("adresse IP", m) for m in _IPV4.findall(text)
                if not m.startswith(("0.", "127.")) and max(map(int, m.split("."))) > 20]
    low = text.lower()
    if "names" in cats:
        out += [("nom d'auteur", n) for n in _expand_names(content.get("names") or []) if n.lower() in low]
    out += [("terme à masquer", t) for t in content.get("terms") or [] if t.strip() and t.lower() in low]
    return out


def _make_redactor(content):
    cats = set(content.get("cats") or CONTENT_CATS)
    counts = {}

    def hit(kind, token):
        counts[kind] = counts.get(kind, 0) + 1
        return token

    names = _expand_names(content.get("names") or []) if "names" in cats else []
    terms = [t.strip() for t in content.get("terms") or [] if t.strip()]

    def redact(text):
        if "bank" in cats:
            text = _IBAN.sub(lambda m: hit("IBAN", "[IBAN masqué]") if _iban_ok(m.group(0)) else m.group(0), text)
            text = _CARD.sub(lambda m: hit("carte bancaire", "[carte masquée]")
                             if _luhn_ok(re.sub(r"\D", "", m.group(0))) else m.group(0), text)
            text = _NIR.sub(lambda m: hit("n° de sécurité sociale", "[n° sécu masqué]"), text)
        if "email" in cats:
            text = _EMAIL.sub(lambda m: hit("e-mail", "[e-mail masqué]"), text)
        if "phone" in cats:
            for rx in (_PHONE_FR, _PHONE_INT):
                text = rx.sub(lambda m: hit("numéro de téléphone", "[téléphone masqué]"), text)
        if "path" in cats:
            text = _PATH.sub(lambda m: hit("chemin sur un disque", "[chemin masqué]"), text)
        if "ip" in cats:
            text = _IPV4.sub(lambda m: hit("adresse IP", "[IP masquée]")
                             if not m.group(0).startswith(("0.", "127.")) and max(map(int, m.group(0).split("."))) > 20
                             else m.group(0), text)
        for n in names:
            text = re.sub(re.escape(n), lambda m: hit("nom d'auteur", "[nom masqué]"), text, flags=re.I)
        for t in terms:
            text = re.sub(re.escape(t), lambda m: hit("terme à masquer", "[masqué]"), text, flags=re.I)
        return text

    return redact, counts


def _helper_path():
    for c in (os.environ.get("PDFFLAT", ""), os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdfflat")):
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def flatten_pdf(data, literals=(), dpi=150):
    """Redessine chaque page du PDF en image, en noircissant d'abord les textes donnés.
    Renvoie (octets, {texte: nombre d'occurrences noircies}) ou None si l'outil est absent."""
    exe = _helper_path()
    if not exe:
        return None
    import json as _json
    with tempfile.TemporaryDirectory() as d:
        src, dst, tf = (os.path.join(d, n) for n in ("in.pdf", "out.pdf", "terms.json"))
        with open(src, "wb") as f:
            f.write(data)
        with open(tf, "w", encoding="utf-8") as f:
            _json.dump(list(literals), f)
        r = subprocess.run([exe, src, dst, str(dpi), tf], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(dst):
            return None
        with open(dst, "rb") as f:
            out = f.read()
    try:
        counts = _json.loads(r.stdout or "{}")
    except ValueError:
        counts = {}
    return out, counts


def redact_file(data, filename, content):
    """Masque les identifiants dans le texte du fichier. Renvoie (octets, rapport)."""
    rep = new_report()
    ext = os.path.splitext(filename)[1].lower()
    if is_drawio(data) or is_svg(data, ext):
        redact, counts = _make_redactor(content)
        out = _redact_xml_doc(data, redact)
        if out is None:
            rep["notes"].append("Masquage impossible dans ce fichier (XML non reconnu) : contenu inchangé.")
            return data, rep
        rep["redacted"] = counts
        if is_drawio(data):
            rep["notes"].append("Les pages du schéma sont réécrites en XML lisible (draw.io les ouvre normalement).")
        return out, rep
    if ext in _TEXT_EXT:
        raw = data
        try:
            text, enc = raw.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            text, enc = raw.decode("latin-1"), "latin-1"
        redact, counts = _make_redactor(content)
        new = redact(text)
        rep["redacted"] = counts
        return new.encode(enc), rep
    if ext in ZIP_DOC_EXT and zipfile.is_zipfile(io.BytesIO(data)):
        redact, counts = _make_redactor(content)
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as dst:
            for info in src.infolist():
                body = src.read(info.filename)
                if _CONTENT_MEMBER.match(info.filename) or info.filename == "content.xml":
                    try:
                        text = body.decode("utf-8")
                        new = _XML_TEXT.sub(lambda m: ">" + redact(m.group(1)) + "<", text)
                        import xml.etree.ElementTree as ET
                        ET.fromstring(new.encode("utf-8"))
                        body = new.encode("utf-8")
                    except Exception:  # noqa: BLE001
                        pass
                dst.writestr(info, body)
        rep["redacted"] = counts
        rep["notes"].append("Le texte coupé en plusieurs morceaux par le traitement de texte peut échapper au masquage : "
                            "vérifiez le résultat.")
        return buf.getvalue(), rep
    if data[:5] == b"%PDF-":
        text = extract_text(data, filename) or ""
        found = _matches(text, content)
        literals = list(dict.fromkeys(m for _k, m in found))
        res = flatten_pdf(data, literals) if (literals or content.get("force_flat")) else None
        if res is None and not literals:
            rep["redacted"] = {}
            return data, rep
        if res is None:
            rep["notes"].append("Masquage du PDF indisponible (outil absent) : le contenu n'a pas été modifié.")
            return data, rep
        out, counts = res
        kinds = {}
        for k, m in found:
            kinds[k] = kinds.get(k, 0) + counts.get(m, 0)
        rep["redacted"] = {k: v for k, v in kinds.items() if v}
        missed = [m for _k, m in found if not counts.get(m)]
        rep["flattened"] = True
        rep["notes"].append("PDF redessiné en images : les passages masqués sont noircis, le texte n'est plus sélectionnable.")
        if missed:
            rep["notes"].append(f"{len(missed)} passage(s) repéré(s) dans le texte n'ont pas pu être localisés sur la page et "
                                "ne sont pas noircis : " + ", ".join(dict.fromkeys(missed[:4])) + ". Vérifiez visuellement.")
        return out, rep
    rep["content_unsupported"] = True
    rep["notes"].append("Le contenu de ce type de fichier n'est pas analysé : le texte visible dans une image ou une vidéo "
                        "n'est pas masqué (pas de reconnaissance de texte).")
    return data, rep


# ───────────────────────── Écrire des métadonnées choisies ─────────────────────────

_TEXT_KEYS = ("author", "title", "description", "copyright", "software", "make", "model")
LABELS = {"author": "Auteur", "title": "Titre", "description": "Description", "copyright": "Copyright",
          "software": "Logiciel", "make": "Marque de l'appareil", "model": "Modèle de l'appareil",
          "created": "Date de création", "gps": "Lieu (GPS)"}
# Noms de balises (tels que lus par exiftool) correspondant à chaque champ : sert à reconnaître ce que VOUS avez défini.
FIELD_TAGS = {
    "author": {"Artist", "Creator", "Author", "LastModifiedBy", "Photographer", "OwnerName", "Initial-creator", "InitialCreator"},
    "title": {"Title"},
    "description": {"ImageDescription", "Description", "Subject", "Comment", "UserComment", "Caption-Abstract"},
    "copyright": {"Copyright", "Rights", "CopyrightNotice"},
    "software": {"Software", "CreatorTool", "Application", "Producer", "Encoder", "Generator", "Creator"},
    "make": {"Make", "DeviceManufacturer"}, "model": {"Model", "DeviceModelName"},
    "created": {"CreateDate", "DateTimeOriginal", "ModifyDate", "MetadataDate", "DateCreated", "CreationDate",
                "MediaCreateDate", "TrackCreateDate", "MediaModifyDate", "TrackModifyDate", "ZipModifyDate", "DateTimeCreated",
                "Date", "Creation-date"},
    "gps": {"GPSLatitude", "GPSLongitude", "GPSLatitudeRef", "GPSLongitudeRef", "GPSPosition", "GPSCoordinates",
            "LocationInformation", "GPSAltitude", "GPSAltitudeRef"},
}
_SUPPORT = {  # champs réellement écrits selon le type de fichier
    "pdf": {"author", "title", "description", "software", "created"},
    "office": {"author", "title", "description", "software", "created"},
    "media": {"author", "title", "description", "copyright", "created", "gps"},
    "exif": set(FIELD_TAGS) ,
}


def clean_fields(f):
    """Normalise les champs saisis : ne garde que ceux qui sont remplis et valides."""
    out = {}
    for k in _TEXT_KEYS:
        v = re.sub(r"[\x00-\x1f]", " ", str(f.get(k) or "")).strip()
        if v:
            out[k] = v[:300]
    c = str(f.get("created") or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", c)
    if m:
        y, mo, d, h, mi, s = (int(x) if x else None for x in m.groups())
        if 1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            out["created"] = (y, mo, d, h if h is not None else 12, mi or 0, s or 0)
    try:
        lat, lon = float(str(f.get("lat")).replace(",", ".")), float(str(f.get("lon")).replace(",", "."))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out["gps"] = (lat, lon)
    except (TypeError, ValueError):
        pass
    return out


def tags_for(fields):
    t = set()
    for k in fields:
        t |= FIELD_TAGS.get(k, set())
    return t


def _fmt_date(t, sep=":", tsep=" ", z=""):
    y, mo, d, h, mi, s = t
    return f"{y:04d}{sep}{mo:02d}{sep}{d:02d}{tsep}{h:02d}:{mi:02d}:{s:02d}{z}"


def _set_pdf(data, f):
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(io.BytesIO(data))
    if r.is_encrypted:
        return None
    w = PdfWriter(clone_from=r)
    md = {}
    if "author" in f:
        md["/Author"] = f["author"]
    if "title" in f:
        md["/Title"] = f["title"]
    if "description" in f:
        md["/Subject"] = f["description"]
    if "software" in f:
        md["/Creator"] = md["/Producer"] = f["software"]
    if "created" in f:
        md["/CreationDate"] = md["/ModDate"] = "D:" + _fmt_date(f["created"], "", "") .replace(":", "") + "Z"
    w.add_metadata(md)
    buf = io.BytesIO()
    w.write(buf)
    out = buf.getvalue()
    if "software" not in f and not (r.metadata and r.metadata.get("/Producer")):
        out = re.sub(rb"/Producer\s*\((?:[^()\\]|\\.)*\)", b"", out)   # pypdf s'ajoute comme « Producer » : on le retire
    return out


def _xml_esc(v):
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_put(xml, root, items):
    """Remplace ou ajoute des éléments (balise, contenu) dans l'élément racine `root` d'un petit XML."""
    for tag, inner, attrs in items:
        el = f"<{tag}{attrs}>{inner}</{tag}>"
        rx = re.compile(rf"<{re.escape(tag)}\b[^>]*?(?:/>|>.*?</{re.escape(tag)}>)", re.S)
        if rx.search(xml):
            xml = rx.sub(lambda m: el, xml, count=1)
        elif re.search(rf"<{re.escape(root)}\b[^>]*/>", xml):
            xml = re.sub(rf"<{re.escape(root)}\b([^>]*)/>", lambda m: f"<{root}{m.group(1)}>{el}</{root}>", xml, count=1)
        else:
            xml = xml.replace(f"</{root}>", el + f"</{root}>", 1)
    return xml


def _set_zip(data, f):
    src = zipfile.ZipFile(io.BytesIO(data))
    names = set(src.namelist())
    buf = io.BytesIO()
    changed = False
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            body = src.read(info.filename)
            text = None
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                pass
            if info.filename == "docProps/core.xml" and text is not None:
                items = []
                if "title" in f:
                    items.append(("dc:title", _xml_esc(f["title"]), ""))
                if "author" in f:
                    items += [("dc:creator", _xml_esc(f["author"]), ""), ("cp:lastModifiedBy", _xml_esc(f["author"]), "")]
                if "description" in f:
                    items.append(("dc:description", _xml_esc(f["description"]), ""))
                if "created" in f:
                    d = _fmt_date(f["created"], "-", "T", "Z")
                    items += [("dcterms:created", d, ' xsi:type="dcterms:W3CDTF"'), ("dcterms:modified", d, ' xsi:type="dcterms:W3CDTF"')]
                if items:
                    body, changed = _xml_put(text, "cp:coreProperties", items).encode("utf-8"), True
            elif info.filename == "docProps/app.xml" and text is not None and "software" in f:
                body, changed = _xml_put(text, "Properties", [("Application", _xml_esc(f["software"]), "")]).encode("utf-8"), True
            elif info.filename == "meta.xml" and text is not None:
                items = []
                if "title" in f:
                    items.append(("dc:title", _xml_esc(f["title"]), ""))
                if "author" in f:
                    items += [("dc:creator", _xml_esc(f["author"]), ""), ("meta:initial-creator", _xml_esc(f["author"]), "")]
                if "description" in f:
                    items.append(("dc:description", _xml_esc(f["description"]), ""))
                if "software" in f:
                    items.append(("meta:generator", _xml_esc(f["software"]), ""))
                if "created" in f:
                    d = _fmt_date(f["created"], "-", "T")
                    items += [("meta:creation-date", d, ""), ("dc:date", d, "")]
                if items:
                    body, changed = _xml_put(text, "office:meta", items).encode("utf-8"), True
            zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            zi.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            zi.external_attr = info.external_attr & 0xFFFF0000
            dst.writestr(zi, body)
    return buf.getvalue() if changed else None


def _set_media(data, ext, f):
    ff = shutil.which("ffmpeg")
    if not ff:
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in" + ext), os.path.join(d, "out" + ext)
        with open(src, "wb") as fh:
            fh.write(data)
        cmd = [ff, "-y", "-loglevel", "error", "-i", src, "-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy",
               "-map_metadata", "0", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact"]
        mp = {"author": "artist", "title": "title", "description": "comment", "copyright": "copyright"}
        for k, name in mp.items():
            if k in f:
                cmd += ["-metadata", f"{name}={f[k]}"]
        if "created" in f:
            cmd += ["-metadata", "creation_time=" + _fmt_date(f["created"], "-", "T", "Z")]
        if "gps" in f:
            lat, lon = f["gps"]
            cmd += ["-metadata", f"location={lat:+08.4f}{lon:+09.4f}/"]
        cmd.append(dst)
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return None
        with open(dst, "rb") as fh:
            return fh.read()


def _set_exif(data, ext, f):
    et = shutil.which("exiftool")
    if not et:
        return None
    a = []
    if "author" in f:
        a += [f"-Artist={f['author']}", f"-XMP-dc:Creator={f['author']}"]
    if "title" in f:
        a += [f"-XMP-dc:Title={f['title']}"]
    if "description" in f:
        a += [f"-ImageDescription={f['description']}", f"-XMP-dc:Description={f['description']}"]
    if "copyright" in f:
        a += [f"-Copyright={f['copyright']}", f"-XMP-dc:Rights={f['copyright']}"]
    if "software" in f:
        a += [f"-Software={f['software']}", f"-XMP-xmp:CreatorTool={f['software']}"]
    if "make" in f:
        a += [f"-Make={f['make']}", f"-XMP-tiff:Make={f['make']}"]
    if "model" in f:
        a += [f"-Model={f['model']}", f"-XMP-tiff:Model={f['model']}"]
    if "created" in f:
        d = _fmt_date(f["created"])
        a += [f"-DateTimeOriginal={d}", f"-CreateDate={d}", f"-ModifyDate={d}"]
    if "gps" in f:
        lat, lon = f["gps"]
        a += [f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
              f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}"]
    a.append("-XMP-x:XMPToolkit=")        # exiftool signe sinon le XMP de son nom : c'est une trace de l'outil
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f" + ext)
        with open(p, "wb") as fh:
            fh.write(data)
        r = subprocess.run([et, "-m", "-overwrite_original", "-q", "-q", *a, p], capture_output=True, text=True)
        if r.returncode != 0:
            return None
        with open(p, "rb") as fh:
            return fh.read()


def set_metadata(data, filename, fields):
    """Écrit les métadonnées choisies. Renvoie (octets, rapport, champs écrits)."""
    rep = new_report()
    f = clean_fields(fields)
    if not f:
        return data, rep, {}
    ext = os.path.splitext(filename)[1].lower()
    if data[:5] == b"%PDF-":
        kind, out = "pdf", _set_pdf(data, f)
    elif ext in ZIP_DOC_EXT and zipfile.is_zipfile(io.BytesIO(data)):
        kind, out = "office", _set_zip(data, f)
    elif ext in MEDIA_EXT:
        kind, out = "media", _set_media(data, ext, f)
    else:
        kind, out = "exif", _set_exif(data, ext, f)
    if out is None:
        rep["notes"].append("Impossible d'écrire des métadonnées dans ce type de fichier : aucune n'a été définie.")
        return data, rep, {}
    ok = {k: v for k, v in f.items() if k in _SUPPORT[kind]}
    skipped = [LABELS[k] for k in f if k not in _SUPPORT[kind]]
    rep["removed"].append("Métadonnées définies par vous : " + ", ".join(LABELS[k] for k in ok))
    if skipped:
        rep["notes"].append("Non pris en charge par ce type de fichier (ignoré) : " + ", ".join(skipped) + ".")
    return out, rep, ok


# ───────────────────────── draw.io (.drawio, .dio) et SVG ─────────────────────────

_MXFILE_ATTRS = {"host": "Application hôte", "agent": "Navigateur / système / version de draw.io", "modified": "Date de modification",
                 "etag": "Identifiant d'édition", "version": "Version de draw.io", "type": "Type de stockage",
                 "scale": None, "border": None}   # None = technique, conservé
_REMOVE_MX = ("host", "agent", "modified", "etag", "version", "type")
_B64_IMG = re.compile(r"(data:image/(?:png|jpe?g|webp|gif)(?:;base64)?,)([A-Za-z0-9+/=]{80,})")


def is_drawio(data):
    head = data[:3000].decode("utf-8", "ignore").lstrip("\ufeff \t\r\n")
    head = re.sub(r"^<\?xml[^>]*\?>\s*", "", head)
    head = re.sub(r"^(<!--.*?-->\s*)+", "", head, flags=re.S)
    return head.startswith("<mxfile")


def is_svg(data, ext=""):
    if ext == ".svg":
        return True
    return b"<svg" in data[:3000] and data[:3000].lstrip()[:5] in (b"<?xml", b"<svg ", b"<!DOC", b"<!-- ")


def _drawio_decode(payload):
    """Contenu d'une page draw.io : XML direct, ou « base64(deflate(urlencode(xml))) »."""
    t = payload.strip()
    if not t or t.startswith("<"):
        return None
    try:
        return urllib.parse.unquote(zlib.decompress(base64.b64decode(t + "=" * (-len(t) % 4)), -15).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _drawio_pages(text):
    """[(début, fin, xml décodé ou None)] pour chaque <diagram>."""
    out = []
    for m in re.finditer(r"(<diagram\b[^>]*>)(.*?)(</diagram>)", text, re.S):
        out.append((m.start(2), m.end(2), _drawio_decode(m.group(2)), m.group(2)))
    return out


def _clean_images_in(xml):
    """Nettoie l'EXIF/GPS des images embarquées (data:image/...) d'un XML draw.io ou SVG. Renvoie (xml, nombre)."""
    n = 0

    def fix(m):
        nonlocal n
        try:
            raw = base64.b64decode(m.group(2) + "=" * (-len(m.group(2)) % 4))
            cleaned, r = clean_bytes(raw, "img", embedded=True)
            if r["removed"]:
                n += 1
                return m.group(1) + base64.b64encode(cleaned).decode()
        except Exception:  # noqa: BLE001
            pass
        return m.group(0)
    return _B64_IMG.sub(fix, xml), n


def _strip_mxfile_tag(text, rep):
    def fix(m):
        tag = m.group(0)
        for a in _REMOVE_MX:
            rx = re.compile(r'\s+' + a + r'="[^"]*"')
            if rx.search(tag):
                rep["removed"].append(f"{_MXFILE_ATTRS[a]} ({a})")
                tag = rx.sub("", tag)
        return tag
    return re.sub(r"<mxfile\b[^>]*>", fix, text, count=1)


def clean_drawio(data):
    rep = new_report()
    text = data.decode("utf-8-sig", "replace")
    n_comments = len(re.findall(r"<!--.*?-->", text, re.S))
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if n_comments:
        rep["removed"].append("Commentaires XML")
    text = _strip_mxfile_tag(text, rep)
    images = 0
    for start, end, xml, raw in reversed(_drawio_pages(text)):
        body = xml if xml is not None else raw
        new, n = _clean_images_in(body)
        if n:
            images += n
            text = text[:start] + new + text[end:]        # une page modifiée est réécrite en XML clair (draw.io la relit)
    if images:
        rep["removed"].append(f"EXIF/GPS de {images} image(s) embarquée(s) dans le schéma")
    rep["notes"].append("Le contenu du schéma (textes, noms, liens) n'est pas modifié : utilisez « Masquer les informations "
                        "personnelles » pour les e-mails, téléphones, etc.")
    return text.encode("utf-8"), rep


_SVG_ATTR_NS = re.compile(r'\s+(?:inkscape|sodipodi|i|sketch|serif|xmlns:(?:inkscape|sodipodi|i|sketch|serif|x|xlink_unused)):[A-Za-z\-]+="[^"]*"')
_SVG_ATTR_NS2 = re.compile(r'\s+xmlns:(?:inkscape|sodipodi|sketch|serif)="[^"]*"')


def clean_svg(data):
    rep = new_report()
    text = data.decode("utf-8-sig", "replace")
    n = len(re.findall(r"<!--.*?-->", text, re.S))
    if n:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        rep["removed"].append("Commentaires (logiciel de création, mentions)")
    for tag, label in (("metadata", "Bloc <metadata> (auteur, dates, licence, RDF)"),
                       (r"sodipodi:namedview", "Réglages Inkscape (sodipodi:namedview)"),
                       (r"i:pgf", "Données Adobe Illustrator embarquées"),
                       (r"inkscape:[A-Za-z]+", "Éléments Inkscape")):
        text, k = re.subn(rf"<({tag})\b[^>]*?(?:/>|>.*?</\1>)", "", text, flags=re.S)
        if k:
            rep["removed"].append(label)
    text, k = _SVG_ATTR_NS.subn("", text)
    if k:
        rep["removed"].append("Attributs Inkscape / Illustrator (version, chemin du fichier, exports)")
    text = _SVG_ATTR_NS2.sub("", text)
    # SVG exporté par draw.io : tout le schéma est dans l'attribut content="<mxfile ...>"
    def fix_content(m):
        inner = _html_mod.unescape(m.group(2))
        if not inner.lstrip().startswith("<mxfile"):
            return m.group(0)
        sub = new_report()
        inner = re.sub(r"<!--.*?-->", "", inner, flags=re.S)
        inner = _strip_mxfile_tag(inner, sub)
        imgs = 0
        for start, end, xml, raw in reversed(_drawio_pages(inner)):
            new, c = _clean_images_in(xml if xml is not None else raw)
            if c:
                imgs += c
                inner = inner[:start] + new + inner[end:]
        rep["removed"].extend(sub["removed"] + ([f"EXIF/GPS de {imgs} image(s) embarquée(s)"] if imgs else []))
        return m.group(1) + _html_mod.escape(inner, quote=True) + m.group(3)
    text = re.sub(r'(\scontent=")([^"]*)(")', fix_content, text, count=1)
    text, imgs = _clean_images_in(text)
    if imgs:
        rep["removed"].append(f"EXIF/GPS de {imgs} image(s) embarquée(s)")
    rep["removed"] = list(dict.fromkeys(rep["removed"]))
    rep["notes"].append("Le texte et les titres du dessin ne sont pas modifiés.")
    return text.encode("utf-8"), rep


def inspect_xml_doc(data, ext=""):
    """Métadonnées d'un fichier draw.io ou SVG (exiftool n'en voit rien). Même format que inspect()."""
    text = data.decode("utf-8-sig", "replace")
    items, tech = [], 0

    def add(group, tag, val):
        val = _html_mod.unescape(str(val)).strip()
        if val:
            items.append({"group": group, "tag": tag, "value": val if len(val) <= 140 else val[:137] + "…"})

    def mxfile_items(t):
        m = re.search(r"<mxfile\b[^>]*>", t)
        if m:
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(0)))
            for key, tag in (("host", "Host"), ("agent", "Agent"), ("modified", "ModifyDate"), ("etag", "Etag"),
                             ("version", "AppVersion"), ("type", "StorageType")):
                if key in attrs:
                    add("draw.io", tag, attrs[key])
    if is_drawio(data):
        mxfile_items(text)
        tech = len(re.findall(r"<diagram\b", text))
    else:
        for m in re.finditer(r"<!--(.*?)-->", text, re.S):
            c = m.group(1).strip()
            if re.search(r"created with|generator|exported|illustrator|inkscape|sketch", c, re.I):
                add("SVG", "Generator", c)
        for attr, tag in (("inkscape:version", "Application"), ("sodipodi:docname", "DocumentName"),
                          ("inkscape:export-filename", "ExportFilename")):
            m = re.search(attr + r'="([^"]*)"', text)
            if m:
                add("Inkscape", tag, m.group(1))
        md = re.search(r"<metadata\b.*?</metadata>", text, re.S)
        if md:
            for tag_, tag in (("dc:creator", "Creator"), ("dc:publisher", "Publisher"), ("dc:date", "CreateDate"),
                              ("dc:rights", "Rights"), ("cc:license", "License")):
                for v in re.findall(rf"<{tag_}\b[^>]*>(.*?)</{tag_}>", md.group(0), re.S):
                    add("SVG metadata", tag, re.sub(r"<[^>]+>", " ", v))
            for v in re.findall(r"<dc:title>(.*?)</dc:title>", md.group(0), re.S):
                add("SVG metadata", "Creator", re.sub(r"<[^>]+>", " ", v))
        if "<i:pgf" in text:
            add("Illustrator", "Application", "Données Adobe Illustrator embarquées")
        m = re.search(r'\scontent="([^"]*)"', text)
        if m and _html_mod.unescape(m.group(1)).lstrip().startswith("<mxfile"):
            mxfile_items(_html_mod.unescape(m.group(1)))
    return {"items": items, "technical": tech, "all": [(i["group"], i["tag"], i["value"]) for i in items]}


_DRAWIO_ATTR = re.compile(r'(\b(?:label|value|tooltip|link)=")([^"]*)(")')


def _inline_pages(text):
    """Remplace les pages draw.io compressées par leur XML en clair."""
    for start, end, xml, _raw in reversed(_drawio_pages(text)):
        if xml is not None:
            text = text[:start] + xml + text[end:]
    return text


def _xml_doc_text(data):
    text = data.decode("utf-8-sig", "replace")
    m = re.search(r'\scontent="([^"]*)"', text)
    if m and _html_mod.unescape(m.group(1)).lstrip().startswith("<mxfile"):
        text += "\n" + _html_mod.unescape(m.group(1))
    text = _inline_pages(text)
    vals = [_html_mod.unescape(v) for _a, v, _b in _DRAWIO_ATTR.findall(text)]
    plain = re.sub(r"<[^>]+>", " ", _html_mod.unescape(" ".join(vals)))
    nodes = re.sub(r"\s+", " ", " ".join(_html_mod.unescape(t) for t in _XML_TEXT_ONLY.findall(text) if t.strip()))
    return (plain + "\n" + nodes)[:3_000_000]


_XML_TEXT_ONLY = re.compile(r">([^<>]+)<")


def _redact_xml_doc(data, redact):
    """Masque les informations personnelles dans un draw.io ou un SVG. Renvoie le nouvel octets ou None."""
    text = data.decode("utf-8-sig", "replace")

    def do_drawio(t):
        t = _inline_pages(t)
        return _DRAWIO_ATTR.sub(lambda m: m.group(1) + redact(m.group(2)) + m.group(3), t)
    if is_drawio(data):
        new = do_drawio(text)
    else:
        def fix_content(m):
            inner = _html_mod.unescape(m.group(2))
            if not inner.lstrip().startswith("<mxfile"):
                return m.group(0)
            return m.group(1) + _html_mod.escape(do_drawio(inner), quote=True) + m.group(3)
        new = re.sub(r'(\scontent=")([^"]*)(")', fix_content, text, count=1)
        new = _XML_TEXT.sub(lambda m: ">" + redact(m.group(1)) + "<", new)
    try:
        import xml.etree.ElementTree as ET
        ET.fromstring(new.encode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return new.encode("utf-8")


# ───────────────────────── Formats supplémentaires ─────────────────────────

# Fichiers de développement, de texte ou de ressources : pas de métadonnées personnelles à effacer.
PASSTHROUGH_EXT = {
    ".php", ".phpt", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".css", ".scss", ".sass", ".less", ".map",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".conf", ".cfg", ".env", ".sh", ".bash", ".zsh", ".py", ".rb", ".go",
    ".rs", ".java", ".c", ".h", ".cpp", ".cs", ".swift", ".sql", ".md", ".markdown", ".txt", ".log", ".csv", ".tsv",
    ".xml", ".twig", ".ejs", ".mo", ".lgpl", ".license", ".example", ".dist", ".in", ".snap", ".lock", ".ser", ".z",
    ".ttf", ".otf", ".woff", ".woff2", ".eot", ".afm", ".ufm", ".icc", ".icm", ".bkp", ".tex", ".srt", ".vtt",
}
UNSUPPORTED_MSG = {
    ".afpub": "Format Affinity Publisher (propriétaire) : non pris en charge. Exportez en PDF ou en image, puis anonymisez l'export.",
    ".afphoto": "Format Affinity Photo (propriétaire) : non pris en charge. Exportez en image, puis anonymisez l'export.",
    ".afdesign": "Format Affinity Designer (propriétaire) : non pris en charge. Exportez en SVG, PDF ou image, puis anonymisez l'export.",
    ".indd": "Format InDesign : non pris en charge. Exportez en PDF, puis anonymisez l'export.",
    ".sketch": "Format Sketch : non pris en charge. Exportez en PDF ou SVG, puis anonymisez l'export.",
}


def sniff_av(data):
    """Reconnaît l'audio/vidéo par son contenu (une extension comme « .media » ne dit rien)."""
    h = data[:16]
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return ".wav"
    if h[:4] == b"RIFF" and h[8:12] == b"AVI ":
        return ".avi"
    if h[:4] == b"fLaC":
        return ".flac"
    if h[:4] == b"OggS":
        return ".ogg"
    if h[:4] == b"\x1aE\xdf\xa3":
        return ".mkv"
    if h[:4] == b"FORM" and h[8:12] in (b"AIFF", b"AIFC"):
        return ".aiff"
    if h[:3] == b"ID3" or (h[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        return ".mp3"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"qt  ",):
            return ".mov"
        if brand in (b"M4A ", b"M4B "):
            return ".m4a"
        if brand in (b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"M4V ", b"3gp4", b"3gp5", b"MSNV"):
            return ".mp4"
    return None


# ── PSD
_PSD_REMOVE = {1028: "IPTC", 1033: "Miniature", 1034: "Copyright", 1035: "URL", 1036: "Miniature", 1057: "Version (logiciel)",
               1058: "EXIF", 1060: "XMP", 1061: "Empreinte de légende", 1064: "Aspect des pixels", 1077: "Infos d'affichage",
               1082: "Réglages d'impression", 1083: "Réglages d'impression", 1005: "", 1011: "Impression"}
_PSD_REMOVE = {k: v for k, v in _PSD_REMOVE.items() if k not in (1005, 1064, 1077)}


def clean_psd(data):
    """Photoshop : retire dans les « ressources d'image » l'EXIF, l'XMP, l'IPTC, les miniatures et la version du logiciel."""
    rep = new_report()
    if data[:4] != b"8BPS":
        raise ValueError("PSD invalide")
    off = 26
    cm_len = struct.unpack(">I", data[off:off + 4])[0]
    off += 4 + cm_len
    ir_len = struct.unpack(">I", data[off:off + 4])[0]
    start, end = off + 4, off + 4 + ir_len
    pos, kept, gone = start, bytearray(), []
    while pos + 12 <= end and data[pos:pos + 4] == b"8BIM":
        rid = struct.unpack(">H", data[pos + 4:pos + 6])[0]
        nlen = data[pos + 6]
        name_total = 1 + nlen + ((1 + nlen) % 2)
        sz_at = pos + 6 + name_total
        size = struct.unpack(">I", data[sz_at:sz_at + 4])[0]
        blk_end = sz_at + 4 + size + (size % 2)
        if rid in _PSD_REMOVE:
            gone.append(_PSD_REMOVE[rid])
        else:
            kept += data[pos:blk_end]
        pos = blk_end
    kept += data[pos:end]
    out = data[:off] + struct.pack(">I", len(kept)) + bytes(kept) + data[end:]
    rep["removed"] = sorted({g for g in gone if g}) or ["Aucune ressource d'image à retirer"]
    rep["notes"].append("Photoshop enregistre la date de modification de chaque calque : elle est conservée (la retirer risquerait "
                        "d'abîmer le fichier). Pour l'effacer, aplatissez ou exportez le PSD en image avant de l'anonymiser. "
                        "Les noms des calques ne sont pas modifiés.")
    return out, rep


# ── gzip / tar
NEUTRAL_TS = 946684800


def _is_tar(data):
    return len(data) > 512 and data[257:262] == b"ustar"


def _gz_header(data):
    flg = data[3]
    mtime = struct.unpack("<I", data[4:8])[0]
    pos, name = 10, ""
    if flg & 4:
        pos += 2 + struct.unpack("<H", data[pos:pos + 2])[0]
    if flg & 8:
        e = data.index(b"\0", pos)
        name, pos = data[pos:e].decode("latin-1"), e + 1
    return mtime, name


def _clean_tar_bytes(inner, depth, opts, rep):
    out = io.BytesIO()
    n = 0
    with tarfile.open(fileobj=io.BytesIO(inner)) as src, tarfile.open(fileobj=out, mode="w", format=tarfile.GNU_FORMAT) as dst:
        for m in src:
            ti = tarfile.TarInfo(m.name)
            ti.mode, ti.type, ti.linkname = m.mode, m.type, m.linkname
            ti.mtime, ti.uid, ti.gid, ti.uname, ti.gname = NEUTRAL_TS, 0, 0, "", ""
            if m.isfile():
                body = src.extractfile(m).read()
                if depth < 2 and len(body) <= 100 * 1024 * 1024:
                    try:
                        cleaned, r = clean_bytes(body, m.name, depth=depth + 1, **opts)
                        if not r.get("unsupported"):
                            body = cleaned
                            n += 1
                    except Exception:  # noqa: BLE001
                        pass
                ti.size = len(body)
                dst.addfile(ti, io.BytesIO(body))
            else:
                dst.addfile(ti)
    rep["removed"].append("En-têtes de l'archive (dates, propriétaire, groupe)")
    if n:
        rep["removed"].append(f"{n} fichier(s) de l'archive nettoyé(s)")
    return out.getvalue()


def clean_tar(data, depth, opts):
    rep = new_report()
    return _clean_tar_bytes(data, depth, opts, rep), rep


def clean_gzip(data, filename, depth, opts):
    rep = new_report()
    mtime, name = _gz_header(data)
    raw = gzip.decompress(data) if len(data) <= 300 * 1024 * 1024 else None
    if raw is None:
        raise ValueError("Archive trop volumineuse pour être nettoyée (300 Mo maximum).")
    if _is_tar(raw):
        raw = _clean_tar_bytes(raw, depth, opts, rep)
    elif depth < 2:
        inner_name = filename[:-3] if filename.lower().endswith(".gz") else filename
        try:
            cleaned, r = clean_bytes(raw, inner_name, depth=depth + 1, **opts)
            if not r.get("unsupported"):
                raw = cleaned
                rep["removed"] += r["removed"]
        except Exception:  # noqa: BLE001
            pass
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", filename="", mtime=0, compresslevel=9) as g:
        g.write(raw)
    rep["removed"].insert(0, "En-tête gzip (date, nom d'origine du fichier)")
    return buf.getvalue(), rep


def inspect_archive(data):
    items, tech = [], 0
    raw = None
    if data[:2] == b"\x1f\x8b":
        try:
            mtime, name = _gz_header(data)
            if mtime:
                items.append({"group": "GZIP", "tag": "ModifyDate", "value": time_str(mtime)})
            if name:
                items.append({"group": "GZIP", "tag": "FileName", "value": name})
            raw = gzip.decompress(data) if len(data) <= 300 * 1024 * 1024 else None
        except Exception:  # noqa: BLE001
            raw = None
    else:
        raw = data
    if raw is not None and _is_tar(raw):
        try:
            users, groups, times = set(), set(), set()
            with tarfile.open(fileobj=io.BytesIO(raw)) as t:
                for i, m in enumerate(t):
                    if i > 5000:
                        break
                    if m.uname:
                        users.add(m.uname)
                    if m.gname:
                        groups.add(m.gname)
                    if m.mtime not in (0, NEUTRAL_TS):
                        times.add(m.mtime)
                    tech += 1
            for u in sorted(users):
                items.append({"group": "TAR", "tag": "OwnerName", "value": u})
            for g in sorted(groups):
                items.append({"group": "TAR", "tag": "GroupName", "value": g})
            if times:
                items.append({"group": "TAR", "tag": "ModifyDate", "value": f"{time_str(min(times))} → {time_str(max(times))}"})
        except Exception:  # noqa: BLE001
            pass
    return {"items": items, "technical": tech, "all": [(i["group"], i["tag"], i["value"]) for i in items]}


def time_str(ts):
    import time as _t
    return _t.strftime("%Y:%m:%d %H:%M:%S", _t.gmtime(ts))


# ── HTML et fichiers de traduction (.po)
_HTML_META = re.compile(r"<meta\s+[^>]*?(?:name|property)\s*=\s*[\"'](author|generator|creator|copyright|designer|publisher|owner|"
                        r"reply-to|application-name|created|date|last-modified|revised|dc\.[a-z.]+|article:author|"
                        r"article:published_time|article:modified_time|og:updated_time|msapplication-[a-z\-]+)[\"'][^>]*>", re.I)
_HTML_COMMENT = re.compile(r"<!--(?:(?!-->).)*?(?:generated by|created with|saved from url|exported|converted|made with)(?:(?!-->).)*?-->",
                           re.I | re.S)
_PO_HEADER = re.compile(r'^("(?:Last-Translator|Language-Team|PO-Revision-Date|POT-Creation-Date|X-Generator|Report-Msgid-Bugs-To):)[^\n]*?(\\n")[ \t]*$',
                        re.M)
_PO_COMMENT = re.compile(r"^#[^\n]*(?:<[^>\n]+@[^>\n]+>|FIRST AUTHOR|Translators?:)[^\n]*\n", re.M)


def clean_html(data):
    rep = new_report()
    text = data.decode("utf-8", "replace")
    text, n = _HTML_META.subn("", text)
    if n:
        rep["removed"].append(f"{n} balise(s) <meta> (auteur, générateur, dates…)")
    text, k = _HTML_COMMENT.subn("", text)
    if k:
        rep["removed"].append("Commentaires de génération (logiciel, URL d'origine)")
    rep["notes"].append("Le texte et les liens de la page ne sont pas modifiés.")
    return text.encode("utf-8"), rep


def clean_po(data):
    rep = new_report()
    text = data.decode("utf-8", "replace")
    text, n = _PO_HEADER.subn(lambda m: m.group(1) + " " + m.group(2), text)
    text, k = _PO_COMMENT.subn("", text)
    if n or k:
        rep["removed"].append("En-tête de traduction (traducteur, équipe, dates, générateur)")
    return text.encode("utf-8"), rep


def inspect_text_meta(data, ext):
    text = data.decode("utf-8", "replace")
    items = []
    if ext in (".po", ".pot"):
        for m in re.finditer(r'^"(Last-Translator|Language-Team|PO-Revision-Date|POT-Creation-Date|X-Generator|Report-Msgid-Bugs-To):\s*([^\n]*?)\\n"', text, re.M):
            v = m.group(2).strip()
            if v:
                items.append({"group": "PO", "tag": {"Last-Translator": "Creator", "Language-Team": "Publisher", "PO-Revision-Date": "ModifyDate",
                              "POT-Creation-Date": "CreateDate", "X-Generator": "Generator", "Report-Msgid-Bugs-To": "Publisher"}[m.group(1)], "value": v})
    else:
        for m in _HTML_META.finditer(text):
            tag = m.group(0)
            c = re.search(r'content\s*=\s*["\']([^"\']*)', tag, re.I)
            if c and c.group(1).strip():
                items.append({"group": "HTML", "tag": {"author": "Creator", "generator": "Generator", "date": "CreateDate"}.get(m.group(1).lower(), m.group(1).capitalize()),
                              "value": c.group(1).strip()[:140]})
        for m in _HTML_COMMENT.finditer(text):
            items.append({"group": "HTML", "tag": "Generator", "value": re.sub(r"\s+", " ", m.group(0)[4:-3]).strip()[:140]})
    return {"items": items, "technical": 0, "all": [(i["group"], i["tag"], i["value"]) for i in items]}
