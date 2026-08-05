# RenPy-Fan-Video

Tool standalone (PySide6) per creare patch video per giochi Ren'Py.

## Cosa fa

RenPy-Fan-Video estrae le immagini statiche usate nelle scene di un gioco Ren'Py e permette di sostituirle con video `.webm` generati esternamente. Il tool genera un file `.rpy` che ridefinisce le `image` originali con `Movie(...)`, seguendo il meccanismo del patch "AWAM Fan Animations": essendo caricato dopo le definizioni originali, l'ultima `image` vince e non e' necessario modificare i file del gioco.

## Requisiti

- Python 3.9+
- PySide6 6.6+
- Pillow 10+
- uv (gestito automaticamente dagli script `start.sh` / `start.bat`)
- ffmpeg installato (opzionale, per conversioni future)

## Avvio

### macOS / Linux

```bash
./start.sh
```

### Windows

```bat
start.bat
```

## Uso

1. **Seleziona il gioco**: scegli il `.app` di macOS o la cartella contenente `game/`.
2. **Analizza**: il tool estrae gli `.rpa`, decompila gli `.rpyc` e scansiona le istruzioni `scene` / `show` per trovare le immagini statiche.
3. **Galleria**: filtra e cerca le immagini, visualizza l'anteprima e scegli quella da sostituire.
4. **Associa video**: seleziona un file `.webm` e, opzionalmente, un `last frame` statico.
5. **Genera patch**: il tool crea la cartella `game/fan_video_patch/` contenente `fan_videos.rpy`, copia i video in `game/videos/` e il last frame in `game/images/video frames/`.
6. **Avvia il gioco**: le scene che mostravano l'immagine originale ora riprodurranno il video.

## File generati

- `game/fan_video_patch/fan_videos.rpy` - definizioni `image ... = Movie(...)`
- `game/videos/*.webm` - video copiati
- `game/images/video frames/*` - eventuali last frame
- `game/fan_video_patch/uninstall.txt` - istruzioni per rimuovere il patch

## Struttura progetto

```
RenPy-Fan-Video/
├── fv_tool.py        # GUI PySide6
├── fv_extractor.py   # Estrazione .rpa + decompilazione .rpyc
├── fv_scanner.py     # Scansione scene/show e risoluzione immagini
├── fv_generator.py   # Generazione del patch
├── pyproject.toml    # Dipendenze
├── start.sh          # Launcher macOS/Linux
├── start.bat         # Launcher Windows
└── UnRen Tools/      # rpatool + unrpyc
```

## Note

- Il tool non modifica i file originali del gioco.
- I video devono essere in formato `.webm`.
- L'ultima `image` in Ren'Py vince: caricare il patch dopo le definizioni originali.
