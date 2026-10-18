import os, struct, sys
from unicorn import *
from unicorn.arm_const import *
"""Emulation tests for the patched image. Usage: test_patch.py <patched.bin> <data_init.bin>
Needs `pip install unicorn`. data_init.bin comes from tools/decompress_data.py (stock image)."""
FL=0x08003000
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_patch as bp          # the single source of truth for the flash layout
fw=open(sys.argv[1],'rb').read(); data=open(sys.argv[2],'rb').read()
def bl_target(addr):
    o=addr-FL; h1,h2=struct.unpack_from('<HH',fw,o)
    s=(h1>>10)&1; j1=(h2>>13)&1; j2=(h2>>11)&1
    i1=(~(j1^s))&1; i2=(~(j2^s))&1
    off=(s<<24)|(i1<<23)|(i2<<22)|((h1&0x3ff)<<12)|((h2&0x7ff)<<1)
    if s: off-=1<<25
    return addr+4+off
T_TRANS=bl_target(0x08004036); T_INIT=bl_target(0x08008CF8); T_RX=bl_target(0x08004ABA); T_TICK=bl_target(0x08008D06)
print('hooks: translate',hex(T_TRANS),'init',hex(T_INIT),'rx',hex(T_RX),'tick',hex(T_TICK))
def new():
    mu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    mu.mem_map(0x08000000,0x40000); mu.mem_write(FL,fw)
    mu.mem_map(0x20000000,0x5000); mu.mem_write(0x20000000,data)
    mu.mem_map(0x40000000,0x100000); mu.mem_map(0xE0000000,0x100000)
    return mu
def run(mu,pc,r0=0,r1=0,stubs=()):
    hits=[]
    def hk(uc,addr,size,ud):
        hits.append(addr); uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR)&~1|1) if False else None
    for a in stubs:
        mu.hook_add(UC_HOOK_CODE,lambda uc,addr,sz,ud: (hits.append(addr),uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR)|1)) ,begin=a&~1,end=(a&~1)+1)
    mu.reg_write(UC_ARM_REG_R0,r0); mu.reg_write(UC_ARM_REG_R1,r1)
    mu.reg_write(UC_ARM_REG_SP,0x20004000); mu.reg_write(UC_ARM_REG_LR,0x08000001)
    try: mu.emu_start(pc|1,0x08000000,count=300000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC)!=0x08000000: raise
    return hits,mu.reg_read(UC_ARM_REG_R0)
ok=True
def check(name,cond,detail=''):
    global ok; ok&=bool(cond); print(('PASS ' if cond else 'FAIL ')+name+('' if cond else '  '+str(detail)))

# 1. descriptors parse
dev=fw[bp.DESC_DEV_ADDR-FL:bp.DESC_DEV_ADDR-FL+18]; cfg=fw[bp.DESC_CFG_ADDR-FL:bp.DESC_CFG_ADDR-FL+119]
check('device descriptor 18 B, class 0, EP0=64',dev[0]==18 and dev[1]==1 and dev[4]==0 and dev[7]==64)
total=struct.unpack_from('<H',cfg,2)[0]; check('config wTotalLength==119==len',total==119==len(cfg))
i=0; ifaces=[]; eps=[]; types=[]
while i<len(cfg):
    l,t=cfg[i],cfg[i+1]; assert l>0
    if t==4: ifaces.append((cfg[i+2],cfg[i+5],cfg[i+6],cfg[i+4]))
    if t==5: eps.append((cfg[i+2],cfg[i+3],struct.unpack_from('<H',cfg,i+4)[0]))
    types.append(t); i+=l
check('descriptors chain exactly to end',i==len(cfg))
check('interfaces 0 AC(1/1) 1 MS(1/3) 2 DFU(fe)',[(a,b,c) for a,b,c,_ in ifaces]==[(0,1,1),(1,1,3),(2,0xfe,1)])
check('endpoints: 0x01 bulk64 OUT, 0x81 bulk64 IN',eps==[(0x01,2,64),(0x81,2,64)])
ms_hdr=cfg.index(bytes([7,0x24,1,0,1])); mslen=struct.unpack_from('<H',cfg,ms_hdr+5)[0]
end_ms=ms_hdr+mslen; check('MS class-specific length covers through last CS endpoint',cfg[end_ms:end_ms+2]==bytes([9,4]))

