import os
import json
import subprocess
import time
import re
import random
import requests
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

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
                print("new Uploaded_Success folder created")
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
            return
        except Exception as e:
            if attempt == 3: return
            time.sleep(10)

def download_from_drive(file_id, output_path):
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
    if not cs_id or not tk_id: raise Exception("client_secret.json or token.json not found!")
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
                if data.get("countryCode") not in valid_countries: return False, "other country"
                if data.get("hosting") == True: return False, "datacenter"
                return True, data.get("country")
    except: pass
    return False, "dead proxy"

def check_if_video_uploaded(youtube, title):
    try:
        channel_req = youtube.channels().list(part="contentDetails", mine=True).execute()
        uploads_playlist = channel_req['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        playlist_req = youtube.playlistItems().list(part="snippet", playlistId=uploads_playlist, maxResults=5).execute()
        for vid_item in playlist_req.get('items', []):
            if vid_item['snippet']['title'] == title:
                return vid_item['snippet']['resourceId']['videoId']
    except Exception as e:
        print(f"Playlist check error: {e}")
    return None

REVIEW_DELAY_SEC = 3600
PENDING_FILE = 'pending_review.json'

def log_ts(msg):
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}")

def get_pending_review():
    fid = get_file_id_by_name(PENDING_FILE)
    if not fid:
        return [], None
    try:
        download_from_drive(fid, PENDING_FILE)
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return (data if isinstance(data, list) else []), fid
    except Exception as e:
        log_ts(f"pending_review read failed: {e}")
        return [], fid

def save_pending_review(entries, file_id):
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(entries, f, indent=2)
    mh = MediaFileUpload(PENDING_FILE, mimetype='application/json')
    for attempt in range(4):
        try:
            if file_id:
                drive_service.files().update(fileId=file_id, media_body=mh).execute()
            else:
                drive_service.files().create(
                    body={'name': PENDING_FILE, 'parents': [DRIVE_FOLDER_ID]},
                    media_body=mh, fields='id').execute()
            return
        except Exception:
            if attempt == 3: raise
            time.sleep(10)

def add_pending_review_entry(video_id):
    entries, fid = get_pending_review()
    if any(e.get('videoId') == video_id for e in entries):
        log_ts(f"pending_review: {video_id} already queued, skipping duplicate")
        return
    entries.append({'videoId': video_id, 'uploadedAt': datetime.now(timezone.utc).isoformat()})
    save_pending_review(entries, fid)
    log_ts(f"pending_review: queued {video_id} (unlisted) - review due in 1h")

def process_pending_review(youtube):
    entries, fid = get_pending_review()
    if not entries:
        log_ts("pending_review: empty, nothing to review")
        return
    now = datetime.now(timezone.utc)
    remaining = []
    for entry in entries:
        vid = entry.get('videoId')
        if not vid:
            continue
        try:
            uploaded_at = datetime.fromisoformat(entry.get('uploadedAt', ''))
            if uploaded_at.tzinfo is None:
                uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
        except Exception:
            uploaded_at = now
        age = (now - uploaded_at).total_seconds()
        if age < REVIEW_DELAY_SEC:
            remaining.append(entry)
            continue
        log_ts(f"reviewing {vid} (unlisted age {age/3600:.1f}h)...")
        try:
            resp = youtube.videos().list(part="status", id=vid).execute()
            items = resp.get('items', [])
            check_failed = False
        except HttpError as e:
            if getattr(e.resp, 'status', None) in (404, 403):
                items = []
                check_failed = False
            else:
                check_failed = True
        except Exception:
            check_failed = True
        if check_failed:
            log_ts(f"status check failed for {vid} (transient) - will retry next run")
            remaining.append(entry)
            continue
        if not items:
            try:
                youtube.videos().delete(id=vid).execute()
            except Exception as e:
                log_ts(f"delete call for {vid} failed (likely already gone): {e}")
            log_ts(f"DELETED {vid} - not retrievable (takedown/copyright hit)")
            continue
        status = items[0].get('status', {})
        up = status.get('uploadStatus')
        if up in ('deleted', 'failed', 'rejected'):
            reason = status.get('rejectionReason') or status.get('failureReason') or up
            try:
                youtube.videos().delete(id=vid).execute()
            except Exception as e:
                log_ts(f"delete call for {vid} failed: {e}")
            log_ts(f"DELETED {vid} - uploadStatus={reason}")
            continue
        try:
            youtube.videos().update(part="status", body={"id": vid, "status": {"privacyStatus": "public"}}).execute()
            log_ts(f"PUBLISHED {vid} - 1h review passed, no takedown")
        except Exception as e:
            log_ts(f"publish failed for {vid}: {e} - will retry next run")
            remaining.append(entry)
    save_pending_review(remaining, fid)
    log_ts(f"pending_review: done, {len(remaining)} still waiting")

