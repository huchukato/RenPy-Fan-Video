#!/usr/bin/env python3
"""
RenPy-Fan-Video - Generator Module
Genera il patch che sostituisce immagini statiche con video webm.

Output:
  game/fan_videos.rpy                          # definizioni image <name> = Movie(...)
  game/videos/fanvideomod/<video>.webm         # file video copiati
  game/images/fanvideomod/<last>.jpg           # ultimi frame (opzionali)

Il file fan_videos.rpy usa `init 999` per garantire che le definizioni
vengano caricate DOPO quelle originali del gioco, indipendentemente
dall'ordine di caricamento dei file. In Ren'Py l'ultima definizione
`image <name> = ...` vince.
"""

import shutil
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass


@dataclass
class PatchEntry:
    """Associazione immagine statica -> video.

    `video_path` puo' essere None per le entry "in attesa" (immagine
    esportata ma video non ancora associato). Vengono skippate in
    fase di generazione del patch.
    """
    image_name: str                          # nome Ren'Py (es. "an 6", "day20_julia_1")
    video_path: Path | None = None           # file webm fornito dall'utente (None = in attesa)
    start_image: str = ""                    # nome start_image (di default = image_name)
    start_image_path: Path | None = None     # file immagine statica di partenza
    last_frame_path: Path | None = None      # ultimo frame (opzionale)
    last_frame_name: str | None = None       # nome Ren'Py del last frame
    loop: bool = True                        # True = loop, False = play once (con last_frame)

    @property
    def has_video(self) -> bool:
        """True se il video e' stato associato."""
        return self.video_path is not None and self.video_path.exists()