# 1b. independent parse with the usb-protocol library (skipped when it is not installed)
try:
    from usb_protocol.types.descriptors import standard as _S, midi1 as _M
    d=_S.DeviceDescriptor.parse(dev)
    check('usb-protocol parses the device descriptor (USB 2.0, VID 17cc, PID 1700, bcd 0.51 for recovery)',d.bcdUSB==2.0 and d.idVendor==0x17cc and d.idProduct==0x1700 and d.bcdDevice==0.51 or d.bcdDevice==0x51,(d.bcdUSB,hex(d.idVendor),hex(d.idProduct),d.bcdDevice))
    i=0; n_if=n_ep=0
    while i<len(cfg):
        seg=cfg[i:i+cfg[i]]
        if seg[1]==4: _S.InterfaceDescriptor.parse(seg); n_if+=1
        elif seg[1]==5: _S.EndpointDescriptor.parse(seg); n_ep+=1
        i+=cfg[i]
    check('usb-protocol parses every interface and endpoint descriptor (3 interfaces, 2 endpoints)',n_if==3 and n_ep==2,(n_if,n_ep))
except ImportError:
    print('SKIP usb-protocol not installed')

# 1c. the seven hook sites call into the new code (which is last in the image), the rest of the original image is untouched
IMG_END=FL+len(fw)
for site,name in ((0x08004036,'translate'),(0x08008CF8,'init'),(0x08008CFC,'boot2'),(0x08004ABA,'rx'),(0x08008D06,'tick')):
    t=bl_target(site); check(f'hook {name} at {site:#x}: bl into the new code at {t:#x}',bp.CODE_ADDR<=t<IMG_END)
# (that the tick hook calls the stock watchdog kick it replaces is checked in test_features.py)

# 2. init hook repoints table, calls original init
mu=new(); hits,_=run(mu,T_INIT,stubs=(0x08007EA3,))
tab=struct.unpack('<4I',mu.mem_read(0x20000080,16))
check('init: table -> new descriptors',tab==(bp.DESC_DEV_ADDR,18,bp.DESC_CFG_ADDR,119))
check('init: original init called',0x08007EA2 in hits)

# 3. rx hook
STRUCT=0x20001028
def rx_session():
    mu=new(); run(mu,T_INIT,stubs=(0x08007EA3,))          # boot hook zeroes translator state
    return mu
def rx(mu,pkt,led_fill=0x55):
    mu.mem_write(0x200001d8,pkt); mu.mem_write(0x20000074,bytes([len(pkt)]))
    mu.mem_write(STRUCT+0x2cf,b'\0'); mu.mem_write(0x20001351,bytes([led_fill]*80))
    hits,_=run(mu,T_RX,stubs=(0x08008799,))
    return 0x08008798 in hits, bytes(mu.mem_read(0x20001351,80)), mu.mem_read(STRUCT+0x2cf,1)[0]
