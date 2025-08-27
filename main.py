from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import subprocess
from datetime import datetime
import tempfile
import shutil

app = Flask(__name__)

# --- Configuration Cookies (Netscape format généré dynamiquement) ---
COOKIES = [
    {"name": "LOGIN_INFO", "value": "AFmmF2swRAIgDzl...", "domain": ".youtube.com", "path": "/", "secure": True, "httponly": True},
    {"name": "PREF", "value": "tz=Europe.Paris&f6=40000000", "domain": ".youtube.com", "path": "/", "secure": True, "httponly": False},
    # Ajoute ici tous les cookies nécessaires
]

def create_cookies_file():
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    for cookie in COOKIES:
        line = f"{cookie['domain']}\tTRUE\t{cookie['path']}\t{'TRUE' if cookie.get('secure', False) else 'FALSE'}\t0\t{cookie['name']}\t{cookie['value']}\n"
        tmp_file.write(line.encode('utf-8'))
    tmp_file.close()
    return tmp_file.name

# --- Vérifier /tmp pour Railway ---
if not os.path.exists('/tmp'):
    os.makedirs('/tmp')

# --- Endpoints ---
@app.route('/')
def home():
    return jsonify({
        'status': 'YouTube TikTok Automation API',
        'version': '1.0',
        'endpoints': ['/download', '/cut', '/file/<filename>', '/cleanup']
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'OK', 
        'timestamp': datetime.now().isoformat(),
        'disk_space': shutil.disk_usage('/tmp').free // (1024**3)
    })

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL YouTube manquante'}), 400
        youtube_url = data['url'].strip()

        # Nettoyer /tmp
        for file in os.listdir('/tmp'):
            if file.endswith('.mp4'):
                try: os.remove(f'/tmp/{file}')
                except: pass

        cookies_file = create_cookies_file()

        ydl_opts = {
            'format': 'mp4[height<=720][filesize<50M]',
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'no_warnings': True,
            'extractaudio': False,
            'writesubtitles': False,
            'noplaylist': True,
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'cookiefile': cookies_file
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

            duration = info.get('duration', 0)
            if duration > 600: return jsonify({'error': 'Vidéo trop longue (max 10min)'}), 400
            if duration < 5: return jsonify({'error': 'Vidéo trop courte (min 5s)'}), 400

            title = info.get('title', 'Video')[:50]
            video_id = info.get('id')

            ydl.download([youtube_url])
            filename = f'/tmp/{video_id}.mp4'

        os.remove(cookies_file)

        if not os.path.exists(filename):
            return jsonify({'error': 'Échec du téléchargement'}), 500

        file_size = os.path.getsize(filename) // (1024*1024)

        return jsonify({
            'success': True,
            'title': title,
            'duration': duration,
            'video_id': video_id,
            'file_size_mb': file_size,
            'file_path': filename,
            'download_url': f"{request.url_root}file/{video_id}.mp4"
        })

    except Exception as e:
        return jsonify({'error': f'Erreur de téléchargement: {str(e)}'}), 500

@app.route('/cut', methods=['POST'])
def cut_video():
    try:
        data = request.get_json()
        if not data or 'video_id' not in data:
            return jsonify({'error': 'video_id manquant'}), 400

        video_id = data['video_id']
        segment_duration = data.get('duration', 60)
        max_segments = data.get('max_segments', 5)
        input_file = f'/tmp/{video_id}.mp4'

        if not os.path.exists(input_file):
            return jsonify({'error': 'Fichier vidéo introuvable'}), 404

        # Vérifier ffmpeg
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            return jsonify({'error': 'FFmpeg non disponible'}), 500

        segments = []
        for i in range(max_segments):
            start_time = i * segment_duration
            output_file = f'/tmp/{video_id}_segment_{i:02d}.mp4'
            cmd = ['ffmpeg', '-i', input_file, '-ss', str(start_time), '-t', str(segment_duration),
                   '-c', 'copy', '-avoid_negative_ts', 'make_zero', output_file, '-y']
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0 and os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                if file_size > 1024:
                    segments.append({
                        'index': i,
                        'start_time': start_time,
                        'duration': segment_duration,
                        'file_size_mb': file_size // (1024*1024),
                        'file_path': output_file,
                        'download_url': f"{request.url_root}file/{video_id}_segment_{i:02d}.mp4"
                    })
            else:
                break

        if not segments:
            return jsonify({'error': 'Aucun segment créé'}), 500

        return jsonify({
            'success': True,
            'original_file': video_id,
            'segments_count': len(segments),
            'segments': segments
        })

    except Exception as e:
        return jsonify({'error': f'Erreur de découpage: {str(e)}'}), 500

@app.route('/file/<filename>')
def serve_file(filename):
    try:
        file_path = f'/tmp/{filename}'
        if os.path.exists(file_path):
            return send_file(file_path, as_attachment=True)
        return jsonify({'error': 'Fichier non trouvé'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    try:
        cleaned = 0
        for file in os.listdir('/tmp'):
            if file.endswith('.mp4'):
                try:
                    os.remove(f'/tmp/{file}')
                    cleaned += 1
                except:
                    pass
        return jsonify({'success': True, 'files_cleaned': cleaned, 'disk_free_gb': shutil.disk_usage('/tmp').free // (1024**3)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
