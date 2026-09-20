cat << 'EOF' > uploader.py
import os
import json
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

def download_file_from_drive(drive_service, file_name, file_id):
    request = drive_service.files().get_media(fileId=file_id)
    with open(file_name, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

def safe_delete_from_drive(drive_service, file_id):
    try:
        drive_service.files().delete(fileId=file_id).execute()
        print(f"🗑️ Drive file {file_id} deleted successfully.")
    except Exception as e:
        print(f"⚠️ Drive deletion warning: {e}")

def process_video_with_pro_editing(input_file, output_file):
    print(f"🎬 Starting Professional Video Processing on: {input_file}")
    duration_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", input_file
    ]
    try:
        duration = float(subprocess.check_output(duration_cmd).decode('utf-8').strip())
        fade_out_start = max(0, duration - 0.1)
    except Exception as e:
        print(f"⚠️ Duration check fallback ({e}).")
        fade_out_start = 119.9

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-vf", (
            f"hflip,"
            f"eq=brightness=0.02:contrast=1.05:saturation=1.1,"
            f"fade=t=in:st=0:d=0.1,"
            f"fade=t=out:st={fade_out_start:.2f}:d=0.1"
        ),
        "-af", "volume=1.2,loudnorm=I=-14:LRA=11:TP=-1.5",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-c:a", "aac",
        output_file
    ]
    result = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"❌ FFmpeg Error: {result.stderr.decode('utf-8')}")
        raise RuntimeError("Video processing failed.")
    print("✨ Professional Video Editing Completed!")

def load_metadata_from_queue(queue_filename, video_base_name):
    title = "Manhwa Recap Video"
    description = "Automated Manhwa/Anime recap video upload."
    tags = ["anime", "manhwa", "recap"]

    if os.path.exists(queue_filename):
        try:
            with open(queue_filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                data = json.loads(content)
                if isinstance(data, list) and len(data) > 0:
                    item = data[0]
                    title = item.get('title', title)
                    description = item.get('description', description)
                    tags = item.get('tags', tags)
                elif isinstance(data, dict):
                    title = data.get('title', title)
                    description = data.get('description', description)
                    tags = data.get('tags', tags)
                print("📝 Successfully loaded Title, Description & Tags from queue.json!")
        except Exception as e:
            print(f"⚠️ queue.json parse warning: {e}")
    return title, description, tags

def main():
    if not os.path.exists('token.json'):
        print("❌ token.json missing locally!")
        return

    with open('token.json', 'r') as f:
        token_data = json.load(f)
    creds = Credentials.from_authorized_user_info(token_data)

    drive_service = build('drive', 'v3', credentials=creds)
    youtube_service = build('youtube', 'v3', credentials=creds)

    print("📥 Scanning Google Drive folder...")
    results = drive_service.files().list(
        pageSize=50, 
        fields="nextPageToken, files(id, name)"
    ).execute()
    items = results.get('files', [])

    raw_video_item = None
    thumbnail_item = None
    queue_item = None
    base_name = None

    for item in items:
        name = item['name']
        if name.endswith('.mp4') and not name.startswith('processed_'):
            raw_video_item = item
            base_name = os.path.splitext(name)[0].strip()
            break

    if not raw_video_item:
        print("❌ No video file (.mp4) found in Google Drive to process.")
        return

    print(f"📥 Downloading raw video: {raw_video_item['name']}...")
    download_file_from_drive(drive_service, raw_video_item['name'], raw_video_item['id'])

    for item in items:
        name = item['name']
        if name == 'queue.json':
            queue_item = item
        elif base_name and base_name in os.path.splitext(name)[0]:
            if name.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                thumbnail_item = item

    if thumbnail_item:
        print(f"🖼️ Downloading matching thumbnail: {thumbnail_item['name']}...")
        download_file_from_drive(drive_service, thumbnail_item['name'], thumbnail_item['id'])

    if queue_item:
        print("📝 Downloading queue.json...")
        download_file_from_drive(drive_service, 'queue.json', queue_item['id'])

    processed_video = f"processed_{raw_video_item['name']}"
    process_video_with_pro_editing(raw_video_item['name'], processed_video)

    title, description, tags = load_metadata_from_queue('queue.json', base_name)

    print("✅ YouTube API Connected Successfully!")
    body = {
        'snippet': {
            'title': title,
            'description': description,
            'tags': tags,
            'categoryId': '24'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
        }
    }

    media = MediaFileUpload(processed_video, chunksize=-1, resumable=True)
    request = youtube_service.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"🚀 Uploading progress: {int(status.progress() * 100)}%")

    video_id = response['id']
    print(f"🎉 Video Uploaded Successfully! Video ID: {video_id}")

    thumbnail_filename = thumbnail_item['name'] if thumbnail_item else None
    if thumbnail_filename and os.path.exists(thumbnail_filename):
        try:
            print(f"🖼️ Uploading Thumbnail: {thumbnail_filename}...")
            youtube_service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_filename)
            ).execute()
            print("✅ Custom Thumbnail Uploaded Successfully!")
        except Exception as e:
            print(f"⚠️ Custom Thumbnail Upload Warning: {e}")

    safe_delete_from_drive(drive_service, raw_video_item['id'])

if __name__ == '__main__':
    main()
EOF
                             
