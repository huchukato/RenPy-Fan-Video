#!/usr/bin/env python3
"""
RenPy-Fan-Video - GUI PySide6
Interfaccia grafica a 3 tab per analizzare giochi Ren'Py e generare patch video.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import cast

from PySide6.QtCore import Qt, QThread, Signal, QSize, QObject, QUrl
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fv_extractor import FVExtractor
from fv_generator import FVGenerator, PatchEntry


class NaturalSortItem(QTableWidgetItem):
    """QTableWidgetItem con sorting naturale (numeric-aware).

    Ordina "1", "2", "10" invece di "1", "10", "2".
    """

    @staticmethod
    def _natural_key(s: str) -> list:
        # Ogni elemento e' una tupla (flag, valore): flag 0 per il testo,
        # 1 per i numeri. Cosi' il confronto e' sempre tra tipi omogenei
        # (mai str comparato con int) indipendentemente da come si
        # alternano testo/numeri nelle due stringhe confrontate.
        return [(1, int(t)) if t.isdigit() else (0, t.lower())
                for t in re.split(r'(\d+)', s) if t != '']

    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        return self._natural_key(self.text()) < self._natural_key(other.text())


class SourceSortItem(NaturalSortItem):
    """Item per la colonna "Source" della Galleria: ordina per timeline
    (prima per file .rpy in ordine naturale, poi per numero di riga),
    non solo per nome del file. Usa i dati (StaticImage) salvati in
    Qt.UserRole per recuperare la riga di prima apparizione.
    """

    def __lt__(self, other):
        if not isinstance(other, QTableWidgetItem):
            return super().__lt__(other)
        my_img = self.data(Qt.UserRole)
        other_img = other.data(Qt.UserRole)
        if my_img is not None and other_img is not None:
            my_used = my_img.used_in[0] if my_img.used_in else (None, 0)
            other_used = other_img.used_in[0] if other_img.used_in else (None, 0)
            my_key = (self._natural_key(str(my_used[0])), my_used[1])
            other_key = (self._natural_key(str(other_used[0])), other_used[1])
            return my_key < other_key
        return super().__lt__(other)


class PatchTable(QTableWidget):
    """QTableWidget del tab Patch con supporto tasti Canc/Backspace."""

    delete_pressed = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self.delete_pressed.emit()
        else:
            super().keyPressEvent(event)


from fv_project import FVProject, PROJECTS_ROOT
from fv_scanner import FVScanner, StaticImage


def _app_icon() -> QIcon:
    """Restituisce l'icona dell'applicazione dal logo in img/."""
    logo = Path(__file__).parent / "img" / "logo_256.png"
    if logo.exists():
        return QIcon(str(logo))
    return QIcon()


# ====================================================================== #
# Localizzazione
# ====================================================================== #
TRANSLATIONS = {
    'en': {
        'title': "RenPy-Fan-Video",
        'tab_game': "1. Game",
        'tab_gallery': "2. Gallery",
        'tab_patch': "3. Patch",
        # Tab 1 - Game
        'no_game_selected': "No game selected",
        'btn_app': "Select .app (macOS)",
        'btn_folder': "Select game folder",
        'btn_analyze': "Analyze",
        'select_app_title': "Select Ren'Py .app",
        'select_folder_title': "Select game folder",
        'select_game_first': "Select a game to analyze first.",
        'analyzing': "Analyzing...",
        'analysis_done_title': "Analysis complete",
        'analysis_done_msg': "Found {} used images.",
        'too_many_images': "Showing {} of {} images. Use the search filter to narrow down.",
        'analysis_error_title': "Analysis error",
        'extracting_rpa': "Extracting .rpa archives...",
        'extract_failed': ".rpa extraction failed",
        'decompiling_rpyc': "Decompiling .rpyc files...",
        'decompile_failed': ".rpyc decompilation failed",
        'scanning_images': "Scanning static images...",
        'found_images': "Found {} used images",
        # Tab 2 - Gallery
        'search_placeholder': "Search by name...",
        'filter_all': "All",
        'filter_static': "Static only",
        'filter_movie': "Already animated",
        'filter_file_all': "All files",
        'col_name': "Name",
        'col_source': "Source",
        'col_line': "Line",
        'col_movie': "Movie",
        'btn_export': "Export image",
        'btn_export_tip': "Copy the selected image to the project folder "
                          "(FanVideoProjects/<game>/sources/) so you can use it "
                          "as input to generate the video with external AI tools.",
        'preview': "Preview",
        'preview_unavailable': "Preview unavailable",
        'select_image_first': "Select an image from the gallery first.",
        'image_not_resolved': "{} has no resolved image file.",
        'cannot_export': "{} has no resolved image file on disk.\nCannot export.",
        'already_movie_title': "Already animated",
        'already_movie_msg': "{} is already defined as Movie. Override it?",
        'export_done_title': "Export complete",
        'export_done_msg': "<b>Image exported:</b><br>{}<br><br>"
                           "You can now use this image as input to generate "
                           "the video with an external AI tool "
                           "(motionmuse.ai, ComfyUI, pollo.ai, etc.).<br><br>"
                           "The image has been added to the Patch tab as "
                           "<b>'pending video'</b>. When the video is ready, "
                           "go to the Patch tab and double-click the row to "
                           "associate it.",
        'btn_open_sources': "Open sources folder",
        'btn_close': "Close",
        'file_label': "File",
        'source_label': "Source",
        'already_replaced': "Already replaced",
        'yes': "Yes",
        'no': "No",
        'not_resolved': "not resolved",
        # Tab 3 - Patch
        'patch_info': "<b style='color:#facc15'>Pending</b> entries have the image "
                      "exported but no video yet. <b>Double-click</b> the Video cell "
                      "of a row to associate (or replace) the generated video manually.",
        'col_image': "Image",
        'col_video': "Video",
        'col_last_frame': "Last frame",
        'col_loop': "Loop",
        'col_status': "Status",
        'btn_add_video': "Add Video",
        'btn_add_video_tip': "Manually associate (or replace) the video of the selected row. "
                             "Use this as a fallback when auto-associate can't find a match.",
        'btn_remove': "Remove selected",
        'btn_associate': "Auto-associate videos...",
        'btn_associate_tip': "Select a folder of .webm videos; each is matched to an image by name",
        'auto_assoc_title': "Select videos folder",
        'auto_assoc_done': "Associated {}/{} videos ({} last frames extracted)",
        'auto_assoc_nomatch': "No matching videos found in the selected folder",
        'btn_remove_patch': "Remove Patch",
        'btn_remove_patch_tip': "Delete fan_videos.rpy and associated videos from the game",
        'remove_patch_title': "Remove Patch",
        'remove_patch_msg': "This will delete fan_videos.rpy and all associated video files from the game folder. Proceed?",
        'remove_patch_done': "Patch removed successfully.",
        'remove_patch_nothing': "No patch found in the game folder.",
        'btn_generate': "Generate Patch",
        'btn_export_mod': "Export Mod",
        'btn_export_mod_tip': "Create a zip archive of the patch to share",
        'export_title': "Export Mod",
        'export_choose_dir': "Choose where to save the mod zip",
        'export_no_patch': "Generate the patch first before exporting.",
        'export_done_title': "Mod exported",
        'export_done_msg': "Mod exported to:<br><b>{}</b>",
        'export_error_title': "Export error",
        'export_empty': "Nothing to export. Generate a patch first.",
        'pending_video': "(pending)",
        'status_ready': "ready",
        'status_pending': "pending",
        'select_patch_row': "Select a row from the Patch tab.",
        'patch_no_selection': "Select a row to preview the image.",
        'no_assignments': "No video assignments to generate.",
        'invalid_game_path': "Invalid game path.",
        'pending_entries_title': "Pending entries",
        'pending_entries_msg': "{} entries are without video (pending) and "
                               "will be skipped. Proceed with {} ready entries?",
        'no_active_entries': "No entry has an associated video. "
                             "Associate videos to exported images first.",
        'nothing_generated': "Nothing generated.",
        'patch_generated_title': "Patch generated",
        'patch_generated_msg': "Patch generated:<br><b>{}</b><br><br>"
                               "Make sure the file is loaded after the "
                               "game's original definitions.",
        'generation_error_title': "Generation error",
        'error_title': "Error",
        # AssociateDialog
        'dlg_associate_title': "Associate video to {}",
        'dlg_image': "Image",
        'dlg_file': "File",
        'dlg_no_video': "No video selected",
        'dlg_choose_video': "Choose .webm video",
        'dlg_no_last_frame': "No last frame",
        'dlg_last_frame_auto': "The last frame will be extracted automatically from the video.",
        'dlg_last_frame_extracted': "Last frame extracted: {}",
        'dlg_last_frame_failed': "Could not extract last frame automatically.",
        'dlg_loop': "Loop the video",
        'dlg_add_to_patch': "Add to patch",
        'dlg_cancel': "Cancel",
        'dlg_select_video_title': "Select .webm video",
        'dlg_select_last_frame_title': "Select last frame",
        'dlg_invalid_video': "Select a valid video file.",
        'dlg_only_webm': "Only .webm files are supported.",
        # Session restore
        'session_restored_title': "Session restored",
        'session_restored_msg': "Restored previous session for:<br><b>{}</b><br>"
                                "Images: {} | Assignments: {} ({} with video)<br><br>"
                                "The gallery has been repopulated from the saved analysis.",
        'session_restore_failed': "Could not restore previous session: {}",
        'session_none': "No previous session found.",
        'language': "Language",
    },
    'it': {
        'title': "RenPy-Fan-Video",
        'tab_game': "1. Gioco",
        'tab_gallery': "2. Galleria",
        'tab_patch': "3. Patch",
        'no_game_selected': "Nessun gioco selezionato",
        'btn_app': "Seleziona .app (macOS)",
        'btn_folder': "Seleziona cartella gioco",
        'btn_analyze': "Analizza",
        'select_app_title': "Seleziona .app Ren'Py",
        'select_folder_title': "Seleziona cartella del gioco",
        'select_game_first': "Seleziona prima il gioco da analizzare.",
        'analyzing': "Analisi in corso...",
        'analysis_done_title': "Analisi completata",
        'analysis_done_msg': "Trovate {} immagini usate.",
        'too_many_images': "Visualizzazione di {} su {} immagini. Usa il filtro di ricerca per restringere.",
        'analysis_error_title': "Errore analisi",
        'extracting_rpa': "Estrazione archivi .rpa in corso...",
        'extract_failed': "Estrazione .rpa fallita",
        'decompiling_rpyc': "Decompilazione .rpyc in corso...",
        'decompile_failed': "Decompilazione .rpyc fallita",
        'scanning_images': "Scansione immagini statiche...",
        'found_images': "Trovate {} immagini usate",
        'search_placeholder': "Cerca per nome...",
        'filter_all': "Tutte",
        'filter_static': "Solo statiche",
        'filter_movie': "Gia' animate",
        'filter_file_all': "Tutti i file",
        'col_name': "Nome",
        'col_source': "Sorgente",
        'col_line': "Riga",
        'col_movie': "Movie",
        'btn_export': "Esporta immagine",
        'btn_export_tip': "Copia l'immagine selezionata nella cartella di progetto "
                          "(FanVideoProjects/<gioco>/sources/) cosi' puoi usarla "
                          "come input per generare il video con tool AI esterni.",
        'preview': "Anteprima",
        'preview_unavailable': "Anteprima non disponibile",
        'select_image_first': "Seleziona prima un'immagine dalla galleria.",
        'image_not_resolved': "{} non ha un file immagine risolto.",
        'cannot_export': "{} non ha un file immagine risolto su disco.\nImpossibile esportarla.",
        'already_movie_title': "Gia' animata",
        'already_movie_msg': "{} risulta gia' definita come Movie. Vuoi sovrascriverla?",
        'export_done_title': "Esportazione completata",
        'export_done_msg': "<b>Immagine esportata:</b><br>{}<br><br>"
                           "Ora puoi usare questa immagine come input per generare "
                           "il video con un tool AI esterno "
                           "(motionmuse.ai, ComfyUI, pollo.ai, ecc.).<br><br>"
                           "L'immagine e' stata aggiunta al tab Patch come "
                           "<b>'in attesa di video'</b>. Quando il video sara' pronto, "
                           "vai nel tab Patch e fai doppio click sulla riga per associarlo.",
        'btn_open_sources': "Apri cartella sources",
        'btn_close': "Chiudi",
        'file_label': "File",
        'source_label': "Sorgente",
        'already_replaced': "Gia' sostituita",
        'yes': "Si",
        'no': "No",
        'not_resolved': "non risolto",
        'patch_info': "Le entry <b style='color:#facc15'>in attesa</b> hanno l'immagine "
                      "esportata ma senza video. Fai <b>doppio click</b> sulla cella "
                      "Video di una riga per associare (o sostituire) il video manualmente.",
        'col_image': "Immagine",
        'col_video': "Video",
        'col_last_frame': "Last frame",
        'col_loop': "Loop",
        'col_status': "Stato",
        'btn_add_video': "Aggiungi Video",
        'btn_add_video_tip': "Associa (o sostituisce) manualmente il video della riga selezionata. "
                             "Usalo come fallback quando l'auto-associazione non trova un match.",
        'btn_remove': "Rimuovi selezionati",
        'btn_associate': "Auto-associa video...",
        'btn_associate_tip': "Seleziona una cartella di video .webm; ogni video viene associato all'immagine con lo stesso nome",
        'auto_assoc_title': "Seleziona cartella video",
        'auto_assoc_done': "Associati {}/{} video ({} last frame estratti)",
        'auto_assoc_nomatch': "Nessun video corrispondente nella cartella selezionata",
        'btn_remove_patch': "Rimuovi Patch",
        'btn_remove_patch_tip': "Elimina fan_videos.rpy e i video associati dal gioco",
        'remove_patch_title': "Rimuovi Patch",
        'remove_patch_msg': "Verranno eliminati fan_videos.rpy e tutti i video associati dalla cartella del gioco. Procedere?",
        'remove_patch_done': "Patch rimossa con successo.",
        'remove_patch_nothing': "Nessuna patch trovata nella cartella del gioco.",
        'btn_generate': "Genera Patch",
        'btn_export_mod': "Esporta Mod",
        'btn_export_mod_tip': "Crea un archivio zip della patch da condividere",
        'export_title': "Esporta Mod",
        'export_choose_dir': "Scegli dove salvare lo zip della mod",
        'export_no_patch': "Genera prima la patch prima di esportare.",
        'export_done_title': "Mod esportata",
        'export_done_msg': "Mod esportata in:<br><b>{}</b>",
        'export_error_title': "Errore esportazione",
        'export_empty': "Niente da esportare. Genera prima una patch.",
        'pending_video': "(in attesa)",
        'status_ready': "pronto",
        'status_pending': "in attesa",
        'select_patch_row': "Seleziona una riga dal tab Patch.",
        'patch_no_selection': "Seleziona una riga per vedere l'anteprima.",
        'no_assignments': "Nessun'associazione video da generare.",
        'invalid_game_path': "Percorso del gioco non valido.",
        'pending_entries_title': "Entry in attesa",
        'pending_entries_msg': "{} entry sono senza video (in attesa) e verranno "
                               "saltate. Procedere con {} entry pronte?",
        'no_active_entries': "Nessuna entry ha un video associato. "
                             "Associa prima i video alle immagini esportate.",
        'nothing_generated': "Nessuna riga generata.",
        'patch_generated_title': "Patch generato",
        'patch_generated_msg': "Patch generato:<br><b>{}</b><br><br>"
                               "Assicurati che il file venga caricato "
                               "dopo le definizioni originali del gioco.",
        'generation_error_title': "Errore generazione",
        'error_title': "Errore",
        'dlg_associate_title': "Associa video a {}",
        'dlg_image': "Immagine",
        'dlg_file': "File",
        'dlg_no_video': "Nessun video selezionato",
        'dlg_choose_video': "Scegli video .webm",
        'dlg_no_last_frame': "Nessun last frame",
        'dlg_last_frame_auto': "L'ultimo fotogramma verra' estratto automaticamente dal video.",
        'dlg_last_frame_extracted': "Ultimo fotogramma estratto: {}",
        'dlg_last_frame_failed': "Impossibile estrarre l'ultimo fotogramma automaticamente.",
        'dlg_loop': "Ripeti il video in loop",
        'dlg_add_to_patch': "Aggiungi al patch",
        'dlg_cancel': "Annulla",
        'dlg_select_video_title': "Seleziona video .webm",
        'dlg_select_last_frame_title': "Seleziona last frame",
        'dlg_invalid_video': "Seleziona un file video valido.",
        'dlg_only_webm': "Sono supportati solo file .webm.",
        'session_restored_title': "Sessione ripristinata",
        'session_restored_msg': "Ripristinata sessione precedente per:<br><b>{}</b><br>"
                                "Immagini: {} | Associazioni: {} ({} con video)<br><br>"
                                "La galleria e' stata ripopolata dall'analisi salvata.",
        'session_restore_failed': "Impossibile ripristinare la sessione precedente: {}",
        'session_none': "Nessuna sessione precedente trovata.",
        'language': "Lingua",
    },
    'es': {
        'title': "RenPy-Fan-Video",
        'tab_game': "1. Juego",
        'tab_gallery': "2. Galeria",
        'tab_patch': "3. Patch",
        'no_game_selected': "Ningun juego seleccionado",
        'btn_app': "Seleccionar .app (macOS)",
        'btn_folder': "Seleccionar carpeta del juego",
        'btn_analyze': "Analizar",
        'select_app_title': "Seleccionar .app Ren'Py",
        'select_folder_title': "Seleccionar carpeta del juego",
        'select_game_first': "Selecciona primero el juego para analizar.",
        'analyzing': "Analizando...",
        'analysis_done_title': "Analisis completado",
        'analysis_done_msg': "Encontradas {} imagenes usadas.",
        'too_many_images': "Mostrando {} de {} imagenes. Usa el filtro de busqueda para reducir.",
        'analysis_error_title': "Error de analisis",
        'extracting_rpa': "Extrayendo archivos .rpa...",
        'extract_failed': "Extraccion .rpa fallida",
        'decompiling_rpyc': "Descompilando archivos .rpyc...",
        'decompile_failed': "Descompilacion .rpyc fallida",
        'scanning_images': "Escaneando imagenes estaticas...",
        'found_images': "Encontradas {} imagenes usadas",
        'search_placeholder': "Buscar por nombre...",
        'filter_all': "Todas",
        'filter_static': "Solo estaticas",
        'filter_movie': "Ya animadas",
        'filter_file_all': "Todos los archivos",
        'col_name': "Nombre",
        'col_source': "Origen",
        'col_line': "Linea",
        'col_movie': "Movie",
        'btn_export': "Exportar imagen",
        'btn_export_tip': "Copia la imagen seleccionada a la carpeta del proyecto "
                          "(FanVideoProjects/<juego>/sources/) para usarla "
                          "como entrada para generar el video con herramientas "
                          "de IA externas.",
        'preview': "Vista previa",
        'preview_unavailable': "Vista previa no disponible",
        'select_image_first': "Selecciona primero una imagen de la galeria.",
        'image_not_resolved': "{} no tiene un archivo de imagen resuelto.",
        'cannot_export': "{} no tiene un archivo de imagen resuelto en disco.\nNo se puede exportar.",
        'already_movie_title': "Ya animada",
        'already_movie_msg': "{} ya esta definida como Movie. Deseas sobrescribirla?",
        'export_done_title': "Exportacion completada",
        'export_done_msg': "<b>Imagen exportada:</b><br>{}<br><br>"
                           "Ahora puedes usar esta imagen como entrada para generar "
                           "el video con una herramienta de IA externa "
                           "(motionmuse.ai, ComfyUI, pollo.ai, etc.).<br><br>"
                           "La imagen se ha anadido a la pestana Patch como "
                           "<b>'pendiente de video'</b>. Cuando el video este listo, "
                           "ve a la pestana Patch y haz doble clic en la fila para "
                           "asociarlo.",
        'btn_open_sources': "Abrir carpeta sources",
        'btn_close': "Cerrar",
        'file_label': "Archivo",
        'source_label': "Origen",
        'already_replaced': "Ya reemplazada",
        'yes': "Si",
        'no': "No",
        'not_resolved': "no resuelto",
        'patch_info': "Las entradas <b style='color:#facc15'>pendientes</b> tienen "
                      "la imagen exportada pero sin video. Haz <b>doble clic</b> en "
                      "la celda Video de una fila para asociar (o reemplazar) el video manualmente.",
        'col_image': "Imagen",
        'col_video': "Video",
        'col_last_frame': "Ultimo frame",
        'col_loop': "Loop",
        'col_status': "Estado",
        'btn_add_video': "Anadir Video",
        'btn_add_video_tip': "Asocia (o reemplaza) manualmente el video de la fila seleccionada. "
                             "Usalo como respaldo cuando la auto-asociacion no encuentra coincidencia.",
        'btn_remove': "Eliminar seleccionados",
        'btn_associate': "Auto-asociar videos...",
        'btn_associate_tip': "Selecciona una carpeta de videos .webm; cada video se asocia a la imagen con el mismo nombre",
        'auto_assoc_title': "Seleccionar carpeta de videos",
        'auto_assoc_done': "Asociados {}/{} videos ({} ultimos frames extraidos)",
        'auto_assoc_nomatch': "No se encontraron videos coincidentes en la carpeta seleccionada",
        'btn_remove_patch': "Eliminar Patch",
        'btn_remove_patch_tip': "Eliminar fan_videos.rpy y los videos asociados del juego",
        'remove_patch_title': "Eliminar Patch",
        'remove_patch_msg': "Se eliminaran fan_videos.rpy y todos los videos asociados de la carpeta del juego. Continuar?",
        'remove_patch_done': "Patch eliminado con exito.",
        'remove_patch_nothing': "No se encontro ningun patch en la carpeta del juego.",
        'btn_generate': "Generar Patch",
        'btn_export_mod': "Exportar Mod",
        'btn_export_mod_tip': "Crear un archivo zip del parche para compartir",
        'export_title': "Exportar Mod",
        'export_choose_dir': "Elige donde guardar el zip del mod",
        'export_no_patch': "Genera el parche primero antes de exportar.",
        'export_done_title': "Mod exportado",
        'export_done_msg': "Mod exportado a:<br><b>{}</b>",
        'export_error_title': "Error de exportacion",
        'export_empty': "Nada que exportar. Genera un parche primero.",
        'pending_video': "(pendiente)",
        'status_ready': "listo",
        'status_pending': "pendiente",
        'select_patch_row': "Selecciona una fila de la pestana Patch.",
        'patch_no_selection': "Selecciona una fila para ver la vista previa.",
        'no_assignments': "No hay asociaciones de video para generar.",
        'invalid_game_path': "Ruta del juego no valida.",
        'pending_entries_title': "Entradas pendientes",
        'pending_entries_msg': "{} entradas estan sin video (pendientes) y se "
                               "omitiran. Continuar con {} entradas listas?",
        'no_active_entries': "Ninguna entrada tiene un video asociado. "
                             "Asocia primero los videos a las imagenes exportadas.",
        'nothing_generated': "Nada generado.",
        'patch_generated_title': "Patch generado",
        'patch_generated_msg': "Patch generado:<br><b>{}</b><br><br>"
                               "Asegurate de que el archivo se cargue despues "
                               "de las definiciones originales del juego.",
        'generation_error_title': "Error de generacion",
        'error_title': "Error",
        'dlg_associate_title': "Asociar video a {}",
        'dlg_image': "Imagen",
        'dlg_file': "Archivo",
        'dlg_no_video': "Ningun video seleccionado",
        'dlg_choose_video': "Elegir video .webm",
        'dlg_no_last_frame': "Ningun ultimo frame",
        'dlg_last_frame_auto': "El ultimo fotograma se extraera automaticamente del video.",
        'dlg_last_frame_extracted': "Ultimo fotograma extraido: {}",
        'dlg_last_frame_failed': "No se pudo extraer el ultimo fotograma automaticamente.",
        'dlg_loop': "Repetir el video en loop",
        'dlg_add_to_patch': "Anadir al patch",
        'dlg_cancel': "Cancelar",
        'dlg_select_video_title': "Seleccionar video .webm",
        'dlg_select_last_frame_title': "Seleccionar ultimo frame",
        'dlg_invalid_video': "Selecciona un archivo de video valido.",
        'dlg_only_webm': "Solo se admiten archivos .webm.",
        'session_restored_title': "Sesion restaurada",
        'session_restored_msg': "Restaurada sesion anterior para:<br><b>{}</b><br>"
                                "Imagenes: {} | Asociaciones: {} ({} con video)<br><br>"
                                "La galeria se ha repoblado del analisis guardado.",
        'session_restore_failed': "No se pudo restaurar la sesion anterior: {}",
        'session_none': "No se encontro sesion anterior.",
        'language': "Idioma",
    },
}


# ---------------------------------------------------------------------- #
# Worker thread per l'analisi
# ---------------------------------------------------------------------- #
class AnalyzeWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, game_path: str | Path, tr: dict, parent=None):
        super().__init__(parent)
        self.game_path = Path(game_path)
        self.tr = tr

    def run(self):
        try:
            extractor = FVExtractor(
                self.game_path, log_callback=lambda m: self.log.emit(m)
            )

            # Fase 1: estrazione .rpa (0-40%)
            self.log.emit(self.tr['extracting_rpa'])
            ok = extractor.extract_rpa_files(
                progress_callback=lambda c, t: self.progress.emit(
                    int(c / t * 40) if t > 0 else 0, 100
                )
            )
            if not ok:
                self.error.emit(self.tr['extract_failed'])
                return

            # Fase 2: decompilazione .rpyc (40-60%)
            self.log.emit(self.tr['decompiling_rpyc'])
            ok = extractor.decompile_rpyc_files(
                progress_callback=lambda c, t: self.progress.emit(
                    40 + int(c / t * 20) if t > 0 else 40, 100
                )
            )
            if not ok:
                self.error.emit(self.tr['decompile_failed'])
                return

            # Fase 3: scansione (60-100%)
            self.log.emit(self.tr['scanning_images'])
            scanner = FVScanner(
                extractor.output_dir,
                log_callback=lambda m: self.log.emit(m),
            )
            images = scanner.scan(
                progress_callback=lambda c, t: self.progress.emit(
                    60 + int(c / t * 40) if t > 0 else 60, 100
                )
            )
            self.log.emit(self.tr['found_images'].format(len(images)))
            self.progress.emit(100, 100)
            self.finished.emit(images)
        except Exception as e:
            self.error.emit(str(e))


# ---------------------------------------------------------------------- #
# Dialog associazione video
# ---------------------------------------------------------------------- #
class AssociateDialog(QDialog):
    def __init__(self, image_name: str, image_file_path: Path | None, tr: dict, parent=None):
        super().__init__(parent)
        self.image_name = image_name
        self.image_file_path = image_file_path
        self.tr = tr
        self.video_path: Path | None = None
        self.last_frame_path: Path | None = None
        self.loop = False  # default: niente loop
        self.setWindowTitle(tr['dlg_associate_title'].format(image_name))
        self.setMinimumWidth(420)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        tr = self.tr

        file_label = self.image_file_path.name if self.image_file_path else tr['not_resolved']
        info = QLabel(
            f"<b>{tr['dlg_image']}:</b> {self.image_name}<br>"
            f"<b>{tr['dlg_file']}:</b> {file_label}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Video
        video_box = QHBoxLayout()
        self.video_lbl = QLabel(tr['dlg_no_video'])
        btn_video = QPushButton(tr['dlg_choose_video'])
        btn_video.clicked.connect(self._choose_video)
        video_box.addWidget(self.video_lbl, 1)
        video_box.addWidget(btn_video)
        layout.addLayout(video_box)

        # Last frame: estratto automaticamente dal video (label informativa)
        self.lf_lbl = QLabel(tr['dlg_last_frame_auto'])
        self.lf_lbl.setWordWrap(True)
        self.lf_lbl.setStyleSheet("color: #a0c0d0; padding: 4px;")
        layout.addWidget(self.lf_lbl)

        # Loop
        self.chk_loop = QCheckBox(tr['dlg_loop'])
        self.chk_loop.setChecked(False)  # default: niente loop
        layout.addWidget(self.chk_loop)

        # Pulsanti
        btn_box = QHBoxLayout()
        self.btn_ok = QPushButton(tr['dlg_add_to_patch'])
        self.btn_ok.setEnabled(False)
        self.btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton(tr['dlg_cancel'])
        btn_cancel.clicked.connect(self.reject)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_ok)
        btn_box.addWidget(btn_cancel)
        layout.addLayout(btn_box)

    def _choose_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr['dlg_select_video_title'], "", "WebM (*.webm)",
        )
        if path:
            self.video_path = Path(path)
            self.video_lbl.setText(self.video_path.name)
            self.btn_ok.setEnabled(True)

    def _extract_last_frame(self):
        """Estrae l'ultimo fotogramma dal video usando ffmpeg.

        Salva il frame in una cartella temporanea nel progetto.
        """
        if not self.video_path or not self.video_path.exists():
            return

        # Cartella per i last frame estratti (nella cartella del progetto)
        lf_dir = PROJECTS_ROOT / "_last_frames"
        lf_dir.mkdir(parents=True, exist_ok=True)

        stem = self.video_path.stem
        lf_path = lf_dir / f"{stem}_last.jpg"

        try:
            import subprocess
            # Estrae l'ultimo frame: -sseof -1 va alla fine, -frames:v 1 un solo frame
            result = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(self.video_path),
                 "-frames:v", "1", "-q:v", "2", str(lf_path)],
                capture_output=True, timeout=30,
            )
            if lf_path.exists() and lf_path.stat().st_size > 0:
                self.last_frame_path = lf_path
                self.lf_lbl.setText(self.tr['dlg_last_frame_extracted'].format(lf_path.name))
            else:
                # Fallback: prova con l'ultimo frame normale
                result = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(self.video_path),
                     "-vf", "select=last", "-frames:v", "1", "-q:v", "2", str(lf_path)],
                    capture_output=True, timeout=30,
                )
                if lf_path.exists() and lf_path.stat().st_size > 0:
                    self.last_frame_path = lf_path
                    self.lf_lbl.setText(self.tr['dlg_last_frame_extracted'].format(lf_path.name))
                else:
                    self.lf_lbl.setText(self.tr['dlg_last_frame_failed'])
        except Exception as e:
            self.lf_lbl.setText(self.tr['dlg_last_frame_failed'] + f" ({e})")

    def accept(self):
        if not self.video_path or not self.video_path.exists():
            QMessageBox.warning(self, self.tr['error_title'], self.tr['dlg_invalid_video'])
            return
        if self.video_path.suffix.lower() != ".webm":
            QMessageBox.warning(self, self.tr['error_title'], self.tr['dlg_only_webm'])
            return
        self.loop = self.chk_loop.isChecked()
        # Estrai automaticamente l'ultimo fotogramma se non c'e' gia'
        if self.last_frame_path is None or not self.last_frame_path.exists():
            self._extract_last_frame()
        super().accept()


# ---------------------------------------------------------------------- #
# Finestra principale
# ---------------------------------------------------------------------- #
class FanVideoTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.lang = 'en'
        self.tr = TRANSLATIONS[self.lang]
        self.setWindowIcon(_app_icon())
        self.resize(1100, 720)
        self.game_path: Path | None = None
        self.game_dir: Path | None = None
        self.images: list[StaticImage] = []
        self.assignments: list[PatchEntry] = []
        self.project: FVProject | None = None
        self.thread: QThread | None = None
        self.worker = None

        self._build_ui()
        self._apply_style()
        self._retranslate_ui()
        # Ripristina solo la lingua dall'ultima sessione (non il gioco)
        self._restore_lang_only()

    def _restore_lang_only(self):
        """Ripristina solo la lingua dall'ultima sessione globale."""
        global_file = self._global_session_path()
        if not global_file.exists():
            return
        try:
            data = json.loads(global_file.read_text(encoding="utf-8"))
            lang = data.get("lang", "en")
            if lang in TRANSLATIONS and lang != self.lang:
                idx = {"en": 0, "it": 1, "es": 2}.get(lang, 0)
                self.cmb_lang.setCurrentIndex(idx)
        except Exception:
            pass

    def _t(self, key: str, *args) -> str:
        """Helper per tradurre con format args."""
        s = self.tr.get(key, key)
        return s.format(*args) if args else s

    # ------------------------------------------------------------------ #
    # Session persistence (auto-save / auto-restore)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _global_session_path() -> Path:
        """Percorso del file di sessione globale (ultimo gioco + lingua)."""
        return PROJECTS_ROOT / "session.json"

    def _session_path_for_game(self, game_path: Path | None = None) -> Path:
        """Percorso del file di sessione per un gioco specifico.

        Salva le assignments in FanVideoProjects/<game_name>/session.json
        così ogni gioco mantiene il proprio stato indipendentemente.
        """
        gp = game_path or self.game_path
        if not gp:
            return self._global_session_path()
        # Deriva il nome progetto (stessa logica di FVProject)
        name = gp.name
        if name.endswith(".app"):
            name = name[:-4]
        import re as _re
        name = _re.sub(r"[^\w\-]+", "_", name).strip("_") or "unnamed_game"
        return PROJECTS_ROOT / name / "session.json"

    def _save_global_session(self):
        """Salva solo l'ultimo gioco aperto e la lingua (file globale)."""
        if not self.game_path:
            return
        data = {
            "game_path": str(self.game_path),
            "lang": self.lang,
            "saved_at": datetime.now().isoformat(),
        }
        try:
            session_file = self._global_session_path()
            session_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = session_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, session_file)
        except Exception:
            pass

    def _save_session(self):
        """Salva lo stato corrente su disco (auto-save).

        Salva le assignments nel file di sessione del gioco corrente
        (FanVideoProjects/<game_name>/session.json) e aggiorna il
        file globale con l'ultimo gioco e la lingua.
        """
        if not self.game_path:
            return
        data = {
            "game_path": str(self.game_path),
            "lang": self.lang,
            "saved_at": datetime.now().isoformat(),
            "assignments": [],
        }
        for a in self.assignments:
            entry_data = {
                "image_name": a.image_name,
                "video_path": str(a.video_path) if a.video_path else None,
                "start_image": a.start_image,
                "start_image_path": str(a.start_image_path) if a.start_image_path else None,
                "last_frame_path": str(a.last_frame_path) if a.last_frame_path else None,
                "last_frame_name": a.last_frame_name,
                "loop": a.loop,
            }
            data["assignments"].append(entry_data)

        try:
            session_file = self._session_path_for_game()
            session_file.parent.mkdir(parents=True, exist_ok=True)
            # Scrittura atomica: scrive su .tmp poi rinomina
            tmp = session_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, session_file)
        except Exception:
            pass  # non bloccare l'UI se il save fallisce

        # Aggiorna anche il file globale (ultimo gioco + lingua)
        self._save_global_session()

    def _restore_session(self):
        """Ripristina la sessione precedente all'avvio.

        Legge il file globale per l'ultimo gioco aperto e la lingua,
        poi carica le assignments dal file di sessione del gioco.
        """
        # 1. Legge il file globale per game_path + lang
        global_file = self._global_session_path()
        if not global_file.exists():
            return
        try:
            global_data = json.loads(global_file.read_text(encoding="utf-8"))
        except Exception as e:
            self._log(f"[Session] {self.tr['session_restore_failed'].format(e)}")
            return

        game_path = global_data.get("game_path")
        if not game_path or not Path(game_path).exists():
            return

        # Ripristina game_path
        self.game_path = Path(game_path)
        self.lbl_game.setText(str(self.game_path))

        # Ripristina lingua
        lang = global_data.get("lang", "en")
        if lang in TRANSLATIONS and lang != self.lang:
            idx = {"en": 0, "it": 1, "es": 2}.get(lang, 0)
            self.cmb_lang.setCurrentIndex(idx)

        # 2. Carica le assignments dal file di sessione del gioco
        session_file = self._session_path_for_game()
        data = {"assignments": []}
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
            except Exception:
                data = {"assignments": []}

        # Ripristina assignments
        self.assignments = []
        for a_data in data.get("assignments", []):
            video_p = Path(a_data["video_path"]) if a_data.get("video_path") else None
            # Verifica che il video esista ancora
            if video_p and not video_p.exists():
                video_p = None
            start_p = Path(a_data["start_image_path"]) if a_data.get("start_image_path") else None
            if start_p and not start_p.exists():
                start_p = None
            lf_p = Path(a_data["last_frame_path"]) if a_data.get("last_frame_path") else None
            if lf_p and not lf_p.exists():
                lf_p = None

            self.assignments.append(PatchEntry(
                image_name=a_data["image_name"],
                video_path=video_p,
                start_image=a_data.get("start_image", a_data["image_name"]),
                start_image_path=start_p,
                last_frame_path=lf_p,
                last_frame_name=a_data.get("last_frame_name"),
                loop=a_data.get("loop", False),
            ))

        # Fallback: se la session.json non ha assignments ma esiste un
        # project.json per questo gioco, carica le entry da lì.
        # Questo previene la perdita di dati se la session.json viene
        # azzerata (es. crash prima del save).
        if not self.assignments:
            self._restore_from_project()

        # Popola tabella patch
        self._populate_patch()

        # Avvia analisi automatica per ripopolare la galleria
        n_total = len(self.assignments)
        n_with_video = sum(1 for a in self.assignments if a.has_video)
        self._log(f"[Session] Restored: {n_total} assignments ({n_with_video} with video)")
        self._log(self.tr['session_restored_msg'].format(
            self.game_path.name, "?", n_total, n_with_video))
        self._start_analysis(auto=True)

    def _restore_from_project(self):
        """Fallback: carica le entry esportate dal project.json.

        Se la session.json è vuota ma esiste un project.json per il gioco
        selezionato, ricostruisce le assignments dalle entry esportate.
        Questo previene la perdita di dati se la session.json viene azzerata.
        """
        if not self.game_path:
            return
        try:
            proj = FVProject(self.game_path)
            proj.load()
        except Exception:
            return
        if not proj.entries:
            return

        sources_dir = proj.sources_dir
        videos_dir = proj.videos_dir
        lf_dir = proj.last_frames_dir

        for img_name, entry in proj.entries.items():
            if not entry.source_file:
                continue
            src_path = sources_dir / entry.source_file
            if not src_path.exists():
                continue

            video_p = None
            if entry.video_file:
                vp = videos_dir / entry.video_file
                if vp.exists():
                    video_p = vp

            lf_p = None
            if entry.last_frame_file:
                lfp = lf_dir / entry.last_frame_file
                if lfp.exists():
                    lf_p = lfp

            self.assignments.append(PatchEntry(
                image_name=img_name,
                video_path=video_p,
                start_image=img_name,
                start_image_path=src_path,
                last_frame_path=lf_p,
                last_frame_name=f"{proj._safe_filename(img_name)}_last" if lf_p else None,
                loop=entry.loop,
            ))

        self.project = proj
        n_total = len(self.assignments)
        n_with_video = sum(1 for a in self.assignments if a.has_video)
        self._log(f"[Project] Restored {n_total} entries from project.json ({n_with_video} with video)")

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Barra superiore: logo + titolo + language selector
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        # Logo
        logo_path = Path(__file__).parent / "img" / "logo_64.png"
        if logo_path.exists():
            self.lbl_logo = QLabel()
            pix = QPixmap(str(logo_path))
            self.lbl_logo.setPixmap(pix.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            top_bar.addWidget(self.lbl_logo)

        self.lbl_title = QLabel("RenPy-Fan-Video")
        f = self.lbl_title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 4)
        self.lbl_title.setFont(f)
        top_bar.addWidget(self.lbl_title)
        top_bar.addStretch()

        top_bar.addWidget(QLabel(self.tr['language'] + ":"))
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("English", "en")
        self.cmb_lang.addItem("Italiano", "it")
        self.cmb_lang.addItem("Espanol", "es")
        self.cmb_lang.setCurrentIndex(0)
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_change)
        top_bar.addWidget(self.cmb_lang)
        root.addLayout(top_bar)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_tab_select(), "")
        self.tabs.addTab(self._build_tab_gallery(), "")
        self.tabs.addTab(self._build_tab_patch(), "")

    def _build_tab_select(self) -> QWidget:
        tab = QWidget()
        vbox = QVBoxLayout(tab)

        # Selezione percorso
        path_box = QHBoxLayout()
        self.lbl_game = QLabel("")
        self.lbl_game.setWordWrap(True)

        self.btn_app = QPushButton("")
        self.btn_app.clicked.connect(self._select_app)
        self.btn_folder = QPushButton("")
        self.btn_folder.clicked.connect(self._select_folder)

        path_box.addWidget(self.lbl_game, 1)
        path_box.addWidget(self.btn_app)
        path_box.addWidget(self.btn_folder)
        vbox.addLayout(path_box)

        # Pulsante analisi
        self.btn_analyze = QPushButton("")
        self.btn_analyze.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 8px 16px; "
            "background-color: #5fb7c7; color: #0d1b2a; border: 1px solid #80b0c0; border-radius: 4px; }"
            "QPushButton:hover { background-color: #80b0c0; }"
            "QPushButton:pressed { background-color: #4a9aa8; }"
        )
        self.btn_analyze.clicked.connect(self._start_analysis)
        vbox.addWidget(self.btn_analyze)

        # Progress + log
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        vbox.addWidget(self.progress)

        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        vbox.addWidget(self.log_box)

        return tab

    def _build_tab_gallery(self) -> QWidget:
        tab = QWidget()
        hbox = QHBoxLayout(tab)

        # Sidebar sinistra
        left = QVBoxLayout()

        # Filtri
        filter_box = QHBoxLayout()
        self.txt_filter = QLineEdit()
        self.txt_filter.textChanged.connect(self._apply_filter)

        self.cmb_file_filter = QComboBox()
        self.cmb_file_filter.setMinimumWidth(200)
        self.cmb_file_filter.currentIndexChanged.connect(self._apply_filter)

        filter_box.addWidget(self.txt_filter, 1)
        filter_box.addWidget(self.cmb_file_filter)
        left.addLayout(filter_box)

        self.tbl_images = QTableWidget()
        self.tbl_images.setColumnCount(4)
        self.tbl_images.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl_images.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_images.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_images.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_images.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_images.setSelectionMode(QTableWidget.SingleSelection)
        self.tbl_images.setSortingEnabled(True)
        self.tbl_images.itemSelectionChanged.connect(self._on_image_selected)
        self.tbl_images.itemDoubleClicked.connect(self._export_image)
        left.addWidget(self.tbl_images)

        btn_row = QHBoxLayout()
        self.btn_export = QPushButton("")
        self.btn_export.clicked.connect(self._export_image)
        self.btn_sources = QPushButton("")
        self.btn_sources.clicked.connect(self._open_sources_folder)
        btn_row.addWidget(self.btn_export)
        btn_row.addWidget(self.btn_sources)
        left.addLayout(btn_row)

        hbox.addLayout(left, 1)

        # Anteprima destra (piu' spazio per vedere meglio i dettagli dell'immagine)
        right = QVBoxLayout()
        self.lbl_preview_title = QLabel("")
        self.lbl_preview = QLabel()
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setMinimumSize(480, 360)
        self.lbl_preview.setStyleSheet("background-color: #16263a; border: 1px solid #2a4055; border-radius: 4px;")
        self.lbl_preview.setScaledContents(False)
        right.addWidget(self.lbl_preview_title)
        right.addWidget(self.lbl_preview, 1)  # si espande con la finestra

        self.lbl_info = QLabel("")
        self.lbl_info.setWordWrap(True)
        right.addWidget(self.lbl_info)
        right.addStretch()

        hbox.addLayout(right, 1)

        return tab

    def _build_tab_patch(self) -> QWidget:
        tab = QWidget()
        vbox = QVBoxLayout(tab)

        self.lbl_patch_info = QLabel("")
        self.lbl_patch_info.setWordWrap(True)
        self.lbl_patch_info.setStyleSheet("padding: 6px; color: #a0c0d0; background-color: #16263a; border-radius: 4px;")
        vbox.addWidget(self.lbl_patch_info)

        # Corpo: tabella a sinistra, preview a destra
        hbox = QHBoxLayout()

        left = QVBoxLayout()
        self.tbl_patch = PatchTable()
        self.tbl_patch.setColumnCount(5)
        self.tbl_patch.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_patch.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_patch.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_patch.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_patch.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.tbl_patch.setSelectionBehavior(QTableWidget.SelectRows)
        self.tbl_patch.setSelectionMode(QTableWidget.ExtendedSelection)
        self.tbl_patch.setSortingEnabled(True)
        self.tbl_patch.itemDoubleClicked.connect(self._on_patch_double_click)
        self.tbl_patch.itemSelectionChanged.connect(self._on_patch_row_changed)
        self.tbl_patch.delete_pressed.connect(self._remove_assignment)
        left.addWidget(self.tbl_patch)

        btn_box = QHBoxLayout()
        self.btn_add_video = QPushButton("")
        self.btn_add_video.setStyleSheet(
            "QPushButton { padding: 6px 12px; "
            "background-color: #1e3a4a; color: #5fb7c7; border: 1px solid #2a5568; border-radius: 4px; }"
            "QPushButton:hover { background-color: #26485c; }"
            "QPushButton:pressed { background-color: #163040; }"
        )
        self.btn_add_video.clicked.connect(self._add_video_to_selected)
        self.btn_remove = QPushButton("")
        self.btn_remove.clicked.connect(self._remove_assignment)
        self.btn_associate = QPushButton("")
        self.btn_associate.clicked.connect(self._auto_associate_videos)
        self.btn_remove_patch = QPushButton("")
        self.btn_remove_patch.setStyleSheet(
            "QPushButton { padding: 6px 12px; "
            "background-color: #3a2030; color: #e07090; border: 1px solid #603040; border-radius: 4px; }"
            "QPushButton:hover { background-color: #4a2838; }"
            "QPushButton:pressed { background-color: #2a1820; }"
        )
        self.btn_remove_patch.clicked.connect(self._remove_patch)
        self.btn_generate = QPushButton("")
        self.btn_generate.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 8px 16px; "
            "background-color: #5fb7c7; color: #0d1b2a; border: 1px solid #80b0c0; border-radius: 4px; }"
            "QPushButton:hover { background-color: #80b0c0; }"
            "QPushButton:pressed { background-color: #4a9aa8; }"
        )
        self.btn_generate.clicked.connect(self._generate_patch)
        self.btn_export_mod = QPushButton("")
        self.btn_export_mod.setStyleSheet(
            "QPushButton { font-weight: bold; padding: 8px 16px; "
            "background-color: #facc15; color: #0d1b2a; border: 1px solid #f0c020; border-radius: 4px; }"
            "QPushButton:hover { background-color: #f0c020; }"
            "QPushButton:pressed { background-color: #d4a810; }"
        )
        self.btn_export_mod.clicked.connect(self._export_mod)

        btn_box.addWidget(self.btn_add_video)
        btn_box.addWidget(self.btn_remove)
        btn_box.addWidget(self.btn_associate)
        btn_box.addWidget(self.btn_remove_patch)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_generate)
        btn_box.addWidget(self.btn_export_mod)
        left.addLayout(btn_box)

        # Progress bar per operazioni nel tab Patch (es. auto-associazione video)
        self.patch_progress = QProgressBar()
        self.patch_progress.setRange(0, 100)
        self.patch_progress.setValue(0)
        left.addWidget(self.patch_progress)

        hbox.addLayout(left, 2)

        # Preview destra: stacked widget con immagine e video
        right = QVBoxLayout()
        self.lbl_patch_preview_title = QLabel("")
        # Stacked widget: pagina 0 = immagine, pagina 1 = video
        self.patch_preview_stack = QStackedWidget()
        self.patch_preview_stack.setMinimumSize(320, 240)

        # Pagina 0: preview immagine (QLabel)
        self.lbl_patch_preview = QLabel()
        self.lbl_patch_preview.setAlignment(Qt.AlignCenter)
        self.lbl_patch_preview.setStyleSheet(
            "background-color: #16263a; border: 1px solid #2a4055; border-radius: 4px;"
        )
        self.lbl_patch_preview.setScaledContents(False)

        # Pagina 1: preview video (QVideoWidget + QMediaPlayer)
        self.video_player = QMediaPlayer()
        self.video_widget = QVideoWidget()
        self.video_widget.setStyleSheet(
            "background-color: #000000; border: 1px solid #2a4055; border-radius: 4px;"
        )
        self.video_player.setVideoOutput(self.video_widget)

        self.patch_preview_stack.addWidget(self.lbl_patch_preview)   # index 0
        self.patch_preview_stack.addWidget(self.video_widget)        # index 1

        right.addWidget(self.lbl_patch_preview_title)
        right.addWidget(self.patch_preview_stack, 1)  # si espande con la finestra

        self.lbl_patch_preview_info = QLabel("")
        self.lbl_patch_preview_info.setWordWrap(True)
        right.addWidget(self.lbl_patch_preview_info)
        right.addStretch()
        hbox.addLayout(right, 1)

        vbox.addLayout(hbox)

        return tab

    # ------------------------------------------------------------------ #
    # Retranslate (cambio lingua)
    # ------------------------------------------------------------------ #
    def _retranslate_ui(self):
        tr = self.tr
        self.setWindowTitle(tr['title'])
        self.lbl_title.setText(tr['title'])

        # Tab titles
        self.tabs.setTabText(0, tr['tab_game'])
        self.tabs.setTabText(1, tr['tab_gallery'])
        self.tabs.setTabText(2, tr['tab_patch'])

        # Tab 1
        self.lbl_game.setText(tr['no_game_selected'])
        self.btn_app.setText(tr['btn_app'])
        self.btn_folder.setText(tr['btn_folder'])
        self.btn_analyze.setText(tr['btn_analyze'])

        # Tab 2
        self.txt_filter.setPlaceholderText(tr['search_placeholder'])
        # Aggiorna il file filter combo mantenendo la selezione
        self._repopulate_file_filter()
        self.tbl_images.setHorizontalHeaderLabels(
            ["", tr['col_name'], tr['col_source'], tr['col_line']]
        )
        self.btn_export.setText(tr['btn_export'])
        self.btn_export.setToolTip(tr['btn_export_tip'])
        self.btn_sources.setText(tr['btn_open_sources'])
        self.btn_sources.setToolTip(tr['btn_open_sources'])
        self.lbl_preview_title.setText(tr['preview'])
        self.lbl_info.setText(tr['select_image_first'])

        # Tab 3
        self.lbl_patch_info.setText(tr['patch_info'])
        self.tbl_patch.setHorizontalHeaderLabels(
            [tr['col_image'], tr['col_video'], tr['col_last_frame'],
             tr['col_loop'], tr['col_status']]
        )
        self.btn_add_video.setText(tr['btn_add_video'])
        self.btn_add_video.setToolTip(tr['btn_add_video_tip'])
        self.btn_remove.setText(tr['btn_remove'])
        self.btn_associate.setText(tr['btn_associate'])
        self.btn_associate.setToolTip(tr['btn_associate_tip'])
        self.btn_remove_patch.setText(tr['btn_remove_patch'])
        self.btn_remove_patch.setToolTip(tr['btn_remove_patch_tip'])
        self.btn_generate.setText(tr['btn_generate'])
        self.btn_export_mod.setText(tr['btn_export_mod'])
        self.btn_export_mod.setToolTip(tr['btn_export_mod_tip'])
        # Aggiorna preview patch se una riga è selezionata
        self._on_patch_row_changed()

        # Aggiorna contenuti dinamici
        if self.images:
            self._populate_gallery()
        if self.assignments:
            self._populate_patch()

    def _on_lang_change(self, _idx: int):
        code = self.cmb_lang.currentData()
        self.lang = code
        self.tr = TRANSLATIONS[code]
        self._retranslate_ui()
        self._save_session()

    # ------------------------------------------------------------------ #
    # Stile
    # ------------------------------------------------------------------ #
    def _apply_style(self):
        # Palette derivata dal logo:
        #   sfondo    #0d1b2a (blu-grigio molto scuro)
        #   pannelli  #1b2d3f (medio scuro)
        #   input     #16263a (tabella/log)
        #   bordi     #2a4055 (teal scuro)
        #   accento   #5fb7c7 (ciano brillante, da #B0F0F8 desaturato)
        #   accento2  #80b0c0 (ciano medio)
        #   testo     #e0f0f0 (bianco freddo)
        #   testo2    #a0c0d0 (grigio-azzurro)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background-color: #0d1b2a;
                color: #e0f0f0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }
            QLabel {
                color: #e0f0f0;
            }
            QTabWidget::pane {
                border: 1px solid #2a4055;
                background-color: #1b2d3f;
                border-radius: 4px;
            }
            QTabBar::tab {
                background-color: #16263a;
                color: #a0c0d0;
                padding: 8px 18px;
                margin-right: 2px;
                border: 1px solid #2a4055;
                border-bottom: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #2a4055;
                color: #e0f0f0;
            }
            QTabBar::tab:hover:!selected {
                background-color: #1f3450;
            }
            QPushButton {
                background-color: #2a4055;
                color: #e0f0f0;
                border: 1px solid #3a5a75;
                padding: 6px 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3a5a75;
                border: 1px solid #5fb7c7;
            }
            QPushButton:pressed {
                background-color: #1b2d3f;
            }
            QLineEdit, QPlainTextEdit, QComboBox, QTableWidget {
                background-color: #16263a;
                border: 1px solid #2a4055;
                border-radius: 4px;
                color: #e0f0f0;
                selection-background-color: #5fb7c7;
                selection-color: #0d1b2a;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #16263a;
                color: #e0f0f0;
                selection-background-color: #5fb7c7;
                selection-color: #0d1b2a;
            }
            QTableWidget {
                gridline-color: #2a4055;
            }
            QTableWidget::item {
                color: #e0f0f0;
            }
            QTableWidget::item:selected {
                background-color: #5fb7c7;
                color: #0d1b2a;
            }
            QHeaderView::section {
                background-color: #1b2d3f;
                color: #a0c0d0;
                border: 1px solid #2a4055;
                padding: 4px;
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #2a4055;
                border-radius: 4px;
                text-align: center;
                background-color: #16263a;
                color: #e0f0f0;
            }
            QProgressBar::chunk {
                background-color: #5fb7c7;
                border-radius: 3px;
            }
            QCheckBox {
                color: #e0f0f0;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #3a5a75;
                border-radius: 3px;
                background-color: #16263a;
            }
            QCheckBox::indicator:checked {
                background-color: #5fb7c7;
                border: 1px solid #5fb7c7;
            }
            QPlainTextEdit {
                color: #a0c0d0;
            }
            QLabel#log {
                color: #a0c0d0;
            }
            QMessageBox {
                background-color: #1b2d3f;
            }
            """
        )

    # ------------------------------------------------------------------ #
    # Azioni
    # ------------------------------------------------------------------ #
    def _switch_game(self, new_game_path: Path):
        """Cambia gioco: salva la sessione corrente, carica quella del nuovo.

        - Salva le assignments del gioco corrente nel suo session.json
        - Azzera le assignments
        - Imposta il nuovo game_path
        - Carica le assignments del nuovo gioco dal suo session.json
        - Aggiorna la UI (patch table, gallery)
        """
        # Salva la sessione del gioco corrente (se presente)
        if self.game_path:
            self._save_session()

        # Azzera lo stato
        self.assignments = []
        self.images = []
        self.game_dir = None

        # Imposta il nuovo gioco
        self.game_path = new_game_path
        self.lbl_game.setText(str(self.game_path))

        # Carica le assignments del nuovo gioco
        session_file = self._session_path_for_game()
        if session_file.exists():
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                for a_data in data.get("assignments", []):
                    video_p = Path(a_data["video_path"]) if a_data.get("video_path") else None
                    if video_p and not video_p.exists():
                        video_p = None
                    start_p = Path(a_data["start_image_path"]) if a_data.get("start_image_path") else None
                    if start_p and not start_p.exists():
                        start_p = None
                    lf_p = Path(a_data["last_frame_path"]) if a_data.get("last_frame_path") else None
                    if lf_p and not lf_p.exists():
                        lf_p = None
                    self.assignments.append(PatchEntry(
                        image_name=a_data["image_name"],
                        video_path=video_p,
                        start_image=a_data.get("start_image", a_data["image_name"]),
                        start_image_path=start_p,
                        last_frame_path=lf_p,
                        last_frame_name=a_data.get("last_frame_name"),
                        loop=a_data.get("loop", False),
                    ))
                n_total = len(self.assignments)
                n_with_video = sum(1 for a in self.assignments if a.has_video)
                self._log(f"[Session] Loaded {n_total} assignments for {self.game_path.name} "
                          f"({n_with_video} with video)")
            except Exception as e:
                self._log(f"[Session] Failed to load: {e}")

        # Fallback: project.json se la sessione è vuota
        if not self.assignments:
            self._restore_from_project()

        # Aggiorna la UI
        self._populate_patch()
        self._populate_gallery()
        self._save_global_session()

    def _select_app(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self.tr['select_app_title'], "", "App bundle (*.app)"
        )
        if path:
            self._switch_game(Path(path))

    def _select_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, self.tr['select_folder_title']
        )
        if path:
            self._switch_game(Path(path))

    def _log(self, msg: str):
        self.log_box.appendPlainText(msg)

    def _start_analysis(self, auto: bool = False):
        if not self.game_path or not self.game_path.exists():
            if not auto:
                QMessageBox.warning(self, self.tr['error_title'], self.tr['select_game_first'])
            return

        self.log_box.clear()
        self.progress.setValue(0)
        if not auto:
            self.tbl_images.setRowCount(0)
            self.images = []

        self.thread = QThread(self)
        self.worker = AnalyzeWorker(self.game_path, self.tr)
        self.worker.moveToThread(self.thread)

        self.worker.log.connect(self._log)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_analysis_done)
        self.worker.error.connect(self._on_analysis_error)
        self.thread.started.connect(self.worker.run)

        self.thread.start()

    def _on_progress(self, current: int, total: int):
        if total > 0:
            pct = int((current / total) * 100)
            self.progress.setValue(min(pct, 100))

    def _on_analysis_done(self, images: list[StaticImage]):
        self.progress.setValue(100)
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None

        ext = FVExtractor(self.game_path)
        self.game_dir = ext.output_dir

        self.images = images
        self._repopulate_file_filter()
        self._populate_gallery()

        # Se ci sono assignments ripristinate, assicurati che lo start_image_path
        # punti al file corretto usando la galleria appena ricaricata
        for a in self.assignments:
            if a.start_image_path is None or not a.start_image_path.exists():
                # Cerca il file nella galleria
                for img in self.images:
                    if img.name == a.image_name and img.is_resolved:
                        a.start_image_path = img.file_path
                        break

        # Riordina le assignments per timeline del gioco (non per ordine
        # di aggiunta): ora che self.images e' disponibile possiamo usare
        # l'ordine di apparizione negli .rpy come riferimento.
        # Nota: _populate_patch() chiamera' comunque _sort_assignments_by_timeline,
        # ma lo facciamo anche qui per salvare la sessione gia' ordinata.
        self._sort_assignments_by_timeline()

        self._populate_patch()
        self._save_session()
        self.tabs.setCurrentIndex(1)

        n_with_video = sum(1 for a in self.assignments if a.has_video)
        if self.assignments:
            QMessageBox.information(
                self, self.tr['analysis_done_title'],
                self.tr['session_restored_msg'].format(
                    self.game_path.name, len(images),
                    len(self.assignments), n_with_video),
            )
        else:
            QMessageBox.information(
                self, self.tr['analysis_done_title'],
                self.tr['analysis_done_msg'].format(len(images)),
            )

    def _on_analysis_error(self, msg: str):
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait()
            self.thread = None
        self._log(f"[ERROR] {msg}")
        QMessageBox.critical(self, self.tr['analysis_error_title'], msg)

    # ------------------------------------------------------------------ #
    # Galleria
    # ------------------------------------------------------------------ #
    def _safe_name(self, name: str) -> str:
        return re.sub(r"[^\w]+", "_", name).strip("_").lower()

    def _get_movies_folder(self) -> str:
        """Rileva il nome case-sensitive della cartella video del gioco."""
        if self.game_dir:
            for candidate in ("movies", "Movies", "MOVIES"):
                if (self.game_dir / candidate).is_dir():
                    return candidate
        return "movies"

    def _populate_gallery(self):
        self.tbl_images.setSortingEnabled(False)
        self.tbl_images.setRowCount(0)
        visible = self._filtered_images()

        self.tbl_images.setRowCount(len(visible))
        for i, img in enumerate(visible):
            # Colonna 0: thumbnail (caricato lazy solo per immagini risolte)
            thumb_item = NaturalSortItem()
            thumb_item.setData(Qt.UserRole, img)
            if img.file_path and img.file_path.exists():
                # Non caricare il pixmap qui: troppo lento con migliaia di righe.
                # L'anteprima si vede nel pannello destra selezionando la riga.
                pass
            thumb_item.setFlags(thumb_item.flags() & ~Qt.ItemIsEditable)
            self.tbl_images.setItem(i, 0, thumb_item)

            name_item = NaturalSortItem(img.name)
            name_item.setData(Qt.UserRole, img)
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.tbl_images.setItem(i, 1, name_item)

            src = img.used_in[0] if img.used_in else (Path("-"), 0)
            src_item = SourceSortItem(src[0].name if hasattr(src[0], 'name') else str(src[0]))
            src_item.setData(Qt.UserRole, img)
            src_item.setToolTip(str(src[0]))
            src_item.setFlags(src_item.flags() & ~Qt.ItemIsEditable)
            self.tbl_images.setItem(i, 2, src_item)

            line_item = NaturalSortItem(str(src[1]))
            line_item.setData(Qt.UserRole, img)
            line_item.setFlags(line_item.flags() & ~Qt.ItemIsEditable)
            self.tbl_images.setItem(i, 3, line_item)

        self.tbl_images.resizeColumnsToContents()
        self.tbl_images.setSortingEnabled(True)
        self._update_gallery_patch_highlights()

    def _update_gallery_patch_highlights(self):
        """Evidenzia in giallo le righe della galleria gia' presenti nel patch."""
        patch_names = {a.image_name for a in self.assignments}
        default_color = self.palette().text().color()
        for row in range(self.tbl_images.rowCount()):
            name_item = self.tbl_images.item(row, 1)
            if name_item is None:
                continue
            img = name_item.data(Qt.UserRole)
            if img is None:
                continue
            color = Qt.yellow if img.name in patch_names else default_color
            for col in range(self.tbl_images.columnCount()):
                item = self.tbl_images.item(row, col)
                if item is not None:
                    item.setForeground(color)

    def _repopulate_file_filter(self):
        """Ripopola il combo dei file .rpy mantenendo la selezione."""
        prev = self.cmb_file_filter.currentIndex()
        prev_text = self.cmb_file_filter.currentText() if prev > 0 else None
        self.cmb_file_filter.blockSignals(True)
        self.cmb_file_filter.clear()
        self.cmb_file_filter.addItem(self.tr['filter_file_all'])
        # Raccogli i file .rpy da cui provengono le immagini
        files = set()
        for img in self.images:
            for rpy, _ in img.used_in:
                fname = rpy.name if hasattr(rpy, 'name') else str(rpy)
                files.add(fname)
        for fname in sorted(files):
            self.cmb_file_filter.addItem(fname)
        # Ripristina selezione
        if prev_text and prev > 0:
            idx = self.cmb_file_filter.findText(prev_text)
            if idx >= 0:
                self.cmb_file_filter.setCurrentIndex(idx)
        self.cmb_file_filter.blockSignals(False)

    def _filtered_images(self) -> list[StaticImage]:
        text = self.txt_filter.text().lower()
        file_idx = self.cmb_file_filter.currentIndex()
        file_filter = None
        if file_idx > 0:
            file_filter = self.cmb_file_filter.currentText()

        out: list[StaticImage] = []
        for img in self.images:
            # Mostra solo immagini statiche (non già animate)
            if img.already_movie:
                continue
            if file_filter:
                found = False
                for rpy, _ in img.used_in:
                    fname = rpy.name if hasattr(rpy, 'name') else str(rpy)
                    if fname == file_filter:
                        found = True
                        break
                if not found:
                    continue
            if not text or text in img.name.lower():
                out.append(img)
        return out

    def _apply_filter(self):
        self._populate_gallery()

    def resizeEvent(self, event):
        """Ridisegna il preview quando la finestra cambia dimensione."""
        super().resizeEvent(event)
        # Ridisegna preview gallery se c'è una riga selezionata
        if self.tbl_images.currentRow() >= 0:
            self._on_image_selected()
        # Ridisegna preview patch se c'è una riga selezionata
        if self.tbl_patch.currentRow() >= 0:
            self._on_patch_row_changed()

    def _on_image_selected(self):
        row = self.tbl_images.currentRow()
        if row < 0:
            return

        # Usa il dato salvato nell'item invece di ricalcolare _filtered_images()
        item = self.tbl_images.item(row, 1)
        if item is None:
            return
        img = item.data(Qt.UserRole)
        if img is None:
            return

        preview_size = max(self.lbl_preview.width(), self.lbl_preview.height())
        pix = self._load_pixmap(img.file_path, preview_size)
        if pix:
            scaled = pix.scaled(
                self.lbl_preview.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
            self.lbl_preview.setPixmap(scaled)
        else:
            self.lbl_preview.clear()
            self.lbl_preview.setText(self.tr['preview_unavailable'])

        src = img.used_in[0] if img.used_in else (Path("-"), 0)
        src_name = src[0].name if hasattr(src[0], 'name') else str(src[0])
        file_label = str(img.file_path) if img.file_path else self.tr['not_resolved']
        self.lbl_info.setText(
            f"<b>{img.name}</b><br>"
            f"{self.tr['file_label']}: {file_label}<br>"
            f"{self.tr['source_label']}: {src_name} ({self.tr['col_line'].lower()} {src[1]})<br>"
            f"{self.tr['already_replaced']}: "
            f"{self.tr['yes'] if img.already_movie else self.tr['no']}"
        )

    def _export_image(self):
        row = self.tbl_images.currentRow()
        if row < 0:
            QMessageBox.information(self, self.tr['title'], self.tr['select_image_first'])
            return

        item = self.tbl_images.item(row, 1)
        if item is None:
            return
        img = item.data(Qt.UserRole)
        if img is None:
            return

        if not img.is_resolved:
            QMessageBox.warning(self, self.tr['error_title'], self.tr['cannot_export'].format(img.name))
            return

        if self.project is None:
            self.project = FVProject(self.game_path)
            self.project.load()

        try:
            dest = self.project.export_image(img.name, cast(Path, img.file_path))
        except Exception as e:
            QMessageBox.critical(self, self.tr['error_title'], str(e))
            return

        safe = self._safe_name(img.name)
        start_name = f"{safe}_first_frame"

        self.assignments = [a for a in self.assignments if a.image_name != img.name]

        self.assignments.append(
            PatchEntry(
                image_name=img.name,
                video_path=None,
                start_image=start_name,
                start_image_path=img.file_path,
                last_frame_path=None,
                last_frame_name=None,
                loop=False,
            )
        )
        self._populate_patch()
        self._log(f"[Export] {dest.name} -> sources/")

    def _load_pixmap(self, path: Path | None, size: int) -> QPixmap | None:
        try:
            if not path or not path.exists():
                return None
            pixmap = QPixmap(str(path))
            if pixmap.isNull():
                return None
            return pixmap.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Patch
    # ------------------------------------------------------------------ #
    def _on_patch_double_click(self, item):
        """Double-click sulla tabella patch: toggle loop (colonna 3) oppure
        associa/sostituisce manualmente il video (colonna 1)."""
        col = self.tbl_patch.column(item)
        if col not in (1, 3):
            return
        row = self.tbl_patch.row(item)
        if row < 0 or row >= len(self.assignments):
            return
        # Con sorting attivo, row e' l'indice visivo: leggi il nome dalla cella
        name_item = self.tbl_patch.item(row, 0)
        if not name_item:
            return
        entry = next((a for a in self.assignments if a.image_name == name_item.text()), None)
        if not entry:
            return

        if col == 3:  # col_loop
            entry.loop = not entry.loop
            self._populate_patch()
            self._log(f"[Loop] {entry.image_name}: {'ON' if entry.loop else 'OFF'}")
        elif col == 1:  # col_video
            self._manual_associate_video(entry)

    def _ensure_project(self) -> FVProject:
        """Restituisce (creando se necessario) il progetto per il gioco corrente."""
        if self.project is None:
            self.project = FVProject(self.game_path)
            self.project.load()
        return self.project

    def _materialize_association(self, entry: PatchEntry, video_src: Path,
                                  last_frame_src: Path | None, loop: bool) -> Path:
        """Copia video (e last frame) nella cartella di progetto rinominandoli
        in base all'alias Ren'Py dell'immagine ("<alias>_vid.ext",
        "<alias>_last.ext"), poi aggiorna i campi dell'entry del patch.

        Questo e' l'UNICO punto che materializza le associazioni video, cosi'
        il nome file finale non dipende mai da come si chiamava il file
        scaricato dal tool AI esterno (es. "..._preview.webm", "..._v01.webm").
        Funziona anche se l'immagine non era stata esportata esplicitamente.

        Non aggiorna la UI ne' logga: usare _apply_video_association per le
        associazioni singole (manuali), oppure gestire log/refresh a parte
        per operazioni in batch (es. auto-associate).
        """
        project = self._ensure_project()
        project.create()

        video_dest = project.associate_video(entry.image_name, video_src, last_frame_src, loop)

        safe = self._safe_name(entry.image_name)
        last_frame_dest = None
        last_frame_name = None
        if last_frame_src and last_frame_src.exists():
            last_frame_dest = project.last_frames_dir / f"{safe}_last{last_frame_src.suffix.lower()}"
            last_frame_name = f"{safe}_last_frame"

        entry.video_path = video_dest
        entry.last_frame_path = last_frame_dest
        entry.last_frame_name = last_frame_name
        entry.loop = loop

        return video_dest

    def _apply_video_association(self, entry: PatchEntry, video_src: Path,
                                  last_frame_src: Path | None, loop: bool):
        """Come _materialize_association, ma per associazioni singole: aggiorna
        anche la UI (tabella patch, evidenziazioni galleria) e logga."""
        video_dest = self._materialize_association(entry, video_src, last_frame_src, loop)
        self._populate_patch()
        self._update_gallery_patch_highlights()
        self._log(f"[Video] {entry.image_name} <- {video_dest.name}")

    def _manual_associate_video(self, entry: PatchEntry):
        """Associa (o sostituisce) manualmente il video di un'entry del patch,
        direttamente dal tab Patch senza passare dalla Galleria."""
        dlg = AssociateDialog(entry.image_name, entry.start_image_path, self.tr, self)
        if dlg.exec() != QDialog.Accepted:
            return
        self._apply_video_association(entry, cast(Path, dlg.video_path), dlg.last_frame_path, dlg.loop)

    def _add_video_to_selected(self):
        """Pulsante 'Aggiungi Video': fallback manuale quando l'auto-associate
        non trova un match. Associa (o sostituisce) il video della riga
        selezionata nel tab Patch."""
        row = self.tbl_patch.currentRow()
        if row < 0:
            QMessageBox.information(self, self.tr['title'], self.tr['select_patch_row'])
            return
        name_item = self.tbl_patch.item(row, 0)
        if not name_item:
            return
        entry = next((a for a in self.assignments if a.image_name == name_item.text()), None)
        if not entry:
            return
        self._manual_associate_video(entry)

    def _on_patch_row_changed(self):
        """Mostra la preview del video o dell'immagine della riga selezionata."""
        row = self.tbl_patch.currentRow()
        if row < 0 or row >= len(self.assignments):
            self._stop_video_preview()
            self.lbl_patch_preview.clear()
            self.lbl_patch_preview_title.setText("")
            self.lbl_patch_preview_info.setText(self.tr['patch_no_selection'])
            return

        # Con sorting attivo, row e' l'indice visivo: leggi il nome dalla cella
        name_item = self.tbl_patch.item(row, 0)
        if not name_item:
            return
        entry = next((a for a in self.assignments if a.image_name == name_item.text()), None)
        if not entry:
            return
        self.lbl_patch_preview_title.setText(
            self.tr['preview'] + ": " + entry.image_name
        )

        # Se c'e' un video associato, mostra il video
        if entry.video_path and entry.video_path.exists():
            self._play_video_preview(entry.video_path)
        else:
            # Nessun video: mostra l'immagine statica
            self._stop_video_preview()
            self.patch_preview_stack.setCurrentIndex(0)

            # Cerca il path dell'immagine: prima start_image_path, poi nella galleria
            img_path = entry.start_image_path
            if (img_path is None or not Path(img_path).exists()) and self.images:
                for i in self.images:
                    if i.name == entry.image_name:
                        img_path = i.file_path
                        break

            if img_path and Path(img_path).exists():
                pix = QPixmap(str(img_path))
                if not pix.isNull():
                    scaled = pix.scaled(
                        self.lbl_patch_preview.width(),
                        self.lbl_patch_preview.height(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                    self.lbl_patch_preview.setPixmap(scaled)
                else:
                    self.lbl_patch_preview.clear()
            else:
                self.lbl_patch_preview.clear()

        # Info aggiuntive: video associato, loop, stato
        video_str = entry.video_path.name if entry.video_path else self.tr['pending_video']
        loop_str = self.tr['yes'] if entry.loop else self.tr['no']
        status_str = self.tr['status_ready'] if entry.has_video else self.tr['status_pending']
        self.lbl_patch_preview_info.setText(
            f"<b>{self.tr['col_video']}:</b> {video_str}<br>"
            f"<b>{self.tr['col_loop']}:</b> {loop_str}<br>"
            f"<b>{self.tr['col_status']}:</b> {status_str}"
        )

    def _play_video_preview(self, video_path: Path):
        """Avvia la riproduzione del video nella preview del tab Patch."""
        self.patch_preview_stack.setCurrentIndex(1)
        self.video_player.setSource(QUrl.fromLocalFile(str(video_path)))
        self.video_player.play()

    def _stop_video_preview(self):
        """Ferma la riproduzione del video."""
        self.video_player.stop()
        self.video_player.setSource(QUrl())

    def _sort_assignments_by_timeline(self):
        """Riordina self.assignments per timeline del gioco (ordine di
        apparizione negli .rpy), non per ordine di aggiunta.

 Usa self.images (già in ordine timeline dallo scanner) come
 riferimento. Le entry senza corrispondenza in self.images vanno
 in fondo, in ordine alfabetico.
        """
        if not self.images:
            return
        # Mappa: image_name -> indice timeline
        timeline_idx = {img.name: i for i, img in enumerate(self.images)}
        self.assignments.sort(
            key=lambda a: (timeline_idx.get(a.image_name, len(self.images)),
                           a.image_name.lower())
        )

    def _populate_patch(self):
        # Mantieni sempre le assignments in ordine timeline del gioco
        # (non in ordine di aggiunta), cosi' l'utente vede il Patch
        # nell'ordine naturale del gioco.
        self._sort_assignments_by_timeline()
        self.tbl_patch.setSortingEnabled(False)
        self.tbl_patch.setRowCount(len(self.assignments))
        for i, a in enumerate(self.assignments):
            self.tbl_patch.setItem(i, 0, NaturalSortItem(a.image_name))
            self.tbl_patch.setItem(
                i, 1,
                NaturalSortItem(a.video_path.name if a.video_path else self.tr['pending_video'])
            )
            self.tbl_patch.setItem(
                i, 2,
                NaturalSortItem(a.last_frame_path.name if a.last_frame_path else "-")
            )
            self.tbl_patch.setItem(i, 3, NaturalSortItem(self.tr['yes'] if a.loop else self.tr['no']))
            if a.has_video:
                status_item = NaturalSortItem(self.tr['status_ready'])
                status_item.setForeground(Qt.green)
            else:
                status_item = NaturalSortItem(self.tr['status_pending'])
                status_item.setForeground(Qt.yellow)
            self.tbl_patch.setItem(i, 4, status_item)
        self.tbl_patch.setSortingEnabled(True)
        # Auto-save sessione a ogni modifica della tabella patch
        self._save_session()

    def _extract_last_frame_for_video(self, video_path: Path) -> Path | None:
        """Estrae l'ultimo frame da un video usando ffmpeg.

        Salva il frame in FanVideoProjects/_last_frames/<stem>_last.jpg.
        Se esiste già un last frame valido, lo riutilizza.
        """
        lf_dir = PROJECTS_ROOT / "_last_frames"
        lf_dir.mkdir(parents=True, exist_ok=True)

        stem = video_path.stem
        lf_path = lf_dir / f"{stem}_last.jpg"

        # Re-estrai sempre il last frame (il video potrebbe essere cambiato
        # con stesso nome/stessa data ma contenuto diverso)

        try:
            import subprocess
            # Estrae in un file temporaneo per non cancellare eventuali vecchi
            tmp_path = lf_path.with_suffix(".tmp.jpg")
            result = subprocess.run(
                ["ffmpeg", "-y", "-sseof", "-0.1", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(tmp_path)],
                capture_output=True, timeout=30,
            )
            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                tmp_path.rename(lf_path)
                self._log(f"[LastFrame] Extracted: {lf_path.name}")
                return lf_path
            # Fallback: prova con select=last
            self._log(f"[LastFrame] First method failed, trying fallback...")
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path),
                 "-vf", "select=last", "-frames:v", "1", "-q:v", "2", str(tmp_path)],
                capture_output=True, timeout=30,
            )
            if tmp_path.exists() and tmp_path.stat().st_size > 0:
                tmp_path.rename(lf_path)
                self._log(f"[LastFrame] Extracted (fallback): {lf_path.name}")
                return lf_path
            # Pulisci tmp se esiste ma è vuoto
            if tmp_path.exists():
                tmp_path.unlink()
            # Log ffmpeg error
            stderr = result.stderr.decode()[-500:] if result.stderr else ""
            self._log(f"[LastFrame] FAILED for {video_path.name}: {stderr}")
        except Exception as e:
            self._log(f"[LastFrame] Exception: {e}")
        return None

    def _clean_video_names(self, video_dir: Path) -> int:
        """Pulisce i nomi dei file video rimuovendo pattern tipo .ext_NNNN-audio.

        Es: 123.jpg_00001-audio.webm -> 123.webm
            awam (8).webp_00002-audio.webm -> awam (8).webm
        Rinomina i file sul posto. Restituisce il numero di file rinominati.
        """
        import re
        count = 0
        # Rimuove .jpg/.png/.webp/.jpeg + _NNNN-audio
        pattern = re.compile(r'\.(jpg|jpeg|png|webp|avif|bmp|gif)_\d+-audio', re.IGNORECASE)
        for f in video_dir.iterdir():
            if not f.is_file():
                continue
            if pattern.search(f.name):
                new_name = pattern.sub('', f.name)
                new_path = f.parent / new_name
                if not new_path.exists():
                    f.rename(new_path)
                    self._log(f"[Clean] {f.name} -> {new_name}")
                    count += 1
                else:
                    # Se il file pulito esiste già, sovrascrive solo se diverso
                    if new_path.stat().st_size != f.stat().st_size:
                        f.rename(new_path)
                        self._log(f"[Clean] {f.name} -> {new_name}")
                        count += 1
        return count

    def _auto_associate_videos(self):
        """Scansiona una cartella di video .webm e associa automaticamente.

        Prima pulisce i nomi dei file (rimuove .jpg_NNNN-audio etc.),
        poi per ogni video cerca un'assignment con lo stesso nome (safe_name)
        e la associa. Estrae anche il last frame con ffmpeg.
        """
        if not self.assignments:
            QMessageBox.information(self, self.tr['title'], self.tr['select_patch_row'])
            return

        folder = QFileDialog.getExistingDirectory(
            self, self.tr['auto_assoc_title']
        )
        if not folder:
            return

        video_dir = Path(folder)

        # Pulisci i nomi dei file prima del matching
        renamed = self._clean_video_names(video_dir)
        if renamed > 0:
            self._log(f"[Clean] {renamed} files renamed")

        # Mappa: safe_name -> video_path
        videos = {}
        for f in video_dir.iterdir():
            if f.is_file() and f.suffix.lower() == ".webm":
                videos[self._safe_name(f.stem)] = f

        if not videos:
            QMessageBox.information(self, self.tr['title'], self.tr['auto_assoc_nomatch'])
            return

        # Mappa assignments: safe_name -> index
        assignment_map = {}
        for i, a in enumerate(self.assignments):
            assignment_map[self._safe_name(a.image_name)] = i

        # Prepara la progress bar del tab Patch
        self.patch_progress.setRange(0, len(videos))
        self.patch_progress.setValue(0)
        self.btn_associate.setEnabled(False)
        self._log(f"[Auto] Processing {len(videos)} videos...")

        matched = 0
        last_frames = 0
        for i, (vname, vpath) in enumerate(videos.items()):
            # Aggiorna progress bar e mantieni GUI reattiva
            self.patch_progress.setValue(i)
            QApplication.processEvents()

            if vname in assignment_map:
                idx = assignment_map[vname]
                entry = self.assignments[idx]

                # Estrai last frame
                lf_path = self._extract_last_frame_for_video(vpath)
                if lf_path:
                    last_frames += 1

                # Forza loop=False: con last frame serve play-once
                loop = entry.loop
                if lf_path and loop:
                    loop = False
                    self._log(f"[Auto] {entry.image_name}: loop forced OFF (has last frame)")

                video_dest = self._materialize_association(entry, vpath, lf_path, loop)

                matched += 1
                self._log(f"[Auto] {entry.image_name} <- {video_dest.name}")

        self.patch_progress.setValue(len(videos))
        self.btn_associate.setEnabled(True)
        self._populate_patch()
        self._update_gallery_patch_highlights()
        self._log(f"[Auto] Done: {matched}/{len(videos)} videos matched, "
                  f"{last_frames} last frames extracted")
        QMessageBox.information(
            self, self.tr['export_done_title'],
            self.tr['auto_assoc_done'].format(matched, len(videos), last_frames)
        )

    def _remove_assignment(self):
        # Raccoglie i nomi da tutte le righe selezionate (supporta multi-selezione)
        rows = {item.row() for item in self.tbl_patch.selectedItems()}
        if not rows:
            return
        names_to_remove = set()
        for row in rows:
            name_item = self.tbl_patch.item(row, 0)
            if name_item:
                names_to_remove.add(name_item.text())
        if not names_to_remove:
            return
        self.assignments = [
            a for a in self.assignments if a.image_name not in names_to_remove
        ]
        self._populate_patch()  # chiama anche _save_session
        self._update_gallery_patch_highlights()

    def _generate_patch(self):
        if not self.assignments:
            QMessageBox.warning(self, self.tr['error_title'], self.tr['no_assignments'])
            return
        if not self.game_dir or not self.game_dir.exists():
            QMessageBox.warning(self, self.tr['error_title'], self.tr['invalid_game_path'])
            return

        pending = [a for a in self.assignments if not a.has_video]
        active = [a for a in self.assignments if a.has_video]
        if pending:
            resp = QMessageBox.question(
                self, self.tr['pending_entries_title'],
                self.tr['pending_entries_msg'].format(len(pending), len(active)),
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return
        if not active:
            QMessageBox.warning(self, self.tr['error_title'], self.tr['no_active_entries'])
            return

        try:
            gen = FVGenerator(self.game_dir, log_callback=lambda m: self._log(m))
            rpy_path = gen.generate(self.assignments)

            if not rpy_path:
                QMessageBox.warning(self, self.tr['title'], self.tr['nothing_generated'])
                return

            msg = self.tr['patch_generated_msg'].format(rpy_path)
            QMessageBox.information(self, self.tr['patch_generated_title'], msg)

        except Exception as e:
            self._log(f"[ERROR] {e}")
            QMessageBox.critical(self, self.tr['generation_error_title'], str(e))

    def _remove_patch(self):
        """Rimuove la patch dal gioco: elimina fan_videos.rpy e i video associati."""
        if not self.game_dir or not self.game_dir.exists():
            QMessageBox.warning(self, self.tr['error_title'], self.tr['invalid_game_path'])
            return

        rpy_file = self.game_dir / "fan_videos.rpy"
        rpyc_file = self.game_dir / "fan_videos.rpyc"
        movies_folder = self._get_movies_folder()
        videos_dir = self.game_dir / movies_folder / "fanvideomod"
        frames_dir = self.game_dir / "images" / "fanvideomod"

        # Verifica che esista almeno la patch
        if not rpy_file.exists() and not rpyc_file.exists():
            QMessageBox.information(self, self.tr['remove_patch_title'], self.tr['remove_patch_nothing'])
            return

        # Conferma
        resp = QMessageBox.question(
            self, self.tr['remove_patch_title'],
            self.tr['remove_patch_msg'],
            QMessageBox.Yes | QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return

        removed = []

        # Elimina fan_videos.rpy e .rpyc
        for f in [rpy_file, rpyc_file]:
            if f.exists():
                f.unlink()
                removed.append(f.name)
                self._log(f"Deleted: {f}")

        # Elimina i video associati alle assignments correnti
        if self.assignments:
            for a in self.assignments:
                if a.has_video and a.video_path:
                    video_name = a.video_path.name
                    video_in_game = videos_dir / video_name
                    if video_in_game.exists():
                        video_in_game.unlink()
                        removed.append(f"{movies_folder}/fanvideomod/{video_name}")
                        self._log(f"Deleted: {video_in_game}")

        # Elimina i last frames
        if self.assignments:
            for a in self.assignments:
                if a.last_frame_path and a.last_frame_path.exists():
                    lf_name = a.last_frame_path.name
                    lf_in_game = frames_dir / lf_name
                    if lf_in_game.exists():
                        lf_in_game.unlink()
                        removed.append(f"images/fanvideomod/{lf_name}")
                        self._log(f"Deleted: {lf_in_game}")

        self._log(f"\nPatch removed: {len(removed)} files deleted")
        QMessageBox.information(self, self.tr['remove_patch_title'], self.tr['remove_patch_done'])

    def _open_folder(self, path: Path):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            self._log(f"Cannot open folder: {e}")

    def _open_sources_folder(self):
        """Apre la cartella sources/ del progetto corrente."""
        if not self.game_path:
            return
        if self.project is None:
            self.project = FVProject(self.game_path)
            self.project.load()
        sources = self.project.sources_dir
        if not sources.exists():
            sources.mkdir(parents=True, exist_ok=True)
        self._open_folder(sources)

    def _export_mod(self):
        """Esporta la patch come zip condivisibile.

        Crea uno zip contenente:
        - fan_videos.rpy (il patch)
        - {movies_folder}/fanvideomod/ (i file webm)
        - images/fanvideomod/ (gli ultimi frame)
        - README.txt (istruzioni installazione)
        """
        if not self.assignments:
            QMessageBox.warning(self, self.tr['error_title'], self.tr['export_empty'])
            return

        active = [a for a in self.assignments if a.has_video]
        if not active:
            QMessageBox.warning(self, self.tr['error_title'], self.tr['export_empty'])
            return

        if not self.game_dir or not self.game_dir.exists():
            QMessageBox.warning(self, self.tr['error_title'], self.tr['invalid_game_path'])
            return

        # Scegli dove salvare lo zip
        default_name = f"fan_video_mod_{self.game_path.name.replace('.app', '')}.zip"
        if self.game_path:
            default_dir = self.game_path.parent
        else:
            default_dir = Path.home()

        path, _ = QFileDialog.getSaveFileName(
            self, self.tr['export_title'],
            str(default_dir / default_name),
            "ZIP (*.zip)",
        )
        if not path:
            return

        zip_path = Path(path)
        try:
            import zipfile
            from datetime import datetime

            # Genera la patch nel gioco reale (come _generate_patch)
            gen = FVGenerator(self.game_dir, log_callback=lambda m: self._log(m))
            rpy_path = gen.generate(self.assignments)
            if not rpy_path or not rpy_path.exists():
                QMessageBox.warning(self, self.tr['error_title'], self.tr['export_empty'])
                return

            movies_folder = self._get_movies_folder()
            videos_dir = self.game_dir / movies_folder / "fanvideomod"
            frames_dir = self.game_dir / "images" / "fanvideomod"

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                # fan_videos.rpy
                zf.write(rpy_path, "game/fan_videos.rpy")
                self._log("Added: game/fan_videos.rpy")

                # Video
                for a in active:
                    if a.video_path and a.video_path.exists():
                        video_in_game = videos_dir / a.video_path.name
                        if video_in_game.exists():
                            zf.write(video_in_game, f"game/{movies_folder}/fanvideomod/{video_in_game.name}")
                            self._log(f"Added: game/{movies_folder}/fanvideomod/{video_in_game.name}")

                # Last frames
                for a in active:
                    if a.last_frame_path and a.last_frame_path.exists():
                        lf_in_game = frames_dir / a.last_frame_path.name
                        if lf_in_game.exists():
                            zf.write(lf_in_game, f"game/images/fanvideomod/{lf_in_game.name}")
                            self._log(f"Added: game/images/fanvideomod/{lf_in_game.name}")
                        else:
                            self._log(f"[WARN] Last frame non trovato in game dir: {a.last_frame_path.name}")

                # README con istruzioni
                readme = (
                    f"Fan Video Mod - {self.game_path.name}\n"
                    f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"Videos: {len(active)}\n\n"
                    f"INSTALLATION:\n"
                    f"1. Extract this zip into the game folder\n"
                    f"   (where the 'game' subfolder is located)\n"
                    f"2. Make sure fan_videos.rpy is in game/\n"
                    f"3. Launch the game - videos will replace static images\n\n"
                    f"UNINSTALL:\n"
                    f"Delete game/fan_videos.rpy and the video files in game/{movies_folder}/fanvideomod/\n"
                )
                zf.writestr("README.txt", readme)

            self._log(f"\nMod exported to: {zip_path}")
            QMessageBox.information(
                self, self.tr['export_done_title'],
                self.tr['export_done_msg'].format(zip_path),
            )

            # Apri la cartella dove e' stato salvato
            self._open_folder(zip_path.parent)

        except Exception as e:
            self._log(f"[ERROR] Export failed: {e}")
            QMessageBox.critical(self, self.tr['export_error_title'], str(e))

    def closeEvent(self, event):
        """Salva la sessione e termina pulitamente i thread all'uscita."""
        self._stop_video_preview()
        self._save_session()
        if hasattr(self, 'thread') and self.thread is not None:
            try:
                self.thread.quit()
                self.thread.wait(3000)
            except Exception:
                pass
        event.accept()


# ---------------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------------- #
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RenPy-Fan-Video")
    app.setWindowIcon(_app_icon())
    window = FanVideoTool()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
