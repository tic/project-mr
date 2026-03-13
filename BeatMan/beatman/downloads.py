import json
from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TPE2, TALB, TDRC, TRCK, APIC

from beatman.const import DOWNLOADS_FILE, TEMP_DIR, STORAGE_DIR
from beatman.logger import logger
from beatman.utils import (
    sanitize_filename,
    load_json,
    save_json,
    get_spotify_client,
    get_track_info,
    download_track,
    read_file_metadata,
    list_ftp_directories,
    normalize_path_advanced_renamer
)

downloads_bp = Blueprint('downloads', __name__)


@downloads_bp.route('/api/downloads/count', methods=['GET'])
def get_downloads_count():
    """Get count of unprocessed downloads"""
    downloads = load_json(DOWNLOADS_FILE, [])
    unprocessed = [d for d in downloads if not d.get('processed', False)]
    return jsonify({'count': len(unprocessed)})


@downloads_bp.route('/api/downloads/item', methods=['GET'])
def get_download_item():
    """Get a specific unprocessed download with file metadata"""
    index = int(request.args.get('index', 0))
    downloads = load_json(DOWNLOADS_FILE, [])
    unprocessed = [d for d in downloads if not d.get('processed', False)]

    if index < 0 or index >= len(unprocessed):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = unprocessed[index]

    # Find the MP3 file
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    # Read metadata from the file
    file_metadata, album_art = read_file_metadata(matching_file)

    # Find the actual index in the full downloads list
    actual_index = downloads.index(download)

    return jsonify({
        'success': True,
        'index': actual_index,
        'filename': matching_file.name,
        'downloaded_at': download['downloaded_at'],
        'metadata': file_metadata,
        'album_art': album_art
    })


@downloads_bp.route('/api/downloads/<int:index>/audio', methods=['GET'])
def serve_audio(index):
    """Serve audio file for playback"""
    downloads = load_json(DOWNLOADS_FILE, [])

    if index < 0 or index >= len(downloads):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = downloads[index]

    # Find the MP3 file using existing pattern
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    return send_file(
        matching_file,
        mimetype='audio/mpeg',
        as_attachment=False,
        download_name=matching_file.name
    )


@downloads_bp.route('/api/downloads/<int:index>/metadata', methods=['POST'])
def update_metadata(index):
    """Update metadata directly in the MP3 file"""
    data = request.json
    downloads = load_json(DOWNLOADS_FILE, [])

    if index < 0 or index >= len(downloads):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = downloads[index]
    if download.get('processed', False):
        return jsonify({'success': False, 'error': 'Already processed'}), 400

    # Find the MP3 file
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    # Write metadata to the MP3 file
    try:
        audio = MP3(matching_file, ID3=ID3)

        # Add ID3 tag if it doesn't exist
        if audio.tags is None:
            audio.add_tags()

        # Write metadata tags with new schema
        if data.get('title'):
            audio.tags['TIT2'] = TIT2(encoding=3, text=data['title'])
        if data.get('contributing_artists'):
            audio.tags['TPE1'] = TPE1(encoding=3, text=data['contributing_artists'])
        if data.get('album_artist'):
            audio.tags['TPE2'] = TPE2(encoding=3, text=data['album_artist'])
        if data.get('album'):
            audio.tags['TALB'] = TALB(encoding=3, text=data['album'])
        if data.get('year'):
            audio.tags['TDRC'] = TDRC(encoding=3, text=data['year'])
        if data.get('track_number'):
            audio.tags['TRCK'] = TRCK(encoding=3, text=data['track_number'])

        audio.save()
        logger.info(f"Updated metadata for {matching_file}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")
        return jsonify({'success': False, 'error': f'Failed to update metadata: {str(e)}'}), 500


@downloads_bp.route('/api/downloads/<int:index>/album-art', methods=['POST'])
def update_album_art(index):
    """Update album art for a download"""
    downloads = load_json(DOWNLOADS_FILE, [])

    if index < 0 or index >= len(downloads):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = downloads[index]
    if download.get('processed', False):
        return jsonify({'success': False, 'error': 'Already processed'}), 400

    # Find the MP3 file
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    # Get uploaded file
    if 'album_art' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400

    file = request.files['album_art']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400

    # Write album art to MP3 file
    try:
        audio = MP3(matching_file, ID3=ID3)

        # Add ID3 tag if it doesn't exist
        if audio.tags is None:
            audio.add_tags()

        # Remove existing album art
        audio.tags.delall('APIC')

        # Add new album art
        audio.tags.add(
            APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,  # Cover (front)
                desc='Cover',
                data=file.read()
            )
        )

        audio.save()
        logger.info(f"Updated album art for {matching_file}")
        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error updating album art: {e}")
        return jsonify({'success': False, 'error': f'Failed to update album art: {str(e)}'}), 500


