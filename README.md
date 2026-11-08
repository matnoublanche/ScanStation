# ScanStation

Application en ligne de commande pour le ScanSnap S1300i sous Debian 13, testée sur Raspberry Pi 4. Un appel à `scanstation` pilote le travail complet. Le même exécutable sert depuis SSH et depuis l’interface tactile.

## Installer

Brancher un S1300i déjà fonctionnel avec SANE et son firmware. L’utilisateur qui lancera ScanStation doit pouvoir numériser avec `scanimage`. L’installateur utilise les paquets Debian, dont Leptonica 6. Il faut un index APT à jour et un accès sudo pour installer les dépendances et la commande. Depuis le projet décompressé, lancer avec le compte habituel du Pi :

```sh
sh install.sh
scanstation --version
```

### Installer ou mettre à jour depuis GitHub

Exécuter cette commande sur le Raspberry Pi avec le compte de numérisation. Git récupère la branche principale publique dans un dossier temporaire. L’installateur utilise les fichiers de cette même révision et conserve la configuration existante.

```sh
(set -e; d=$(mktemp -d); trap 'rm -rf "$d"' EXIT; git clone -q --depth 1 https://github.com/matnoublanche/ScanStation.git "$d"; sh "$d/install.sh")
```

Le dépôt matnoublanche/ScanStation est la source de référence. Publier chaque changement sur GitHub, puis exécuter cette même commande pour déployer sur le Pi.

## Utiliser depuis SSH

```sh
scanstation lot
scanstation feuille
scanstation multipassage
scanstation lot --no-filtrer --qualite 85
scanstation lot --depuis /chemin/vers/passage-001
scanstation multipassage --depuis /chemin/passage-001 --depuis /chemin/passage-002
```

- **lot** assemble toutes les faces conservées dans un PDF.
- **feuille** produit un PDF par paire recto-verso contenant au moins une face conservée.
- **multipassage** assemble les chargements successifs en un PDF. En SSH, charger les feuilles puis appuyer sur Entrée pour continuer, ou saisir `f` pour finaliser.
- **verifier** vérifie un jeu témoin avec les quatre fichiers `page-001.pnm` à `page-004.pnm`. Résultat attendu : 001, 003 et 004 conservées. Exemple : `scanstation verifier --reference ~/scanstation-test/duplex`.

Chaque exécution de scan crée un dossier de travail distinct. Le moteur acquiert en duplex couleur à 300 ppp, redresse et recadre, classe les faces, détermine l’orientation, nettoie le fond avec Leptonica, choisit gris ou couleur et assemble les JPEG à 200 ppp avec img2pdf. Les PNM de toutes les faces sont conservés. Le dossier `pdf/` apparaît quand l’assemblage de tout le travail est terminé. `pages.json` contient les décisions par face. L’OCR documentaire est laissé à Paperless. Cette version produit les fichiers localement.

## Paramétrer

La configuration est dans `~/.config/scanstation/config.toml` (ou sous `XDG_CONFIG_HOME`). Les options de la commande ont priorité. `--config CHEMIN` sélectionne un autre fichier.

| Configuration | Option | Effet |
|---|---|---|
| `device = "auto"` | `--device` | Détecter le périphérique epjitsu ou fournir son identifiant SANE. Si plusieurs sont présents, choisir explicitement. |
| `sortie = "~/scanstation-travaux"` | `--sortie` | Dossier parent des travaux. |
| `filtrer = true` | `--filtrer` ou `--no-filtrer` | Écarter les faces classées vierges du PDF. Un travail entièrement vierge donne une liste de PDF vide. |
| `qualite = 76` | `--qualite` | Qualité JPEG, de 1 à 95. |
| `reference` (facultatif) | `--reference` | Rejouer le contrôle témoin avant chaque travail filtré. En cas de désaccord, le travail s’arrête avant l’acquisition. |

Une installation neuve fonctionne sans documents personnels. Si le dossier témoin historique se trouve dans le compte du Pi lors de la première installation, l’installateur le renseigne. Pour capturer un nouveau lot, omettre `--depuis`. Pour le rejouer, fournir un dossier contenant des `page-N.pnm` consécutives à partir de 1 et un nombre pair de faces.

## Brancher l’écran tactile

Lancer un seul processus en arrière-plan avec un tableau d’arguments, par exemple `["/usr/local/bin/scanstation", "lot", "--filtrer", "--json"]`. Lire stdout ligne par ligne (UTF-8, un objet JSON par ligne) et lire stderr séparément pour les diagnostics des outils. Ne pas bloquer la boucle d’affichage de LVGL. Le verrou par utilisateur empêche deux acquisitions physiques ScanStation simultanées.

| Événement stdout | Données pour l’écran |
|---|---|
| `reference` | Décision sur une face témoin, si configurée. |
| `travail` | `dossier`, chemin absolu du nouveau travail. |
| `passage` | `numero`, début de l’acquisition ou du rejeu du passage. |
| `face` | `passage`, `numero`, `conserve` après traitement de la face. |
| `attente` | En multipassage physique, proposer « Passage suivant » et « Terminer ». Écrire `suivant\n` ou `fin\n` sur stdin et vider le tampon. |
| `termine` | `pdf` (liste de chemins absolus), `rapport`, `faces`, `conservees`. |
| `erreur` | `message` à afficher. Les originaux déjà acquis sont conservés. |

Un travail réussi se termine avec le code 0. Une erreur de travail renvoie 1 ; des arguments invalides renvoient 2 avec un diagnostic sur stderr. Traiter aussi une sortie non nulle sans événement final. En multipassage automatique depuis des dossiers PNM, tous les passages sont déjà fournis ; aucun échange sur stdin n’est nécessaire.

## Tickets de caisse (0.2.0)

Utiliser `scanstation lot --profil ticket` ou ajouter `--profil ticket --json` à l’appel du tactile. Le profil document reste le choix par défaut. Le profil ticket repère le papier clair sur le fond du chargeur, corrige son inclinaison, estime le sens de lecture sur le ticket recadré et produit un JPEG gris à 300 ppp. En duplex, le filtre compare les motifs du verso avec leur reflet sur le recto. Un verso faible et suffisamment corrélé est classé comme transparent. Utiliser `--no-filtrer` pour conserver les deux faces, notamment pour un ticket avec de faibles annotations au dos. Les originaux restent disponibles. La longueur maximale dépend du pilote SANE.
