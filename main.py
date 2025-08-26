from flask import Flask, request, jsonify, send_file
import yt_dlp
import os
import subprocess
from datetime import datetime
import tempfile
import shutil

app = Flask(__name__)

# Configuration pour Railway
if not os.path.exists('/tmp'):
    os.makedirs('/tmp')

@app.route('/')
def home():
    return jsonify({
        'status': 'YouTube TikTok Automation API',
        'version': '1.0',
        'endpoints': ['/download', '/cut', '/health']
    })

@app.route('/health')
def health():
    return jsonify({
        'status': 'OK', 
        'timestamp': datetime.now().isoformat(),
        'disk_space': shutil.disk_usage('/tmp').free // (1024**3)  # GB libre
    })

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'error': 'URL YouTube manquante'}), 400
            
        youtube_url = data['url']
        
        # Nettoyer le dossier temp
        for file in os.listdir('/tmp'):
            if file.endswith('.mp4'):
                try:
                    os.remove(f'/tmp/{file}')
                except:
                    pass
        
        # Configuration yt-dlp optimisée pour TikTok
        ydl_opts = {
            'format': 'mp4[height<=720][filesize<50M]',  # Max 50MB
            'outtmpl': '/tmp/%(id)s.%(ext)s',
            'no_warnings': True,
            'extractaudio': False,
            'audioformat': 'mp3',
            'embed_subs': False,
            'writesubtitles': False
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Récupérer les infos sans télécharger
            info = ydl.extract_info(youtube_url, download=False)
            
            # Vérifications
            duration = info.get('duration', 0)
            if duration > 600:  # 10 minutes max
                return jsonify({'error': 'Vidéo trop longue (max 10min)'}), 400
                
            if duration < 5:  # 5 secondes min
                return jsonify({'error': 'Vidéo trop courte (min 5s)'}), 400
            
            title = info.get('title', 'Video')[:50]  # Titre court
            video_id = info.get('id')
            
            # Télécharger
            ydl.download([youtube_url])
            
            filename = f'/tmp/{video_id}.mp4'
            
            if not os.path.exists(filename):
                return jsonify({'error': 'Échec du téléchargement'}), 500
            
            file_size = os.path.getsize(filename) // (1024*1024)  # MB
            
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
        segment_duration = data.get('duration', 60)  # 60s par défaut
        max_segments = data.get('max_segments', 5)    # 5 segments max
        
        input_file = f'/tmp/{video_id}.mp4'
        
        if not os.path.exists(input_file):
            return jsonify({'error': 'Fichier vidéo introuvable'}), 404
        
        # Vérifier ffmpeg
        try:
            subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        except:
            return jsonify({'error': 'FFmpeg non disponible'}), 500
        
        segments = []
        
        # Découper avec ffmpeg
        for i in range(max_segments):
            start_time = i * segment_duration
            output_file = f'/tmp/{video_id}_segment_{i:02d}.mp4'
            
            cmd = [
                'ffmpeg', '-i', input_file,
                '-ss', str(start_time),
                '-t', str(segment_duration),
                '-c', 'copy',
                '-avoid_negative_ts', 'make_zero',
                output_file, '-y'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(output_file):
                file_size = os.path.getsize(output_file)
                if file_size > 1024:  # Plus de 1KB = segment valide
                    segments.append({
                        'index': i,
                        'start_time': start_time,
                        'duration': segment_duration,
                        'file_size_mb': file_size // (1024*1024),
                        'file_path': output_file,
                        'download_url': f"{request.url_root}file/{video_id}_segment_{i:02d}.mp4"
                    })
            else:
                break  # Plus de segments possibles
        
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
        else:
            return jsonify({'error': 'Fichier non trouvé'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Nettoyer les fichiers temporaires"""
    try:
        cleaned = 0
        for file in os.listdir('/tmp'):
            if file.endswith('.mp4'):
                try:
                    os.remove(f'/tmp/{file}')
                    cleaned += 1
                except:
                    pass
        
        return jsonify({
            'success': True,
            'files_cleaned': cleaned,
            'disk_free_gb': shutil.disk_usage('/tmp').free // (1024**3)
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
