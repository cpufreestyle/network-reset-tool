#!/usr/bin/env python3
"""Upload network_first_aid_kit.exe to Gitee Release v3.0"""
import urllib.request, urllib.parse, json, os, sys

TOKEN = '8598175f28d65359a5ad1c41180e6920'
OWNER = 'cpufreestyle'
REPO = 'network-reset-tool'
RELEASE_ID = 679537

def api_get(path):
    url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}{path}?access_token={TOKEN}'
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8'))

def api_delete(path):
    url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}{path}'
    data = urllib.parse.urlencode({'access_token': TOKEN}).encode()
    req = urllib.request.Request(url, data=data, method='DELETE')
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        print(f"Delete HTTP {e.code}: {e.read().decode()}")

# 删除旧 exe
print("清理旧 exe...")
files = api_get(f'/releases/{RELEASE_ID}/attach_files')
for f in files:
    fid = f.get('id')
    fname = f.get('name', '')
    if fid and fname.endswith('.exe'):
        try:
            api_delete(f'/releases/{RELEASE_ID}/attach_files/{fid}')
            print(f"  Deleted: {fname} (id={fid})")
        except Exception as e:
            print(f"  Delete failed: {e}")

# 上传新 exe
exe_path = r'D:\qclaw-workspace\network-reset-tool\dist\网络工具箱.exe'
exe_size = os.path.getsize(exe_path)
print(f"\n上传: {os.path.basename(exe_path)} ({exe_size:,} bytes)")

upload_url = f'https://gitee.com/api/v5/repos/{OWNER}/{REPO}/releases/{RELEASE_ID}/attach_files'
boundary = '----FormBoundary' + str(int(os.urandom(4).hex(), 16))

with open(exe_path, 'rb') as f:
    exe_data = f.read()

body = bytearray()
# access_token 字段
body.extend(f'--{boundary}\r\n'.encode())
body.extend(b'Content-Disposition: form-data; name="access_token"\r\n\r\n')
body.extend(f'{TOKEN}\r\n'.encode())
# file 字段
body.extend(f'--{boundary}\r\n'.encode())
fname_header = 'Content-Disposition: form-data; name="file"; filename="网络工具箱.exe"\r\n'
body.extend(fname_header.encode('utf-8'))
body.extend(b'Content-Type: application/octet-stream\r\n\r\n')
body.extend(exe_data)
body.extend(f'\r\n--{boundary}--\r\n'.encode())

req = urllib.request.Request(upload_url, data=bytes(body), method='POST')
req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
req.add_header('Content-Length', str(len(body)))

try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode('utf-8'))
        print(f"[OK] 上传成功! id={result.get('id')} name={result.get('name')} size={result.get('size')}")
except Exception as e:
    print(f"[FAIL] 上传失败: {e}")
    sys.exit(1)
