<div align="center">

<img src="docs/icon.png" width="128" alt="Icône d'Anonymiseur">

# Anonymiseur

**Effacez les métadonnées de vos fichiers, et masquez ce qu'ils contiennent, sans rien envoyer sur Internet.**

[![Licence MIT](https://img.shields.io/badge/licence-MIT-1f6f50)](LICENSE)
![macOS](https://img.shields.io/badge/macOS-12%2B-1f6f50)
![Apple Silicon](https://img.shields.io/badge/Apple%20Silicon-arm64-1f6f50)
![Autonome](https://img.shields.io/badge/rien%20%C3%A0%20installer-%E2%9C%93-1f6f50)

[English version](README.en.md) · [Télécharger](../../releases/latest)

<img src="docs/screenshots/02-file-attente.png" width="860" alt="Anonymiseur : fichiers en attente, actions au choix, bouton Lancer">

</div>

## Ce que ça fait

Une photo, un PDF ou un document Word contient bien plus que ce que l'on voit : **où et quand** il a été créé, **avec quel
appareil et quel logiciel**, **par qui**, parfois **avec quelle IA**. Anonymiseur retire ces traces, vérifie qu'il n'en reste
pas, et vous montre exactement ce qui a été trouvé.

- **Efface les métadonnées** : dates, position GPS, appareil, auteur, logiciel, miniatures, signatures d'IA (C2PA, invites
  de génération Stable Diffusion/ComfyUI…), identifiants d'édition, noms des auteurs de commentaires.
- **Montre l'« origine détectée »** avant nettoyage (appareil, logiciel, auteur, lieu, indices d'IA) et confirme qu'il n'en
  reste rien après.
- **Contrôle de fuite** : cherche dans le fichier final chaque nom ou numéro de série qui figurait avant. Si l'un
  réapparaît, vous le voyez en rouge.
- **Masque le contenu** (bouton à part) : e-mails, téléphones, IBAN, cartes bancaires, n° de sécurité sociale, chemins,
  adresses IP, noms des auteurs et vos propres mots, dans le texte des PDF, Word, Excel, PowerPoint, draw.io, SVG et
  fichiers texte ou code.
- **Définit vos propres métadonnées** (bouton à part) : auteur, titre, date, lieu GPS, appareil, logiciel de votre choix.
- **Chaque action est un bouton indépendant** : anonymiser le fichier sans toucher au contenu, ou l'inverse, ou les deux.
  Vos choix sont mémorisés.
- **Vous gardez la main** : on dépose les fichiers, on choisit les actions, puis on clique sur **« Lancer »**. Rien ne
  démarre tout seul.
- **Dossiers et archives** (ZIP, tar.gz) : traités fichier par fichier, arborescence conservée.
- **Les originaux ne sont jamais modifiés** : le résultat est toujours une copie.

### Formats pris en charge

| Famille | Formats |
|---|---|
| Images | JPEG, PNG, WebP, GIF, TIFF, HEIC, PSD (Photoshop) |
| Documents | PDF, Word, Excel, PowerPoint, OpenDocument (ODT/ODS/ODP) |
| Dessin | draw.io (`.drawio`, `.dio`, `.drawio.svg`, `.drawio.png`), SVG (Inkscape, Illustrator) |
| Audio / vidéo | MP4, MOV, MKV, AVI, MP3, M4A, WAV, FLAC, OGG… |
| Archives | ZIP, TAR, GZ, TGZ |
| Web / texte | HTML, fichiers de traduction `.po`, texte et code (masquage du contenu seulement) |

Les fichiers de code, de texte et les polices ne contiennent pas de métadonnées personnelles : ils sont copiés tels quels
(en dossier) ou signalés « Sans métadonnées ».

## Captures d'écran

| | |
|---|---|
| ![Accueil](docs/screenshots/01-accueil.png) | ![Résultat sur une photo](docs/screenshots/03-resultat-photo.png) |
| **Accueil** : déposez, choisissez, lancez. | **Résultat** : origine détectée, contrôle de fuite, avant/après. |
| ![Contenu masqué](docs/screenshots/05-contenu-masque.png) | ![Vos métadonnées](docs/screenshots/06-mes-metadonnees.png) |
| **Contenu masqué** dans un document Word. | **Vos propres métadonnées** à la place des originales. |
| ![Dossier](docs/screenshots/07-dossier.png) | ![Résultat sur un document](docs/screenshots/04-resultat-document.png) |
| **Un dossier entier**, fichier par fichier. | Un **nom d'auteur** resté dans le texte est signalé. |

*Toutes les données visibles sont fictives (voir `examples/`).*

## Installation

1. Téléchargez `Anonymiseur-1.0-arm64.dmg` depuis la [page des versions](../../releases/latest).
2. Ouvrez le `.dmg` et **glissez Anonymiseur dans Applications**.
3. **Première ouverture** : l'app est signée « ad hoc » mais **pas notarisée par Apple** (cela demande un compte
   développeur payant). macOS la bloque donc au premier lancement :
   - **clic droit** sur Anonymiseur → **Ouvrir** → **Ouvrir** ; ou
   - dans le Terminal : `xattr -dr com.apple.quarantine /Applications/Anonymiseur.app`

**Rien d'autre à installer** : Python, FFmpeg et ExifTool sont embarqués dans l'app (≈ 105 Mo). Aucune connexion Internet
n'est nécessaire, le moteur n'écoute que sur `127.0.0.1` et ne contacte aucun serveur.

Vous pouvez vérifier le téléchargement avec la somme SHA-256 indiquée dans la page de la version :
`shasum -a 256 Anonymiseur-1.0-arm64.dmg`

## Premiers pas

1. **Déposez** des fichiers ou des dossiers dans la fenêtre (ou cliquez pour les choisir, ou faites clic droit →
   *Ouvrir avec* → Anonymiseur dans le Finder). Ils s'affichent dans « Prêts à traiter ».
2. **Choisissez les actions** (boutons) : effacer les métadonnées, nom aléatoire, masquer le contenu, etc.
3. Cliquez sur **« Lancer l'anonymisation »**, puis **Télécharger** chaque résultat (ou **Tout enregistrer…**).

Des fichiers d'essai fictifs sont dans [`examples/`](examples).

## Compatibilité et limites connues

**Ce qui a été testé**

- Mac Apple Silicon sous **macOS 26.6.2**.
- Le moteur de l'app a été lancé **sans Homebrew** (profil `sandbox-exec` interdisant `/opt/homebrew` et `/usr/local`) et
  a passé la batterie de tests (32 fichiers de test × 5 combinaisons d'options, soit 711 vérifications,
  `tests/run_tests.py`).
- L'ouverture de fichiers depuis le Finder (mise en attente sans traitement automatique) a été essayée dans la vraie fenêtre.

**Ce qui n'a pas été testé**

- Un autre Mac, ou une autre version de macOS : le minimum **macOS 12** est calculé d'après les binaires embarqués, mais pas
  vérifié sur une machine sous macOS 12 à 15.
- La première ouverture avec la quarantaine de Gatekeeper sur un `.dmg` téléchargé.
- À la souris, dans la fenêtre : glisser-déposer, « Tout enregistrer… », « Original à la corbeille », export du rapport.
- Les **Mac Intel** ne sont pas pris en charge (Apple Silicon uniquement).

**Limites du nettoyage (à connaître)**

- Certaines traces sont **dans le contenu lui-même** et ne s'effacent pas : bruit propre au capteur d'un appareil photo,
  filigranes invisibles d'IA (par exemple SynthID), style d'écriture. Le mode « Images ré-encodées » efface la structure du
  fichier mais pas ces traces.
- Le texte **visible dans une image ou une vidéo** n'est pas lu (pas de reconnaissance de texte) : il n'est pas masqué.
- **MKV** : la bibliothèque écrit elle-même un marqueur `encoder=Lavf` qui ne peut pas être retiré.
- **PSD** : la date de modification de chaque calque est conservée (la retirer risquerait d'abîmer le fichier).
- **Word / Excel** : un e-mail coupé en plusieurs morceaux par le traitement de texte peut échapper au masquage.
- **Dossiers** : les noms de fichiers et de dossiers sont conservés pour garder l'arborescence.
- **Formats non pris en charge** : Affinity (`.afpub`…), InDesign, Sketch, ZIP protégé par mot de passe. L'app l'indique ;
  exportez en PDF ou en image puis anonymisez l'export.
- Anonymiser ne garantit pas l'anonymat : le texte d'un document, un visage ou un lieu reconnaissable dans une photo restent.

## Construire depuis les sources

Prérequis : un Mac Apple Silicon, les **outils en ligne de commande Xcode** (`xcode-select --install`), et **ExifTool**
pour la construction seulement (`brew install exiftool`). Une connexion Internet est nécessaire la première fois.

```bash
./build_app.sh            # télécharge et vérifie les composants (SHA-256), compile FFmpeg minimal, construit dist/Anonymiseur.app
./make_dmg.sh             # fabrique dist/Anonymiseur-1.0-arm64.dmg et son empreinte SHA-256
./build_app.sh --install  # variante : construit puis installe dans /Applications
```

Le script contrôle qu'aucun chemin personnel de votre machine ne se retrouve dans l'app.

## Organisation du code

```
src/cleaners.py     moteur : nettoyage, masquage, inspection, contrôle de fuite
src/server.py       petit serveur local (127.0.0.1) entre la fenêtre et le moteur
src/index.html      interface (en français, thème clair)
src/main.swift      fenêtre macOS (WebKit) ; lance le moteur embarqué
src/pdfflat.swift   outil qui redessine et noircit les PDF (PDFKit)
scripts/            téléchargement vérifié des composants, compilation de FFmpeg, captures d'écran
tests/              fabrique de fichiers de test fictifs et batterie de tests
examples/           fichiers d'essai fictifs
build_app.sh        construit l'app autonome ;  make_dmg.sh : fabrique le .dmg
```

## Tests

```bash
.deps/python/bin/python3 tests/run_tests.py          # après un premier ./build_app.sh
```

Le test échoue si un fichier de test est absent, pour ne jamais « réussir » en ne testant rien.

## Contribuer

Les signalements de formats mal gérés et les propositions (*issues*, *pull requests*) sont bienvenus. Avant d'envoyer une
modification, lancez les tests ci-dessus. **N'ajoutez jamais de fichiers réels ou de données personnelles** au dépôt :
utilisez des données fictives.

## Licence

[MIT](LICENSE) © 2026 Wudstyz. Les composants embarqués ont leurs propres licences : voir
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). Les marques citées appartiennent à leurs propriétaires ; ce projet n'est
affilié à aucune de ces sociétés.
