# QuoteFinder

A Docker-based Python application that extracts speech from media files and stores it with timestamps for easy querying later.

## Features

- Scan directories recursively for media files (mkv, mp4, avi, mov, wmv, flv, webm)
- Extract audio from video files using FFmpeg
- Convert speech to text using OpenAI Whisper
- Store transcriptions with segment-level timestamps in JSON format
- Skip already-processed files automatically
- Supports multiple Whisper model sizes for accuracy/speed tradeoff

## Quick Start

### 1. Build the Docker image

```bash
docker-compose build
```

### 2. Prepare your media files

Place your media files in the `./media` directory (this will be created automatically or you can create it manually).

### 3. Process media files

```bash
docker-compose run quotefinder --input-dir /media --output-dir /output
```

Transcription JSON files will be saved to the `./output` directory.

## Usage

### Basic Usage

Process all media files in a directory:
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output
```

### Advanced Options

Use a larger Whisper model for better accuracy (slower):
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output --model small
```

Available models: `tiny`, `base` (default), `small`, `medium`, `large`

Detect and record the language of each file:
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output --detect-language
```

Reprocess files that already have JSON output:
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output --reprocess
```

Process only specific file types:
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output --extensions mkv mp4
```

Scan only the top-level directory (no subdirectories):
```bash
docker-compose run quotefinder --input-dir /media --output-dir /output --no-recursive
```

### Getting Help

```bash
docker-compose run quotefinder --help
```

## Output Format

Each processed media file generates a JSON file with the following structure:

```json
{
  "media_file": "/media/video.mkv",
  "media_filename": "video.mkv",
  "processed_at": "2026-02-16T10:30:00Z",
  "duration_seconds": 3600,
  "model": "base",
  "language": "en",
  "total_segments": 120,
  "segments": [
    {
      "id": 0,
      "start": 0.0,
      "end": 3.5,
      "text": "Hello and welcome to the show."
    },
    {
      "id": 1,
      "start": 3.5,
      "end": 7.2,
      "text": "Today we're going to talk about Python."
    }
  ]
}
```

## Directory Structure

```
QuoteFinder/
├── media/              # Input: place your media files here
├── output/             # Output: JSON transcriptions saved here
├── QuoteFinder/        # Application source code
│   ├── main.py
│   ├── media_scanner.py
│   ├── audio_extractor.py
│   ├── speech_processor.py
│   ├── storage.py
│   └── logger.py
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## System Requirements

- Docker and Docker Compose
- Sufficient disk space for:
  - Whisper models (140MB - 2.9GB depending on model size)
  - Temporary audio files during processing
  - JSON output files

## Model Selection Guide

| Model  | Size  | Speed | Accuracy | Use Case |
|--------|-------|-------|----------|----------|
| tiny   | 39M   | Fast  | Lower    | Quick tests, low-resource systems |
| base   | 74M   | Good  | Good     | **Recommended default** |
| small  | 244M  | Slow  | Better   | Better accuracy needed |
| medium | 769M  | Slower| High     | High-quality transcriptions |
| large  | 1550M | Slowest| Highest | Maximum accuracy, powerful hardware |

## Performance Notes

- First run will download the Whisper model (cached for subsequent runs)
- Processing time depends on:
  - Media file duration
  - Whisper model size
  - Available CPU/GPU resources
- Typical processing time: 1-5x real-time (1 hour video = 1-5 hours processing)
- GPU support can significantly speed up processing

## Troubleshooting

### Out of memory errors
- Use a smaller Whisper model (`--model tiny` or `--model base`)
- Process fewer files at once

### FFmpeg errors
- Ensure the media file is not corrupted
- Check that the file format is supported

### Whisper download fails
- Check internet connection
- Ensure sufficient disk space in Docker volume

## Future Enhancements

- Database storage for easier querying
- Web interface for searching transcriptions
- Speaker diarization (identify who is speaking)
- Word-level timestamps for more precision
- GPU acceleration support
