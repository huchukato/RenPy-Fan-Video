#!/usr/bin/env python3
"""
RenPy-Fan-Video - Project Module
Gestisce la cartella di progetto dedicata per ogni gioco.

Struttura:
  ~/FanVideoProjects/<game_name>/
  ├── sources/      # immagini statiche esportate dal gioco
  ├── videos/       # video webm generati esternamente (l'utente li mette qui)
  ├── last_frames/  # ultimi frame (opzionali)
  └── project.json  # metadati: gioco sorgente, data, associazioni

L'idea: l'utente esporta le immagini da animare in sources/, le carica
in un tool AI (motionmuse.ai, ComfyUI, pollo.ai), genera i video e li
salva in videos/, poi torna in Fan-Video per associarli e generare
il patch Ren'Py.
"""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict


# Directory radice dei progetti (home utente)
PROJECTS_ROOT = Path.home() / "FanVideoProjects"


@dataclass
class ProjectEntry:
    """Associazione salvata nel project.json."""
    image_name: str
    source_file: str | None = None       # nome file in sources/
    video_file: str | None = None        # nome file in videos/ (None = in attesa)
    last_frame_file: str | None = None
    loop: bool = True
    exported_at: str = ""
    video_associated_at: str = ""


class FVProject:
    """Gestisce la cartella di progetto per un gioco."""

    def __init__(self, game_path: Path | str):
        """
        Args:
            game_path: percorso al gioco (.app o cartella).
        """
        self.game_path = Path(game_path)
        self.name = self._derive_project_name()
        self.root = PROJECTS_ROOT / self.name
        self.sources_dir = self.root / "sources"
        self.videos_dir = self.root / "videos"
        self.last_frames_dir = self.root / "last_frames"
        self.config_path = self.root / "project.json"

        # Stato delle associazioni (image_name -> ProjectEntry)
        self.entries: dict[str, ProjectEntry] = {}

    # ------------------------------------------------------------------ #
    # Naming
    # ------------------------------------------------------------------ #
    def _derive_project_name(self) -> str:
        """Deriva un nome progetto dal percorso del gioco."""
        name = self.game_path.name
        # .app macOS: usa il nome senza estensione
        if name.endswith(".app"):
            name = name[:-4]
        # Sanitizza: solo word chars, underscore, trattino
        name = re.sub(r"[^\w\-]+", "_", name).strip("_")
        return name or "unnamed_game"

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Converte un nome immagine Ren'Py in nome file safe."""
        return re.sub(r"[^\w]+", "_", name).strip("_").lower()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def exists(self) -> bool:
        """True se la cartella progetto esiste gia'."""
        return self.root.exists()

    def create(self):
        """Crea la struttura directory del progetto."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(exist_ok=True)
        self.videos_dir.mkdir(exist_ok=True)
        self.last_frames_dir.mkdir(exist_ok=True)

    def load(self):
        """Carica le associazioni salvate da project.json."""
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            for name, entry_data in data.get("entries", {}).items():
                self.entries[name] = ProjectEntry(**entry_data)
        except Exception:
            # Se il file e' corrotto, ignora
            pass

    def save(self):
        """Salva le associazioni in project.json."""
        self.create()
        data = {
            "game_path": str(self.game_path),
            "created_at": datetime.now().isoformat(),
            "entries": {name: asdict(e) for name, e in self.entries.items()},
        }
        self.config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ #
    # Esportazione immagini
    # ------------------------------------------------------------------ #
    def export_image(self, image_name: str, source_path: Path) -> Path:
        """Copia un'immagine statica in sources/ e registra l'associazione.

        Args:
            image_name: nome Ren'Py dell'immagine (es. "an 6").
            source_path: file immagine sorgente su disco.

        Returns:
            Path del file copiato in sources/.
        """
        self.create()
        # Usa il nome file originale su disco, non il nome Ren'Py sanitizzato.
        # Questo preserva nomi come "awam (8).webp" invece di "awam_8.webp",
        # mantenendo il collegamento tra immagine esportata e video generato.
        dest = self.sources_dir / source_path.name

        # Se esiste gia', non sovrascrive (stessa immagine)
        if not dest.exists():
            shutil.copy2(source_path, dest)
        elif dest.stat().st_size == source_path.stat().st_size:
            # Stesso file, skip
            pass
        else:
            # File diverso con stesso nome: aggiunge suffisso numerico
            stem = source_path.stem
            ext = source_path.suffix.lower()
            idx = 2
            while dest.exists():
                dest = self.sources_dir / f"{stem}_{idx}{ext}"
                idx += 1
            shutil.copy2(source_path, dest)

        # Registra/aggiorna l'entry
        entry = self.entries.get(image_name, ProjectEntry(image_name=image_name))
        entry.source_file = dest.name
        entry.exported_at = datetime.now().isoformat()
        self.entries[image_name] = entry
        self.save()

        return dest

    def export_images(self, items: list[tuple[str, Path]],
                      progress_callback=None) -> list[Path]:
        """Esporta piu' immagini in batch.

        Args:
            items: lista di (image_name, source_path).
            progress_callback: funzione(current, total).

        Returns:
            lista di Path dei file copiati.
        """
        self.create()
        results = []
        for i, (name, src) in enumerate(items, 1):
            if progress_callback:
                progress_callback(i, len(items))
            if src and src.exists():
                dest = self.export_image(name, src)
                results.append(dest)
        return results

    # ------------------------------------------------------------------ #
    # Associazione video
    # ------------------------------------------------------------------ #
    def associate_video(self, image_name: str, video_path: Path,
                        last_frame_path: Path | None = None,
                        loop: bool = True) -> Path | None:
        """Associa un video a un'immagine esportata.

        Copia il video in videos/ (se non gia' presente), aggiorna
        l'entry in project.json.

        Args:
            image_name: nome Ren'Py dell'immagine.
            video_path: file webm fornito dall'utente.
            last_frame_path: ultimo frame opzionale.
            loop: True per loop, False per play once.

        Returns:
            Path del video copiato in videos/, oppure None se l'entry
            non esiste.
        """
        if image_name not in self.entries:
            return None

        self.create()
        safe = self._safe_filename(image_name)

        # Copia video
        video_dest = self.videos_dir / f"{safe}{video_path.suffix.lower()}"
        if not video_dest.exists():
            shutil.copy2(video_path, video_dest)

        # Copia last frame
        lf_dest_name = None
        if last_frame_path and last_frame_path.exists():
            lf_dest = self.last_frames_dir / f"{safe}_last{last_frame_path.suffix.lower()}"
            if not lf_dest.exists():
                shutil.copy2(last_frame_path, lf_dest)
            lf_dest_name = lf_dest.name

        # Aggiorna entry
        entry = self.entries[image_name]
        entry.video_file = video_dest.name
        entry.last_frame_file = lf_dest_name
        entry.loop = loop
        entry.video_associated_at = datetime.now().isoformat()
        self.save()

        return video_dest

    # ------------------------------------------------------------------ #
    # Query
    # ------------------------------------------------------------------ #
    def get_source_path(self, image_name: str) -> Path | None:
        """Restituisce il path in sources/ per un'immagine esportata."""
        entry = self.entries.get(image_name)
        if entry and entry.source_file:
            p = self.sources_dir / entry.source_file
            if p.exists():
                return p
        return None

    def get_video_path(self, image_name: str) -> Path | None:
        """Restituisce il path in videos/ per un'immagine associata."""
        entry = self.entries.get(image_name)
        if entry and entry.video_file:
            p = self.videos_dir / entry.video_file
            if p.exists():
                return p
        return None

    def is_exported(self, image_name: str) -> bool:
        """True se l'immagine e' stata esportata in sources/."""
        return image_name in self.entries and self.entries[image_name].source_file is not None

    def has_video(self, image_name: str) -> bool:
        """True se l'immagine ha un video associato."""
        return image_name in self.entries and self.entries[image_name].video_file is not None

    def pending_count(self) -> int:
        """Numero di entry esportate ma senza video."""
        return sum(1 for e in self.entries.values()
                   if e.source_file and not e.video_file)

    def associated_count(self) -> int:
        """Numero di entry con video associato."""
        return sum(1 for e in self.entries.values() if e.video_file)

    # ------------------------------------------------------------------ #
    # Elenco video disponibili in videos/ non ancora associati
    # ------------------------------------------------------------------ #
    def list_unassociated_videos(self) -> list[Path]:
        """Restituisce i file video in videos/ non associati a nessuna entry."""
        associated = {e.video_file for e in self.entries.values() if e.video_file}
        result = []
        if self.videos_dir.exists():
            for f in self.videos_dir.iterdir():
                if f.is_file() and f.suffix.lower() in {".webm", ".mp4"}:
                    if f.name not in associated:
                        result.append(f)
        return result


# ---------------------------------------------------------------------- #
# Test da CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python fv_project.py <game_path>")
        sys.exit(1)

    proj = FVProject(sys.argv[1])
    print(f"Progetto: {proj.name}")
    print(f"Root: {proj.root}")
    proj.create()
    print(f"Cartelle create: {proj.root}")

    # Test esportazione
    test_img = Path("/tmp/test_img.jpg")
    test_img.write_bytes(b"fake")  # file fittizio
    out = proj.export_image("an 6", test_img)
    print(f"Esportato: {out}")
    print(f"Entry: {proj.entries}")
    print(f"Pending: {proj.pending_count()}, Associated: {proj.associated_count()}")
