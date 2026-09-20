import os
import json
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

def process_video_with_pro_editing(input_file, output_file):
    """
    FFmpeg Professional Editing Filter:
    1. Invisible Black Cut (0.1s Fade-In / Fade-Out transition)
    2. Horizontal Flip (hflip for copyright safety)
    3. Light Color Grading (Brightness, Contrast, Saturation)
    4. Audio Loudness Normalization (-14 LUFS)
    """
    print(f"🎬 Starting Professional Video Processing on: {input_file}")
    
    # Get video duration using ffprobe
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

def delete_from_drive(drive_service, file_id):
    """Safe deletion from Google Drive with error handling"""
    try:
        drive_service.files().delete(fileId=file_id).execute()
        print(f"🗑️ Drive file {file_id} deleted successfully.")
    except Exception as e:
        print(f"⚠️ Warning: Could not delete file {file_id} from Drive: {e}")

def get_youtube_service():
    if not os.path.exists('token.json'):
        raise FileNotFoundError("token.json file missing!")
    
    with open('token.json', 'r') as f:
        token_data = json.load(f)
    
    creds = Credentials.from_authorized_user_info(token_data)
    return build('youtube', 'v3', credentials=creds)

def main():
    raw_video = "raw_video.mp4"
    processed_video = "processed_full_video.mp4"

    # Step 1: Process and Edit Video
    if os.path.exists(raw_video):
        process_video_with_pro_editing(raw_video, processed_video)
    elif not os.path.exists(processed_video):
        print(f"❌ Error: Neither {raw_video} nor {processed_video} found.")
        return

    # Step 2: YouTube API Authentication
    youtube = get_youtube_service()
    print("✅ YouTube API Successfully Connected!")

    # Step 3: Metadata and Upload
    body = {
        'snippet': {
            'title': 'Manhwa Recap Video',
            'description': 'Automated Manhwa/Anime recap video upload.',
            'tags': ['anime', 'manhwa', 'recap'],
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

    print(f"🎉 Video Uploaded Successfully! Video ID: {response['id']}")

if __name__ == '__main__':
    main()
    
