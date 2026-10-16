"""
Ytuploder — Anime Underworld uploader (PRO v2).

Pipeline per queue item:
  1. Download source from Drive.
  2. PRO edit (edit_anti_copyright_full_video): sync-safe, quality-preserving,
     copyright-fingerprint-breaking transforms. Every filter is duration-neutral
     so A/V can NEVER desync; a sync gate aborts the upload if drift > 40ms.
  3. Upload as UNLISTED.
  4. Extract 1-2 vertical Shorts clips (viral moments), each with its own
     thumbnail, uploaded UNLISTED alongside the long video.
  5. The long video is NEVER cut for Shorts — clips are separate files.
  6. Every upload (long + shorts) enters pending_review.json: after 1 hour,
     healthy videos go PUBLIC, taken-down/rejected videos are DELETED.

YouTube Data API limitation (honest): silent Content ID *claims* that do not
remove a video are NOT visible via the Data API. The review flow catches
takedowns / rejections / removals only.
"""
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

def log_ts(msg):
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {msg}")

def get_or_create_success_folder():
    query = f"name = 'Uploaded_Success' and mimeType = 'application/vnd.google-apps.folder' and '{DRIVE_FOLDER_ID}' in parents and trashed = false"
    for attempt in range(4):
        try:
            results = drive_service.files().list(q=query, fields="files(id, name)").execute()
            files = results.get('files', [])
            if files:
                return files[0]['id']
            else:
                folder_metadata = {'name': 'Uploaded_Success', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [DRIVE_FOLDER_ID]}
                folder = drive_service.files().create(body=folder_metadata, fields='id').execute()
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
            drive_service.files().update(fileId=file_id, addParents=success_folder_id, removeParents=previous_parents, fields='id, parents').execute()
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

