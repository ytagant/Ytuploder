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

# 1. Google Drive Connection Setup
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
    try:
        drive_service.files().delete(fileId=file_id).execute()
        print(f"🗑️ File ID {file_id} successfully deleted from Drive.")
    except Exception as e:
        print(f"⚠️ Could not delete file from Drive: {e}")

def edit_anti_copyright_full_video(input_video, output_video):
    print("🎬 FULL VIDEO PROCESSING: ایڈوانسڈ فلٹرز (مائیکرو کراپ، شارپننگ، کلرز، اور سوفٹ فلیش) کے ساتھ ایڈیٹنگ جاری ہے...")
    
    video_filter = (
        "crop=iw-2:ih-2:1:1,scale=iw:ih,"
        "eq=brightness=0.01:contrast=1.04:saturation=1.08,"
        "unsharp=5:5:0.8:3:3:0.4,"
        "noise=alls=5:allf=t+u,"
        "drawbox=enable='lt(mod(t,12),0.02)':x=0:y=0:w=iw:h=ih:color=black@0.12:t=fill"
    )

    cmd = [
        'ffmpeg', '-y',
        '-i', input_video,
        '-vf', video_filter,
        '-af', "loudnorm=I=-16:TP=-1.5:LRA=11",
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '21',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '192k',
        output_video
    ]
    subprocess.run(cmd, check=True)
    print("✨ Advanced Anti-Copyright & Lip-Sync Safe Video Editing Complete!")

def get_file_id_by_name(filename):
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    if files:
        return files[0]['id']
    return None

def get_youtube_service():
    print("🔑 Google Drive سے client_secret.json اور token.json ڈاؤن لوڈ ہو رہے ہیں...")
    
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

    # گوگل ڈرائیو سے processed_history.json ڈاؤن لوڈ کریں تاکہ پتہ ہو کون سی ویڈیوز ہو چکی ہیں
    history = []
    history_file_id = get_file_id_by_name('processed_history.json')
    if history_file_id:
        download_from_drive(history_file_id, 'processed_history.json')
        try:
            with open('processed_history.json', 'r') as f:
                history = json.load(f)
        except:
            history = []

    # اسمارٹ لوپ: جو ویڈیو پہلے ہسٹری میں آ چکی ہے، اسے فوراً اسکিপ کر کے اگلی نئی ویڈیو پر چلا جائے گا
    item = None
    while queue:
        potential_item = queue[0]
        filename = potential_item['filename']
        
        if filename in history:
            print(f"⚠️ Video '{filename}' پہلے ہی ہسٹری میں موجود ہے، اسے اسکিপ کیا جا رہا ہے۔")
            queue.pop(0)  # پرانی ویڈیو کو لسٹ سے آگے بڑھا دیں
        else:
            # چیک کریں کہ آیا یہ نئی ویڈیو گوگل ڈرائیو پر موجود بھی ہے یا نہیں
            video_id = get_file_id_by_name(filename)
            if not video_id:
                print(f"⚠️ Video '{filename}' گوگل ڈرائیو پر نہیں ملی، اسے ہسٹری میں ڈال کر اسکিপ کیا جا رہا ہے۔")
                history.append(filename)
                queue.pop(0)
            else:
                item = queue.pop(0)
                break

    # کیو (queue.json) کو اپ ڈیٹ کر کے ڈرائیو پر سیو کریں
    with open('queue.json', 'w') as f:
        json.dump(queue, f, indent=4)
    drive_service.files().update(fileId=queue_file_id, media_body=MediaFileUpload('queue.json')).execute()

    if not item:
        print("ℹ️ پروسیس کرنے کے لیے کوئی نئی ویڈیو نہیں ملی۔")
        return

    print(f"🚀 Processing New Video: {item['title']}")
    video_id = get_file_id_by_name(item['filename'])

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

    # گوگل ڈرائیو سے اصل ویڈیو ڈیلیٹ کریں
    delete_from_drive(video_id)

    # کامیابی کے بعد ویڈیو کا نام ہسٹری (processed_history.json) میں پکا محفوظ کر دیں
    if item['filename'] not in history:
        history.append(item['filename'])

    with open('processed_history.json', 'w') as f:
        json.dump(history, f, indent=4)

    media_history = MediaFileUpload('processed_history.json')
    if history_file_id:
        drive_service.files().update(fileId=history_file_id, media_body=media_history).execute()
    else:
        file_metadata = {'name': 'processed_history.json', 'parents': [DRIVE_FOLDER_ID]}
        drive_service.files().create(body=file_metadata, media_body=media_history, fields='id').execute()

    print("✅ ہسٹری اور کیو کامیابی سے اپ ڈیٹ ہو گئیں، اگલી بار اسکرپٹ نئی ویڈیو اٹھائے گا!")

if __name__ == '__main__':
    main()
    
