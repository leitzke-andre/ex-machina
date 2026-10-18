import sys, math, struct, collections
def ent(b):
    if not b: return 0
    c=collections.Counter(b); n=len(b)
    return -sum(v/n*math.log2(v/n) for v in c.values())
for path in sys.argv[1:]:
    d=open(path,'rb').read()
    print('==',path,len(d))
    blk=256*1024
    print(' entropy/256K:',' '.join(f'{ent(d[i:i+blk]):.2f}' for i in range(0,len(d),blk)))
    # Cortex-M vector table candidates: SP in SRAM, reset odd in flash-ish, several handlers odd & near
    hits=[]
    for i in range(0,len(d)-64,4):
        w=struct.unpack_from('<8I',d,i)
        sp,rst=w[0],w[1]
        if 0x20000000<=sp<=0x20100000 and sp%4==0 and rst&1 and all((x&1) and 0x08000000<=x<0x08200000 or 0x00000000<x<0x00200000 for x in w[1:4]):
            hits.append((i,hex(sp),[hex(x) for x in w[1:4]]))
    print(' vector-table candidates:',len(hits)); [print('  ',h) for h in hits[:10]]
    for sig in [b'PK\x03\x04',b'\x1f\x8b',b'7z\xbc\xaf',b'DfuSe',b'UFD',b'\x89PNG',b'Rar!',b'BZh',b'\xfd7zXZ',b'\x5d\x00\x00']:
        n=d.count(sig); 
        if n: print(' sig',sig,n, [hex(i) for i in ( __import__('re').finditer(__import__('re').escape(sig),d) and [m.start() for m in __import__('re').finditer(__import__('re').escape(sig),d)][:5])])