class FVGenerator:
    """Genera il patch fan_video per un gioco Ren'Py."""

    def __init__(self, game_path, log_callback=None):
        """
        Args:
            game_path: percorso al gioco (.app o cartella).
            log_callback: funzione(str) per log.
        """
        self.game_path = Path(game_path)
        self.log = log_callback or (lambda msg: print(msg))

        # Risolve la directory game
        if self.game_path.suffix == '.app':
            self.game_dir = self.game_path / "Contents" / "Resources" / "autorun" / "game"
        else:
            self.game_dir = self.game_path / "game"
            if not self.game_dir.exists():
                self.game_dir = self.game_path

        self.patch_dir = self.game_dir  # file .rpy va direttamente in game/
        self.videos_dir = self.game_dir / "videos" / "fanvideomod"
        self.frames_dir = self.game_dir / "images" / "fanvideomod"

        # Rileva la risoluzione del gioco per scalare i video
        self.screen_size = self._detect_screen_size()

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #
    def _detect_screen_size(self) -> tuple[int, int] | None:
        """Rileva la risoluzione del gioco legendo config.screen_width/height.

        Cerca nei .rpy e .rpyc decompilati. Se non trova nulla, prova
        a dedurre dalla dimensione delle immagini del gioco.
        """
        import re
        w, h = None, None
        try:
            for rpy in self.game_dir.rglob("*.rpy"):
                try:
                    text = rpy.read_text(encoding='utf-8', errors='replace')
                except Exception:
                    continue
                # Cerca define config.screen_width = NNN
                mw = re.search(r'config\.screen_width\s*=\s*(\d+)', text)
                mh = re.search(r'config\.screen_height\s*=\s*(\d+)', text)
                if mw:
                    w = int(mw.group(1))
                if mh:
                    h = int(mh.group(1))
                if w and h:
                    break
        except Exception:
            pass

        if w and h:
            self.log(f"Game resolution: {w}x{h}")
            return (w, h)

        # Fallback: deduce dalla dimensione di un'immagine del gioco
        try:
            images_dir = self.game_dir / "images"
            if images_dir.exists():
                import subprocess
                for img_path in images_dir.rglob("*.jpg"):
                    if not img_path.is_file():
                        continue
                    # Prova ffprobe prima, poi sips (macOS)
                    try:
                        result = subprocess.run(
                            ["ffprobe", "-v", "error", "-select_streams", "v:0",
                             "-show_entries", "stream=width,height", "-of", "csv=p=0",
                             str(img_path)],
                            capture_output=True, timeout=10,
                        )
                        out = result.stdout.decode().strip()
                        if out:
                            parts = out.split(",")
                            w, h = int(parts[0]), int(parts[1])
                            self.log(f"Game resolution (from image): {w}x{h}")
                            return (w, h)
                    except Exception:
                        pass
                    try:
                        result = subprocess.run(
                            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(img_path)],
                            capture_output=True, timeout=10,
                        )
                        out = result.stdout.decode()
                        mw = re.search(r'pixelWidth:\s*(\d+)', out)
                        mh = re.search(r'pixelHeight:\s*(\d+)', out)
                        if mw and mh:
                            w, h = int(mw.group(1)), int(mh.group(1))
                            self.log(f"Game resolution (from image): {w}x{h}")
                            return (w, h)
                    except Exception:
                        pass
                    break  # basta il primo che funziona
        except Exception:
            pass

        self.log("Game resolution: unknown (videos will not be scaled)")
        return None

    @staticmethod
    def _renpy_name_to_filename(name: str) -> str:
        """Converte un nome immagine Ren'Py in nome file safe.

        Ren'Py usa spazi nei nomi image ma i file usano `_`.
        Mantiene case originale (Ren'Py e' case-insensitive nei nomi
        ma alcuni giochi fanno affidamento sulla case dei file).
        """
        return name.replace(' ', '_')

    def _image_rel_path(self, file_path: Path) -> str:
        """Restituisce il percorso relativo da usare in un'istruzione image.

        Se il file e' dentro game/images/, restituisce il path relativo
        a images/. Altrimenti cerca di calcolare il path relativo a game/.
        Se il file non e' dentro game_dir (es. export in cartella temporanea),
        restituisce solo il nome file dentro images/.
        """
        images_dir = self.game_dir / "images"
        try:
            if file_path.parent == images_dir or images_dir in file_path.parents:
                return str(file_path.relative_to(images_dir).as_posix())
        except ValueError:
            pass
        try:
            return str(file_path.relative_to(self.game_dir).as_posix())
        except ValueError:
            # Il file non e' dentro game_dir (es. export in temp dir):
            # usa il nome file dentro images/
            return file_path.name

    def _unique_video_name(self, video_path: Path) -> str:
        """Restituisce il nome file per game/videos/.

        Usa il nome originale del video. Le immagini sostituite sono
        statiche (JPG), quindi non ci possono essere collisioni con
        video originali del gioco.
        """
        return video_path.name

    def _unique_frame_name(self, frame_path: Path) -> tuple[str, str]:
        """Restituisce (nome_file, nome_renpy) univoco per video frames.

        Returns:
            (filename, renpy_name) dove renpy_name e' il nome senza
            estensione da usare come `image="..."` nel Movie.
        """
        # Usa lo stem del file come nome Ren'Py, sanitizzato
        # (i nomi image di Ren'Py non possono contenere . o - o altri caratteri speciali)
        renpy_name = self._safe_renpy_name(frame_path.stem)
        target_name = frame_path.name
        target = self.frames_dir / target_name
        if not target.exists():
            return target_name, renpy_name
        stem = frame_path.stem
        suffix = frame_path.suffix
        idx = 2
        while target.exists():
            target_name = f"{stem}_fan{idx}{suffix}"
            target = self.frames_dir / target_name
            idx += 1
        # Il nome Ren'Py segue il nome file (senza ext), sanitizzato
        renpy_name = self._safe_renpy_name(Path(target_name).stem)
        return target_name, renpy_name

    @staticmethod
    def _safe_renpy_name(name: str) -> str:
        """Converte un nome file in un nome valido per `image` di Ren'Py.

        Ren'Py image names can contain letters, digits, underscores and spaces.
        Everything else is replaced with underscore.
        """
        import re
        return re.sub(r"[^\w]+", "_", name).strip("_")

    # ------------------------------------------------------------------ #
    # Generazione
    # ------------------------------------------------------------------ #
    def generate(self, entries: list[PatchEntry]) -> Path:
        """Genera il patch con le associazioni fornite.

        Le entry senza video (in attesa) vengono skippate con un warning.

        Args:
            entries: lista di PatchEntry (immagine -> video).

        Returns:
            Path del file fan_videos.rpy generato, oppure None se nessuna
            entry ha un video associato.
        """
        if not entries:
            self.log("Nessuna associazione da generare")
            return None

        # Filtra le entry in attesa (senza video)
        pending = [e for e in entries if not e.has_video]
        active = [e for e in entries if e.has_video]
        if pending:
            self.log(f"Skip di {len(pending)} entry in attesa di video:")
            for e in pending:
                self.log(f"  - {e.image_name}")
        if not active:
            self.log("Nessuna entry con video associato: impossibile generare")
            return None

        # Crea le directory necessarie
        self.videos_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(parents=True, exist_ok=True)

        lines = []
        lines.append("# ============================================================")
        lines.append("# Fan Video Patch - generato da RenPy-Fan-Video")
        lines.append(f"# Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"# Immagini sostituite: {len(active)}")
        lines.append("#")
        lines.append("# Questo file sovrascrive le definizioni `image` originali")
        lines.append("# del gioco con video Movie. Usa init 999 per garantire")
        lines.append("# che le definizioni vengano caricate DOPO quelle originali,")
        lines.append("# indipendentemente dall'ordine di caricamento dei file.")
        lines.append("#")
        lines.append("# Per disinstallare: elimina questo file fan_videos.rpy")
        lines.append("# e i video associati in game/videos/fanvideomod/ (vedi lista sotto).")
        lines.append("# ============================================================")
        lines.append("")
        lines.append("init 999:")

        copied_videos = []
        copied_frames = []

        for entry in active:
            # --- Copia video ---
            video_filename = self._unique_video_name(entry.video_path)
            video_dest = self.videos_dir / video_filename
            if not video_dest.exists():
                self.log(f"Copia video: {entry.video_path.name} -> videos/fanvideomod/{video_filename}")
                shutil.copy2(entry.video_path, video_dest)
                copied_videos.append(video_dest)
            else:
                self.log(f"Video gia' presente: videos/fanvideomod/{video_filename}")

            # --- Copia last frame (opzionale) ---
            last_frame_renpy = None
            if entry.last_frame_path and entry.last_frame_path.exists():
                frame_filename, frame_renpy = self._unique_frame_name(
                    entry.last_frame_path)
                frame_dest = self.frames_dir / frame_filename
                if not frame_dest.exists():
                    self.log(f"Copia last frame: {entry.last_frame_path.name} "
                             f"-> images/fanvideomod/{frame_filename}")
                    shutil.copy2(entry.last_frame_path, frame_dest)
                    copied_frames.append(frame_dest)
                last_frame_renpy = frame_renpy
            elif entry.last_frame_name:
                # Nome fornito senza file (riferimento a immagine esistente)
                last_frame_renpy = entry.last_frame_name

            # --- Definizioni frame statici ---
            start_img = entry.start_image or entry.image_name
            if entry.start_image_path and entry.start_image_path.exists():
                first_rel = self._image_rel_path(entry.start_image_path)
                lines.append(f'    image {start_img} = "{first_rel}"')
                self.log(f"  first frame: {start_img} = {first_rel}")

            if last_frame_renpy and entry.last_frame_path:
                frame_rel = f"fanvideomod/{frame_dest.name}"
                if self.screen_size:
                    # Scala il last frame alla risoluzione del gioco
                    # usando im.Scale che ridimensiona l'immagine
                    sw, sh = self.screen_size
                    lines.append(
                        f'    image {last_frame_renpy} = im.Scale("{frame_rel}", '
                        f'{sw}, {sh})'
                    )
                else:
                    lines.append(f'    image {last_frame_renpy} = "{frame_rel}"')
                self.log(f"  last frame: {last_frame_renpy} = {frame_rel}")

            # --- Genera riga image ---
            movie_args = [f'play="videos/fanvideomod/{video_filename}"']
            movie_args.append(f'start_image="{start_img}"')

            # Scala il video alla risoluzione del gioco se rilevata
            if self.screen_size:
                movie_args.append(f'size=({self.screen_size[0]}, {self.screen_size[1]})')

            if last_frame_renpy:
                movie_args.append(f'image="{last_frame_renpy}"')
                movie_args.append('loop=False')
            elif not entry.loop:
                movie_args.append('loop=False')

            movie_call = f"Movie({', '.join(movie_args)})"
            line = f'    image {entry.image_name} = {movie_call}'
            lines.append(line)
            self.log(f"  {entry.image_name}  ->  {movie_call}")

        lines.append("")
        rpy_path = self.patch_dir / "fan_videos.rpy"
        rpy_path.write_text('\n'.join(lines), encoding='utf-8')
        self.log(f"\nPatch generato: {rpy_path}")
        self.log(f"  {len(copied_videos)} video copiati in {self.videos_dir}")
        self.log(f"  {len(copied_frames)} last frame copiati in {self.frames_dir}")

        return rpy_path


# ---------------------------------------------------------------------- #
# Test da CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Uso: python fv_generator.py <game_path> <video.webm> [image_name] [last_frame.jpg]")
        sys.exit(1)

    game_path = sys.argv[1]
    video = Path(sys.argv[2])
    image_name = sys.argv[3] if len(sys.argv) > 3 else "test_image"
    last_frame = Path(sys.argv[4]) if len(sys.argv) > 4 else None

    entry = PatchEntry(
        image_name=image_name,
        video_path=video,
        start_image=image_name,
        last_frame_path=last_frame,
        loop=last_frame is None,
    )

    gen = FVGenerator(game_path)
    out = gen.generate([entry])
    if out:
        print(f"\nGenerato: {out}")
