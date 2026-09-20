import os
import json
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

def get_drive_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json missing!")
    with open('token.json', 'r') as f:
        token_data = json.load(f)
    creds = Credentials.from_authorized_user_info(token_data)
    return build('drive', 'v3', credentials=creds)

def get_youtube_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json missing!")
    with open('token.json', 'r') as f:
        token_data = json.load(f)
    creds = Credentials.from_authorized_user_info(token_data)
    return build('youtube', 'v3', credentials=creds)

def download_files_from_drive(drive_service):
    """Google Drive سے ملتی جلتی فائلیں ڈاؤن لوڈ کرنا"""
    print("📥 Checking Google Drive for files...")
    results = drive_service.files().list(
        pageSize=20, 
        fields="nextPageToken, files(id, name)"
    ).execute()
    items = results.get('files', [])

    if not items:
        print("❌ No files found in Google Drive.")
        return None, None, None

    raw_video_file = None
    thumbnail_file = None
    metadata_file = None
    base_name = None

    # Find raw video first
    for item in items:
        name = item['name']
        if name.endswith('.mp4') and not name.startswith('processed_'):
            raw_video_file = item
            base_name = os.path.splitext(name)[0]
            break

    if not raw_video_file:
        print("❌ No .mp4 video file found in Google Drive.")
        return None, None, None

    # Download Video
    print(f"📥 Downloading raw video: {raw_video_file['name']}...")
    request = drive_service.files().get_media(fileId=raw_video_file['id'])
    with open(raw_video_file['name'], 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()

    # Look for matching thumbnail and metadata files
    for item in items:
        name = item['name']
        if base_name in name or name in ['queue.json', 'data.js', 'data.json']:
            if name.endswith(('.jpg', '.png', '.jpeg', '.webp')):
                thumbnail_file = item
            elif name.endswith(('.json', '.js')):
                metadata_file = item

    # Download Thumbnail if exists
    if thumbnail_file:
        print(f"🖼️ Downloading thumbnail: {thumbnail_file['name']}...")
        req = drive_service.files().get_media(fileId=thumbnail_file['id'])
        with open(thumbnail_file['name'], 'wb') as fh:
            MediaIoBaseDownload(fh, req).next_chunk()

    # Download Metadata file if exists
    if metadata_file:
        print(f"📝 Downloading metadata: {metadata_file['name']}...")
        req = drive_service.files().get_media(fileId=metadata_file['id'])
        with open(metadata_file['name'], 'wb') as fh:
            MediaIoBaseDownload(fh, req).next_chunk()

    return raw_video_file['name'], thumbnail_file['name'] if thumbnail_file else None, metadata_file['name'] if metadata_file else None

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
        print(f"⚠️ Could not detect duration ({e}). Defaulting to fallback.")
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
    print("✨ Video Editing Completed Successfully!")

def load_metadata(metadata_filename):
    title = "Manhwa Recap Video"
    description = "Automated Manhwa/Anime recap video upload."
    tags = ["anime", "manhwa", "recap"]

    if metadata_filename and os.path.exists(metadata_filename):
        try:
            with open(metadata_filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if metadata_filename.endswith('.js') and '{' in content:
                    content = content[content.find('{'):content.rfind('}')+1]
                data = json.loads(content)
                title = data.get('title', title)
                description = data.get('description', description)
                tags = data.get('tags', tags)
                print("📝 Loaded Title, Description & Tags!")
        except Exception as e:
            print(f"⚠️ Metadata read error: {e}")
    return title, description, tags

def main():
    drive_service = get_drive_service()
    raw_video, thumbnail_file, metadata_file = download_files_from_drive(drive_service)

    if not raw_video:
        print("❌ Error: No video downloaded from Drive. Aborting.")
        return

    processed_video = f"processed_{raw_video}"
    process_video_with_pro_editing(raw_video, processed_video)

    title, description, tags = load_metadata(metadata_file)
    youtube = get_youtube_service()
    print("✅ YouTube API Connected!")

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
    request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"🚀 Uploading progress: {int(status.progress() * 100)}%")

    video_id = response['id']
    print(f"🎉 Video Uploaded Successfully! Video ID: {video_id}")

    if thumbnail_file and os.path.exists(thumbnail_file):
        try:
            print(f"🖼️ Uploading Thumbnail: {thumbnail_file}...")
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_file)).execute()
            print("✅ Custom Thumbnail Uploaded!")
        except Exception as e:
            print(f"⚠️ Thumbnail Upload Warning: {e}")

if __name__ == '__main__':
    main()
    
