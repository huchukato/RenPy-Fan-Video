#!/usr/bin/env python3
"""
RenPy-Fan-Video - Extractor Module
Gestisce l'estrazione dei file .rpa e la decompilazione dei file .rpyc.

Riusa la logica di RenPy-WTForge/wt_extractor.py, adattata per il tool
di generazione patch video.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def _is_frozen() -> bool:
    """True se stiamo girando dentro un bundle PyInstaller."""
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def _get_python_executable() -> str:
    """Restituisce il path di un Python eseguibile per i subprocess.

    In un'app PyInstaller frozen, sys.executable e' l'app stessa, non
    Python. Usarlo per subprocess rilancerebbe l'intera app (fork bomb).
    Cerchiamo invece il Python di sistema.
    """
    if not _is_frozen():
        return sys.executable

    # Cerca Python di sistema in ordine di preferenza
    candidates = [
        "/opt/homebrew/bin/python3",
        "/usr/local/bin/python3",
        "/usr/bin/python3",
        "/Library/Frameworks/Python.framework/Versions/Current/bin/python3",
    ]
    for p in candidates:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # Fallback: shutil.which
    found = shutil.which("python3")
    if found:
        return found

    # Ultimo resort: sys.executable (causera' fork bomb, ma almeno
    # non crashiamo silenziosamente)
    return sys.executable


class FVExtractor:
    """Estrae archivi .rpa e decompila .rpyc di un gioco Ren'Py."""

    def __init__(self, game_path, output_dir=None, log_callback=None):
        """
        Args:
            game_path: percorso al gioco (.app macOS o cartella Windows/Linux).
            output_dir: directory di output (default: game_path/game).
            log_callback: funzione(str) per log testuale.
        """
        self.game_path = Path(game_path)
        self.output_dir = Path(output_dir) if output_dir else self._find_game_dir()
        self.script_dir = Path(__file__).parent
        self.unren_tools = self.script_dir / "UnRen Tools"
        self.log = log_callback or (lambda msg: print(msg))

    # ------------------------------------------------------------------ #
    # Risoluzione percorsi
    # ------------------------------------------------------------------ #
    def _find_game_dir(self):
        """Trova la directory `game` del gioco Ren'Py."""
        # macOS .app: Game.app/Contents/Resources/autorun/game
        if self.game_path.suffix == '.app':
            game_dir = self.game_path / "Contents" / "Resources" / "autorun" / "game"
            if game_dir.exists():
                return game_dir

        # Cartella con sub-directory `game`
        game_dir = self.game_path / "game"
        if game_dir.exists():
            return game_dir

        # Assume che il percorso sia già la directory `game`
        return self.game_path

    # ------------------------------------------------------------------ #
    # Estrazione .rpa
    # ------------------------------------------------------------------ #
    def _rpa_marker(self, rpa_file):
        return rpa_file.with_suffix('.rpa.extracted')

    def _is_extracted(self, rpa_file):
        return self._rpa_marker(rpa_file).exists()

    def _mark_extracted(self, rpa_file):
        try:
            self._rpa_marker(rpa_file).touch()
        except Exception:
            pass

    def extract_rpa_files(self, progress_callback=None):
        """Estrae tutti i .rpa nella directory game.

        Args:
            progress_callback: funzione(current, total) per aggiornare la UI.

        Returns:
            bool: True se l'estrazione e' completata con successo.
        """
        rpa_files = list(self.output_dir.glob("*.rpa"))

        if not rpa_files:
            self.log("Nessun file .rpa trovato")
            return True

        self.log(f"Trovati {len(rpa_files)} file .rpa da estrarre")
        rpatool_path = self.unren_tools / "rpatool"

        for i, rpa_file in enumerate(rpa_files):
            if progress_callback:
                progress_callback(i + 1, len(rpa_files))

            if self._is_extracted(rpa_file):
                self.log(f"Gia' estratto, salto: {rpa_file.name}")
                try:
                    rpa_file.unlink()
                except Exception as e:
                    self.log(f"Avviso: impossibile rimuovere {rpa_file.name}: {e}")
                continue

            self.log(f"Estrazione di {rpa_file.name}...")
            try:
                result = subprocess.run(
                    [_get_python_executable(), str(rpatool_path), '-x',
                     str(rpa_file), '-o', str(self.output_dir)],
                    capture_output=True, text=True
                )
                if result.returncode != 0:
                    self.log(f"Errore nell'estrazione di {rpa_file.name}: {result.stderr}")
                    return False
            except Exception as e:
                self.log(f"Errore durante l'estrazione: {e}")
                return False

            try:
                rpa_file.unlink()
                self._mark_extracted(rpa_file)
                self.log(f"Estratto e rimosso: {rpa_file.name}")
            except Exception as e:
                self.log(f"Avviso: impossibile rimuovere {rpa_file.name}: {e}")

        self.log("Estrazione completata")
        return True

    # ------------------------------------------------------------------ #
    # Decompilazione .rpyc
    # ------------------------------------------------------------------ #
    def decompile_rpyc_files(self, progress_callback=None):
        """Decompila tutti i .rpyc nella directory game.

        Salta i file di sistema (gui, screens, options, images) e quelli
        per cui esiste gia' un .rpy piu' recente.

        Args:
            progress_callback: funzione(current, total).

        Returns:
            bool: True se la decompilazione e' completata con successo.
        """
        rpyc_files = []
        for rpyc_file in self.output_dir.rglob("*.rpyc"):
            if any(x in rpyc_file.name.lower()
                   for x in ['gui', 'screens', 'options', 'images']):
                continue
            rpy_file = rpyc_file.with_suffix('.rpy')
            if rpy_file.exists() and rpy_file.stat().st_mtime >= rpyc_file.stat().st_mtime:
                continue
            rpyc_files.append(rpyc_file)

        if not rpyc_files:
            self.log("Nessun file .rpyc da decompilare (gia' presenti)")
            return True

        self.log(f"Trovati {len(rpyc_files)} file .rpyc da decompilare")

        decompiler_dir = self.unren_tools / "decompiler"
        if str(decompiler_dir) not in sys.path:
            sys.path.insert(0, str(decompiler_dir))

        unrpyc_path = self.unren_tools / "unrpyc.py"

        # Decompila in batch per evitare problemi con troppi argomenti
        batch_size = 50
        for i in range(0, len(rpyc_files), batch_size):
            batch = rpyc_files[i:i + batch_size]
            if progress_callback:
                progress_callback(i + len(batch), len(rpyc_files))

            try:
                py = _get_python_executable()
                # In app frozen, forziamo single-process (-p 1) per evitare
                # che multiprocessing.Pool rilanci l'app
                extra_args = ['-p', '1'] if _is_frozen() else []
                result = subprocess.run(
                    [py, str(unrpyc_path), '-c'] + extra_args + [str(f) for f in batch],
                    capture_output=True, text=True, cwd=str(self.output_dir)
                )
                if result.returncode != 0:
                    self.log(f"Errore nella decompilazione: {result.stderr}")
                    return False
            except Exception as e:
                self.log(f"Errore durante la decompilazione: {e}")
                return False

        self.log("Decompilazione completata")
        return True

    # ------------------------------------------------------------------ #
    # Elenco file .rpy
    # ------------------------------------------------------------------ #
    def get_rpy_files(self):
        """Restituisce la lista dei file .rpy per l'analisi."""
        rpy_files = []
        for rpy_file in self.output_dir.rglob("*.rpy"):
            # Escludi file di sistema e patch gia' generate
            if any(x in rpy_file.name.lower()
                   for x in ['gui', 'screens', 'options', 'images',
                             'fan_videos', 'fan_video_patch']):
                continue
            rpy_files.append(rpy_file)
        return rpy_files


# ---------------------------------------------------------------------- #
# Test da CLI
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python fv_extractor.py <percorso_gioco>")
        sys.exit(1)

    extractor = FVExtractor(sys.argv[1])
    print(f"Directory di output: {extractor.output_dir}")
    extractor.extract_rpa_files()
    extractor.decompile_rpyc_files()

    rpy_files = extractor.get_rpy_files()
    print(f"\nFile .rpy trovati: {len(rpy_files)}")
    for rpy in rpy_files[:5]:
        print(f"  - {rpy.name}")