mu=rx_session()
orig,led,flag=rx(mu,bytes([0x09,0x91,5,0x7f, 0x09,0x91,7,0x20, 0x08,0x81,7,0]))
check('rx: MIDI not passed to stock parser',not orig)
check('rx: LED channel: note5 vel127 -> LED5=127, note7 on then off -> 0, others skipped (0xff), flag set',led[5]==127 and led[7]==0 and led[0]==0xff and led[79]==0xff and flag==1)
PAD4_NOTE=fw[0x0800CE00-FL+5+15]          # cfg.pad_note[15]: pad 4 (report index 15)
orig,led,flag=rx(mu,bytes([0x09,0x90,PAD4_NOTE,0x40]))
check('rx: main channel note of pad 4 (report index 15) -> LED 54',led[54]==0x40 and led[39]==0xff and flag==1)
orig,led,flag=rx(mu,bytes([0x0b,0xb0,58,127]))
check('rx: CC58 (Rec, button id 23) value 127 -> LED 23 bright (0x7f)',led[23]==0x7f and led[0]==0xff and flag==1)
orig,led,flag=rx(mu,bytes([0x0b,0xb0,58,0]))
check('rx: CC58 value 0 -> LED 23 off',led[23]==0 and flag==1)
orig,led,flag=rx(mu,bytes([0x0b,0xb0,58,40, 0x0b,0xb0,44,80]))
check('rx: CC value ranges -> dim 0x7c / normal 0x7e',led[23]==0x7c and led[3]==0x7e)
orig,led,flag=rx(mu,bytes([0x0b,0xb0,57,127]))
check('rx: CC57 no longer lights Play (Play is MIDI Start now, it has no CC to match)',flag==0 and led[22]==0x55)
orig,led,flag=rx(mu,bytes([0x09,0x90,100,0x40]))
check('rx: main channel unmapped note ignored',flag==0 and led[0]==0x55)
orig,led,flag=rx(mu,bytes([0x80]+[0]*63))
check('rx: NI report (0x80...) goes to stock parser untouched',orig and flag==0 and led[0]==0x55)
orig,led,flag=rx(mu,bytes([0x0b,0xb0,1,2]))
check('rx: unmapped CC ignored, no LED change',not orig and flag==0 and led[0]==0x55)

# 3b. SysEx: display region + LED frame
def pack7(data):
    out=bytearray()
    for i in range(0,len(data),7):
        g=data[i:i+7]; out.append(sum(((v>>7)&1)<<k for k,v in enumerate(g)))
        out+=bytes(v&0x7f for v in g)
    return bytes(out)
def usb_packets(msg):
    pk=[]; i=0
    while len(msg)-i>3: pk.append(bytes([4])+msg[i:i+3]); i+=3
    rest=msg[i:]; pk.append(bytes([{1:5,2:6,3:7}[len(rest)]])+rest+bytes(3-len(rest)))
    return b''.join(pk)
def send(mu,msg):
    raw=usb_packets(msg)
    for o in range(0,len(raw),64): rx(mu,raw[o:o+64]+b'')   # 64-byte OUT transfers (multiple of 4)
import random
random.seed(1)
mu=rx_session()
pix=bytes(random.randrange(256) for _ in range(256))
mu.mem_write(0x200013A1,bytes(8)); mu.mem_write(0x200013A9,bytes(256))
send(mu,bytes([0xF0,0x7D,0x4D,0x4B,1, 0,0,127,1])+pack7(pix)+bytes([0xF7]))
hdr=bytes(mu.mem_read(0x200013A1,8)); data=bytes(mu.mem_read(0x200013A9,256)); dflag=mu.mem_read(STRUCT+0x2d0,1)[0]
check('sysex display: header x=0 page=0 w=128 h=2, flag set',hdr==bytes([0,0,0,0,128,0,2,0]) and dflag==1)
check('sysex display: 256 pixel bytes round-trip through 7-bit packing (message spans several USB transfers)',data==pix)
mu.mem_write(STRUCT+0x2d0,b'\0'); mu.mem_write(0x200013A1,bytes(8))
send(mu,bytes([0xF0,0x7D,0x4D,0x4B,1, 120,3,15,0])+pack7(bytes(range(16)))+bytes([0xF7]))
check('sysex display: x+w>128 rejected',mu.mem_read(STRUCT+0x2d0,1)[0]==0)
send(mu,bytes([0xF0,0x7D,0x4D,0x4B,1, 10,2,3,1])+pack7(bytes(range(8)))+bytes([0xF7]))
check('sysex display: small region accepted (x=10 page=2 w=4 h=2)',bytes(mu.mem_read(0x200013A1,8))==bytes([10,0,2,0,4,0,2,0]) and mu.mem_read(STRUCT+0x2d0,1)[0]==1 and bytes(mu.mem_read(0x200013A9,8))==bytes(range(8)))
mu.mem_write(STRUCT+0x2d0,b'\x01')
send(mu,bytes([0xF0,0x7D,0x4D,0x4B,1, 0,0,0,0, 0,0,0xF7][:9])+pack7(b'\xaa')+bytes([0xF7]))
check('sysex display: dropped while previous region still pending',bytes(mu.mem_read(0x200013A9,1))==bytes([0]) and mu.mem_read(STRUCT+0x2d0,1)[0]==1)
frame=bytes((i*3)&0x7f for i in range(80))
mu=rx_session()
orig,led,flag=rx(mu,usb_packets(bytes([0xF0,0x7D,0x4D,0x4B,2])+frame+bytes([0xF7])))
check('sysex LED frame: 80 values copied, flag set',led==frame and flag==1)
send(mu,bytes([0xF0,0x01,0x02,0xF7])); send(mu,bytes([0xF0,0x7D,0x4D,0x4B]))
check('sysex: foreign / truncated messages ignored',True)
import os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import mmk3_host
bm=mmk3_host.border_bitmap(); msgs=mmk3_host.bitmap_to_messages(bm)
mu=rx_session(); got=bytearray()
for m in msgs:
    mu.mem_write(STRUCT+0x2d0,b'\0'); send(mu,m)
    got+=bytes(mu.mem_read(0x200013A9,256)); assert mu.mem_read(STRUCT+0x2d0,1)[0]==1
