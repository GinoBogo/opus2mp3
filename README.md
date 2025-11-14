# opus2mp3
GUI application that converts Opus audio files to MP3 format.

This script provides a user-friendly graphical interface for converting Opus audio files (.opus) into the more widely compatible MP3 format. It's designed for simplicity and efficiency, allowing users to easily select Opus files, convert them, and save them as MP3s with just a few clicks. The application handles the underlying conversion process, making it accessible even for users who are not familiar with command-line tools.

Key Features:
- **Batch Conversion:** Convert multiple Opus files to MP3 simultaneously.
- **Intuitive GUI:** Easy-to-use interface for selecting files and managing conversions.
- **Progress Tracking:** Monitor the conversion progress of each file.
- **Error Handling:** Provides feedback on any conversion failures.

How it Works:
The application leverages external libraries to perform the audio conversion. This includes a two-step pre-processing phase for each Opus file to normalize the music level, ensuring consistent playback volume. When you select Opus files and initiate the conversion, the script processes each file, transcodes the audio data from Opus to MP3, and saves the new MP3 files to your specified output directory.

![figure_01.png](docs/images/figure_01.png)

## Technologies Used
The `opus2mp3` script is built using the following key technologies:
- **PySide6:** For creating the graphical user interface, providing a modern and responsive experience.
- **FFmpeg:** An essential open-source multimedia framework used for handling the audio conversion from Opus to MP3 format.
- **Python:** The core programming language for the application logic.

## Installation

To run this application, you need to have Python installed, along with the following dependencies. It is recommended to use a virtual environment.

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/opus2mp3.git
    cd opus2mp3
    ```
2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv .venv
    # On Windows
    .venv\Scripts\activate
    # On macOS/Linux
    source .venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Install FFmpeg:**
    This application requires FFmpeg to be installed and accessible in your system's PATH. Please refer to the official FFmpeg website for installation instructions specific to your operating system.

## How to Run

After installing the dependencies, you can run the application using:
```bash
python opus2mp3.py
```


