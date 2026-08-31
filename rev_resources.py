'''逆向第2步:枚举 WXWorkResources.dll 资源段,找 duilib 布局 XML(RCDATA)'''
import pefile

PATH = r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkResources.dll'
pe = pefile.PE(PATH, fast_load=True)
pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])


def stats(entries):
    st = [0, 0]  # count, total
    for x in entries:
        if hasattr(x, 'directory'):
            sub = stats(x.directory.entries)
            st[0] += sub[0]
            st[1] += sub[1]
        else:
            st[0] += 1
            st[1] += x.data.struct.Size
    return st


rt = pe.DIRECTORY_ENTRY_RESOURCE.entries
print('顶层资源类型:')
for e in rt:
    name = e.name or pefile.RESOURCE_TYPE.get(e.id, e.id)
    count, total = stats(e.directory.entries)
    print(f'  {name}: {count} 项, 共 {total/1048576:.1f}MB')
