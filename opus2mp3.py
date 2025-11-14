#!/usr/bin/env python

"""
Opus to MP3 Converter Application
Author: Gino Bogo

This script provides a graphical user interface (GUI) application for converting
Opus audio files to MP3 format. It utilizes FFmpeg for the conversion process,
including a two-pass loudnorm filter for consistent audio levels. The application
supports batch conversion, progress tracking, and logging of conversion events.
"""

import configparser
import concurrent.futures
import json
import os
import subprocess
import sys
import threading
from enum import Enum

import base64
from mutagen.id3 import ID3
from mutagen.id3._frames import APIC, TIT2, TPE1, TALB, TDRC, TCON, TRCK
from mutagen.mp3 import MP3
from mutagen.oggopus import OggOpus
from mutagen.flac import Picture

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

CONFIG_FILE = "opus2mp3.cfg"

################################################################################


class LogType(Enum):
    """Enum for different types of log messages.

    Each member defines a color and a display name for the log message.
    """

    OVERWRITING = ("#BF00E1", "OVERWRITING")
    CONVERTING = ("#0000FF", "CONVERTING")
    FINISHED = ("#008000", "FINISHED")
    ERROR = ("#FF0000", "ERROR")
    WARNING = ("#FFA500", "WARNING")
    INFO = ("#333333", "INFO")

    ############################################################################

    def __init__(self, color, display_name):
        """Initializes a LogType member.

        Args:
            color (str): The hexadecimal color code for the log message.
            display_name (str): The string to display as the log type prefix.
        """
        self.color = color
        self.display_name = display_name


################################################################################


