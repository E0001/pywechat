'''逆向第3步:dump WXWorkResources.dll 的 CSS/JS 资源,识别 Web 界面组成'''
import os

import pefile

PATH = r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkResources.dll'
OUT = r'D:\VibeCoding\pywechat\debug_shots\wxwork_webres'
os.makedirs(OUT, exist_ok=True)

pe = pefile.PE(PATH, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])

count = 0
for e in pe.DIRECTORY_ENTRY_RESOURCE.entries:
    name = str(e.name or pefile.RESOURCE_TYPE.get(e.id, e.id))
    if name not in ('CSS', 'JS', 'DATA'):
        continue
    for sub in e.directory.entries:
        for item in sub.directory.entries:
            data = pe.get_data(item.data.struct.OffsetToData, item.data.struct.Size)
            res_name = str(sub.name or sub.id)
            count += 1
            fname = f'{name}_{res_name}'.replace('\\', '_').replace('/', '_')[:80]
            path = os.path.join(OUT, fname[:60] + '.txt')
            with open(path, 'wb') as f:
                f.write(data)
            head = data[:200].decode('utf-8', errors='replace').replace('\n', ' ')[:120]
            print(f'{fname[:55]:57} {len(data):8d}B  {head}')
print(f'\n共 {count} 项 → {OUT}')
