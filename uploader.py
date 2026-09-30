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

def download_from_drive(file_id, output_path):
    print(f"📥 ڈرائیو سے فائل {output_path} ڈاؤنلوڈ کی جا رہی ہے...")
    for attempt in range(4):
        try:
            request = drive_service.files().get_media(fileId=file_id)
            with open(output_path, 'wb') as f:
                f.write(request.execute())
            print("✅ ڈاؤنلوڈ مکمل ہو گیا!")
            return
        except Exception as e:
            print(f"⚠️ ڈاؤنلوڈ نیٹ ورک ایرر (کوشش {attempt+1}/4): {e}")
            if attempt == 3: raise e
            time.sleep(10)

def delete_from_drive(file_id):
    for attempt in range(4):
        try:
            drive_service.files().update(fileId=file_id, body={'trashed': True}).execute()
            print(f"🗑️ فائل آئی ڈی {file_id} کو ڈرائیو کے ٹریش (Trash) میں منتقل کر دیا گیا ہے۔")
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def edit_anti_copyright_full_video(input_video, output_video):
    print("🎬 مکمل ویڈیو پروسیسنگ: FFmpeg کے ذریعے اینٹی کاپی رائٹ فلٹرز لگائے جا رہے ہیں...")
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
    print("✨ مکمل ویڈیو کی اینٹی کاپی رائٹ ایڈیٹنگ مکمل ہو گئی!")

