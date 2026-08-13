#!/usr/bin/env python3
"""
RenPy-Fan-Video - Scanner Module
Scansiona i file .rpy decompilati per individuare le immagini statiche
usate nelle istruzioni `scene`/`show` e ne risolve il file su disco.

Logica di risoluzione nome -> file:
  1. Definizioni `image <name> = "<path>"` trovate nei .rpy
  2. Definizioni `image <name> = Movie(...)` -> marcate come gia' animate
  3. Risoluzione automatica Ren'Py: normalizza il nome (spazi -> `_`,
     case-insensitive) e cerca in `game/images/` ricorsivamente.

In Ren'Py l'ultima definizione `image` vince, quindi un'immagine puo'
essere sia definita staticamente che sovrascritta da un Movie: in tal
caso viene marcata `already_movie=True` ma mantenuta in elenco (l'utente
puo' comunque sostituirla).
"""

import re
from pathlib import Path
from dataclasses import dataclass, field


# Estensioni immagine gestite da Ren'Py
IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.avif', '.bmp', '.gif'}

# Keyword Ren'Py che terminano il nome immagine in scene/show
SCENE_KEYWORDS = {
    'with', 'at', 'as', 'behind', 'expression', 'onlayer', 'zorder',
    'to', 'from',
}

# Nomi da escludere (non sono immagini reali)
EXCLUDE_NAMES = {
    'black', 'white', 'bg', 'background', 'overlay', 'text',
    'vbox', 'hbox', 'screen', 'transform', 'null', 'solid',
    'imagebutton', 'textbutton', 'frame', 'window', 'viewport',
}


@dataclass
class StaticImage:
    """Rappresenta un'immagine statica individuata nei .rpy."""
    name: str                       # nome Ren'Py (es. "day20_waking_up 1", "an 6")
    file_path: Path | None = None   # file su disco (None se non risolto)
    used_in: list = field(default_factory=list)  # [(rpy_file, line_no), ...]
    already_movie: bool = False     # True se esiste gia' una def Movie
    movie_definition: str | None = None  # testo della def Movie se presente
    definition_file: Path | None = None   # .rpy dove e' definita (se presente)
    definition_line: int | None = None

    @property
    def is_resolved(self) -> bool:
        return self.file_path is not None