def persist_history(history, history_file_id):
    with open('processed_history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4)
    mh = MediaFileUpload('processed_history.json', mimetype='application/json')
    for attempt in range(4):
        try:
            if history_file_id:
                drive_service.files().update(fileId=history_file_id, media_body=mh).execute()
            else:
                drive_service.files().create(body={'name': 'processed_history.json', 'parents': [DRIVE_FOLDER_ID]}, media_body=mh, fields='id').execute()
            return
        except Exception:
            if attempt == 3: raise
            time.sleep(10)

def probe_video_size(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=60)
        w, h = r.stdout.strip().split(',')[:2]
        return int(w), int(h)
    except Exception:
        return 1280, 720

def probe_format_duration(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=60)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def probe_av_durations(path):
    v = a = None
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=duration', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=60)
        v = float(r.stdout.strip().split()[0])
    except Exception:
        pass
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=duration', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=60)
        a = float(r.stdout.strip().split()[0])
    except Exception:
        pass
    return v, a

def has_audio_stream(path):
    try:
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=index', '-of', 'csv=p=0', path], capture_output=True, text=True, timeout=60)
        return bool(r.stdout.strip())
    except Exception:
        return False

_rubberband_ok = None

def build_pro_video_filter(W, H):
    zx, zy = int(W * 0.02), int(H * 0.02)
    sw, sh = int(W * 1.1), int(H * 1.1)
    return (
        "rotate=0.007:fillcolor=black,"
        f"scale={sw}:{sh},"
        f"crop={W}:{H}:'(iw-{W})/2+{zx}*sin(2*PI*t/40)':'(ih-{H})/2+{zy}*cos(2*PI*t/53)',"
        "hue=h=4,"
        "curves=all='0/0 0.5/0.53 1/1',"
        "vignette=PI/5,"
        "rgbashift=rh=1:bh=-1,"
        "hqdn3d=4:3:6:4.5,"
        "unsharp=5:5:0.6:5:5:0.0,"
        "noise=alls=4:allf=t,"
        "eq=brightness='0.008*sin(2*PI*t/9)':contrast=1.03:saturation=1.06"
    )

def build_pro_audio_filter():
    global _rubberband_ok
    if _rubberband_ok is None:
        try:
            r = subprocess.run(['ffmpeg', '-hide_banner', '-h', 'filter=rubberband'], capture_output=True, text=True, timeout=30)
            _rubberband_ok = (r.returncode == 0 and 'rubberband' in r.stdout.lower())
        except Exception:
            _rubberband_ok = False
    if _rubberband_ok:
        pitch = "rubberband=pitch=1.025"
    else:
        pitch = "asetrate=45202,aresample=44100,atempo=0.97561"
    return (f"{pitch},bass=g=2:f=120:w=0.8,equalizer=f=1200:t=q:w=1.2:g=-1.2,treble=g=1.5:f=9000:w=0.7,extrastereo=m=1.3,loudnorm=I=-16:TP=-1.5:LRA=11,aresample=async=1")

def verify_av_sync(path):
    v, a = probe_av_durations(path)
    if v is None or a is None:
        log_ts(f"sync gate: could not probe durations for {path} - ABORT")
        return False
    drift = abs(v - a)
    log_ts(f"sync gate: video={v:.3f}s audio={a:.3f}s drift={drift:.3f}s")
    if drift <= 0.04:
        log_ts("sync gate: PASS")
        return True
    tmp = path + ".syncfix.mp4"
    try:
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', path, '-c:v', 'copy', '-af', 'aresample=async=1', '-c:a', 'aac', '-b:a', '160k', tmp], check=True, timeout=900)
        v2, a2 = probe_av_durations(tmp)
        if v2 is not None and a2 is not None and abs(v2 - a2) <= 0.04:
            os.replace(tmp, path)
            log_ts("sync gate: corrected via aresample=async=1 - PASS")
            return True
        if v2 and a2 and a2 > 0:
            ratio = a2 / v2
            if 0.9 <= ratio <= 1.1:
                subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', tmp, '-c:v', 'copy', '-af', f'atempo={ratio:.6f}', '-c:a', 'aac', '-b:a', '160k', path], check=True, timeout=900)
                v3, a3 = probe_av_durations(path)
                if v3 is not None and a3 is not None and abs(v3 - a3) <= 0.04:
                    log_ts("sync gate: corrected via exact atempo - PASS")
                    return True
    except Exception as e:
        log_ts(f"sync gate correction error: {e}")
    finally:
        if os.path.exists(tmp):
            try: os.remove(tmp)
            except Exception: pass
    log_ts("sync gate: FAILED - A/V desync persists, upload ABORTED")
    return False

def edit_anti_copyright_full_video(input_video, output_video):
    W, H = probe_video_size(input_video)
    log_ts(f"pro edit: source {W}x{H}")
    vf = build_pro_video_filter(W, H)
    af = build_pro_audio_filter()
    cmd = ['ffmpeg', '-y', '-v', 'error', '-i', input_video, '-vf', vf, '-af', af,
           '-c:v', 'libx264', '-preset', 'medium', '-crf', '22', '-maxrate', '8M', '-bufsize', '16M',
           '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', output_video]
    log_ts("pro edit: encoding (preset medium, crf 22)...")
    subprocess.run(cmd, check=True, timeout=7200)
    log_ts("pro edit: encode done, running sync gate...")
    if not verify_av_sync(output_video):
        raise RuntimeError("A/V desync after pro edit - upload aborted")

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

def upload_local_thumbnail(youtube, video_id, jpg_path):
    for attempt in range(4):
        try:
            media = MediaFileUpload(jpg_path, mimetype='image/jpeg')
            youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
            log_ts(f"thumbnail uploaded for {video_id}")
            return True
        except Exception as e:
            if attempt == 3:
                log_ts(f"thumbnail upload failed for {video_id}: {e}")
                return False
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
    creds_yt = Credentials(token=token_data.get('token'), refresh_token=token_data.get('refresh_token'),
        token_uri=client_info.get('token_uri', 'https://oauth2.googleapis.com/token'),
        client_id=client_info['client_id'], client_secret=client_info['client_secret'], scopes=token_data.get('scopes'))
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
            return [p for p in response.text.strip().split('\r\n') if p]
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
                if data.get("countryCode") not in ['IN', 'PK', 'AE', 'BD']: return False, "other country"
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

def get_pending_review():
    fid = get_file_id_by_name(PENDING_FILE)
    if not fid: return [], None
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
                drive_service.files().create(body={'name': PENDING_FILE, 'parents': [DRIVE_FOLDER_ID]}, media_body=mh, fields='id').execute()
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
        if not vid: continue
        try:
            uploaded_at = datetime.fromisoformat(entry.get('uploadedAt', ''))
            if uploaded_at.tzinfo is None: uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
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
            try: youtube.videos().delete(id=vid).execute()
            except Exception as e: log_ts(f"delete call for {vid} failed (likely already gone): {e}")
            log_ts(f"DELETED {vid} - not retrievable (takedown/copyright hit)")
            continue
        status = items[0].get('status', {})
        up = status.get('uploadStatus')
        if up in ('deleted', 'failed', 'rejected'):
            reason = status.get('rejectionReason') or status.get('failureReason') or up
            try: youtube.videos().delete(id=vid).execute()
            except Exception as e: log_ts(f"delete call for {vid} failed: {e}")
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

SHORTS_MAX = 2
SHORTS_CLIP_SEC = 45
SHORTS_MAX_SEC = 60

def parse_ts(s):
    s = str(s).strip()
    if not s: return 0.0
    if ':' not in s: return max(0.0, float(s))
    sec = 0.0
    for part in s.split(':'): sec = sec * 60 + float(part)
    return max(0.0, sec)

def detect_viral_segments(src_path, clip_dur=SHORTS_CLIP_SEC, max_clips=SHORTS_MAX):
    total = probe_format_duration(src_path)
    if total <= clip_dur + 10:
        return [(0.0, min(float(SHORTS_MAX_SEC), total))] if total > 10 else []
    if not has_audio_stream(src_path):
        return [(max(0.0, total / 3 - clip_dur / 2), clip_dur), (max(0.0, 2 * total / 3 - clip_dur / 2), clip_dur)][:max_clips]
    cmd = ['ffmpeg', '-hide_banner', '-v', 'info', '-i', src_path, '-map', '0:a', '-af', 'ebur128=peak=true:framelog=quiet', '-f', 'null', '-']
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    except Exception:
        return [(max(0.0, total / 3 - clip_dur / 2), clip_dur)][:max_clips]
    frames = []
    for line in (r.stderr or '').splitlines():
        m = re.search(r't:\s*([\d.]+)\s*M:\s*(\S+)', line)
        if m:
            try:
                t = float(m.group(1)); ms = m.group(2)
                M = -70.0 if ms in ('-inf', 'inf') else float(ms)
                frames.append((t, M))
            except Exception: pass
    if not frames:
        return [(max(0.0, total / 3 - clip_dur / 2), clip_dur)][:max_clips]
    step = 5.0; cands = []; t = 0.0
    while t + clip_dur <= total:
        window = [M for (tt, M) in frames if t <= tt < t + clip_dur]
        avg = sum(window) / len(window) if window else -70.0
        cands.append((avg, t)); t += step
    cands.sort(reverse=True)
    picked = []
    for avg, st in cands:
        if all(abs(st - p) >= clip_dur for p in picked):
            picked.append(st)
            log_ts(f"shorts: candidate @{st:.0f}s (mean {avg:.1f} LUFS)")
        if len(picked) >= max_clips: break
    picked.sort()
    return [(max(0.0, st), clip_dur) for st in picked]

def get_shorts_specs(item, src_path):
    specs = []
    if isinstance(item.get('shorts'), list):
        for s in item['shorts'][:SHORTS_MAX]:
            try:
                start = parse_ts(s.get('start', '0'))
                dur = min(float(SHORTS_MAX_SEC), max(15.0, float(s.get('duration', SHORTS_CLIP_SEC))))
                specs.append((start, dur))
            except Exception: pass
        if specs:
            log_ts(f"shorts: using {len(specs)} user-specified segment(s)")
            return specs
    log_ts("shorts: auto-detecting viral segments")
    return detect_viral_segments(src_path)

def build_shorts_video_filter():
    return ("hue=h=4,curves=all='0/0 0.5/0.53 1/1',"
        "eq=brightness='0.008*sin(2*PI*t/9)':contrast=1.05:saturation=1.08,"
        "vignette=PI/6,unsharp=5:5:0.5:5:5:0.0,noise=alls=2:allf=t")

def extract_and_edit_short(src_path, start, dur, out_path):
    W, H = probe_video_size(src_path)
    pre = "crop=ih*9/16:ih:(iw-ow)/2:(ih-oh)/2,scale=720:1280," if W >= H else "scale=720:1280,"
    vf = pre + build_shorts_video_filter()
    af = build_pro_audio_filter()
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', f'{start:.2f}', '-i', src_path, '-t', f'{dur:.2f}',
           '-vf', vf, '-af', af, '-c:v', 'libx264', '-preset', 'medium', '-crf', '22',
           '-maxrate', '8M', '-bufsize', '16M', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k', out_path]
    log_ts(f"shorts: encoding 9:16 clip @{start:.0f}s ({dur:.0f}s)...")
    subprocess.run(cmd, check=True, timeout=1800)
    if not verify_av_sync(out_path):
        raise RuntimeError("shorts clip A/V desync - aborting")

def make_shorts_thumbnail(clip_path, out_jpg):
    d = probe_format_duration(clip_path) or 20.0
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', f'{d / 2:.1f}', '-i', clip_path, '-vframes', '1',
           '-vf', 'eq=contrast=1.12:saturation=1.15,unsharp=5:5:1.0', '-q:v', '2', out_jpg]
    subprocess.run(cmd, check=True, timeout=120)

