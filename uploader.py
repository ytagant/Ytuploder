import os
import json
import subprocess
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')

# 1. Drive Connection Setup
with open('service_account.json', 'w') as f:
    f.write(SERVICE_ACCOUNT_JSON)

creds_drive = service_account.Credentials.from_service_account_file(
    'service_account.json', scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds_drive)

def download_from_drive(file_id, output_path):
    print(f"📥 Downloading file {output_path} from Drive...")
    try:
        request = drive_service.files().get_media(fileId=file_id)
        with open(output_path, 'wb') as f:
            f.write(request.execute())
    except Exception as e:
        print(f"⚠️ Standard download failed, trying export for {output_path}...")
        request = drive_service.files().export_media(fileId=file_id, mimeType='text/plain')
        with open(output_path, 'wb') as f:
            f.write(request.execute())
    print("✅ Download Complete!")

def delete_from_drive(file_id):
    drive_service.files().delete(fileId=file_id).execute()

def edit_anti_copyright_full_video(input_video, output_video):
    print("🎬 FULL VIDEO PROCESSING: پوری ویڈیو پر اینٹی کاپی رائٹ ایڈیٹنگ اور بلیک کٹ ٹرانزिशन لگایا جا رہا ہے...")
    
    # یہاں expr کی جگہ درست drawbox سینٹیکس استعمال کیا گیا ہے جو بلैक फ्लैश کٹ لگائے گا
    video_filter = (
        "hflip,"
        "eq=brightness=0.02:contrast=1.05:saturation=1.1,"
        "setpts=PTS/1.03,"
        "fade=t=in:st=0:d=0.1,"
        "drawbox=enable='lt(mod(t,10),0.01)':x=0:y=0:w=iw:h=ih:color=black:t=fill"
    )

    cmd = [
        'ffmpeg', '-y',
        '-i', input_video,
        '-vf', video_filter,
        '-af', "atempo=1.03,asetrate=44100*1.02,aresample=44100",
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-c:a', 'aac', '-b:a', '128k',
        output_video
    ]
    subprocess.run(cmd, check=True)
    print("✨ Full Video Anti-Copyright & Black Transition Editing Complete!")

def get_file_id_by_name(filename):
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def get_youtube_service():
    print("🔑 Google Drive سے client_secret.json اور token.json ڈاؤن لوڈ ہو رہے हैं...")
    
    cs_id = get_file_id_by_name('client_secret.json')
    tk_id = get_file_id_by_name('token.json')
    
    if not cs_id or not tk_id:
        raise Exception("❌ Google Drive میں client_secret.json یا token.json نہیں ملی!")

    download_from_drive(cs_id, 'client_secret.json')
    download_from_drive(tk_id, 'token.json')

    with open('client_secret.json', 'r') as f:
        client_secret_data = json.load(f)
    
    with open('token.json', 'r') as f:
        token_data = json.load(f)

    client_info = client_secret_data.get('web') or client_secret_data.get('installed')

    creds_yt = Credentials(
        token=token_data.get('token'),
        refresh_token=token_data.get('refresh_token'),
        token_uri=client_info['token_uri'],
        client_id=client_info['client_id'],
        client_secret=client_info['client_secret'],
        scopes=token_data.get('scopes')
    )
    creds_yt.refresh(Request())
    print("✅ YouTube API Successfully Connected!")
    return build('youtube', 'v3', credentials=creds_yt)

def upload_thumbnail(youtube, video_id, thumbnail_filename):
    t_id = get_file_id_by_name(thumbnail_filename)
    if t_id:
        download_from_drive(t_id, 'thumb.jpg')
        youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload('thumb.jpg')).execute()
        delete_from_drive(t_id)
        print("🖼️ Custom Thumbnail Uploaded Successfully!")

def main():
    queue_file_id = get_file_id_by_name('queue.json')

    if not queue_file_id:
        print("ℹ️ Google Drive میں queue.json نہیں ملی۔")
        return

    download_from_drive(queue_file_id, 'queue.json')

    with open('queue.json', 'r') as f:
        queue = json.load(f)

    if not queue:
        print("ℹ️ Queue خالی ہے۔")
        return

    item = queue.pop(0)
    print(f"🚀 Processing: {item['title']}")

    video_id = get_file_id_by_name(item['filename'])

    if not video_id:
        print(f"❌ Video file {item['filename']} Drive پر نہیں ملی۔")
        return

    download_from_drive(video_id, 'raw_video.mp4')
    edit_anti_copyright_full_video('raw_video.mp4', 'edited_video.mp4')

    youtube = get_youtube_service()

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

    media = MediaFileUpload('edited_video.mp4', chunksize=-1, resumable=True)
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
    response = request.execute()
    yt_video_id = response['id']

    print(f"🎉 Full Video YouTube پر کامیابی سے اپ لوڈ ہو گئی! Video ID: {yt_video_id}")

    if 'thumbnail' in item:
        upload_thumbnail(youtube, yt_video_id, item['thumbnail'])

    delete_from_drive(video_id)

    with open('queue.json', 'w') as f:
        json.dump(queue, f, indent=4)

    drive_service.files().update(fileId=queue_file_id, media_body=MediaFileUpload('queue.json')).execute()
    print("✅ Drive سے ویڈیو ڈیلیٹ اور queue.json اپ ڈیٹ ہو گئی۔")

if __name__ == '__main__':
    main()
    