class OpusToMp3Converter(QWidget):
    """Main application window for the Opus to MP3 Converter.

    Provides the user interface for selecting files, managing conversions, and
    displaying progress and output.
    """

    def __init__(self):
        """Initializes the OpusToMp3Converter application window."""
        super().__init__()
        self.setWindowTitle("Opus to MP3 Converter")
        self.setMinimumSize(600, 800)
        self.conversion_thread = None
        self._setup_ui()
        self._apply_styles()
        self._load_settings()

    ############################################################################
    # UI Setup Methods
    ############################################################################

    def _setup_ui(self):
        """Initializes the user interface.

        Sets up all the widgets and layouts for the main application window.
        """
        layout = QVBoxLayout(self)
        self._setup_directory_controls(layout)
        self._setup_file_table(layout)
        self._setup_selection_buttons(layout)
        self._setup_action_buttons(layout)
        self._setup_progress_bar(layout)
        self._setup_output_log(layout)

    def _apply_styles(self):
        """Applies CSS styles to the application.

        Sets the stylesheet for the main application window.
        """
        self.setStyleSheet(
            """
            QWidget {
                background-color: #f0f0f0;
                color: #333;
            }
            QLineEdit, QTextEdit, QTableWidget {
                background-color: #fff;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton {
                background-color: #0078d7;
                color: #fff;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #005a9e;
            }
            QPushButton:pressed {
                background-color: #004578;
            }
            QPushButton:disabled {
                background-color: #d3d3d3;
                color: #888;
            }
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
            }
        """
        )

    def _setup_directory_controls(self, parent_layout: QVBoxLayout):
        """Sets up source and destination directory controls.

        Creates and arranges widgets for selecting source and destination
        directories.

        Args:
            parent_layout (QVBoxLayout): The layout to which these controls will be
            added.
        """
        grid_layout = QGridLayout()

        # Source directory controls
        src_label = QLabel("Source:")
        src_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.src_line_edit = QLineEdit()
        self.src_line_edit.setPlaceholderText("Source Directory")
        self.src_button = QPushButton("Browse")
        self.src_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.src_button.clicked.connect(self.browse_source)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_button.clicked.connect(self.refresh_files)

        # Destination directory controls
        dest_label = QLabel("Destination:")
        dest_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.dest_line_edit = QLineEdit()
        self.dest_line_edit.setPlaceholderText("Destination Directory")
        self.dest_button = QPushButton("Browse")
        self.dest_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dest_button.clicked.connect(self.browse_destination)
        self.dest_refresh_button = QPushButton("Refresh")
        self.dest_refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dest_refresh_button.clicked.connect(self.refresh_destination)

        # Add widgets to grid
        grid_layout.addWidget(src_label, 0, 0)
        grid_layout.addWidget(self.src_line_edit, 0, 1)
        grid_layout.addWidget(self.src_button, 0, 2)
        grid_layout.addWidget(self.refresh_button, 0, 3)
        grid_layout.addWidget(dest_label, 1, 0)
        grid_layout.addWidget(self.dest_line_edit, 1, 1)
        grid_layout.addWidget(self.dest_button, 1, 2)
        grid_layout.addWidget(self.dest_refresh_button, 1, 3)

        parent_layout.addLayout(grid_layout)

    def _setup_file_table(self, parent_layout: QVBoxLayout):
        """Sets up the file table widget.

        Configures the table for displaying Opus files and their conversion
        status.

        Args:
            parent_layout (QVBoxLayout): The layout to which the file table will be
            added.
        """
        self.file_table = QTableWidget()
        self.file_table.setColumnCount(3)
        self.file_table.setHorizontalHeaderLabels(["Convert", "Filename", "Duration"])

        # Configure header resize modes
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.file_table.itemChanged.connect(self._update_buttons_state)

        parent_layout.addWidget(self.file_table)

    def _setup_selection_buttons(self, parent_layout: QVBoxLayout):
        """Sets up file selection buttons.

        Creates 'Select All' and 'Deselect All' buttons for managing file
        selections.

        Args:
            parent_layout (QVBoxLayout): The layout to which these buttons will be
            added.
        """
        select_layout = QHBoxLayout()

        self.select_all_button = QPushButton("Select All")
        self.select_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.select_all_button.clicked.connect(self.select_all)
        self.select_all_button.setEnabled(False)

        self.deselect_all_button = QPushButton("Deselect All")
        self.deselect_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deselect_all_button.clicked.connect(self.deselect_all)
        self.deselect_all_button.setEnabled(False)

        select_layout.addWidget(self.select_all_button)
        select_layout.addWidget(self.deselect_all_button)
        parent_layout.addLayout(select_layout)

    def _setup_action_buttons(self, parent_layout: QVBoxLayout):
        """Sets up conversion action buttons.

        Creates 'Convert' and 'Cancel' buttons for initiating and stopping
        conversions.

        Args:
            parent_layout (QVBoxLayout): The layout to which these buttons will be
            added.
        """
        button_layout = QHBoxLayout()

        self.convert_button = QPushButton("Convert")
        self.convert_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.convert_button.clicked.connect(self.start_conversion)
        self.convert_button.setEnabled(False)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_button.clicked.connect(self.cancel_conversion)
        self.cancel_button.setEnabled(False)

        button_layout.addWidget(self.convert_button)
        button_layout.addWidget(self.cancel_button)
        parent_layout.addLayout(button_layout)

    def _setup_progress_bar(self, parent_layout: QVBoxLayout):
        """Sets up the progress bar.

        Initializes the QProgressBar widget for displaying conversion progress.

        Args:
            parent_layout (QVBoxLayout): The layout to which the progress bar will
            be added.
        """
        self.progress_bar = QProgressBar()
        parent_layout.addWidget(self.progress_bar)

    def _setup_output_log(self, parent_layout: QVBoxLayout):
        """Sets up the output log.

        Initializes the QTextEdit widget for displaying conversion output and
        messages.

        Args:
            parent_layout (QVBoxLayout): The layout to which the output log will be
            added.
        """
        self.output_log = QTextEdit()
        self.output_log.setReadOnly(True)
        parent_layout.addWidget(self.output_log)

    ############################################################################
    # Configuration Methods
    ############################################################################

    def _load_settings(self):
        """Loads window settings from the configuration file."""
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE)

        width = config.getint("MainWindow", "width", fallback=800)
        height = config.getint("MainWindow", "height", fallback=600)
        x_pos = config.getint("MainWindow", "x_pos", fallback=100)
        y_pos = config.getint("MainWindow", "y_pos", fallback=100)

        self.setGeometry(x_pos, y_pos, width, height)

    def _save_settings(self):
        """Saves current window settings to the configuration file."""
        config = configparser.ConfigParser()
        # Read existing config to preserve other sections if they exist
        config.read(CONFIG_FILE)

        if "MainWindow" not in config:
            config["MainWindow"] = {}

        config["MainWindow"]["width"] = str(self.width())
        config["MainWindow"]["height"] = str(self.height())
        config["MainWindow"]["x_pos"] = str(self.x())
        config["MainWindow"]["y_pos"] = str(self.y())

        with open(CONFIG_FILE, "w") as config_file:
            config.write(config_file)

    ############################################################################
    # File Management Methods
    ############################################################################

    def _validate_source_directory(self):
        """Validates that the source directory exists.

        Checks if the path in `src_line_edit` points to an existing directory.

        Returns:
            bool: True if the source directory is valid, False otherwise.
        """
        src_dir = self.src_line_edit.text()
        if not os.path.isdir(src_dir):
            self.append_log(
                LogType.WARNING,
                "Source directory not set. Please select a valid directory.",
            )
            return False
        return True

    def _get_opus_files(self, src_dir):
        """Gets a list of Opus files in the specified directory.

        Scans the given source directory for files ending with '.opus'.

        Args:
            src_dir (str): The absolute path to the source directory.

        Returns:
            list: A list of Opus filenames found in the directory.
        """
        try:
            return [f for f in os.listdir(src_dir) if f.endswith(".opus")]
        except FileNotFoundError:
            self.output_log.append(f"Source directory not found: {src_dir}")
            return []

    def _add_file_to_table(self, row, opus_file, src_dir):
        """Adds a file to the file table.

        Inserts a new row into the file table with a checkbox, filename, and
        duration.

        Args:
            row (int): The row index where the file should be added. opus_file
            (str): The filename of the Opus file. src_dir (str): The source
            directory of the Opus file.
        """
        self.file_table.insertRow(row)

        # Create checkbox item
        check_item = QTableWidgetItem()
        check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
        check_item.setCheckState(Qt.CheckState.Checked)

        # Create filename item
        file_item = QTableWidgetItem(opus_file)
        file_item.setFlags(file_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Create duration item
        duration_str = self.get_duration_str(os.path.join(src_dir, opus_file))
        duration_item = QTableWidgetItem(duration_str)
        duration_item.setFlags(duration_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        # Add items to table
        self.file_table.setItem(row, 0, check_item)
        self.file_table.setItem(row, 1, file_item)
        self.file_table.setItem(row, 2, duration_item)

    def get_duration_str(self, filepath):
        """Gets the duration string for a media file using ffprobe.

        Executes `ffprobe` to extract the duration of a given media file and
        formats it as MM:SS.

        Args:
            filepath (str): The absolute path to the media file.

        Returns:
            str: A string representing the duration (MM:SS) or "--:--" if
            duration cannot be determined.
        """
        command = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            filepath,
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            duration = float(result.stdout.strip())
            minutes = int(duration // 60)
            seconds = int(duration % 60)
            return f"{minutes:02d}:{seconds:02d}"
        except (subprocess.CalledProcessError, FileNotFoundError):
            return "--:--"

    ############################################################################
    # UI Interaction Methods
    ############################################################################

    def _get_existing_directory(self, title):
        """Opens a directory dialog and returns the selected path.

        Temporarily disables the main window while the dialog is open.

        Args:
            title (str): The title for the directory selection dialog.

        Returns:
            str: The absolute path of the selected directory, or an empty string
            if cancelled.
        """
        self.setEnabled(False)
        dir_path = QFileDialog.getExistingDirectory(self, title)
        self.setEnabled(True)
        return dir_path

    def browse_source(self):
        """Browses for the source directory.

        Opens a directory selection dialog and updates the source path and file
        list.
        """
        dir_path = self._get_existing_directory("Select Source Directory")
        if dir_path:
            self.src_line_edit.setText(dir_path)
            self.refresh_files()

    def browse_destination(self):
        """Browsers for the destination directory.

        Opens a directory selection dialog and updates the destination path.
        """
        dir_path = self._get_existing_directory("Select Destination Directory")
        if dir_path:
            self.dest_line_edit.setText(dir_path)
            self.refresh_destination()

    def refresh_destination(self):
        """Refreshes the count of MP3 files in the destination directory.

        Reads the current destination path and updates the log with the number
        of MP3 files found, without opening a directory selection dialog.
        """
        dir_path = self.dest_line_edit.text()
        if not dir_path:
            self.append_log(
                LogType.WARNING,
                "Destination directory not set. Please select a valid directory.",
            )
            return

        try:
            mp3_files = [
                f
                for f in os.listdir(dir_path)
                if f.endswith(".mp3") and not f.startswith(".")
            ]
            self.append_log(
                LogType.INFO,
                f"Found {len(mp3_files)} MP3 files in destination folder.",
            )
        except FileNotFoundError:
            self.append_log(
                LogType.ERROR, f"Destination directory not found: {dir_path}"
            )

    def refresh_files(self):
        """Refreshes the list of Opus files in the source directory.

        Clears the current file table and repopulates it with files from the
        selected source directory.
        """
        self.setEnabled(False)

        if not self._validate_source_directory():
            self.setEnabled(True)
            return

        src_dir = self.src_line_edit.text()

        try:
            self.file_table.itemChanged.disconnect(self._update_buttons_state)
        except RuntimeError:
            pass  # Ignore error if not connected

        self.file_table.setRowCount(0)

        opus_files = self._get_opus_files(src_dir)

        self.append_log(
            LogType.INFO, f"Found {len(opus_files)} Opus files in source folder."
        )

        for i, opus_file in enumerate(opus_files):
            self._add_file_to_table(i, opus_file, src_dir)

        self.file_table.itemChanged.connect(self._update_buttons_state)
        self._update_buttons_state()

        self.setEnabled(True)

    def _update_buttons_state(self):
        """Updates the enabled state of the buttons based on file selection.

        - 'Convert' is enabled only if at least one file is checked.
        - 'Select All' and 'Deselect All' are enabled if there are any files in
          the table.
        """
        has_files = self.file_table.rowCount() > 0
        has_selected_files = False

        if has_files:
            for i in range(self.file_table.rowCount()):
                item = self.file_table.item(i, 0)
                if item and item.checkState() == Qt.CheckState.Checked:
                    has_selected_files = True
                    break

        self.convert_button.setEnabled(has_selected_files)
        self.select_all_button.setEnabled(has_files)
        self.deselect_all_button.setEnabled(has_files)

    def _set_table_check_state(self, state):
        """Sets the check state for all files in the table.

        Iterates through all rows in the file table and sets the checkbox state.

        Args:
            state (Qt.CheckState): The `Qt.CheckState` to apply (e.g.,
            `Qt.CheckState.Checked`).
        """
        try:
            self.file_table.itemChanged.disconnect(self._update_buttons_state)
        except RuntimeError:
            pass  # Ignore error if not connected

        for i in range(self.file_table.rowCount()):
            item = self.file_table.item(i, 0)
            if item is not None:
                item.setCheckState(state)

        self.file_table.itemChanged.connect(self._update_buttons_state)
        self._update_buttons_state()

    def select_all(self):
        """Selects all files in the table.

        Checks all checkboxes in the file table and temporarily disables the UI.
        """
        self.setEnabled(False)
        self._set_table_check_state(Qt.CheckState.Checked)
        self.setEnabled(True)

    def deselect_all(self):
        """Deselects all files in the table.

        Unchecks all checkboxes in the file table and temporarily disables the UI.
        """
        self.setEnabled(False)
        self._set_table_check_state(Qt.CheckState.Unchecked)
        self.setEnabled(True)

    ############################################################################
    # Conversion Control Methods
    ############################################################################

    def _validate_destination_directory(self):
        """Validates and prepares the destination directory.

        Checks if the destination directory is set and creates it if it doesn't
        exist.

        Returns:
            str or None: The absolute path of the destination directory, or None
            if invalid or creation failed.
        """
        dest_dir = self.dest_line_edit.text()

        if not dest_dir:
            self.output_log.append("Destination directory not set.")
            return None

        if not os.path.isdir(dest_dir):
            try:
                os.makedirs(dest_dir)
                self.output_log.append(f"Created destination directory: {dest_dir}")
            except OSError as e:
                self.output_log.append(f"Error creating destination directory: {e}")
                return None

        return dest_dir

    def _get_selected_files(self):
        """Gets a list of selected files for conversion.

        Iterates through the file table and collects paths of checked Opus
        files.

        Returns:
            list: A list of absolute paths to the selected Opus files.
        """
        files_to_convert = []
        src_dir = self.src_line_edit.text()

        for i in range(self.file_table.rowCount()):
            check_item = self.file_table.item(i, 0)
            if (
                check_item is not None
                and check_item.checkState() == Qt.CheckState.Checked
            ):
                filename_item = self.file_table.item(i, 1)
                if filename_item is not None:
                    filename = filename_item.text()
                    files_to_convert.append(os.path.join(src_dir, filename))

        return files_to_convert

    def set_conversion_ui_state(self, is_converting):
        """Updates UI state during conversion.

        Enables or disables various UI widgets based on whether a conversion is
        active.

        Args:
            is_converting (bool): A boolean indicating if a conversion is
            currently in progress.
        """
        widgets_to_toggle = [
            self.src_line_edit,
            self.src_button,
            self.refresh_button,
            self.dest_line_edit,
            self.dest_button,
            self.file_table,
            self.select_all_button,
            self.deselect_all_button,
            self.convert_button,
        ]

        for widget in widgets_to_toggle:
            widget.setEnabled(not is_converting)

        self.cancel_button.setEnabled(is_converting)

    def _prepare_conversion_ui(self):
        """Prepares the UI for conversion start.

        Updates the UI state, resets the progress bar, and clears the output
        log.
        """
        self.set_conversion_ui_state(True)
        self.progress_bar.setValue(0)
        self.output_log.clear()

    def _setup_conversion_thread(self, files_to_convert, dest_dir):
        """Sets up and configures the conversion thread.

        Initializes the `ConversionThread` with files and destination, and
        connects its signals.

        Args:
            files_to_convert (list): A list of absolute paths to Opus files to
            convert. dest_dir (str): The absolute path to the destination
            directory for MP3 files.
        """
        if self.conversion_thread and self.conversion_thread.isRunning():
            self.conversion_thread.finished.disconnect(self.conversion_finished)

        self.conversion_thread = ConversionThread(files_to_convert, dest_dir)
        self.conversion_thread.progress.connect(self.progress_bar.setValue)
        self.conversion_thread.output.connect(self.append_log)
        self.conversion_thread.finished.connect(self.conversion_finished)

    def start_conversion(self):
        """Starts the conversion process.

        Validates directories and selected files, then initiates the conversion
        thread.
        """
        dest_dir = self._validate_destination_directory()
        if not dest_dir:
            return

        files_to_convert = self._get_selected_files()
        if not files_to_convert:
            self.output_log.append("No files selected for conversion.")
            return

        self._prepare_conversion_ui()
        self._setup_conversion_thread(files_to_convert, dest_dir)
        if self.conversion_thread is not None:
            self.conversion_thread.start()

    def cancel_conversion(self):
        """Cancels the ongoing conversion.

        Signals the conversion thread to stop and updates the UI state.
        """
        if self.conversion_thread and self.conversion_thread.isRunning():
            self.conversion_thread.stop()
            self.output_log.append("Conversion cancelled.")
            self.set_conversion_ui_state(False)

    def conversion_finished(self):
        """Handles conversion completion.

        Logs a completion message and resets the UI state.
        """
        self.output_log.append("Conversion complete.")
        self.set_conversion_ui_state(False)

    ############################################################################
    # Utility Methods
    ############################################################################

    def append_log(self, log_type: LogType, message: str):
        """Appends a formatted log message to the output log.

        Formats the message with the specified log type and color, then appends
        it to the QTextEdit log.

        Args:
            log_type (LogType): The `LogType` enum member indicating the type of
            log message. message (str): The raw string content of the log
            message.
        """
        color = log_type.color
        display_name = log_type.display_name

        formatted_message = f"{display_name}: {message}"
        escaped_message = self._escape_html(formatted_message)

        self.output_log.append(f'<font color="{color}">{escaped_message}</font>')

    def _escape_html(self, text):
        """Escapes HTML special characters in text.

        Converts characters like '&', '<', '>', and newline to their HTML
        entities.

        Args:
            text (str): The input string to escape.

        Returns:
            str: The HTML-escaped string.
        """
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )

    def closeEvent(self, event):
        """Overrides the close event to save window settings."""
        self._save_settings()
        event.accept()


################################################################################


class ConversionThread(QThread):
    """QThread for handling Opus to MP3 conversion in a separate thread.

    Manages the conversion of multiple Opus files to MP3 format, including
    progress tracking, output logging, and cancellation.
    """

    progress = Signal(int)
    output = Signal(LogType, str)

    ############################################################################

    def __init__(self, files_to_convert, dest_dir):
        """Initializes the ConversionThread.

        Args:
            files_to_convert (list): A list of absolute paths to Opus files to
            convert. dest_dir (str): The absolute path to the destination
            directory for MP3 files.
        """
        super().__init__()
        self.files_to_convert = files_to_convert
        self.dest_dir = dest_dir
        self.running = True
        self.completed_files = 0
        self.lock = threading.Lock()

    ############################################################################
    # Core Conversion Methods
    ############################################################################

    def convert_file(self, src_path):
        """Converts a single Opus file to MP3.

        Orchestrates the conversion process for a single file, including
        handling existing files, executing FFmpeg, and processing results.

        Args:
            src_path (str): The absolute path to the source Opus file.

        Raises:
            FileNotFoundError: If `ffmpeg` is not found during execution.
            Exception: For any other errors during conversion.
        """
        if not self.running:
            return

        opus_file = os.path.basename(src_path)
        filename = os.path.splitext(opus_file)[0]
        dest_path = os.path.join(self.dest_dir, f"{filename}.mp3")

        self._handle_existing_file(dest_path, opus_file)

        try:
            # First pass
            first_pass_command = self._get_ffmpeg_first_pass_command(src_path)
            loudnorm_stats = self._execute_first_pass(first_pass_command)

            # Second pass
            second_pass_command = self._get_ffmpeg_second_pass_command(
                src_path, dest_path, loudnorm_stats
            )
            returncode, output = self._execute_second_pass(
                second_pass_command, opus_file
            )
            self._handle_conversion_result(returncode, output, opus_file)
            if returncode == 0:
                # Find and copy cover art
                picture = self._find_front_cover(src_path, opus_file)
                if picture:
                    self._copy_cover_art(dest_path, picture)
                self._copy_id3_tags(src_path, dest_path)

        except FileNotFoundError as e:
            self.output.emit(LogType.ERROR, str(e))
            self.running = False
        except Exception as e:
            self.output.emit(
                LogType.ERROR,
                f"An error occurred during conversion of {opus_file}: {e}",
            )

    def _handle_existing_file(self, dest_path, opus_file):
        """Handles logging for existing files.

        Emits a log message indicating whether a file is being overwritten or
        converted.

        Args:
            dest_path (str): The absolute path to the destination MP3 file.
            opus_file (str): The base name of the source Opus file.
        """
        if os.path.exists(dest_path):
            self.output.emit(LogType.OVERWRITING, f"{os.path.basename(dest_path)}...")
        else:
            self.output.emit(LogType.CONVERTING, f"{opus_file}...")

    def _handle_conversion_result(self, returncode, output, opus_file):
        """Processes the result of a conversion attempt.

        Emits appropriate log messages and updates the progress bar based on the
        FFmpeg return code.

        Args:
            returncode (int): The exit code of the FFmpeg process. output (str):
            The output captured from the FFmpeg process. opus_file (str): The
            base name of the source Opus file.
        """
        if returncode == 0:
            self.output.emit(LogType.FINISHED, f"{opus_file}.")

            with self.lock:
                self.completed_files += 1
                progress = int(
                    (self.completed_files / len(self.files_to_convert)) * 100
                )
                self.progress.emit(progress)
        else:
            self.output.emit(
                LogType.ERROR,
                f"Converting {opus_file}. ffmpeg returned non-zero exit code.",
            )
            self.output.emit(LogType.ERROR, f"{output.strip()}")

    ############################################################################
    # FFmpeg Command Methods
    ############################################################################

    def _get_ffmpeg_first_pass_command(self, src_path):
        """Builds the FFmpeg command for the first pass of loudnorm.

        Constructs a list of arguments for the FFmpeg subprocess, including
        input, output, and audio filtering options.

        Args:
            src_path (str): The absolute path to the source Opus file.

        Returns:
            list: A list of strings representing the FFmpeg command.
        """
        return [
            "ffmpeg",
            "-i",
            src_path,
            "-af",
            "loudnorm=I=-12:LRA=11:TP=-1.5:print_format=json",
            "-f",
            "null",
            "-",
        ]

    def _get_ffmpeg_second_pass_command(self, src_path, dest_path, loudnorm_stats):
        """Builds the FFmpeg command for the second pass of loudnorm.

        Constructs a list of arguments for the FFmpeg subprocess, including
        input, output, and audio filtering options.

        Args:
            src_path (str): The absolute path to the source Opus file. dest_path
            (str): The absolute path to the destination MP3 file. loudnorm_stats
            (dict): A dictionary of loudnorm stats from the first pass.

        Returns:
            list: A list of strings representing the FFmpeg command.
        """
        loudnorm_params = (
            f"loudnorm=I=-12:LRA=11:TP=-1.5:"
            f"measured_I={loudnorm_stats['input_i']}:"
            f"measured_LRA={loudnorm_stats['input_lra']}:"
            f"measured_TP={loudnorm_stats['input_tp']}:"
            f"measured_thresh={loudnorm_stats['input_thresh']}:"
            f"offset={loudnorm_stats['target_offset']}"
        )

        if loudnorm_stats["normalization_type"] == "dynamic":
            loudnorm_params += ":linear=true"

        return [
            "ffmpeg",
            "-y",
            "-i",
            src_path,
            "-af",
            loudnorm_params,
            "-q:a",
            "0",
            "-ar",
            "48000",
            dest_path,
        ]

    ############################################################################
    # FFmpeg Execution Methods
    ############################################################################

    def _execute_first_pass(self, command):
        """Executes the first pass of FFmpeg loudnorm and returns the parsed stats.

        Runs the FFmpeg command as a subprocess and captures its output.

        Args:
            command (list): A list of strings representing the FFmpeg command.

        Returns:
            dict: A dictionary containing the parsed loudnorm stats.

        Raises:
            FileNotFoundError: If the `ffmpeg` executable is not found.
            RuntimeError: If the conversion fails for other reasons.
        """
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
            )

            _, stderr = process.communicate()
            if process.returncode != 0:
                raise RuntimeError(f"ffmpeg returned non-zero exit code: {stderr}")

            return self._parse_loudnorm_stats(stderr)

        except FileNotFoundError:
            raise FileNotFoundError("ffmpeg not found")
        except Exception as e:
            raise RuntimeError(f"First pass failed: {e}")

    def _execute_second_pass(self, command, opus_file):
        """Executes the second pass of FFmpeg loudnorm.

        Runs the FFmpeg command as a subprocess and captures its output.

        Args:
            command (list): A list of strings representing the FFmpeg command.
            opus_file (str): The base name of the source Opus file.

        Returns:
            tuple: A tuple containing the return code of the FFmpeg process and
            its output.

        Raises:
            FileNotFoundError: If the `ffmpeg` executable is not found.
            RuntimeError: If the conversion fails for other reasons.
        """
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                ),
            )

            output, _ = process.communicate()
            return process.returncode, output
        except FileNotFoundError:
            raise FileNotFoundError("ffmpeg not found")
        except Exception as e:
            raise RuntimeError(f"Conversion failed: {e}")

    def _parse_loudnorm_stats(self, stderr):
        """Parses the JSON output from the first pass of loudnorm.

        Args:
            stderr (str): The stderr output from the ffmpeg process.

        Returns:
            dict: A dictionary containing the parsed loudnorm stats.
        """
        json_start = stderr.find("{")
        json_end = stderr.rfind("}")

        if json_start == -1 or json_end == -1:
            raise ValueError("Could not find loudnorm stats in FFmpeg output.")

        json_str = stderr[json_start : json_end + 1]
        stats = json.loads(json_str)

        for key, value in stats.items():
            if key != "normalization_type":
                stats[key] = float(value)

        return stats

    ############################################################################
    # Metadata Handling Methods
    ############################################################################

    def _copy_id3_tags(self, src_opus_path, dest_mp3_path):
        """Copies ID3 tags from an Opus file to an MP3 file.

        Args:
            src_opus_path (str): The absolute path to the source Opus file.
            dest_mp3_path (str): The absolute path to the destination MP3 file.
        """
        try:
            opus_audio = OggOpus(src_opus_path)
            mp3_audio = MP3(dest_mp3_path, ID3=ID3)

            if mp3_audio.tags is None:
                mp3_audio.tags = ID3()

            if opus_audio.tags:
                self._process_opus_tags(
                    opus_audio, mp3_audio, os.path.basename(src_opus_path)
                )
                mp3_audio.save()
                self.output.emit(
                    LogType.INFO,
                    f"Copied ID3 tags from {os.path.basename(src_opus_path)} to {os.path.basename(dest_mp3_path)}.",
                )
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Error copying ID3 tags from {os.path.basename(src_opus_path)} to {os.path.basename(dest_mp3_path)}: {e}",
            )

    def _process_opus_tags(self, opus_audio, mp3_audio, src_filename):
        """Process and copy tags from Opus to MP3.

        Args:
            opus_audio: The Opus audio file object.
            mp3_audio: The MP3 audio file object to copy tags to.
            src_filename: The source filename for error messages.
        """
        TAG_MAPPING = {
            "title": TIT2,
            "artist": TPE1,
            "album": TALB,
            "genre": TCON,
            "tracknumber": TRCK,
        }

        for tag_name, tag_value in opus_audio.tags.items():
            if tag_name == "metadata_block_picture":
                self._handle_cover_art(tag_value, mp3_audio)
                continue

            if tag_name == "date":
                self._handle_date_tag(tag_value, mp3_audio, src_filename)
            elif tag_name in TAG_MAPPING:
                self._copy_simple_tag(tag_name, tag_value, TAG_MAPPING, mp3_audio)

    def _copy_simple_tag(self, tag_name, tag_value, tag_mapping, mp3_audio):
        """Copy a simple tag from Opus to MP3.

        Args:
            tag_name: The name of the tag to copy.
            tag_value: The value of the tag.
            tag_mapping: Dictionary mapping tag names to ID3 frame classes.
            mp3_audio: The MP3 audio file object to add the tag to.
        """
        id3_frame_class = tag_mapping[tag_name]
        # Handle both list and non-list tag values
        text_values = tag_value if isinstance(tag_value, list) else [str(tag_value)]
        # Ensure all values are strings
        text_values = [str(v) for v in text_values if v is not None]
        if text_values:  # Only add if we have valid values
            mp3_audio.tags[id3_frame_class.__name__] = id3_frame_class(
                encoding=3, text=text_values
            )

    def _parse_year_from_date(self, date_val, src_filename):
        """Parses a year from a date value."""
        try:
            return str(int(date_val))
        except (ValueError, TypeError):
            self.output.emit(
                LogType.WARNING,
                f"Invalid date format in {src_filename}: '{date_val}'. Skipping this date value.",
            )
            return None

    def _handle_date_tag(self, tag_value, mp3_audio, src_filename):
        """Handle date tag conversion from Opus to MP3.

        Args:
            tag_value: The date value from the Opus file.
            mp3_audio: The MP3 audio file object to add the date tag to.
            src_filename: The source filename for error messages.
        """
        try:
            date_values = tag_value if isinstance(tag_value, list) else [tag_value]
            years = [
                year
                for date_val in date_values
                if (year := self._parse_year_from_date(date_val, src_filename))
            ]

            if years:
                mp3_audio.tags["TDRC"] = TDRC(encoding=3, text=years)
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Error processing date tag for {src_filename}: {e}",
            )

    ############################################################################
    # Cover Art Handling Methods
    ############################################################################

    def _copy_cover_art(self, mp3_path, picture):
        """Helper function to add cover art to an MP3 file.

        Args:
            mp3_path (str): The absolute path to the MP3 file.
            picture (Picture): The mutagen Picture object to add.
        """
        try:
            mp3_audio = MP3(mp3_path, ID3=ID3)

            # Ensure ID3 tags exist
            if mp3_audio.tags is None:
                mp3_audio.tags = ID3()
                mp3_audio.save()  # Save the newly created tags

            # Remove existing APIC frames to avoid duplicates
            mp3_audio.tags.delall("APIC")

            mp3_audio.tags.add(
                APIC(
                    encoding=3,
                    mime=picture.mime,
                    type=3,  # 3 is for the front cover
                    desc="Cover",
                    data=picture.data,
                )
            )
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Failed to add cover art to {os.path.basename(mp3_path)}: {e}",
            )

    def _find_front_cover(self, src_opus_path, src_opus_basename):
        """Finds the front cover Picture object from an OggOpus file.

        Args:
            src_opus_path (str): The absolute path to the source Opus file.
            src_opus_basename (str): The base name of the source Opus file for logging.

        Returns:
            Picture or None: The front cover Picture object if found, otherwise None.
        """
        try:
            opus_audio = OggOpus(src_opus_path)
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Failed to create OggOpus object for {src_opus_basename}: {e}",
            )
            return None

        if opus_audio.tags:
            metadata_block_pictures = opus_audio.tags.get("metadata_block_picture")
            return self._get_picture_from_metadata_block(
                metadata_block_pictures, src_opus_basename
            )
        else:
            self.output.emit(
                LogType.WARNING,
                f"No tags found in {src_opus_basename}.",
            )
        return None

    def _get_picture_from_metadata_block(
        self, metadata_block_pictures, src_opus_basename
    ):
        """Extracts the front cover art from the metadata of an Opus file.

        This function iterates through a list of picture data blocks, decodes
        them, and attempts to create a Picture object or an APIC frame.

        Args:
            metadata_block_pictures (list or str): A list of base64-encoded
            picture data blocks, or a single block. src_opus_basename (str): The
            base name of the source Opus file, used for logging.

        Returns:
            mutagen.flac.Picture or mutagen.id3.APIC or None: The extracted
            cover art, or None if no valid front cover is found.
        """
        if not metadata_block_pictures:
            self.output.emit(
                LogType.WARNING,
                f"No metadata block pictures found in {src_opus_basename}",
            )
            return None

        if not isinstance(metadata_block_pictures, list):
            metadata_block_pictures = [metadata_block_pictures]

        for pic_data_b64 in metadata_block_pictures:
            pic_data = self._decode_picture_data(pic_data_b64, src_opus_basename)
            if not pic_data:
                continue

            picture = self._create_picture_object(pic_data, src_opus_basename)
            if picture:
                return picture

            apic_frame = self._create_apic_frame(pic_data, src_opus_basename)
            if apic_frame:
                return apic_frame

        self.output.emit(
            LogType.WARNING,
            f"No valid front cover found in {src_opus_basename}",
        )
        return None

    def _decode_picture_data(self, pic_data_b64, src_opus_basename):
        """Decodes picture data from base64 or bytes."""
        try:
            if isinstance(pic_data_b64, str):
                try:
                    return base64.b64decode(pic_data_b64, validate=True)
                except Exception:
                    return pic_data_b64.encode("utf-8")
            return pic_data_b64
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Failed to decode picture data for {src_opus_basename}: {e}",
            )
            return None

    def _create_picture_object(self, pic_data, src_opus_basename):
        """Tries to create a Picture object from the data."""
        try:
            picture = Picture(pic_data)
            if picture.type == 3:  # 3 is for the front cover
                return picture
        except Exception:
            # If creating Picture fails, we'll try creating an APIC frame next.
            pass

    def _create_apic_frame(self, pic_data, src_opus_basename):
        """Creates an APIC frame as a fallback."""
        try:
            mime = "image/jpeg"  # default to jpeg
            if pic_data.startswith(b"\x89PNG"):
                mime = "image/png"

            return APIC(
                encoding=3,  # UTF-8
                mime=mime,
                type=3,  # 3 is for the front cover
                desc="Cover",
                data=pic_data,
            )
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Failed to create APIC frame for {src_opus_basename}: {e}",
            )
            return None

    def _get_picture_from_picture_data(self, picture_data):
        """Extracts a Picture object from picture data.

        Args:
            picture_data: The picture data from the Opus file.

        Returns:
            A Picture object or the original picture data.
        """
        if not picture_data:
            return None

        if isinstance(picture_data, list):
            picture_data = picture_data[0]

        if isinstance(picture_data, str):
            return Picture(base64.b64decode(picture_data))
        else:
            return picture_data

    def _handle_cover_art(self, picture_data, mp3_audio):
        """Handle cover art from metadata block picture.

        Args:
            picture_data: The picture data from the Opus file.
            mp3_audio: The MP3 audio file object to add the cover art to.
        """
        try:
            picture = self._get_picture_from_picture_data(picture_data)
            if picture and hasattr(picture, "data"):
                self._copy_cover_art(mp3_audio.filename, picture)
                self.output.emit(
                    LogType.INFO,
                    f"Copied cover art to {os.path.basename(mp3_audio.filename)}.",
                )
        except Exception as e:
            self.output.emit(
                LogType.WARNING,
                f"Failed to process cover art: {e}",
            )

    ############################################################################
    # Thread Management Methods
    ############################################################################

    def _setup_parallel_conversion(self):
        """Sets up and manages parallel file conversion.

        Initializes a thread pool and submits conversion tasks for all selected
        files.
        """
        num_workers = os.cpu_count()
        self.output.emit(
            LogType.INFO, f"Starting conversion with {num_workers} parallel workers."
        )

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(self.convert_file, file): file
                for file in self.files_to_convert
            }
            self._monitor_conversion_progress(futures)

    def _monitor_conversion_progress(self, futures):
        """Monitors conversion progress and handles cancellation.

        Iterates through completed futures and checks for cancellation requests.

        Args:
            futures (dict): A dictionary of futures representing ongoing
            conversions.
        """
        for _ in concurrent.futures.as_completed(futures):
            if not self.running:
                self._cancel_pending_conversions(futures)
                break

    def _cancel_pending_conversions(self, futures):
        """Cancels all pending conversions.

        Iterates through a list of futures and attempts to cancel each one.

        Args:
            futures (list): A list of futures representing pending conversions.
        """
        for future in futures:
            future.cancel()

    def run(self):
        """Main conversion execution method.

        Initiates the parallel conversion process for all selected files.
        """
        if not self.files_to_convert:
            self.output.emit(LogType.INFO, "No files selected for conversion.")
            return

        self._setup_parallel_conversion()

    def stop(self):
        """Stops the conversion process.

        Sets an internal flag to signal ongoing conversions to cease.
        """
        self.running = False


################################################################################


def main():
    """Main application entry point.

    Initializes and runs the Opus to MP3 Converter application.
    """
    try:
        app = QApplication(sys.argv)
        converter = OpusToMp3Converter()
        converter.show()
        sys.exit(app.exec())
    except Exception as e:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Critical)
        msg.setText("An unexpected error occurred")
        msg.setInformativeText(str(e))
        msg.setWindowTitle("Error")
        msg.exec()


################################################################################


if __name__ == "__main__":
    main()
