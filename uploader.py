import os
import json
import subprocess
import time
import re
import urllib.parse
import urllib.request
from PIL import Image, ImageEnhance  # थंबनेल को बेहतर बनाने के लिए
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')
WHATSAPP_NUMBER = os.environ.get('WHATSAPP_NUMBER')
WHATSAPP_API_KEY = os.environ.get('WHATSAPP_API_KEY')

with open('service_account.json', 'w') as f:
    f.write(SERVICE_ACCOUNT_JSON)

creds_drive = service_account.Credentials.from_service_account_file(
    'service_account.json', scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds_drive)

def send_whatsapp_message(message):
    if not WHATSAPP_NUMBER or not WHATSAPP_API_KEY:
        print("⚠️ WhatsApp API Key या Number सेट नहीं है। मेसेज नहीं भेजा गया।")
        return
    try:
        encoded_message = urllib.parse.quote(message)
        url = f"https://api.callmebot.com/whatsapp.php?phone={WHATSAPP_NUMBER}&text={encoded_message}&apikey={WHATSAPP_API_KEY}"
        urllib.request.urlopen(url)
        print("📱 WhatsApp पर नोटिफिकेशन भेज दिया गया है!")
    except Exception as e:
        print(f"⚠️ WhatsApp मेसेज भेजने में एरर: {e}")

def enhance_thumbnail(input_path, output_path):
    print("🎨 थंबनेल की क्वालिटी (Brightness/Contrast) बढ़ाई जा रही है...")
    try:
        img = Image.open(input_path)
        # ब्राइटनेस 15% बढ़ाना
        enhancer = ImageEnhance.Brightness(img)
        img = enhancer.enhance(1.15)
        # कंट्रास्ट 20% बढ़ाना
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(1.20)
        
        img.save(output_path, quality=95)
        print("✅ थंबनेल एन्हांसमेंट पूरा हुआ!")
    except Exception as e:
        print(f"⚠️ थंबनेल एडिट एरर: {e}")
        # अगर कोई एरर आए, तो असली वाली फाइल ही यूज़ करें
        os.rename(input_path, output_path)

def download_from_drive(file_id, output_path):
    print(f"📥 Downloading file {output_path} from Drive...")
    for attempt in range(4):
        try:
            request = drive_service.files().get_media(fileId=file_id)
            with open(output_path, 'wb') as f:
                f.write(request.execute())
            print("✅ Download Complete!")
            return
        except Exception as e:
            print(f"⚠️ डाउनलोड नेटवर्क एरर (कोशिश {attempt+1}/4): {e}")
            if attempt == 3: raise e
            time.sleep(10)

def delete_from_drive(file_id):
    for attempt in range(4):
        try:
            drive_service.files().update(fileId=file_id, body={'trashed': True}).execute()
            print(f"🗑️ File ID {file_id} Drive के ट्रैश में भेज दी गई है।")
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def edit_anti_copyright_full_video(input_video, output_video):
    print("🎬 FULL VIDEO PROCESSING: एडवांस्ड फिल्टर्स के साथ पूरी वीडियो की एडिटिंग जारी है...")
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
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '28',
        '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '128k',
        output_video
    ]
    subprocess.run(cmd, check=True)
    print("✨ Full Video Anti-Copyright Editing Complete!")

def get_file_id_by_name(filename):
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    for attempt in range(4):
        try:
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            return files[0]['id'] if files else None
        except Exception as e:
            if attempt == 3: return None
            time.sleep(10)

def get_youtube_service():
    cs_id = get_file_id_by_name('client_secret.json')
    tk_id = get_file_id_by_name('token.json')
    if not cs_id or not tk_id: raise Exception("❌ Tokens नहीं मिले!")
    download_from_drive(cs_id, 'client_secret.json')
    download_from_drive(tk_id, 'token.json')

    with open('client_secret.json', 'r') as f: client_secret_data = json.load(f)
    with open('token.json', 'r') as f: token_data = json.load(f)
    client_info = client_secret_data.get('web') or client_secret_data.get('installed')

    creds_yt = Credentials(
        token=token_data.get('token'), refresh_token=token_data.get('refresh_token'),
        token_uri=client_info['token_uri'], client_id=client_info['client_id'],
        client_secret=client_info['client_secret'], scopes=token_data.get('scopes')
    )
    
    for attempt in range(4):
        try:
            creds_yt.refresh(Request())
            return build('youtube', 'v3', credentials=creds_yt)
        except Exception as e:
            if attempt == 3: raise e
            time.sleep(10)

