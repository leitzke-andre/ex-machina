import struct
from unicorn import *
from unicorn.arm_const import *
"""Runs the stock LED command (0x08005490) and prints which LED-matrix bytes (RAM 0x20000f06...) it changes.
Usage: emu_led.py <stock fw.bin> <data_init.bin>"""
import sys
fw=open(sys.argv[1],'rb').read()[:0x9dc8]; data=open(sys.argv[2],'rb').read()
def setled(idx,code):
    mu=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
    mu.mem_map(0x08000000,0x40000); mu.mem_write(0x08003000,fw)
    mu.mem_map(0x20000000,0x5000); mu.mem_write(0x20000000,data); mu.mem_map(0x40000000,0x100000)
    before=bytes(mu.mem_read(0x20000e1c+0xea,0x120))
    mu.reg_write(UC_ARM_REG_R0,idx); mu.reg_write(UC_ARM_REG_R1,code)
    mu.reg_write(UC_ARM_REG_SP,0x20004000); mu.reg_write(UC_ARM_REG_LR,0x08000001)
    try: mu.emu_start(0x08005491,0x08000000,count=200000)
    except UcError:
        if mu.reg_read(UC_ARM_REG_PC)!=0x08000000: raise
    after=bytes(mu.mem_read(0x20000e1c+0xea,0x120))
    return {i:after[i] for i in range(0x120) if after[i]!=before[i]}
for idx,code,name in [(0,0x06,'button LED 0 code 6 (colour 1 var 2)'),(0,0x07,'button LED 0 code 7'),(39,(1<<2)|2,'pad 0 red var2'),(39,(9<<2)|3,'pad 0 cyan(9) var3'),(39,(16<<2)|2,'pad 0 fuchsia(16) var2'),(39,(17<<2)|2,'pad 0 code>=68 white'),(39,0,'pad 0 off'),(55,(6<<2)|2,'strip seg 0 yellow? (colour 6) var2'),(79,(11<<2)|2,'strip seg 24 colour 11'),(3,(1<<2)|2,'button LED 3 (2 channels)')]:
    print(f'{name:45s} ->',setled(idx,code))
