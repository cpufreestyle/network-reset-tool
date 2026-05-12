fname = r'D:\qclaw-workspace\network-reset-tool\network_reset_gui.py'
with open(fname, 'rb') as f:
    data = bytearray(f.read())

# 找 sparkle (UTF-8 ✨) 的实际字节
# ✨ in UTF-8: E2 9C A8
sparkle_utf8 = b'\xe2\x9c\xa8'
pos = data.find(sparkle_utf8)
print('Sparkle position:', pos)
if pos >= 0:
    print('Context:', data[pos-20:pos+30])
