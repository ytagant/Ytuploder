import os
import json
import glob
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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
        print(f"⚠️ Warning: Could not detect video duration ({e}). Using fallback settings.")
        fade_out_start = 119.9

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", input_file,
        "-vf", (
            f"hflip,"
            f"eq=brightness=0.02:contrast=1.05:saturation=1.1,"
            f"fade=t=in:st=0:d=0.1,"
            f"fade=t=out:st={fade_out_start:.2f}:d=0.1"
        ),
        "-af", "volume=1.2,loudnorm=I=-14:LRA=11:TP=-1.5",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "22",
        "-c:a", "aac",
        output_file
    ]

    result = subprocess.run(ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        print(f"❌ FFmpeg Error: {result.stderr.decode('utf-8')}")
        raise RuntimeError("Video processing failed.")
    
    print("✨ Video Editing Completed Successfully!")

def get_youtube_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json file missing!")
    
    with open('token.json', 'r') as f:
        token_data = json.load(f)
    
    creds = Credentials.from_authorized_user_info(token_data)
    return build('youtube', 'v3', credentials=creds)

def find_thumbnail(base_name):
    """ویدیو کے سیم نام کی تھمب نیل فائل ڈھونڈنا"""
    for ext in ['.jpg', '.png', '.jpeg', '.webp']:
        thumb_path = base_name + ext
        if os.path.exists(thumb_path):
            return thumb_path
    # اگر خاص نام نہ ملے تو کوئی بھی جنرل تھمب نیل دیکھنا
    for fallback in ['thumbnail.jpg', 'thumbnail.png', 'cover.jpg']:
        if os.path.exists(fallback):
            return fallback
    return None

def load_metadata_from_file(base_name):
    """JS یا JSON فائل سے میٹا ڈیٹا لوڈ کرنا"""
    title = "Manhwa Recap Video"
    description = "Automated Manhwa/Anime recap video upload."
    tags = ["anime", "manhwa", "recap"]

    # 1. Check JS/JSON files matching base name or data.js / queue.json
    data_files = [f"{base_name}.json", f"{base_name}.js", "data.json", "data.js", "queue.json"]
    
    for df in data_files:
        if os.path.exists(df):
            try:
                with open(df, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    # If it's a JS file like `module.exports = {...}` or `const data = {...}`
                    if df.endswith('.js') and '{' in content:
                        content = content[content.find('{'):content.rfind('}')+1]
                    
                    data = json.loads(content)
                    title = data.get('title', title)
                    description = data.get('description', description)
                    tags = data.get('tags', tags)
                    print(f"📝 Loaded Title & Metadata from: {df}")
                    break
            except Exception as e:
                print(f"⚠️ Could not parse metadata file {df}: {e}")
                
    return title, description, tags

def main():
    # 1. ڈھونڈیں کہ کون سی ویڈیو فائل موجود ہے
    raw_video = None
    for f in os.listdir('.'):
        if f.endswith('.mp4') and not f.startswith('processed_'):
            raw_video = f
            break
            
    if not raw_video:
        if os.path.exists('processed_full_video.mp4'):
            processed_video = 'processed_full_video.mp4'
            base_name = 'video'
        else:
            print("❌ Error: No video file found for processing.")
            return
    else:
        base_name = os.path.splitext(raw_video)[0]
        processed_video = f"processed_{raw_video}"
        process_video_with_pro_editing(raw_video, processed_video)

    # 2. سیم نام والا تھمب نیل اور JS/JSON سے ڈیٹا حاصل کریں
    thumbnail_file = find_thumbnail(base_name)
    title, description, tags = load_metadata_from_file(base_name)

    print(f"📌 Video Title: {title}")
    print(f"🖼️ Thumbnail File: {thumbnail_file if thumbnail_file else 'Not found'}")

    # 3. یوٹیوب اپلوڈ
    youtube = get_youtube_service()
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
    
    request = youtube.videos().insert(
        part=','.join(body.keys()),
        body=body,
        media_body=media
    )
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"🚀 Uploading progress: {int(status.progress() * 100)}%")

    video_id = response['id']
    print(f"🎉 Video Uploaded Successfully! Video ID: {video_id}")

    # 4. سیم نام والا تھمب نیل اپلوڈ کریں
    if thumbnail_file and os.path.exists(thumbnail_file):
        try:
            print(f"🖼️ Uploading Matching Thumbnail: {thumbnail_file}...")
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_file)
            ).execute()
            print("✅ Custom Thumbnail Uploaded Successfully!")
        except Exception as e:
            print(f"⚠️ Warning: Could not upload thumbnail: {e}")
    else:
        print("ℹ️ No matching thumbnail image found, skipping thumbnail upload.")

if __name__ == '__main__':
    main()
    