def upload_thumbnail(youtube, video_id, thumbnail_filename):
    t_id = get_file_id_by_name(thumbnail_filename)
    if not t_id: return
    download_from_drive(t_id, 'raw_thumb.jpg')
    
    # थंबनेल एन्हांसर कॉल करना
    enhance_thumbnail('raw_thumb.jpg', 'thumb.jpg')
    
    for attempt in range(4):
        try:
            media = MediaFileUpload('thumb.jpg', mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            print("✅ थंबनेल अपलोड हो गया!")
            delete_from_drive(t_id)
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def main():
    queue_file_id = get_file_id_by_name('queue.json')
    if not queue_file_id: return
    download_from_drive(queue_file_id, 'queue.json')

    with open('queue.json', 'r', encoding='utf-8') as f: queue = json.load(f)
    if not queue: return

    history = []
    history_file_id = get_file_id_by_name('processed_history.json')
    if history_file_id:
        download_from_drive(history_file_id, 'processed_history.json')
        try:
            with open('processed_history.json', 'r', encoding='utf-8') as f: history = json.load(f)
        except: pass

    item = None
    while queue:
        if queue[0]['filename'] in history: queue.pop(0)
        elif not get_file_id_by_name(queue[0]['filename']):
            history.append(queue[0]['filename'])
            queue.pop(0)
        else:
            item = queue.pop(0)
            break

    with open('queue.json', 'w', encoding='utf-8') as f: json.dump(queue, f, indent=4)
    for attempt in range(4):
        try:
            drive_service.files().update(fileId=queue_file_id, media_body=MediaFileUpload('queue.json')).execute()
            break
        except Exception:
            if attempt == 3: raise
            time.sleep(10)

    if not item: return

    print(f"🚀 Processing: {item['title']}")
    video_id = get_file_id_by_name(item['filename'])
    download_from_drive(video_id, 'raw_video.mp4')
    
    edit_anti_copyright_full_video('raw_video.mp4', 'edited_video.mp4')

    youtube = get_youtube_service()

    original_desc = item.get('description', '')
    clean_desc = re.sub(r'http[s]?://\S+|www\.\S+', '', original_desc)
    clean_desc = re.sub(r'\n\s*\n', '\n\n', clean_desc).strip()
    
    disclaimer_text = (
        "⚠️ Copyright Disclaimer:\n"
        "Under section 107 of the Copyright Act 1976, allowance is made for 'fair use' "
        "for purposes such as criticism, comment, news reporting, teaching, scholarship, and research."
    )
    
    if "disclaimer" not in clean_desc.lower() and "copyright" not in clean_desc.lower():
        clean_desc = f"{clean_desc}\n\n{disclaimer_text}"
        
    formatted_description = f"{clean_desc}\n\n{item.get('hashtags', '')}".strip()
    
    body = {
        'snippet': {
            'title': item['title'],
            'description': formatted_description,
            'tags': item.get('tags', []),
            'categoryId': '24'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
        }
    }

    try:
        media = MediaFileUpload('edited_video.mp4', chunksize=-1, resumable=True)
        request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
        
        for attempt in range(4):
            try:
                response = request.execute()
                print(f"🎉 Full Video Uploaded! ID: {response['id']}")
                video_url = f"https://youtu.be/{response['id']}"
                
                if 'thumbnail' in item: upload_thumbnail(youtube, response['id'], item['thumbnail'])
                delete_from_drive(video_id)
                
                if item['filename'] not in history: history.append(item['filename'])
                with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
                
                mh = MediaFileUpload('processed_history.json')
                if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
                else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()
                
                # अपलोड के बाद WhatsApp पर मेसेज भेजना
                msg = f"🎉 सफलता! आपकी वीडियो अपलोड हो गई है।\n\n📺 टाइटल: {item['title']}\n🔗 लिंक: {video_url}"
                send_whatsapp_message(msg)
                
                break
            except Exception as e:
                print(f"⚠️ अपलोड नेटवर्क एरर: {e}")
                if attempt == 3: raise e
                time.sleep(10)
    except Exception as e:
        print(f"❌ Upload Failed: {e}")

    for file in ['raw_video.mp4', 'edited_video.mp4', 'raw_thumb.jpg', 'thumb.jpg', 'client_secret.json', 'token.json', 'service_account.json']:
        if os.path.exists(file): os.remove(file)

if __name__ == '__main__':
    main()
