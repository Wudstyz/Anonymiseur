# Composants tiers / Third-party components

Anonymiseur est publié sous licence MIT (voir `LICENSE`). L'application autonome embarque les composants ci-dessous, chacun
sous sa propre licence. / Anonymiseur is released under the MIT license (see `LICENSE`). The standalone app bundles the
components below, each under its own license.

| Composant | Version | Licence | Rôle | Source |
|---|---|---|---|---|
| Python (build « python-build-standalone ») | 3.13.18 (build 20261026) | PSF License ; scripts de build MPL-2.0 | Exécute le moteur d'anonymisation | https://github.com/astral-sh/python-build-standalone |
| Pillow | 13.0.0 | MIT-CMU (HPND) | Lecture/écriture d'images (mode « Images ré-encodées ») | https://github.com/python-pillow/Pillow |
| pypdf | 7.0.1 | BSD-3-Clause | Lecture/écriture de PDF | https://github.com/py-pdf/pypdf |
| ExifTool | 13.55 | Artistic License ou GPL v1+ (comme Perl) | Lecture des métadonnées de nombreux formats | https://exiftool.org |
| FFmpeg (version minimale compilée par `scripts/build_ffmpeg.sh`) | 9.0.2 | LGPL v2.1 ou ultérieure | Recopie des flux audio/vidéo sans métadonnées | https://ffmpeg.org |

## Détails

- **Pillow** embarque des bibliothèques dynamiques (libjpeg-turbo, libtiff, libwebp, libpng, libavif, FreeType, HarfBuzz,
  Little CMS, OpenJPEG, zlib-ng, etc.), chacune avec sa licence : voir le dossier `licenses` de la roue Pillow, copié dans
  `Contents/Resources/python/lib/python3.13/site-packages/pillow-13.0.0.dist-info/`.
- **FFmpeg** : la version embarquée est compilée **sans aucune option GPL ni bibliothèque externe** (pas de x264, pas de
  x265…), uniquement avec les démultiplexeurs, multiplexeurs, analyseurs et filtres de flux nécessaires à la recopie
  « sans décodage » (`-c copy`). La configuration exacte est dans `scripts/build_ffmpeg.sh` ; elle compile l'archive officielle
  `ffmpeg-9.0.2.tar.xz` (SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e`). Conformément à la
  LGPL, vous pouvez remplacer `ffmpeg` et `ffprobe` dans `Contents/Resources/bin/` par votre propre compilation.
- **ExifTool** : copie fidèle du programme Perl et de ses modules (`Image::ExifTool`). L'application utilise le Perl fourni
  par macOS (`/usr/bin/perl`).
- Les outils du système macOS `sips` (conversion HEIC) et `PDFKit` (via `pdfflat`, écrit pour ce projet) sont utilisés
  tels que fournis par le système.

## Marques / Trademarks

draw.io est une marque de JGraph Ltd ; Photoshop, Illustrator et PDF sont des marques d'Adobe ; Inkscape est une marque de
The Inkscape Project ; Word, Excel et PowerPoint sont des marques de Microsoft ; Affinity est une marque de Serif (Europe)
Ltd ; Apple, macOS, HEIC et Mac sont des marques d'Apple Inc. ; ChatGPT/DALL·E (OpenAI), Midjourney, Stable Diffusion,
ComfyUI et les autres outils cités ne le sont qu'à titre d'exemples de signatures détectées. Toutes ces marques
appartiennent à leurs propriétaires respectifs. Ce projet n'est affilié à aucune de ces sociétés et n'est ni approuvé ni
sponsorisé par elles.

All trademarks belong to their respective owners. This project is not affiliated with, endorsed or sponsored by any of them.
