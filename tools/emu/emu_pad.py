"""Runs the stock pad routine (0x08003970) in Unicorn with synthetic ADC values and prints the
events it would put in HID report 2. Usage: emu_pad.py <stock fw.bin> <data_init.bin>"""
import struct, sys
from unicorn import *
from unicorn.arm_const import *
fw=open(sys.argv[1],'rb').read()[:0x9dc8]; data=open(sys.argv[2],'rb').read()
FL=0x08003000; RAM=0x20000000
def run(adc_seq, thr0=0, offsets=None, pads=(0,)):
    mu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    mu.mem_map(0x08000000,0x40000); mu.mem_write(FL,fw)
    mu.mem_map(RAM,0x8000); mu.mem_write(RAM,data)
    mu.mem_map(0x40000000,0x100000)  # peripherals (unused)
    mu.mem_map(0xE0000000,0x100000)
    if offsets: mu.mem_write(0x20000cc8,bytes(offsets))
    if thr0: mu.mem_write(0x2000014a,struct.pack('<H',thr0))
    out=[]
    for t,vals in enumerate(adc_seq):
        for p in range(16):
            mu.mem_write(0x20000758+2*p,struct.pack('<H',vals.get(p,0)))
        for p in range(16):
            a=0x20001028+p*8+0xc; c=mu.mem_read(a,1)[0]
            if c<255: mu.mem_write(a,bytes([c+1]))
        mu.mem_write(0x20001028+0x2ce,b'\0')
        mu.reg_write(UC_ARM_REG_SP,0x20007000)
        mu.reg_write(UC_ARM_REG_LR,0x08000001)
        try: mu.emu_start(0x08003970|1,0x08000000,count=200000)
        except UcError as e:
            if mu.reg_read(UC_ARM_REG_PC)!=0x08000000: print('err',e,hex(mu.reg_read(UC_ARM_REG_PC))); break
        flag=mu.mem_read(0x20001028+0x2ce,1)[0]
        if flag:
            buf=mu.mem_read(0x20001028+0x2ea,63)
            for i in range(0,63,3):
                if buf[i+1] or buf[i+2] or buf[i]: 
                    out.append((t,buf[i],buf[i+1],buf[i+2]))
    return out
if __name__=='__main__':
    import sys
    def show(title,seq,**kw):
        print('==',title)
        for t,pad,b1,b2 in run(seq,**kw):
            typ=b1>>4; val=((b1&0xf)<<8)|b2
            print(f'  t={t:3d} pad={pad:2d} type={typ:#x} value={val}')
    def stretch(curve,n): return [{0:v} for v in curve for _ in range(n)]
    idle=[{} for _ in range(40)]
    show('hard hit (fast rise, peak 3000)', idle+stretch([200,900,2200,3000,2900,2400,1800,1200,600,0],3)+idle)
    show('soft hit (peak 900)', idle+stretch([200,500,800,900,850,600,300,0],3)+idle)
    show('slow press/hold with pressure wobble', idle+stretch([300,500,700,900,1100,1300,1500,1500,1400,1600,1500,900,300,0],10)+idle)
