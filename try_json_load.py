import json
p = r"c:\Users\domin\OneDrive\Desktop\python apps\closed captioning\license.json"
try:
    with open(p,'r',encoding='utf-8') as f:
        data = json.load(f)
    print('Loaded OK, keys:', list(data.keys()))
except Exception as e:
    print('JSON load error:', repr(e))
    try:
        with open(p,'r',encoding='utf-8') as f:
            txt = f.read()
            print('\n--- START FILE PREVIEW ---')
            print(txt[:2000])
            print('--- END PREVIEW ---')
    except Exception as e2:
        print('Also failed to read file:', e2)
