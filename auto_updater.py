# -*- coding: utf-8 -*-
"""
通用自动更新模块 - Gitee Release 自动检查与下载
适用于所有 PyInstaller 打包的 Windows GUI 应用

使用方法:
    from auto_updater import AutoUpdater

    updater = AutoUpdater(
        app_name="MyApp",
        current_version="1.0.0",
        gitee_owner="yourname",
        gitee_repo="myapp",
        exe_pattern="MyApp-v{version}.exe"  # Release 中的 exe 文件名模式
    )

    # 检查更新（返回 None 或新版本号）
    new_ver = updater.check_update()

    # 如果有更新，下载并安装
    if new_ver:
        if updater.download_and_update(new_ver):
            # 需要重启应用
            import os, sys
            os.execv(sys.executable, sys.argv)
"""

import os
import sys
import json
import shutil
import threading
import tempfile
import zipfile
import subprocess
import hashlib
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from datetime import datetime


class UpdateIntegrityError(Exception):
    """更新完整性校验失败（无校验和 / 校验和不匹配 / 域名不在白名单）。

    fail-closed 策略: 宁可拒绝更新, 也不用未校验的二进制覆盖自身。
    """


def parse_checksums(text, wanted=None):
    """解析 Release 附带的 SHA256 校验文件。

    支持三种格式:
      - sha256sum 风格: "<64位hex>  <文件名>"(可多行)
      - 纯 hex(整个文件只有一个校验值, 无名)
      - JSON: {"文件名": "hex", ...}
    返回 {文件名: hex}; 纯 hex 格式返回 {"*": hex}。
    wanted 非空且存在具名条目时, 只保留该文件名的条目。
    """
    if not text or not text.strip():
        return {}
    text = text.strip()
    # JSON 优先
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            out = {str(k): str(v).strip().lower() for k, v in data.items()}
            if wanted:
                return {k: v for k, v in out.items() if k == wanted}
            return out
    except (ValueError, TypeError):
        pass
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        digest = parts[0].strip().lower()
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            continue
        if len(parts) == 1:
            result['*'] = digest
        else:
            name = parts[1].strip().lstrip('*').strip()
            if name:
                result[name] = digest
    if wanted and '*' not in result:
        return {k: v for k, v in result.items() if k == wanted}
    return result


