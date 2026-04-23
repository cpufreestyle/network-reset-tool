@echo off
set TCL_LIBRARY=C:\Program Files\Python311\tcl\tcl8.6
set TK_LIBRARY=C:\Program Files\Python311\tcl\tk8.6
cd /d C:\Users\michael\.qclaw\workspace\network-reset-tool
"C:\Program Files\Python311\python.exe" -m PyInstaller --onefile --noconfirm --name NetworkReset network_reset_gui.py
