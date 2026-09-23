import zipfile
zf = zipfile.ZipFile('windows/launcher_go/safeer-os-windows.zip')
names = zf.namelist()
print('skupaj vnosov:', len(names))
tops = sorted(set(n.split('/')[0] for n in names))
print('vrhnje mape/datoteke v zipu:', tops)
for pref in ['core/', 'windows/', 'assets/']:
    print(pref, sum(1 for n in names if n.startswith(pref)))
