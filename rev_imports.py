'''逆向第1步:WXWork.exe / WXWorkResources.dll 导入表分析(找 UIA/MSAA Provider API)'''
import pefile

FILES = [
    r'C:\Program Files (x86)\WXWork\WXWork.exe',
    r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkResources.dll',
    r'C:\Program Files (x86)\WXWork\5.0.9.6029\WXWorkStrings.dll',
]

INTEREST_DLLS = {'uiautomationcore.dll', 'oleacc.dll', 'oleaut32.dll', 'user32.dll', 'msimg32.dll', 'atl.dll', 'mfc*.dll'}

for path in FILES:
    print(f'\n===== {path} =====')
    pe = pefile.PE(path, fast_load=True)
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_BOUND_IMPORT'],
    ])
    machine = pe.FILE_HEADER.Machine
    print(f'Machine: {"x86(32bit)" if machine == 0x14c else "x64" if machine == 0x8664 else hex(machine)}')
    try:
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            dll = entry.dll.decode().lower()
            marked = any((dll == d if '*' not in d else dll.startswith(d.replace('*', ''))) for d in INTEREST_DLLS)
            if marked or 'uia' in dll or 'access' in dll or 'oleacc' in dll:
                funcs = [imp.name.decode() if imp.name else f'ord{imp.ordinal}' for imp in entry.imports]
                print(f'  {dll}: {len(funcs)} 函数')
                for f in funcs:
                    print(f'    - {f}')
    except AttributeError:
        print('  无导入表')
    # 全部 DLL 列表(简)
    try:
        dlls = [e.dll.decode() for e in pe.DIRECTORY_ENTRY_IMPORT]
        print(f'  全部导入 DLL({len(dlls)}): {", ".join(sorted(set(d.lower() for d in dlls)))}')
    except AttributeError:
        pass
    pe.close()
