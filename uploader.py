import os
import json
import subprocess
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

# --- Configuration ---
DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
YOUTUBE_CLIENT_SECRET_JSON = os.environ.get('YOUTUBE_CLIENT_SECRET_JSON')
YOUTUBE_TOKEN_JSON = os.environ.get('YOUTUBE_TOKEN_JSON')

# 1. Google Drive Connection
with open('service_account.json', 'w') as f:
    f.write(SERVICE_ACCOUNT_JSON)

creds_drive = service_account.Credentials.from_service_account_file(
    'service_account.json', scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds_drive)

# 2. YouTube API Connection
with open('client_secret.json', 'w') as f:
    f.write(YOUTUBE_CLIENT_SECRET_JSON)

with open('token.json', 'w') as f:
    f.write(YOUTUBE_TOKEN_JSON)

creds_yt = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/youtube.upload'])
youtube = build('youtube', 'v3', credentials=creds_yt)

def download_from_drive(file_id, output_path):
    request = drive_service.files().get_media(fileId=file_id)
    with open(output_path, 'wb') as f:
        f.write(request.execute())

def delete_from_drive(file_id):
    drive_service.files().delete(fileId=file_id).execute()

def edit_anti_copyright(input_video, output_video):
    print("🎬 FFmpeg سے Anti-Copyright Filters اپلائی ہو رہے ہیں...")
    cmd = [
        'ffmpeg', '-y', '-i', input_video,
        '-vf', "hflip,eq=brightness=0.02:contrast=1.05:saturation=1.1,setpts=PTS/1.03",
        '-af', "atempo=1.03,asetrate=44100*1.02,aresample=44100",
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        output_video
    ]
    subprocess.run(cmd, check=True)
    print("✨ Video Editing مکمل ہو گئی!")

def main():
    query = f"name = 'queue.json' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])

    if not files:
        print("ℹ️ Google Drive میں queue.json نہیں ملی۔")
        return

    queue_file_id = files[0]['id']
    download_from_drive(queue_file_id, 'queue.json')

    with open('queue.json', 'r') as f:
        queue = json.load(f)

    if not queue:
        print("ℹ️ Queue خالی ہے، کوئی ویڈیو باقی نہیں۔")
        return

    item = queue.pop(0)
    print(f"🚀 پروسیسنگ شروع: {item['title']}")

    v_query = f"name = '{item['filename']}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    v_results = drive_service.files().list(q=v_query, fields="files(id)").execute()
    v_files = v_results.get('files', [])

    if not v_files:
        print(f"❌ Video file {item['filename']} Drive پر نہیں ملی۔")
        return

    video_id = v_files[0]['id']
    raw_video_path = "raw_video.mp4"
    edited_video_path = "edited_video.mp4"

    download_from_drive(video_id, raw_video_path)
    edit_anti_copyright(raw_video_path, edited_video_path)

    body = {
        'snippet': {
            'title': item['title'],
            'description': item['description'],
            'tags': item.get('tags', []),
            'categoryId': '24'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
        }
    }

    media = MediaFileUpload(edited_video_path, chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    response = request.execute()

    print(f"🎉 یوٹیوب پر ویڈیو کامیابی سے اپ لوڈ ہو گئی! Video ID: {response['id']}")

    delete_from_drive(video_id)

    with open('queue.json', 'w') as f:
        json.dump(queue, f, indent=4)

    media_queue = MediaFileUpload('queue.json')
    drive_service.files().update(fileId=queue_file_id, media_body=media_queue).execute()
    print("✅ Drive صاف ہو گئی اور queue اپ ڈیٹ ہو گئی۔")

if __name__ == '__main__':
    main()

