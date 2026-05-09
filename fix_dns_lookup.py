#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix dns_lookup function in network_reset_gui.py"""

filepath = r'C:\Users\michael\.qclaw\workspace\network-reset-tool\network_reset_gui.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Find start and end of dns_lookup function
start_marker = '    def dns_lookup(self, target, dns_server=None):'
end_marker = '    def traceroute'

if start_marker not in content:
    print('FAILED: start_marker not found')
    exit(1)

start_idx = content.index(start_marker)
end_idx = content.index(end_marker, start_idx)

# The new function body
new_func_body = '''    def dns_lookup(self, target, dns_server=None):
        """DNS 解析测试 - 使用 nslookup 获取 IP 地址"""
        try:
            if dns_server:
                cmd = ['nslookup', target, dns_server]
            else:
                cmd = ['nslookup', target]
            result = subprocess.run(cmd, capture_output=True, text=True,
                                   encoding='gbk', timeout=5)
            output = result.stdout
            # 提取所有 IPv4 地址
            ipv4_addrs = re.findall(r'\\b\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\b', output)
            # nslookup 输出中，第一个 IPv4 是 DNS 服务器自身，后续才是解析结果
            ip = ipv4_addrs[1] if len(ipv4_addrs) > 1 else None
            # 检查是否解析成功
            name_resolved = ("can't find" not in output.lower()
                             and '找不到' not in output
                             and ip is not None)
            return name_resolved, ip, output
        except Exception as e:
            return False, None, str(e)

'''

new_content = content[:start_idx] + new_func_body + content[end_idx:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_content)

print('SUCCESS: dns_lookup function replaced')
print(f'Old function: bytes {start_idx}-{end_idx} (len={end_idx-start_idx})')