def upload_short_video(youtube, filepath, title, description, tags):
    body = {'snippet': {'title': title, 'description': description, 'tags': tags, 'categoryId': '24'},
            'status': {'privacyStatus': 'unlisted', 'selfDeclaredMadeForKids': False}}
    for master_attempt in range(3):
        asian_proxies = get_strict_asian_proxies()
        if not asian_proxies: asian_proxies = ['direct']
        for proxy in asian_proxies:
            if proxy != 'direct':
                is_clean, info = verify_ip_cleanliness(proxy)
                if not is_clean: continue
                os.environ['http_proxy'] = f"http://{proxy}"
                os.environ['https_proxy'] = f"http://{proxy}"
            else:
                os.environ.pop('http_proxy', None)
                os.environ.pop('https_proxy', None)
            try:
                media = MediaFileUpload(filepath, chunksize=-1, resumable=True)
                req = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
                try:
                    resp = req.execute()
                    log_ts(f"shorts: uploaded unlisted -> {resp['id']}")
                    return resp['id']
                except Exception as e:
                    time.sleep(300)
                    th = os.environ.pop('http_proxy', None); ts = os.environ.pop('https_proxy', None)
                    vid = check_if_video_uploaded(youtube, title)
                    if th: os.environ['http_proxy'] = th
                    if ts: os.environ['https_proxy'] = ts
                    if vid: return vid
            except Exception as e:
                continue
        time.sleep(15)
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    return None