def enhance_and_upload_thumbnail(youtube, video_id, thumbnail_filename):
    t_id = get_file_id_by_name(thumbnail_filename)
    if not t_id: return
    download_from_drive(t_id, 'raw_thumb.jpg')
    
    print("🎨 FFmpeg کے ذریعے تھمب نیل کو منفرد (Unique) بنایا جا رہا ہے...")
    thumb_filter = "crop=iw*0.96:ih*0.96,scale=iw:ih,eq=brightness=0.02:contrast=1.08:saturation=1.1,noise=alls=2:allf=t+u,unsharp=3:3:0.5"
    cmd = [
        'ffmpeg', '-y',
        '-i', 'raw_thumb.jpg',
        '-vf', thumb_filter,
        '-q:v', '2',
        'edited_thumb.jpg'
    ]
    try:
        subprocess.run(cmd, check=True)
        print("✨ تھمب نیل کامیابی سے منفرد ہو گیا!")
    except Exception as e:
        print(f"⚠️ تھمب نیل ایڈیٹ کرنے میں ایرر، اصل تھمب نیل استعمال کیا جا رہا ہے: {e}")
        os.rename('raw_thumb.jpg', 'edited_thumb.jpg')
    
    for attempt in range(4):
        try:
            media = MediaFileUpload('edited_thumb.jpg', mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            print("✅ ایڈیٹ شدہ تھمب نیل یوٹیوب پر اپلوڈ ہو گیا!")
            delete_from_drive(t_id)
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
        except Exception as e:
            if attempt == 3: return None
            time.sleep(10)

def get_youtube_service():
    cs_id = get_file_id_by_name('client_secret.json')
    tk_id = get_file_id_by_name('token.json')
    if not cs_id or not tk_id: raise Exception("❌ client_secret.json یا token.json ڈرائیو میں نہیں ملا!")
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

def get_strict_asian_proxies():
    print("🔍 انٹرنیٹ سے صرف اعلیٰ کوالٹی کی ایشین پراکسیز (پاکستان، انڈیا، یو اے ای، بنگلہ دیش) تلاش کی جا رہی ہیں...")
    url = "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=IN,PK,AE,BD&ssl=yes&anonymity=elite"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            proxies = response.text.strip().split('\r\n')
            valid_proxies = [p for p in proxies if p]
            print(f"✅ کل {len(valid_proxies)} ایشین پراکسیز مل گئیں!")
            return valid_proxies
    except Exception as e:
        print(f"⚠️ پراکسی تلاش کرنے میں ایرر: {e}")
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
                if data.get("countryCode") not in valid_countries:
                    return False, f"بیرونی ملک/یورپین ({data.get('country')})"
                if data.get("hosting") == True:
                    return False, "ڈیٹا سینٹر/سپیم آئی پی"
                return True, data.get("country")
    except:
        pass
    return False, "چیک فیل (پراکسی ڈیڈ ہے)"

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

    print(f"🚀 پروسیسنگ شروع: {item['title']}")
    video_id = get_file_id_by_name(item['filename'])
    download_from_drive(video_id, 'raw_video.mp4')
    
    edit_anti_copyright_full_video('raw_video.mp4', 'edited_video.mp4')

    # ٹائٹل اور ٹیگز رینڈمائزیشن
    final_title = f"{item['title']} \u200B"
    tags_list = item.get('tags', [])
    if tags_list:
        random.shuffle(tags_list)

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
        
    credit_section = ""
    orig_url = item.get('webpage_url') or item.get('original_url')
    orig_channel = item.get('uploader') or item.get('channel')
    
    if orig_channel and orig_url:
        credit_section = f"\n\n🎥 ویڈیو کریڈٹ (Video Credit): {orig_channel}\n🔗 اصل لنک (Original): {orig_url}"
    elif orig_channel:
        credit_section = f"\n\n🎥 ویڈیو کریڈٹ (Video Credit): {orig_channel}"
    elif orig_url:
        credit_section = f"\n\n🎥 ویڈیو کریڈٹ (Video Credit): {orig_url}"
    else:
        credit_section = "\n\n🎥 ویڈیو کریڈٹ (Credit): Respective Owner"

    formatted_description = f"{clean_desc}\n\n{item.get('hashtags', '')}{credit_section}".strip()
    
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

    asian_proxies = get_strict_asian_proxies()
    if not asian_proxies:
        print("⚠️ کوئی ایشین پراکسی نہیں ملی۔ ڈائریکٹ نیٹ ورک ٹرائی کر رہے ہیں...")
        asian_proxies = ['direct']

    upload_success = False

    for proxy in asian_proxies:
        country_info = ""
        
        if proxy != 'direct':
            is_clean, country_info = verify_ip_cleanliness(proxy)
            if not is_clean:
                print(f"🚫 پراکسی مسترد کر دی گئی ({country_info}): {proxy}")
                continue
            
            print(f"🌐 ٹیسٹ کی جا رہی ہے کلین ایشین پراکسی ({country_info}): {proxy}")
            os.environ['http_proxy'] = f"http://{proxy}"
            os.environ['https_proxy'] = f"http://{proxy}"
        else:
            print("🌐 ڈائریکٹ اپلوڈ (بغیر پراکسی) ٹرائی کر رہے ہیں...")
            os.environ.pop('http_proxy', None)
            os.environ.pop('https_proxy', None)

        try:
            youtube = get_youtube_service()
            media = MediaFileUpload('edited_video.mp4', chunksize=-1, resumable=True)
            request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
            
            for attempt in range(4):
                try:
                    response = request.execute()
                    print(f"🎉 مکمل ویڈیو اپلوڈ ہو گئی! ID: {response['id']}")
                    
                    print("\n" + "="*60)
                    if proxy != 'direct':
                        print(f"🚀 SUCCESS LOG: یہ ویڈیو کامیابی کے ساتھ {proxy} ({country_info}) کے IP سے اپلوڈ ہو گئی ہے!")
                    else:
                        print(f"🚀 SUCCESS LOG: یہ ویڈیو کامیابی کے ساتھ ڈائریکٹ گٹ ہب آئی پی سے اپلوڈ ہو گئی ہے!")
                    print("="*60 + "\n")
                    
                    if 'thumbnail' in item: 
                        enhance_and_upload_thumbnail(youtube, response['id'], item['thumbnail'])
                    delete_from_drive(video_id)
                    
                    if item['filename'] not in history: history.append(item['filename'])
                    with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
                    
                    mh = MediaFileUpload('processed_history.json')
                    if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
                    else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()
                    
                    upload_success = True
                    break
                except Exception as e:
                    print(f"⚠️ اپلوڈ نیٹ ورک ایرر (کوشش {attempt+1}/4): {e}")
                    if attempt == 3: raise e
                    time.sleep(10)
            
            if upload_success:
                os.environ.pop('http_proxy', None)
                os.environ.pop('https_proxy', None)
                break
                
        except Exception as e:
            print(f"❌ پراکسی {proxy} فیل ہو گئی: {e} | اگلی ٹرائی کر رہے ہیں...")
            
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)

    for file in ['raw_video.mp4', 'edited_video.mp4', 'raw_thumb.jpg', 'edited_thumb.jpg', 'client_secret.json', 'token.json', 'service_account.json']:
        if os.path.exists(file): os.remove(file)

if __name__ == '__main__':
    main()