want=bytearray()
for page in range(4):
    for x in range(128): want.append(sum((0 if bm[page*8+b][x] else 1)<<b for b in range(8)))
check('host helper: border bitmap survives encode -> USB-MIDI -> firmware decode for both halves',bytes(got)==bytes(want))

# 3c. late boot hook: optional sensitivity / boot-delay overrides from the config block
T_BOOT2=bl_target(0x08008CFC)
def boot2(sens,boot_ms):
    mu=new(); CFGA=0x0800CE00-FL
    # cfg layout: sens at +91, boot_ms at +93 (see struct cfg)
    mu.mem_write(0x0800CE00+91,bytes([sens])); mu.mem_write(0x0800CE00+93,struct.pack('<H',boot_ms))
    mu.mem_write(STRUCT+0x5e1,bytes([80])); mu.mem_write(STRUCT+2,struct.pack('<H',6000)); mu.mem_write(0x2000014a,b'\x78\x00')
    hits,_=run(mu,T_BOOT2,stubs=(0x08008BAD,0x080046B9))
    return hits,mu.mem_read(STRUCT+0x5e1,1)[0],struct.unpack('<H',mu.mem_read(STRUCT+2,2))[0]
hits,sv,bm=boot2(0xFF,0xFFFF)
check('boot2 default: stock stage-2 init runs, sensitivity and boot delay untouched',0x08008BAC in hits and 0x080046B8 not in hits and sv==80 and bm==6000,(hits,sv,bm))
hits,sv,bm=boot2(50,500)
check('boot2 override: sensitivity 50 stored and threshold recomputed via the stock routine; boot delay 500 ms',0x080046B8 in hits and sv==50 and bm==500,(hits,sv,bm))

# 4. interface setting patch (stock fn at 0x08008458: r0=interface, r1=alt)
for ifc,alt,exp in [(0,0,0),(1,0,0),(2,0,0),(3,0,2),(0,1,2)]:
    mu=new(); _,r=run(mu,0x08008458,ifc,alt); check(f'get_interface_setting(iface={ifc},alt={alt}) -> {exp}',r==exp)

# 5. USB reset programs EP1 as bulk (SetEPType arg recorded)
mu=new(); calls=[]
def hk(uc,addr,sz,ud):
    calls.append((uc.reg_read(UC_ARM_REG_R0),uc.reg_read(UC_ARM_REG_R1)))
    uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR)|1)
mu.hook_add(UC_HOOK_CODE,hk,begin=0x08007a54,end=0x08007a55)
for a in (0x08007900,0x0800795c,0x080079ec,0x0800797c,0x080079c0,0x08007a0c,0x08007a28,0x080038b4):
    mu.hook_add(UC_HOOK_CODE,lambda uc,addr,sz,ud: uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR)|1),begin=a,end=a+1)
mu.mem_write(0x20000060,struct.pack('<I',0x20000200))
try: run(mu,0x080084d0)
except Exception as e: print('reset run:',e)
check('reset: SetEPType calls = EP0 control(0x200), EP1 bulk(0x000)',calls==[(0,0x200),(1,0x000)])
print('ALL PASS' if ok else 'SOME FAILED')
