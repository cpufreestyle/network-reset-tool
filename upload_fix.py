#!/usr/bin/env python3
"""Upload fixed exe to Gitee Release v3.0"""
import urllib.request, urllib.parse, json, os

TOKEN = '8598175f28d65359a5ad1c41180e6920'
OWNER = 'cpufreestyle'
REPO = 'network-reset-tool'
RELEASE_ID = 679537  # v3.0

# List existing assets
list_url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}'
req = urllib.request.Request(list_url)
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode('utf-8'))

existing = data.get('assets', [])
print(f'Existing assets: {len(existing)}')
for a in existing:
    aid = a.get('id', a.get('asset_id', '?'))
    print(f'  - {a.get("name", "?")} (id={aid})')

# Delete old exe assets
for a in existing:
    aid = a.get('id', a.get('asset_id'))
    if a.get('name', '').endswith('.exe') and aid:
        del_url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}/attach_files/{aid}'
        del_data = urllib.parse.urlencode({'access_token': TOKEN}).encode()
        del_req = urllib.request.Request(del_url, data=del_data, method='DELETE')
        try:
            with urllib.request.urlopen(del_req) as resp:
                print(f'  Deleted: {a.get("name", "?")} (id={aid})')
        except Exception as e:
            print(f'  Delete failed: {e}')

# Upload new exe
exe_path = r'D:\qclaw-workspace\network-reset-tool\dist\网络急救箱.exe'
exe_size = os.path.getsize(exe_path)
print(f'Uploading: {exe_path} ({exe_size} bytes)')

upload_url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}/attach_files'
boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
with open(exe_path, 'rb') as f:
    exe_data = f.read()

body = bytearray()
body.extend(f'--{boundary}\r\n'.encode())
body.extend(f'Content-Disposition: form-data; name="access_token"\r\n\r\n'.encode())
body.extend(f'{TOKEN}\r\n'.encode())
body.extend(f'--{boundary}\r\n'.encode())
body.extend(f'Content-Disposition: form-data; name="file"; filename="\u7f51\u7edc\u6025\u6551\u7bb1.exe"\r\n'.encode())
body.extend(f'Content-Type: application/octet-stream\r\n\r\n'.encode())
body.extend(exe_data)
body.extend(f'\r\n--{boundary}--\r\n'.encode())

req = urllib.request.Request(upload_url, data=bytes(body), method='POST')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
req.add_header('Content-Length', str(len(body)))

with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read().decode('utf-8'))
    print(f'Upload success! Asset id={result["id"]}, name={result["name"]}, size={result.get("size", "?")}')
