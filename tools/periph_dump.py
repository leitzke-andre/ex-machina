#!/usr/bin/env python3
"""Reads how the running firmware has set up the chip's peripherals, with the read-only PEEK diagnostic (firmware from 2026-10-19 on, which
whitelists the configuration registers; docs/clean-firmware-plan.md, stage 1), and prints it decoded: clocks, enabled peripherals, the mode
of every GPIO pin, the debug-port setting, ADC sequence and timing, DMA channels, timers, SPI, I2C, the enabled interrupts, SysTick, USB.
Nothing is written to the device.

    periph_dump.py [--json out.json]     (needs mido + python-rtmidi; the device on this computer, no other MIDI program using SysEx)"""
import json, os, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'midi_patch'))
import mmk3_config as mc

BLOCKS = {   # name: (base, bytes)
    'RCC': (0x40021000, 0x28), 'AFIO': (0x40010000, 0x20), 'EXTI': (0x40010400, 0x18),
    'GPIOA': (0x40010800, 0x1C), 'GPIOB': (0x40010C00, 0x1C), 'GPIOC': (0x40011000, 0x1C), 'GPIOD': (0x40011400, 0x1C), 'GPIOE': (0x40011800, 0x1C),
    'ADC1': (0x40012400, 0x4C), 'ADC2': (0x40012800, 0x4C), 'DMA1': (0x40020000, 0x90),
    'TIM1': (0x40012C00, 0x4C), 'TIM2': (0x40000000, 0x4C), 'TIM3': (0x40000400, 0x4C), 'TIM4': (0x40000800, 0x4C),
    'SPI1': (0x40013000, 0x0C), 'SPI2': (0x40003800, 0x0C), 'I2C1': (0x40005400, 0x10), 'I2C2': (0x40005800, 0x10),
    'IWDG': (0x40003000, 0x10), 'PWR': (0x40007000, 0x08), 'BKP': (0x40006C00, 0x2C), 'USB': (0x40005C00, 0x54),
    'SysTick': (0xE000E010, 0x10), 'NVIC_ISER': (0xE000E100, 0x20), 'NVIC_IPR': (0xE000E400, 0x40), 'SCB': (0xE000ED00, 0x40),
}
IRQ = ['WWDG', 'PVD', 'TAMPER', 'RTC', 'FLASH', 'RCC', 'EXTI0', 'EXTI1', 'EXTI2', 'EXTI3', 'EXTI4', 'DMA1_Ch1', 'DMA1_Ch2', 'DMA1_Ch3', 'DMA1_Ch4',
       'DMA1_Ch5', 'DMA1_Ch6', 'DMA1_Ch7', 'ADC1_2', 'USB_HP_CAN_TX', 'USB_LP_CAN_RX0', 'CAN_RX1', 'CAN_SCE', 'EXTI9_5', 'TIM1_BRK', 'TIM1_UP',
       'TIM1_TRG_COM', 'TIM1_CC', 'TIM2', 'TIM3', 'TIM4', 'I2C1_EV', 'I2C1_ER', 'I2C2_EV', 'I2C2_ER', 'SPI1', 'SPI2', 'USART1', 'USART2', 'USART3',
       'EXTI15_10', 'RTC_Alarm', 'USBWakeup']
APB2 = {0: 'AFIO', 2: 'GPIOA', 3: 'GPIOB', 4: 'GPIOC', 5: 'GPIOD', 6: 'GPIOE', 9: 'ADC1', 10: 'ADC2', 11: 'TIM1', 12: 'SPI1', 14: 'USART1'}
APB1 = {0: 'TIM2', 1: 'TIM3', 2: 'TIM4', 11: 'WWDG', 14: 'SPI2', 17: 'USART2', 18: 'USART3', 21: 'I2C1', 22: 'I2C2', 23: 'USB', 25: 'CAN', 27: 'BKP', 28: 'PWR'}
AHB = {0: 'DMA1', 2: 'SRAM', 4: 'FLITF', 6: 'CRC'}

def read_all(d):
    out = {}
    for name, (base, n) in BLOCKS.items():
        b = b''
        while len(b) < n: b += d.peek(base + len(b), min(64, n - len(b)))
        out[name] = list(struct.unpack(f'<{n // 4}I', b))
    return out