def sha256_file(path):
    """计算文件的 SHA256 十六进制摘要"""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class AutoUpdater:
    """基于 Gitee Release 的自动更新器"""

    def __init__(self, app_name, current_version, gitee_owner, gitee_repo,
                 exe_pattern=None, check_on_start=True, silent=True,
                 require_checksum=True):
        """
        参数:
            app_name: 应用名称（用于日志和标题）
            current_version: 当前版本号 (如 "1.0.0")
            gitee_owner: Gitee 用户名
            gitee_repo: Gitee 仓库名
            exe_pattern: Release 中 exe 的文件名模式，{version} 会被替换为版本号
                         如果为 None，自动从 Release assets 中查找 .exe 文件
            check_on_start: 是否在构造时自动检查更新
            silent: 静默模式（不弹窗提示，仅返回结果）
        """
        self.app_name = app_name
        self.current_version = self._parse_version(current_version)
        self.current_version_str = current_version
        self.gitee_owner = gitee_owner
        self.gitee_repo = gitee_repo
        self.exe_pattern = exe_pattern
        self.silent = silent
        # 安全策略：默认强制 SHA256 校验（fail-closed），仅调试时可显式关闭
        self.require_checksum = require_checksum
        self._verified_digest = None

        # 本地更新状态文件
        self.state_file = os.path.join(
            os.environ.get('APPDATA', os.path.expanduser('~')),
            app_name, 'update_state.json'
        )

        self._latest_release = None
        self._latest_version = None
        self._download_dir = None

        if check_on_start:
            self.check_update()

    @staticmethod
    def _parse_version(v):
        """解析版本号为元组，方便比较"""
        return tuple(int(x) for x in v.replace('v', '').split('.')[:3])

    # 下载域名白名单：只允许 gitee.com 及其子域（防 DNS 劫持/中间人）
    ALLOWED_DOWNLOAD_HOSTS = ("gitee.com",)

    @staticmethod
    def _user_agent(name):
        """ASCII 安全的 User-Agent。

        urllib 以 latin-1 编码 HTTP 头, 中文 app_name 曾让每次请求直接抛异常。
        非 latin-1 可编码字符按 UTF-8 percent-encode, 保证头始终合法。
        """
        out = []
        for ch in str(name):
            try:
                ch.encode('latin-1')
                out.append(ch)
            except UnicodeEncodeError:
                out.extend(f"%{b:02X}" for b in ch.encode('utf-8'))
        return f"{''.join(out)}-AutoUpdater/2.0"

    def _check_host(self, url):
        """校验 URL 主机在下载白名单内（精确或子域匹配），否则拒绝。

        返回 True；不在白名单时抛 UpdateIntegrityError（fail-closed）。
        """
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        for allowed in self.ALLOWED_DOWNLOAD_HOSTS:
            if host == allowed or host.endswith("." + allowed):
                return True
        raise UpdateIntegrityError(f"拒绝非白名单下载地址: {host or '(无主机名)'}")

    def _open(self, url, timeout=15):
        """打开 URL 前校验白名单；跟随重定向后对最终地址二次校验。"""
        self._check_host(url)
        resp = urllib.request.urlopen(url, timeout=timeout)
        final = resp.geturl()
        if final and final != url:
            self._check_host(final)
        return resp

    @staticmethod
    def verify_file(path, expected):
        """校验文件 SHA256；不匹配/缺期望值一律抛 UpdateIntegrityError。成功返回摘要。"""
        expected = (expected or "").strip().lower()
        if not expected:
            raise UpdateIntegrityError("缺少期望的 SHA256 校验值, 拒绝安装未校验的更新")
        actual = sha256_file(path)
        if actual != expected:
            raise UpdateIntegrityError(f"SHA256 不匹配: 期望 {expected}, 实际 {actual}")
        return actual

    def get_checksum_url(self):
        """从最新 Release assets 里找校验和文件, 返回 (name, url) 或 (None, None)。"""
        if not self._latest_release:
            return None, None
        names = ('.sha256', '.sha256sums', '.sha256sum')
        for a in self._latest_release.get('assets', []):
            name = (a.get('name') or '')
            low = name.lower()
            if low.endswith(names) or low in ('sha256sums', 'checksums.txt', 'sha256.txt'):
                return name, a.get('browser_download_url')
        return None, None

    def _expected_digest(self, asset_name):
        """下载并解析 Release 的 SHA256 校验文件, 返回该 exe 的期望摘要(没有则 None)。"""
        name, url = self.get_checksum_url()
        if not url:
            return None
        try:
            with self._open(url, timeout=20) as resp:
                text = resp.read().decode('utf-8', 'replace')
            table = parse_checksums(text, wanted=asset_name)
            if '*' in table:
                return table['*']
            return table.get(asset_name)
        except UpdateIntegrityError:
            raise
        except Exception as e:
            print(f"[AutoUpdater] 获取校验值失败: {e}")
            return None

    @property
    def api_url(self):
        return f"https://gitee.com/api/v5/repos/{self.gitee_owner}/{self.gitee_repo}/releases/latest"

    def check_update(self, force=False):
        """
        检查是否有新版本
        返回: 新版本号字符串，无更新返回 None
        """
        try:
            # 节流：24 小时内不重复检查（除非 force）
            if not force:
                last_check = self._get_state('last_check')
                if last_check:
                    last_dt = datetime.fromisoformat(last_check)
                    if (datetime.now() - last_dt).total_seconds() < 86400:
                        cached = self._get_state('latest_version')
                        if cached and self._parse_version(cached) > self.current_version:
                            return cached
                        return None

            req = urllib.request.Request(
                self.api_url,
                headers={'User-Agent': self._user_agent(self.app_name)}
            )
            with self._open(req, timeout=10) as resp:
                self._latest_release = json.loads(resp.read().decode('utf-8'))

            tag = self._latest_release.get('tag_name', '').replace('v', '')
            if not tag:
                return None

            self._latest_version = tag
            self._set_state('last_check', datetime.now().isoformat())
            self._set_state('latest_version', tag)

            if self._parse_version(tag) > self.current_version:
                return tag
            return None

        except Exception as e:
            print(f"[AutoUpdater] 检查更新失败: {e}")
            return None

    def get_changelog(self):
        """获取最新版本的更新日志"""
        if self._latest_release:
            return self._latest_release.get('body', '')
        return ''

    def get_download_url(self, version=None):
        """
        获取下载链接
        返回: (asset_name, download_url) 或 (None, None)
        """
        if not self._latest_release:
            self.check_update(force=True)
        if not self._latest_release:
            return None, None

        assets = self._latest_release.get('assets', [])
        ver = version or self._latest_version or self.current_version_str

        # 如果指定了 exe_pattern，直接匹配
        if self.exe_pattern:
            target = self.exe_pattern.replace('{version}', ver)
            target = target.replace('{Version}', ver.capitalize() if ver[0].islower() else ver)
            for a in assets:
                if a.get('name', '') == target:
                    return a['name'], a['browser_download_url']

        # 否则找第一个 .exe 文件
        for a in assets:
            name = a.get('name', '')
            if name.lower().endswith('.exe'):
                return a['name'], a['browser_download_url']

        # 最后找任何文件
        for a in assets:
            return a['name'], a['browser_download_url']

        return None, None

    def download_and_update(self, version=None, progress_callback=None):
        """
        下载新版本并准备更新
        返回: True 表示下载成功，准备就绪

        参数:
            version: 目标版本（默认为最新版）
            progress_callback: 进度回调 callback(downloaded_bytes, total_bytes)
        """
        asset_name, download_url = self.get_download_url(version)
        if not download_url:
            print(f"[AutoUpdater] 未找到下载链接")
            return False

        ver = version or self._latest_version or 'unknown'
        self._download_dir = os.path.join(tempfile.gettempdir(), f"{self.app_name}_update_{ver}")
        os.makedirs(self._download_dir, exist_ok=True)

        target_path = os.path.join(self._download_dir, asset_name)
        print(f"[AutoUpdater] 正在下载 {asset_name}...")

        try:
            req = urllib.request.Request(
                download_url,
                headers={'User-Agent': self._user_agent(self.app_name)}
            )
            with self._open(req, timeout=60) as resp:
                total = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 8192

                with open(target_path, 'wb') as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback:
                            progress_callback(downloaded, total)

            print(f"[AutoUpdater] 下载完成: {target_path}")

            # 完整性校验（fail-closed）：取不到校验值或验不过, 就不进入安装
            try:
                expected = self._expected_digest(asset_name)
            except UpdateIntegrityError as e:
                print(f"[AutoUpdater] {e}")
                return False
            if expected:
                try:
                    self._verified_digest = self.verify_file(target_path, expected)
                except UpdateIntegrityError as e:
                    print(f"[AutoUpdater] 校验失败: {e}")
                    return False
            elif self.require_checksum:
                print("[AutoUpdater] 未找到 SHA256 校验值, 已拒绝本次更新(fail-closed)")
                return False
            return True

        except Exception as e:
            print(f"[AutoUpdater] 下载失败: {e}")
            return False

    def apply_update(self, callback=None):
        """
        执行更新（替换当前 exe）
        注意：必须在新进程中执行，因为当前 exe 正在运行

        参数:
            callback: 更新完成后的回调函数路径（字符串）
        """
        if not self._download_dir or not os.path.isdir(self._download_dir):
            print("[AutoUpdater] 没有已下载的更新包")
            return False

        # 找到下载的 exe
        exe_files = list(Path(self._download_dir).glob('*.exe'))
        if not exe_files:
            print("[AutoUpdater] 更新包中未找到 exe 文件")
            return False

        new_exe = str(exe_files[0])
        # 安装前二次校验：下载时验过, 覆盖自身前再确认一次
        if self.require_checksum:
            if not self._verified_digest:
                print("[AutoUpdater] 更新包未通过 SHA256 校验, 拒绝覆盖自身")
                return False
            try:
                self.verify_file(new_exe, self._verified_digest)
            except UpdateIntegrityError as e:
                print(f"[AutoUpdater] 安装前校验失败: {e}")
                return False
        current_exe = sys.executable if getattr(sys, 'frozen', False) else None
        if not current_exe:
            # 开发模式，使用当前脚本
            current_exe = os.path.abspath(sys.argv[0])

        # 生成更新脚本
        start_line = f'start "" "{current_exe}"' if not self.silent else ''
        update_script = f'''@echo off
echo 正在更新 {self.app_name}...
timeout /t 2 /nobreak >nul

:wait_loop
tasklist /fi "imagename eq {os.path.basename(current_exe)}" 2>nul | find /i "{os.path.basename(current_exe)}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_loop
)

copy /y "{new_exe}" "{current_exe}" >nul 2>&1
echo 更新完成！
{start_line}
rmdir /s /q "{self._download_dir}" >nul 2>&1
'''

        script_path = os.path.join(self._download_dir, 'apply_update.bat')
        with open(script_path, 'w', encoding='gbk') as f:
            f.write(update_script)

        # 启动更新脚本并退出当前程序
        subprocess.Popen(
            f'cmd /c "{script_path}"',
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True
        )

        if callback:
            try:
                callback()
            except:
                pass

        return True

    def _get_state(self, key):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    return json.load(f).get(key)
        except:
            pass
        return None

    def _set_state(self, key, value):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            state = {}
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    state = json.load(f)
            state[key] = value
            with open(self.state_file, 'w') as f:
                json.dump(state, f)
        except:
            pass


def check_update_background(app_name, current_version, gitee_owner, gitee_repo,
                            exe_pattern=None, callback=None):
    """
    后台线程检查更新（非阻塞）
    callback(new_version, updater) - 有更新时回调
    """
    def _check():
        try:
            updater = AutoUpdater(
                app_name=app_name,
                current_version=current_version,
                gitee_owner=gitee_owner,
                gitee_repo=gitee_repo,
                exe_pattern=exe_pattern,
                check_on_start=False,
                silent=True
            )
            new_ver = updater.check_update(force=True)
            if new_ver and callback:
                callback(new_ver, updater)
        except Exception as e:
            print(f"[AutoUpdater] 后台检查失败: {e}")

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    return t