def process_shorts_for_item(youtube, item, history, history_file_id):
    try:
        specs = get_shorts_specs(item, 'raw_video.mp4')
    except Exception as e:
        log_ts(f"shorts: spec detection failed: {e}")
        return
    if not specs:
        log_ts("shorts: no segments found, skipping")
        return
    base_title = item.get('title', 'video')
    for i, (start, dur) in enumerate(specs[:SHORTS_MAX]):
        histkey = f"{item['filename']}#short{i}"
        if histkey in history:
            log_ts(f"shorts: {histkey} already done, skipping")
            continue
        clip_path, thumb_path = f"short_{i}.mp4", f"short_{i}.jpg"
        try:
            extract_and_edit_short('raw_video.mp4', start, dur, clip_path)
            make_shorts_thumbnail(clip_path, thumb_path)
            title = (base_title + " #shorts")[:100]
            desc = ((item.get('description', '') or '')[:500] + "\n\n#shorts").strip()
            tags = (list(item.get('tags', [])) + ['shorts'])[:15]
            vid = check_if_video_uploaded(youtube, title)
            if not vid:
                vid = upload_short_video(youtube, clip_path, title, desc, tags)
            if vid:
                upload_local_thumbnail(youtube, vid, thumb_path)
                add_pending_review_entry(vid)
                history.append(histkey)
                persist_history(history, history_file_id)
                log_ts(f"shorts: clip {i + 1} done -> {vid} (unlisted, queued for 1h review)")
            else:
                log_ts(f"shorts: clip {i + 1} upload failed")
        except Exception as e:
            log_ts(f"shorts: clip {i + 1} failed: {e}")
        finally:
            for f in (clip_path, thumb_path):
                if os.path.exists(f):
                    try: os.remove(f)
                    except Exception: pass

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
    body = {'snippet': {'title': final_title, 'description': formatted_description, 'tags': tags_list, 'categoryId': '24'},
            'status': {'privacyStatus': 'unlisted', 'selfDeclaredMadeForKids': False}}
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
                    persist_history(history, history_file_id)
                    if new_video_id:
                        try: add_pending_review_entry(new_video_id)
                        except Exception as e: log_ts(f"could not queue {new_video_id} for review: {e}")
                    try:
                        process_shorts_for_item(youtube, item, history, history_file_id)
                    except Exception as e:
                        log_ts(f"shorts pipeline failed: {e}")
                    break
            except Exception as e:
                pass
        if not upload_success:
            time.sleep(15)
    if not upload_success:
        if item['filename'] not in history:
            history.append(item['filename'])
            persist_history(history, history_file_id)
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    for file in ['raw_video.mp4', 'edited_video.mp4', 'raw_thumb.jpg', 'edited_thumb.jpg', 'client_secret.json', 'token.json', 'service_account.json', PENDING_FILE]:
        if os.path.exists(file): os.remove(file)

if __name__ == '__main__':
    main()
