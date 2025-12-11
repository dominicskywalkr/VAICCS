p = r"c:\Users\domin\OneDrive\Desktop\python apps\closed captioning\license.json"
with open(p,'rb') as f:
    b = f.read()
print('len', len(b))
start=1400
end=1560
seg = b[start:end]
print(seg)
print('\nREPR:\n')
print(repr(seg.decode('utf-8', errors='replace')))