def pin_mode(cnf_mode, odr_bit):
    mode, cnf = cnf_mode & 3, cnf_mode >> 2
    if mode == 0: return ['analog', 'input floating', 'input pull-' + ('up' if odr_bit else 'down'), 'input (reserved)'][cnf]
    speed = {1: '10MHz', 2: '2MHz', 3: '50MHz'}[mode]
    return ['output push-pull', 'output open-drain', 'AF push-pull', 'AF open-drain'][cnf] + ' ' + speed

def show(r):
    rcc = r['RCC']; cfgr = rcc[1]
    sw = ['HSI', 'HSE', 'PLL', '?'][(cfgr >> 2) & 3]
    pllmul = ((cfgr >> 18) & 15) + 2; pllsrc = 'HSE' + ('/2' if cfgr >> 17 & 1 else '') if cfgr >> 16 & 1 else 'HSI/2'
    ahb = [1] * 8 + [2, 4, 8, 16, 64, 128, 256, 512]
    print(f'clocks: SYSCLK from {sw} (PLL = {pllsrc} x {pllmul}), AHB /{ahb[(cfgr >> 4) & 15]}, APB1 /{[1, 1, 1, 1, 2, 4, 8, 16][(cfgr >> 8) & 7]}, '
          f'APB2 /{[1, 1, 1, 1, 2, 4, 8, 16][(cfgr >> 11) & 7]}, ADC /{[2, 4, 6, 8][(cfgr >> 14) & 3]}, USB /{"1" if cfgr >> 22 & 1 else "1.5"}; '
          f'RCC_CR {rcc[0]:#010x} (HSE {"on" if rcc[0] >> 16 & 1 else "off"}, PLL {"on" if rcc[0] >> 24 & 1 else "off"})')
    en = lambda reg, names: ', '.join(v for k, v in names.items() if reg >> k & 1)
    print(f'clock enabled: AHB [{en(rcc[5], AHB)}]  APB2 [{en(rcc[6], APB2)}]  APB1 [{en(rcc[7], APB1)}]')
    mapr = r['AFIO'][1]
    swj = {0: 'full JTAG + SWD', 1: 'JTAG + SWD without NJTRST', 2: 'SWD only (JTAG off)', 4: 'JTAG and SWD OFF'}.get((mapr >> 24) & 7, '?')
    print(f'AFIO_MAPR {mapr:#010x}: debug port = {swj}; remaps: ' + ', '.join(n for b, n in ((0, 'SPI1'), (1, 'I2C1'), (2, 'USART1'), (3, 'USART2'), (8, 'TIM2a'), (9, 'TIM2b'), (11, 'TIM3full'), (10, 'TIM3part'), (12, 'TIM4'), (15, 'PD01')) if mapr >> b & 1) or 'none')
    print(f'AFIO_EXTICR {[hex(x) for x in r["AFIO"][2:6]]}; EXTI IMR {r["EXTI"][0]:#x} EMR {r["EXTI"][1]:#x} RTSR {r["EXTI"][2]:#x} FTSR {r["EXTI"][3]:#x}')
    for port in 'ABCDE':
        crl, crh, idr, odr = r['GPIO' + port][:4]
        if not rcc[6] >> (2 + 'ABCDE'.index(port)) & 1: print(f'GPIO{port}: clock off'); continue
        pins = []
        for p in range(16):
            cm = ((crl if p < 8 else crh) >> (4 * (p & 7))) & 15
            if cm == 4 and not (odr >> p & 1): continue                  # the reset state (input floating) is not listed
            pins.append(f'P{port}{p}={pin_mode(cm, odr >> p & 1)}{"" if (cm & 3) == 0 else " out=" + str(odr >> p & 1)}')
        print(f'GPIO{port} (IDR {idr:#06x} ODR {odr:#06x}): ' + '; '.join(pins))
    for adc in ('ADC1', 'ADC2'):
        a = r[adc]; sr, cr1, cr2, smpr1, smpr2 = a[:5]; sqr1, sqr2, sqr3 = a[11:14]
        if not cr2 & 1: print(f'{adc}: off'); continue
        n = ((sqr1 >> 20) & 15) + 1
        seq = [(sqr3 >> 5 * i) & 31 for i in range(6)] + [(sqr2 >> 5 * i) & 31 for i in range(6)] + [(sqr1 >> 5 * i) & 31 for i in range(4)]
        smp = lambda ch: [1.5, 7.5, 13.5, 28.5, 41.5, 55.5, 71.5, 239.5][((smpr2 >> 3 * ch) if ch < 10 else (smpr1 >> 3 * (ch - 10))) & 7]
        print(f'{adc}: CR1 {cr1:#x} (scan {cr1 >> 8 & 1}), CR2 {cr2:#x} (continuous {cr2 >> 1 & 1}, DMA {cr2 >> 8 & 1}, ext trigger {"on" if cr2 >> 20 & 1 else "off"} sel {(cr2 >> 17) & 7}), '
              f'{n} conversions: ' + ' '.join(f'ch{c}({smp(c)}cyc)' for c in seq[:n]))
    dma = r['DMA1']
    for ch in range(7):
        ccr, cndtr, cpar, cmar = dma[2 + 5 * ch:6 + 5 * ch]
        if ccr & 1 or cpar: print(f'DMA1 ch{ch + 1}: CCR {ccr:#06x} (en {ccr & 1}, dir {"mem->periph" if ccr >> 4 & 1 else "periph->mem"}, circ {ccr >> 5 & 1}, minc {ccr >> 7 & 1}, '
                                  f'psize {8 << (ccr >> 8 & 3)}, msize {8 << (ccr >> 10 & 3)}, prio {ccr >> 12 & 3}), count {cndtr}, periph {cpar:#010x}, mem {cmar:#010x}')
    for t in ('TIM1', 'TIM2', 'TIM3', 'TIM4'):
        v = r[t]; cr1, cr2, smcr, dier = v[:4]; ccmr1, ccmr2, ccer, cnt, psc, arr = v[6:12]
        if cr1 & 1 or psc or arr not in (0, 0xFFFF):
            print(f'{t}: CR1 {cr1:#x} (en {cr1 & 1}), PSC {psc}, ARR {arr}, DIER {dier:#x}, CCMR {ccmr1:#06x}/{ccmr2:#06x}, CCER {ccer:#06x}, CCR {v[13:17]}, SMCR {smcr:#x}, CR2 {cr2:#x}')
    for s in ('SPI1', 'SPI2'):
        cr1, cr2, sr = r[s]
        if cr1: print(f'{s}: CR1 {cr1:#06x} (enabled {cr1 >> 6 & 1}, master {cr1 >> 2 & 1}, clock /{2 << ((cr1 >> 3) & 7)}, CPOL {cr1 >> 1 & 1} CPHA {cr1 & 1}, '
                      f'{"LSB" if cr1 >> 7 & 1 else "MSB"} first, {"16" if cr1 >> 11 & 1 else "8"} bit, bidi {cr1 >> 15 & 1} txonly {cr1 >> 10 & 1}), CR2 {cr2:#x}')
    for i in ('I2C1', 'I2C2'):
        if r[i][0]: print(f'{i}: CR1 {r[i][0]:#x} CR2 {r[i][1]:#x} (hardware I2C in use)')
    iser = r['NVIC_ISER'][0] | r['NVIC_ISER'][1] << 32
    ipr = b''.join(struct.pack('<I', x) for x in r['NVIC_IPR'])
    print('interrupts enabled: ' + ', '.join(f'{IRQ[k]}(prio {ipr[k] >> 4})' for k in range(len(IRQ)) if iser >> k & 1))
    st = r['SysTick']; print(f'SysTick: CTRL {st[0]:#x} (clock {"AHB" if st[0] >> 2 & 1 else "AHB/8"}), LOAD {st[1]} -> period {(st[1] + 1)} ticks')
    scb = r['SCB']; print(f'SCB: VTOR {scb[2]:#010x}, AIRCR {scb[3]:#010x} (priority grouping {(scb[3] >> 8) & 7}), SHPR {scb[6]:#x} {scb[7]:#x} {scb[8]:#x}, SHCSR {scb[9]:#x}')
    iw = r['IWDG']; print(f'IWDG: prescaler /{4 << (iw[1] & 7)}, reload {iw[2]} -> about {(iw[2] + 1) * (4 << (iw[1] & 7)) / 40000:.2f} s at 40 kHz')
    u = r['USB']; print(f'USB: CNTR {u[16]:#06x}, DADDR {u[19]:#x}, BTABLE {u[20]:#x}, EPnR ' + ' '.join(f'{x:#06x}' for x in u[:8]))

if __name__ == '__main__':
    d = mc.Device(timeout=2.0)
    r = read_all(d)
    show(r)
    if '--json' in sys.argv: json.dump(r, open(sys.argv[sys.argv.index('--json') + 1], 'w'), indent=1)