def main():
    success_folder_id = get_or_create_success_folder()
    youtube = None
    try:
        youtube = get_youtube_service()
        process_pending_review(youtube)
    except Exception as e:
        log_ts(f"startup pending-review skipped: {e}")
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
    video_id = get_file_id_by_name(item['filename'])
    download_from_drive(video_id, 'raw_video.mp4')
    edit_anti_copyright_full_video('raw_video.mp4', 'edited_video.mp4')
    final_title = f"{item['title']} \u200B"
    tags_list = item.get('tags', [])
    if tags_list: random.shuffle(tags_list)
    original_desc = item.get('description', '')
    clean_desc = re.sub(r'http[s]?://\S+|www\.\S+', '', original_desc)
    clean_desc = re.sub(r'\n\s*\n', '\n\n', clean_desc).strip()
    formatted_description = f"{clean_desc}\n\nCopyright Disclaimer: Under section 107 of the Copyright Act 1976...".strip()
    body = {
        'snippet': {
            'title': final_title,
            'description': formatted_description,
            'tags': tags_list,
            'categoryId': '24'
        },
        'status': {
            'privacyStatus': 'unlisted',
            'selfDeclaredMadeForKids': False,
        }
    }
    upload_success = False
    new_video_id = None
    max_master_retries = 3
    if youtube is None:
        try:
            youtube = get_youtube_service()
        except Exception as e:
            print(f"YouTube connection failed: {e}")
            return
    for master_attempt in range(max_master_retries):
        if upload_success: break
        asian_proxies = get_strict_asian_proxies()
        if not asian_proxies: asian_proxies = ['direct']
        for proxy in asian_proxies:
            if upload_success: break
            vid_id = check_if_video_uploaded(youtube, final_title)
            if vid_id:
                upload_success = True
                break
            if proxy != 'direct':
                is_clean, info = verify_ip_cleanliness(proxy)
                if not is_clean: continue
                os.environ['http_proxy'] = f"http://{proxy}"
                os.environ['https_proxy'] = f"http://{proxy}"
            else:
                os.environ.pop('http_proxy', None)
                os.environ.pop('https_proxy', None)
            try:
                media = MediaFileUpload('edited_video.mp4', chunksize=-1, resumable=True)
                request = youtube.videos().insert(part=','.join(body.keys()), body=body, media_body=media)
                try:
                    response = request.execute()
                    vid_id = response['id']
                    new_video_id = response['id']
                    upload_success = True
                except Exception as e:
                    time.sleep(300)
                    temp_http = os.environ.pop('http_proxy', None)
                    temp_https = os.environ.pop('https_proxy', None)
                    vid_id = check_if_video_uploaded(youtube, final_title)
                    if temp_http: os.environ['http_proxy'] = temp_http
                    if temp_https: os.environ['https_proxy'] = temp_https
                    if vid_id:
                        new_video_id = vid_id
                        upload_success = True
                if upload_success:
                    if 'thumbnail' in item: enhance_and_upload_thumbnail(youtube, vid_id, item['thumbnail'], success_folder_id)
                    if success_folder_id: move_file_to_success_folder(video_id, success_folder_id)
                    if item['filename'] not in history: history.append(item['filename'])
                    with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
                    mh = MediaFileUpload('processed_history.json')
                    if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
                    else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()
                    if new_video_id:
                        try:
                            add_pending_review_entry(new_video_id)
                        except Exception as e:
                            log_ts(f"could not queue {new_video_id} for review: {e}")
                    break
            except Exception as e:
                pass
        if not upload_success:
            time.sleep(15)
    if not upload_success:
        if item['filename'] not in history:
            history.append(item['filename'])
            with open('processed_history.json', 'w', encoding='utf-8') as f: json.dump(history, f, indent=4)
            mh = MediaFileUpload('processed_history.json')
            if history_file_id: drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
            else: drive_service.files().create(body={'name':'processed_history.json','parents':[DRIVE_FOLDER_ID]}, media_body=mh).execute()
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    for file in ['raw_video.mp4', 'edited_video.mp4', 'raw_thumb.jpg', 'edited_thumb.jpg', 'client_secret.json', 'token.json', 'service_account.json', PENDING_FILE]:
        if os.path.exists(file): os.remove(file)

if __name__ == '__main__':
    main()
