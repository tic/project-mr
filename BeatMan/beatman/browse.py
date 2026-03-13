from flask import Blueprint, jsonify, request
from beatman.logger import logger
from beatman.utils import get_ftp_connection

browse_bp = Blueprint('browse', __name__)


def list_ftp_subdirectories(ftp, path):
    """List subdirectories at a given FTP path"""
    try:
        ftp.cwd(path)
        items = []
        ftp.dir(items.append)

        directories = []
        for item in items:
            parts = item.split()
            if len(parts) >= 9 and parts[0].startswith('d'):
                dir_name = ' '.join(parts[8:])
                directories.append(dir_name)

        return directories
    except Exception as e:
        logger.error(f"Error listing subdirectories at {path}: {e}")
        raise


def list_ftp_files(ftp, path):
    """List audio files at a given FTP path with metadata"""
    try:
        ftp.cwd(path)
        items = []
        ftp.dir(items.append)

        audio_extensions = ['.mp3', '.flac', '.wav', '.m4a']
        files = []

        for item in items:
            parts = item.split()
            if len(parts) >= 9 and not parts[0].startswith('d'):
                filename = ' '.join(parts[8:])

                if any(filename.lower().endswith(ext) for ext in audio_extensions):
                    # Parse track pattern: "{number} - {title}.ext"
                    track_number = ""
                    title = filename

                    if ' - ' in filename:
                        split_parts = filename.split(' - ', 1)
                        track_number = split_parts[0].strip()
                        title = split_parts[1].rsplit('.', 1)[0]
                    else:
                        title = filename.rsplit('.', 1)[0]

                    # Get file size (5th column)
                    size = int(parts[4]) if len(parts) >= 5 and parts[4].isdigit() else 0

                    files.append({
                        'filename': filename,
                        'track_number': track_number,
                        'title': title,
                        'size': size
                    })

        return files
    except Exception as e:
        logger.error(f"Error listing files at {path}: {e}")
        raise


@browse_bp.route('/api/browse/artists', methods=['GET'])
def get_artists():
    """List all artists in a library"""
    library = request.args.get('library', '')

    if not library:
        return jsonify({'success': False, 'error': 'Library parameter required'}), 400

    try:
        ftp = get_ftp_connection()
        artists = list_ftp_subdirectories(ftp, library)
        ftp.quit()

        return jsonify({'success': True, 'artists': artists})
    except Exception as e:
        logger.error(f"Error in get_artists: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@browse_bp.route('/api/browse/albums', methods=['GET'])
def get_albums():
    """List all albums for an artist"""
    library = request.args.get('library', '')
    artist = request.args.get('artist', '')

    if not library or not artist:
        return jsonify({'success': False, 'error': 'Library and artist parameters required'}), 400

    try:
        ftp = get_ftp_connection()
        path = f"{library}/{artist}"
        albums = list_ftp_subdirectories(ftp, path)
        ftp.quit()

        return jsonify({'success': True, 'albums': albums})
    except Exception as e:
        logger.error(f"Error in get_albums: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@browse_bp.route('/api/browse/tracks', methods=['GET'])
def get_tracks():
    """List all tracks in an album"""
    library = request.args.get('library', '')
    artist = request.args.get('artist', '')
    album = request.args.get('album', '')

    if not library or not artist or not album:
        return jsonify({
            'success': False,
            'error': 'Library, artist, and album parameters required'
        }), 400

    try:
        ftp = get_ftp_connection()
        path = f"{library}/{artist}/{album}"
        tracks = list_ftp_files(ftp, path)
        ftp.quit()

        return jsonify({'success': True, 'tracks': tracks})
    except Exception as e:
        logger.error(f"Error in get_tracks: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
