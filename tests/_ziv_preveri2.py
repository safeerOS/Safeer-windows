import zipfile
zf = zipfile.ZipFile('windows/launcher_go/safeer-os-windows.zip')
lh = zf.read('core/link_hub.py').decode('utf-8', 'replace')
cb = zf.read('windows/safeer_windows/control_backend.py').decode('utf-8', 'replace')
oa = zf.read('windows/safeer_windows/os_app.py').decode('utf-8', 'replace')
print('link_hub ima povezi:', 'def povezi(' in lh, 'poveži:', 'def poveži(' in lh)
print('control_backend ima p.povezi():', 'p.povezi()' in cb, 'p.zacni():', 'p.zacni()' in cb)
print('os_app pravilen ok_js:', 'ok_js = "true" if ok else "false"' in oa, 'napacen inline true/false:', '{true if ok else false}' in oa)
