import os
import json
import subprocess
import re
import unicodedata
from ftplib import FTP
from beatman.const import TEMP_DIR
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TDRC, TRCK, APIC

from beatman.logger import logger


def sanitize_filename(filename):
    """Remove or replace characters that are invalid in filenames"""
    # Replace invalid characters with underscore
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    return filename


def normalize_path_advanced_renamer(path):
    """
    Normalize path according to Advanced Renamer logic.
    Handles invalid characters, unicode normalization, and special character replacements.
    """
    # Normalize unicode characters (decompose and remove combining marks)
    path = unicodedata.normalize('NFKD', path)
    path = path.encode('ASCII', 'ignore').decode('ASCII')

    # Replace common problematic characters following Advanced Renamer patterns
    replacements = {
        ':': ' -',
        '/': '_',
        '\\': '-',
        '|': '-',
        '"': "'",
        '<': '(',
        '>': ')',
        '*': '',
        '?': '',
        '\t': ' ',
        '\n': ' ',
        '\r': ' ',
    }

    for old_char, new_char in replacements.items():
        path = path.replace(old_char, new_char)

    # Collapse multiple spaces into one
    path = re.sub(r'\s+', ' ', path)

    # Remove leading/trailing spaces and dots from each path component
    parts = path.split('/')
    parts = [part.strip('. ') for part in parts]
    path = '/'.join(parts)

    return path


def get_ftp_config():
    """Get FTP configuration from environment variable"""
    ftp_config_str = os.getenv('FTP_CONFIGURATION')
    logger.info(ftp_config_str)
    if not ftp_config_str:
        raise ValueError("FTP_CONFIGURATION not set in environment variables")

    try:
        return json.loads(ftp_config_str)
    except json.JSONDecodeError:
        raise ValueError("FTP_CONFIGURATION is not valid JSON")


def get_ftp_connection():
    """Create and return an FTP connection"""
    config = get_ftp_config()

    ftp = FTP()
    ftp.connect(config['host'])
    ftp.login(config['username'], config['password'])

    # Navigate to base directory
    if config.get('base_directory'):
        ftp.cwd(config['base_directory'])

    return ftp


def list_ftp_directories():
    """List directories in the FTP base directory"""
    try:
        ftp = get_ftp_connection()

        # Get list of all items
        items = []
        ftp.dir(items.append)

        # Filter for directories only
        directories = []
        for item in items:
            # Parse directory listing (format: drwxr-xr-x ...)
            parts = item.split()
            if len(parts) >= 9 and parts[0].startswith('d'):
                # Directory name is the last part (may contain spaces)
                dir_name = ' '.join(parts[8:])
                directories.append(dir_name)

        ftp.quit()
        return directories
    except Exception as e:
        logger.error(f"Error listing FTP directories: {e}")
        raise


def load_json(filepath, default):
    """Load JSON file or return default if not exists"""
    if filepath.exists():
        with open(filepath, 'r') as f:
            return json.load(f)
    return default


def save_json(filepath, data):
    """Save data to JSON file"""
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)