@downloads_bp.route('/api/ftp/directories', methods=['GET'])
def get_ftp_directories():
    """List directories in FTP base directory"""
    try:
        directories = list_ftp_directories()
        return jsonify({'success': True, 'directories': directories})
    except Exception as e:
        logger.error(f"Error in get_ftp_directories: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@downloads_bp.route('/api/downloads/<int:index>/generate-path', methods=['POST'])
def generate_path(index):
    """Generate default path for a download based on metadata"""
    downloads = load_json(DOWNLOADS_FILE, [])

    if index < 0 or index >= len(downloads):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = downloads[index]

    # Find the MP3 file
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    # Read metadata from file
    file_metadata, _ = read_file_metadata(matching_file)

    # Get selected folder from request
    data = request.json
    selected_folder = data.get('folder', '')

    # Generate path: {artist name}/{track number} - {track title}.mp3
    artist = file_metadata.get('album_artist') or file_metadata.get('contributing_artists') or 'Unknown Artist'
    track_number = file_metadata.get('track_number', '')
    title = file_metadata.get('title', 'Unknown Title')

    artist = normalize_path_advanced_renamer(artist)
    title = normalize_path_advanced_renamer(title)

    # Format the filename
    if track_number:
        filename = f"{track_number} - {title}.mp3"
    else:
        filename = f"{title}.mp3"

    # Construct full path
    path = f"{artist}/{filename}"

    # Add selected folder prefix if provided
    if selected_folder:
        path = f"{selected_folder}/{path}"

    return jsonify({'success': True, 'path': path})


@downloads_bp.route('/api/downloads/<int:index>/process', methods=['POST'])
def process_download(index):
    """Process a download - upload to FTP with custom path"""
    downloads = load_json(DOWNLOADS_FILE, [])
    data = request.json

    if index < 0 or index >= len(downloads):
        return jsonify({'success': False, 'error': 'Invalid index'}), 400

    download = downloads[index]
    if download.get('processed', False):
        return jsonify({'success': False, 'error': 'Already processed'}), 400

    # Get parameters from request
    selected_folder = data.get('folder', '')
    custom_path = data.get('path', '')

    if not custom_path:
        return jsonify({'success': False, 'error': 'Path is required'}), 400

    # Find the downloaded file using sanitized names
    safe_artist = sanitize_filename(download['artist'])
    safe_name = sanitize_filename(download['name'])
    search_pattern = f"{safe_artist} - {safe_name}"
    downloaded_files = list(TEMP_DIR.glob("*.mp3"))

    matching_file = None
    for f in downloaded_files:
        if search_pattern.lower() in f.name.lower():
            matching_file = f
            break

    if not matching_file:
        return jsonify({'success': False, 'error': 'File not found'}), 404

    # Read metadata for logging
    file_metadata, _ = read_file_metadata(matching_file)

    # TODO: Implement FTP upload
    # For now, log the request details
    logger.info("=== PROCESS TRACK REQUEST ===")
    logger.info(f"Track Index: {index}")
    logger.info(f"Local File: {matching_file}")
    logger.info(f"Selected Folder: {selected_folder}")
    logger.info(f"Destination Path: {custom_path}")
    logger.info(f"Metadata: {json.dumps(file_metadata, indent=2)}")
    logger.info("=============================")

    # Move to local storage for now (simulating successful processing)
    dest_file = STORAGE_DIR / matching_file.name
    matching_file.rename(dest_file)

    # Mark as processed
    downloads[index]['processed'] = True
    downloads[index]['processed_at'] = datetime.now().isoformat()
    downloads[index]['ftp_folder'] = selected_folder
    downloads[index]['ftp_path'] = custom_path
    downloads[index]['local_storage_path'] = str(dest_file)

    save_json(DOWNLOADS_FILE, downloads)

    return jsonify({'success': True})


@downloads_bp.route('/api/download-track', methods=['POST'])
def download_track_endpoint():
    """Download a single track from Spotify URL"""
    data = request.json
    track_url = data.get('url', '').strip()

    if not track_url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400

    try:
        # Get Spotify client
        sp = get_spotify_client()

        # Extract track metadata from Spotify
        track_info = get_track_info(sp, track_url)

        if not track_info:
            return jsonify({'success': False, 'error': 'Failed to fetch track info from Spotify'}), 400

        logger.info(f"Downloading: {track_info['artist']} - {track_info['name']}")

        # Download the track
        if download_track(track_info):
            # Add to downloads list
            downloads = load_json(DOWNLOADS_FILE, [])
            downloads.append({
                'uri': track_info['uri'],
                'name': track_info['name'],
                'artist': track_info['artist'],
                'album': track_info['album'],
                'downloaded_at': f'{datetime.now().isoformat()}Z',
                'processed': False
            })
            save_json(DOWNLOADS_FILE, downloads)

            return jsonify({
                'success': True,
                'track': f"{track_info['artist']} - {track_info['name']}"
            })
        else:
            return jsonify({'success': False, 'error': 'Download failed'}), 500

    except Exception as e:
        logger.error(f"Error in download_track_endpoint: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
