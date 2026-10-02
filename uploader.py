import os
import json
import subprocess
import time
import re
import random
import requests
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_FOLDER_ID = os.environ.get('DRIVE_FOLDER_ID')
SERVICE_ACCOUNT_JSON = os.environ.get('SERVICE_ACCOUNT_JSON')

with open('service_account.json', 'w') as f:
    f.write(SERVICE_ACCOUNT_JSON)

creds_drive = service_account.Credentials.from_service_account_file(
    'service_account.json', scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds_drive)

def get_or_create_success_folder():
    query = f"name = 'Uploaded_Success' and mimeType = 'application/vnd.google-apps.folder' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    for attempt in range(4):
        try:
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            if files:
                return files[0]['id'] 
            else:
                folder_metadata = {
                    'name': 'Uploaded_Success',
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [DRIVE_FOLDER_ID]
                }
                folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
                print("📁 نیا 'Uploaded_Success' فولڈر بنا دیا گیا ہے۔")
                return folder.get('id')
        except Exception as e:
            if attempt == 3: return None
            time.sleep(10)

def move_file_to_success_folder(file_id, success_folder_id):
    if not success_folder_id: return
    for attempt in range(4):
        try:
            file = drive_service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents', []))
            
            drive_service.files().update(
                fileId=file_id,
                addParents=success_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            print(f"📦 ویڈیو فائل کو 'Uploaded_Success' فولڈر میں منتقل کر دیا گیا ہے۔")
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def download_from_drive(file_id, output_path):
    print(f"📥 گوگل ڈرائیو سے فائل ڈاؤنلوڈ ہو رہی ہے...")
    for attempt in range(4):
        try:
            request = drive_service.files().get_media(fileId=file_id)
            with open(output_path, 'wb') as f:
                f.write(request.execute())
            return
        except Exception as e:
            if attempt == 3: raise e
            time.sleep(10)

def edit_anti_copyright_full_video(input_video, output_video):
    print("🎬 ویڈیو پروسیسنگ: گٹ ہب سرور پر ویڈیو کو ایڈٹ کیا جا رہا ہے...")
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
    print("✨ سرور پر ویڈیو کی پروسیسنگ مکمل ہو گئی!")

def enhance_and_upload_thumbnail(youtube, video_id, thumbnail_filename, success_folder_id):
    t_id = get_file_id_by_name(thumbnail_filename)
    if not t_id: return
    download_from_drive(t_id, 'raw_thumb.jpg')
    
    thumb_filter = "crop=iw*0.96:ih*0.96,scale=iw:ih,eq=brightness=0.02:contrast=1.08:saturation=1.1,noise=alls=2:allf=t+u,unsharp=3:3:0.5"
    cmd = ['ffmpeg', '-y', '-i', 'raw_thumb.jpg', '-vf', thumb_filter, '-q:v', '2', 'edited_thumb.jpg']
    try:
        subprocess.run(cmd, check=True)
    except:
        os.rename('raw_thumb.jpg', 'edited_thumb.jpg')
    
    for attempt in range(4):
        try:
            media = MediaFileUpload('edited_thumb.jpg', mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            print("✅ تھمب نیل یوٹیوب پر اپلوڈ ہو گیا!")
            if success_folder_id: move_file_to_success_folder(t_id, success_folder_id)
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def get_file_id_by_name(filename):
    query = f"name = '{filename}' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    for attempt in range(4):
        try:
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            return files[0]['id'] if files else None
        except Exception:
            if attempt == 3: return None
            time.sleep(10)

def get_youtube_service():
    cs_id = get_file_id_by_name('client_secret.json')
    tk_id = get_file_id_by_name('token.json')
    if not cs_id or not tk_id: raise Exception("❌ client_secret.json یا token.json نہیں ملا!")
    download_from_drive(cs_id, 'client_secret.json')
    download_from_drive(tk_id, 'token.json')

    with open('client_secret.json', 'r') as f: client_secret_data = json.load(f)
    with open('token.json', 'r') as f: token_data = json.load(f)
    client_info = client_secret_data.get('web') or client_secret_data.get('installed')

    creds_yt = Credentials(
        token=token_data.get('token'), refresh_token=token_data.get('refresh_token'),
        token_uri=client_info.get('token_uri', 'https://oauth2.googleapis.com/token'), 
        client_id=client_info['client_id'], client_secret=client_info['client_secret'], 
        scopes=token_data.get('scopes')
    )
    
    if not creds_yt.valid:
        if creds_yt.expired and creds_yt.refresh_token:
            for attempt in range(4):
                try:
                    creds_yt.refresh(Request())
                    token_data['token'] = creds_yt.token
                    with open('token.json', 'w') as f: json.dump(token_data, f)
                    media = MediaFileUpload('token.json', mimetype='application/json')
                    drive_service.files().update(fileId=tk_id, media_body=media).execute()
                    break
                except:
                    if attempt == 3: raise
                    time.sleep(10)
    return build('youtube', 'v3', credentials=creds_yt)

def get_strict_asian_proxies():
    url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=IN,PK,AE,BD&ssl=yes&anonymity=elite"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            proxies = [p for p in response.text.strip().split('\r\n') if p]
            return proxies
    except: pass
    return []

def verify_ip_cleanliness(proxy_ip):
    ip_only = proxy_ip.split(':')[0]
    verify_url = f"http://ip-api.com/json/{ip_only}?fields=status,country,countryCode,hosting"
    try:
        res = requests.get(verify_url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "success":
                valid_countries = ['IN', 'PK', 'AE', 'BD']
                if data.get("countryCode") not in valid_countries: return False, "بیرونی ملک"
                if data.get("hosting") == True: return False, "ڈیٹا سینٹر"
                return True, data.get("country")
    except: pass
    return False, "ڈیڈ پراکسی"

def check_if_video_uploaded(youtube, title):
    try:
        channel_req = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist = channel_req['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        playlist_req = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist, maxResults=5).execute()
        for vid_item in playlist_req.get('items', []):
            if vid_item['snippet']['title'] == title:
                return vid_item['snippet']['resourceId']['videoId']
    except Exception as e:
        print(f"⚠️ Playlist check error: {e}")
    return None

def main():
    success_folder_id = get_or_create_success_folder()

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
        except:
            if attempt == 3: raise
            time.sleep(10)

    if not item: return

    print(f"\n🚀 پروسیسنگ شروع: {item['title']}")
    video_id = get_file_id_by_name(item['filename'])
    download_from_drive(video_id, 'raw_video.mp4')
    
    edit_anti_copyright_full_video('raw_video.mp4', 'edited_video.mp4')

    final_title = f"{item['title']} \u200B"
    tags_list = item.get('tags', [])
    if tags_list: random.shuffle(tags_list)

    original_desc = item.get('description', '')
    clean_desc = re.sub(r'http[s]?://\S+|www\.\S+', '', original_desc)
    clean_desc = re.sub(r'\n\s*\n', '\n\n', clean_desc).strip()
    
    formatted_description = f"{clean_desc}\n\n⚠️ Copyright Disclaimer: Under section 107 of the Copyright Act 1976...".strip()
    
    body = {
        'snippet': {
            'title': final_title,
            'description': formatted_description,
            'tags': tags_list,
            'categoryId': '24'
        },
        'status': {
            'privacyStatus': 'public',
            'selfDeclaredMadeForKids': False,
        }
    }

    upload_success = False
    max_master_retries = 3  
    youtube = None
    
    try:
        youtube = get_youtube_service()
    except Exception as e:
        print(f"❌ یوٹیوب کنکشن فیل: {e}")
        return

    for master_attempt in range(max_master_retries):
        if upload_success: break
            
        print(f"\n🔄 نیٹ ورک/پراکسی راؤنڈ {master_attempt + 1}/{max_master_retries}...")
        asian_proxies = get_strict_asian_proxies()
        if not asian_proxies: asian_proxies = ['direct']

        for proxy in asian_proxies:
            if upload_success: break
            
            print("🔍 سیکیورٹی چیک: چیک کیا جا رہا ہے کہ کیا ویڈیو پہلے سے اپلوڈ ہو چکی ہے...")
            vid_id = check_if_video_uploaded(youtube, final_title)
            if vid_id:
                print(f"✅ محفوظ روک: یہ ویڈیو چینل پر پہلے سے موجود ہے! (ID: {vid_id}) ڈپلیکیٹ اپلوڈ کو روک دیا گیا۔")
                upload_success = True
                break

            if proxy != 'direct':
                is_clean, info = verify_ip_cleanliness(proxy)
                if not is_clean: continue
                os.environ['http_proxy'] = f"http://{proxy}"
                os.environ['https_proxy'] = f"http://{proxy}"
                print(f"🌐 پراکسی کے ذریعے اپلوڈ ہو رہا ہے: {proxy}")
            else:
                os.environ.pop('http_proxy', None)
                os.environ.pop('https_proxy', None)
                print("🌐 ڈائریکٹ اپلوڈ ہو رہا ہے...")

            try:
                media = MediaFileUpload('edited_video.mp4', chunksize=-1, resumable=True)
                request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
                
                try:
                    response = request.execute()
                    print(f"🎉 ویڈیو کامیابی کے ساتھ اپلوڈ ہو گئی! ID: {response['id']}")
                    vid_id = response['id']
                    upload_success = True
                except Exception as e:
                    print(f"⚠️ اپلوڈ کے دوران کنکشن ٹوٹا (Error: {e})")
                    
                    # 🔴 نیا حل: 5 منٹ (300 سیکنڈ) کا انتظار تاکہ یوٹیوب ویڈیو پروسیس کر لے 🔴
                    print("⏳ پراکسی ڈسکنیکٹ ہو گئی! ممکن ہے آدھی اپلوڈ کے بعد ویڈیو سرور پر چلی گئی ہو۔")
                    print("🔍 سمارٹ چیکنگ: یوٹیوب پروسیسنگ کے لیے 5 منٹ (300 سیکنڈ) کا انتظار کیا جا رہا ہے...")
                    time.sleep(300) 
                    
                    temp_http = os.environ.pop('http_proxy', None)
                    temp_https = os.environ.pop('https_proxy', None)
                    
                    # 5 منٹ بعد چینل میں چیک
                    vid_id = check_if_video_uploaded(youtube, final_title)
                    
                    if temp_http: os.environ['http_proxy'] = temp_http
                    if temp_https: os.environ['https_proxy'] = temp_https

                    if vid_id:
                        print(f"🎉 سمارٹ چیک پاس! ویڈیو بیک گراؤنڈ میں کامیابی سے اپلوڈ ہو چکی تھی۔ ID: {vid_id}")
                        upload_success = True
                    else:
                        print("⚠ 5 منٹ انتظار کے بعد بھی چینل پر ویڈیو نہیں ملی۔ اب اگلی پراکسی سے دوبارہ اپلوڈ شروع کیا جائے گا۔")

                if upload_success:
                    if 'thumbnail' in item: enhance_and_upload_thumbnail(youtube, vid_id, item['thumbnail'], success_folder_id)
                    if success_folder_id: move_file_to_success_folder(video_id, success_folder_id)
                    
                    if item['filename'] not in history: history.append(item['filename'])
                    with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
                    mh = MediaFileUpload('processed_history.json')
                    if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
                    else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()
                    
                    break # پراکسی لوپ بریک کر دیں
                    
            except Exception as e:
                print(f"❌ اپلوڈ پروسیس میں ایرر: {e} | اگلی پراکسی ٹرائی کر رہے ہیں...")
                
        if not upload_success:
            time.sleep(15)

    if not upload_success:
        print("\n⚠ تمام کوششوں کے باوجود ویڈیو اپلوڈ نہیں ہو سکی۔")
        if item['filename'] not in history:
            history.append(item['filename'])
            with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
            mh = MediaFileUpload('processed_history.json')
            if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
            else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()

    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    for file in ['raw_video.mp4', 'edited_video.mp4', 'raw_thumb.jpg', 'edited_thumb.jpg', 'client_secret.json', 'token.json', 'service_account.json']:
        if os.path.exists(file): os.remove(file)

if __name__ == '__main__':
    main()