def get_spotify_client():
    """Initialize Spotify client with credentials from env vars"""
    client_id = os.getenv('SPOTIFY_CLIENT_ID')
    client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

    if not client_id or not client_secret:
        raise ValueError("Spotify credentials not set in environment variables")

    auth_manager = SpotifyClientCredentials(
        client_id=client_id,
        client_secret=client_secret
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def get_track_info(sp, track_url):
    """Get track metadata from a single Spotify track URL"""
    # Extract track ID from URL (handles various formats)
    # https://open.spotify.com/track/{id}?...
    track_id = track_url.split('/')[-1].split('?')[0]

    try:
        track = sp.track(track_id)
        album = track['album']

        # Extract album art URL (prefer medium size ~300px)
        album_art_url = None
        if album.get('images'):
            if len(album['images']) > 1:
                album_art_url = album['images'][1]['url']
            elif len(album['images']) > 0:
                album_art_url = album['images'][0]['url']

        # Extract year from release_date
        year = ''
        if album.get('release_date'):
            year = album['release_date'].split('-')[0]

        return {
            'uri': track['uri'],
            'name': track['name'],
            'artist': ', '.join([a['name'] for a in track['artists']]),
            'album': album['name'],
            'album_art_url': album_art_url,
            'year': year,
            'track_number': str(track.get('track_number', ''))
        }
    except Exception as e:
        logger.error(f"Error fetching track info: {e}")
        return None


def write_track_metadata(file_path, track_info):
    """Write Spotify metadata to MP3 file"""
    try:
        audio = MP3(file_path, ID3=ID3)

        # Add ID3 tag if it doesn't exist
        if audio.tags is None:
            audio.add_tags()

        # Write basic metadata from Spotify
        audio.tags['TIT2'] = TIT2(encoding=3, text=track_info['name'])          # Title
        audio.tags['TPE1'] = TPE1(encoding=3, text=track_info['artist'])        # Contributing Artists
        audio.tags['TPE2'] = TPE2(encoding=3, text=track_info['artist'])        # Album Artist
        audio.tags['TALB'] = TALB(encoding=3, text=track_info['album'])         # Album

        # Write year if available
        if track_info.get('year'):
            audio.tags['TDRC'] = TDRC(encoding=3, text=track_info['year'])

        # Write track number if available
        if track_info.get('track_number'):
            audio.tags['TRCK'] = TRCK(encoding=3, text=track_info['track_number'])

        # Download and embed album art if URL is available
        if track_info.get('album_art_url'):
            try:
                import urllib.request
                with urllib.request.urlopen(track_info['album_art_url']) as response:
                    album_art_data = response.read()

                # Remove existing album art
                audio.tags.delall('APIC')

                # Add new album art
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,  # Cover (front)
                        desc='Cover',
                        data=album_art_data
                    )
                )
                logger.info(f"Downloaded and embedded album art for {file_path}")
            except Exception as e:
                logger.warning(f"Failed to download album art: {e}")

        audio.save()
        logger.info(f"Wrote Spotify metadata to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error writing metadata to {file_path}: {e}")
        return False


def download_track(track_info):
    """Download a track using yt-dlp"""
    try:
        # Construct search query from Spotify metadata
        search_query = f"ytsearch:{track_info['artist']} - {track_info['name']}"

        # Sanitize artist and track name for safe filenames
        safe_artist = sanitize_filename(track_info['artist'])
        safe_name = sanitize_filename(track_info['name'])

        # Construct output filename using Spotify metadata to ensure consistency
        output_template = str(TEMP_DIR / f"{safe_artist} - {safe_name}.%(ext)s")

        result = subprocess.run(
            [
                'yt-dlp',
                search_query,
                '--extract-audio',           # Extract audio only
                '--audio-format', 'mp3',     # Convert to MP3
                '--output', output_template, # Output path with filename
                '--no-playlist',             # Only download single video
                '--embed-metadata',          # Embed metadata from YouTube
                '--quiet',                   # Reduce output noise
                '--no-warnings'              # Suppress warnings
            ],
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode != 0:
            logger.error(f"yt-dlp failed for {track_info['artist']} - {track_info['name']}: {result.stderr}")
            logger.error(f"stdout: {result.stdout}")
            return False

        logger.info(f"Successfully downloaded {track_info['artist']} - {track_info['name']}")

        # Write Spotify metadata to the downloaded file
        downloaded_file = TEMP_DIR / f"{safe_artist} - {safe_name}.mp3"
        if downloaded_file.exists():
            write_track_metadata(downloaded_file, track_info)

        return True
    except Exception as e:
        logger.error(f"Error downloading {track_info['artist']} - {track_info['name']}: {e}")
        return False


def read_file_metadata(file_path):
    """Read metadata from MP3 file"""
    try:
        audio = MP3(file_path, ID3=ID3)
        if audio.tags is None:
            return {}, None

        metadata = {
            'title': str(audio.tags.get('TIT2', [''])[0]) if audio.tags.get('TIT2') else '',
            'contributing_artists': str(audio.tags.get('TPE1', [''])[0]) if audio.tags.get('TPE1') else '',
            'album_artist': str(audio.tags.get('TPE2', [''])[0]) if audio.tags.get('TPE2') else '',
            'album': str(audio.tags.get('TALB', [''])[0]) if audio.tags.get('TALB') else '',
            'year': str(audio.tags.get('TDRC', [''])[0]) if audio.tags.get('TDRC') else '',
            'track_number': str(audio.tags.get('TRCK', [''])[0]) if audio.tags.get('TRCK') else ''
        }

        # Extract album art
        album_art = None
        for tag in audio.tags.values():
            if isinstance(tag, APIC):
                import base64
                album_art = base64.b64encode(tag.data).decode('utf-8')
                break

        return metadata, album_art
    except Exception as e:
        logger.error(f"Error reading metadata from {file_path}: {e}")
        return {}, None