class FVScanner:
    """Scansiona i .rpy di un gioco Ren'Py per individuare immagini statiche."""

    # Regex per scene/show (con indentazione opzionale)
    _RE_SCENE = re.compile(r'^(\s*)(scene|show)\s+(.+)$')
    # Regex per definizioni image
    _RE_IMAGE_DEF = re.compile(
        r'^image\s+(.+?)\s*=\s*(.+)$'
    )
    # Regex per image Movie
    _RE_MOVIE = re.compile(r'Movie\s*\(', re.IGNORECASE)
    # Regex per estrarre start_image da Movie
    _RE_START_IMAGE = re.compile(r'start_image\s*=\s*"([^"]+)"')
    # Regex per stringa tra virgolette (per image = "path")
    _RE_STRING = re.compile(r'"([^"]+)"')

    def __init__(self, game_dir: Path, log_callback=None):
        """
        Args:
            game_dir: directory `game` del gioco Ren'Py.
            log_callback: funzione(str) per log.
        """
        self.game_dir = Path(game_dir)
        self.images_dir = self.game_dir / "images"
        self.log = log_callback or (lambda msg: print(msg))

        # Indice dei file immagine su disco: normalized_name -> Path
        self._file_index: dict[str, Path] = {}
        # Definizioni image trovate: name -> (definition_text, file, line)
        self._image_defs: dict[str, tuple[str, Path, int]] = {}
        # Definizioni Movie trovate: name -> (definition_text, file, line)
        self._movie_defs: dict[str, tuple[str, Path, int]] = {}

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #
    @staticmethod
    def _normalize(name: str) -> str:
        """Normalizza un nome immagine per il matching con i file.

        Ren'Py tratta `_` come separatore di parole equivalente allo spazio
        nella risoluzione automatica dei file. Per il lookup usiamo
        lowercase + spazi -> `_`.
        """
        return name.strip().lower().replace(' ', '_')

    def _build_file_index(self, progress_callback=None):
        """Costruisce l'indice dei file immagine in game/images/."""
        self._file_index.clear()
        if not self.images_dir.exists():
            self.log(f"Directory immagini non trovata: {self.images_dir}")
            return

        # Prima conta i file totali per la progress bar
        all_files = list(self.images_dir.rglob('*'))
        total = len(all_files)
        self.log(f"Indicizzazione di {total} file in {self.images_dir}...")

        count = 0
        for i, f in enumerate(all_files):
            if progress_callback and (i % 500 == 0 or i == total - 1):
                progress_callback(i + 1, total)
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                key = self._normalize(f.stem)
                if key not in self._file_index:
                    self._file_index[key] = f
                    count += 1

        if progress_callback:
            progress_callback(total, total)
        self.log(f"Indicizzati {count} file immagine in {self.images_dir}")

    def _resolve_image_file(self, name: str) -> Path | None:
        """Risolve un nome immagine Ren'Py in un file su disco.

        Prova in ordine:
          1. Lookup diretto nell'indice (nome normalizzato)
          2. Se il nome contiene spazi, prova anche con `_`
          3. Se la definizione image referenzia un path esplicito, lo usa
        """
        # 1. Lookup diretto
        key = self._normalize(name)
        if key in self._file_index:
            return self._file_index[key]

        # 2. Prova varianti: se il nome ha underscore, prova anche con spazi
        #    (raro, gestito dalla normalizzazione che va gia' a `_`)
        # 3. Definizione esplicita con path file
        if name in self._image_defs:
            def_text, _, _ = self._image_defs[name]
            match = self._RE_STRING.search(def_text)
            if match:
                path_str = match.group(1)
                # Path relativo a game/
                candidate = self.game_dir / path_str
                if candidate.exists():
                    return candidate
                # Prova senza il prefisso images/
                candidate2 = self.images_dir / path_str
                if candidate2.exists():
                    return candidate2

        return None

    # ------------------------------------------------------------------ #
    # Parsing
    # ------------------------------------------------------------------ #
    def _parse_image_definitions(self, rpy_file: Path):
        """Estrae le definizioni `image <name> = ...` da un file .rpy."""
        try:
            lines = rpy_file.read_text(encoding='utf-8', errors='replace').splitlines()
        except Exception as e:
            self.log(f"Errore lettura {rpy_file.name}: {e}")
            return

        for i, line in enumerate(lines, 1):
            # Solo definizioni top-level (niente indentazione)
            if line.startswith((' ', '\t')):
                continue
            m = self._RE_IMAGE_DEF.match(line)
            if not m:
                continue

            name = m.group(1).strip()
            value = m.group(2).strip()

            # Salta definizioni con nome che contiene '=' (malformate)
            if '=' in name:
                continue

            if self._RE_MOVIE.search(value):
                # Definizione Movie
                self._movie_defs[name] = (value, rpy_file, i)
            else:
                # Definizione statica (stringa o espressione)
                self._image_defs[name] = (value, rpy_file, i)

    def _parse_scene_show(self, rpy_file: Path, usages: dict):
        """Estrae le istruzioni scene/show da un file .rpy.

        Args:
            usages: dict name -> list[(rpy_file, line)] da popolare.
        """
        try:
            lines = rpy_file.read_text(encoding='utf-8', errors='replace').splitlines()
        except Exception:
            return

        for i, line in enumerate(lines, 1):
            m = self._RE_SCENE.match(line)
            if not m:
                continue

            rest = m.group(3).strip()
            # Salta `expression` (show expression "..." as foo)
            if rest.startswith('expression'):
                continue

            # Estrae il nome: token fino alla prima keyword Ren'Py
            tokens = rest.split()
            name_tokens = []
            for tok in tokens:
                if tok in SCENE_KEYWORDS:
                    break
                name_tokens.append(tok)

            if not name_tokens:
                continue

            name = ' '.join(name_tokens)

            # Salta nomi esclusi
            if name.lower() in EXCLUDE_NAMES:
                continue
            # Salta nomi che iniziano con keyword strane
            if name.startswith(('#', '"', "'", '$')):
                continue
            # Salta nomi con caratteri non validi per un'immagine statica
            # (parentesi quadre/graffe = interpolazione; parentesi tonde =
            # displayable dinamico; $ = variabile)
            if any(c in name for c in '()[]{}$'):
                continue

            usages.setdefault(name, []).append((rpy_file, i))

    # ------------------------------------------------------------------ #
    # API pubblica
    # ------------------------------------------------------------------ #
    def scan(self, rpy_files: list[Path] | None = None,
             progress_callback=None) -> list[StaticImage]:
        """Scansiona i .rpy e restituisce le immagini statiche trovate.

        Args:
            rpy_files: lista di Path .rpy da analizzare. Se None, cerca
                       ricorsivamente in game_dir.
            progress_callback: funzione(current, total).

        Returns:
            list[StaticImage] ordinate per nome.
        """
        if rpy_files is None:
            rpy_files = list(self.game_dir.rglob("*.rpy"))
            # Filtra file di sistema
            rpy_files = [
                f for f in rpy_files
                if not any(x in f.name.lower()
                           for x in ['gui', 'screens', 'options',
                                     'fan_videos', 'fan_video_patch'])
            ]

        self.log(f"Scansione di {len(rpy_files)} file .rpy...")

        # Fase 1: parse definizioni image (0-40%)
        for idx, rpy_file in enumerate(rpy_files, 1):
            if progress_callback:
                progress_callback(idx, len(rpy_files) * 4)
            self._parse_image_definitions(rpy_file)

        # Fase 2: parse scene/show (40-50%)
        usages: dict[str, list[tuple[Path, int]]] = {}
        for idx, rpy_file in enumerate(rpy_files, 1):
            if progress_callback:
                progress_callback(len(rpy_files) + idx, len(rpy_files) * 4)
            self._parse_scene_show(rpy_file, usages)

        # Fase 3: build file index (50-75%)
        # Usa un sub-progress mappato su 1 unita' del totale
        n_rpy = len(rpy_files)
        def _index_sub_progress(c, t):
            if progress_callback and t > 0:
                # Mappa [0..t] su [2*n_rpy .. 3*n_rpy]
                mapped = 2 * n_rpy + int(c / t * n_rpy)
                progress_callback(mapped, n_rpy * 4)
        self._build_file_index(progress_callback=_index_sub_progress)

        # Fase 4: combina usages + definizioni + risoluzione file (75-100%)
        images: list[StaticImage] = []
        n_usages = len(usages)
        for idx, (name, locations) in enumerate(usages.items(), 1):
            if progress_callback and (idx % 200 == 0 or idx == n_usages):
                progress_callback(3 * n_rpy + idx, n_rpy * 4)
            already_movie = name in self._movie_defs
            movie_def_text = None
            def_file = None
            def_line = None

            if already_movie:
                movie_def_text, def_file, def_line = self._movie_defs[name]
            elif name in self._image_defs:
                _, def_file, def_line = self._image_defs[name]

            file_path = self._resolve_image_file(name)

            # Salta immagini non risolte (bottoni, icone UI, displayable composti)
            # che non hanno un file su disco e non possono essere sostituite
            if file_path is None:
                continue

            images.append(StaticImage(
                name=name,
                file_path=file_path,
                used_in=locations,
                already_movie=already_movie,
                movie_definition=movie_def_text,
                definition_file=def_file,
                definition_line=def_line,
            ))

        # Ordina: prima per risolte, poi per nome
        images.sort(key=lambda img: (not img.is_resolved, img.name.lower()))

        n_resolved = sum(1 for img in images if img.is_resolved)
        n_movie = sum(1 for img in images if img.already_movie)
        self.log(f"Trovate {len(images)} immagini usate "
                 f"({n_resolved} risolte, {n_movie} gia' animate)")

        return images

    def get_image_by_name(self, name: str) -> Path | None:
        """Risolve un nome immagine in file (utile per start_image)."""
        return self._resolve_image_file(name)


# ---------------------------------------------------------------------- #
# Test da CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python fv_scanner.py <game_dir> [rpy_dir]")
        sys.exit(1)

    game_dir = Path(sys.argv[1])
    scanner = FVScanner(game_dir)

    # Se fornito un secondo argomento, usa quello come dir dei .rpy
    rpy_files = None
    if len(sys.argv) >= 3:
        rpy_dir = Path(sys.argv[2])
        rpy_files = list(rpy_dir.rglob("*.rpy"))

    images = scanner.scan(rpy_files)

    print(f"\n=== {len(images)} immagini trovate ===")
    for img in images[:30]:
        status = "MOVIE" if img.already_movie else ("OK" if img.is_resolved else "??")
        print(f"  [{status}] {img.name}  <-  {img.file_path}")
        if img.used_in:
            rpy, line = img.used_in[0]
            print(f"         usato in: {rpy.name}:{line} (+{len(img.used_in)-1} altri)")
