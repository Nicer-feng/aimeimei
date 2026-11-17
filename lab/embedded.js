import { colors, plot } from './lab-visuals.js';

export const embeddedLessons = [
  {
    id: 16,
    title: '让 GPIO 输入有个默认值',
    category: '嵌入式进阶',
    eyebrow: 'GPIO PULL-UP',
    description: '给夜灯加一个按键，看看上拉电阻和输入漏电如何共同决定松手后的电平。',
    minutes: 9,
    sections: [
      { title: '上拉电阻给松开的按键定电平', body: '把按钮接在 GPIO 和地之间，再用一只上拉电阻把 GPIO 接到 3.3 V。松手时，输入被拉高。按下时，开关给输入提供一条通向地的低阻路径，输入变低。没有上拉或下拉时，松开的输入容易受周围信号影响。' },
      { title: '数字输入也要看电压', body: '输入低于低电平上限时保证读 0，高于高电平下限时保证读 1。两条线之间的读数缺乏保证。本实验把一条漏电路径近似为接地电阻，它和上拉电阻构成分压。实物的输入阈值和漏电规格以芯片手册为准。' },
    ],
    task: '保持漏电等效电阻为 30 kΩ，把上拉从 10 kΩ 逐渐加到 100 kΩ。观察输入电压跨过哪两条阈值线。',
    question: {
      prompt: '电源 3.3 V，上拉和接地漏电等效电阻都为 30 kΩ。GPIO 约为 1.65 V，而示例低、高电平阈值分别为 0.8 V 和 2.0 V。此时能保证读到什么？',
      options: ['0', '1', '无法保证是 0 还是 1'],
      correct: 2,
      explanation: '两个相等的电阻把输入分到电源电压的一半。1.65 V 落在两条阈值线之间，芯片手册在这个范围通常不保证读数。',
    },
  },
  {
    id: 17,
    title: '一次按下为什么会触发多次',
    category: '嵌入式进阶',
    eyebrow: 'BUTTON DEBOUNCE',
    description: '把手动按键的触点抖动和程序确认的按下事件放到同一张时序图里。',
    minutes: 9,
    sections: [
      { title: '机械触点要经过短暂抖动才稳定', body: '按下按钮后，触点可能在导通和断开之间来回几次。程序每看见一次有效边沿就切换一次灯时，一次按下可能变成多次操作。示波器或逻辑分析仪可以直接看到原始信号的来回变化。' },
      { title: '输入保持稳定一段时间后再确认', body: '每次发现输入变化时，先记录候选电平和时刻。持续达到设定的时间才更新确认状态。若期间输入又变了，就按新电平重新计时。窗口越长越能抑制抖动，按下到确认的等待也越长。' },
    ],
    task: '先将稳定窗口调到 1 ms，数出确认信号有几次上升沿，再改到 8 ms 对比次数和延迟。',
    question: {
      prompt: '按下后输入变成 1，过了 2 ms 又变回 0。软件要求新状态稳定 8 ms 才确认。这次短暂的 1 会发生什么？',
      options: ['它会被确认成一次按下', '它会被滤掉', '8 ms 后它还会被补报'],
      correct: 1,
      explanation: '候选高电平在凑满 8 ms 之前已消失。消抖计时根据最新输入重新开始，确认状态保持原值。',
    },
  },
  {
    id: 18,
    title: '轮询和中断怎么发现短脉冲',
    category: '嵌入式进阶',
    eyebrow: 'POLLING & IRQ',
    description: '对比按固定间隔读引脚和由硬件捕捉上升沿，看看哪一种能发现来得很快的信号。',
    minutes: 10,
    sections: [
      { title: '轮询只知道读取瞬间的电平', body: '用轮询时，程序每隔一段时间查一次 GPIO。两次读取之间完整出现并消失的脉冲可能被漏掉。提高轮询频率能缩短空档，也会让程序更频繁地执行检查。' },
      { title: '中断把边沿变成待处理事件', body: '假设引脚配置为上升沿中断，边沿可以先由硬件识别，再由 CPU 执行中断处理函数。即使运行处理函数时引脚已变回低电平，先前捕捉到的事件仍可有效。实际系统的响应时间也受屏蔽、高优先级任务和硬件条件影响。' },
    ],
    task: '脉冲从 7 ms 开始。把宽度设为 2 ms，先用 5 ms 的间隔轮询，再改成 4 ms。跟图上的读点对照。',
    question: {
      prompt: '程序在 0、5、10 ms 查询 GPIO。高脉冲从 7 ms 开始，9 ms 结束。假定硬件能够识别该上升沿，哪一种方法能发现这个脉冲？',
      options: ['只有轮询能发现', '轮询和上升沿中断都能发现', '上升沿中断能发现，轮询会错过'],
      correct: 2,
      explanation: '查询在 5 ms 和 10 ms 时都读到低电平。中断可以在 7 ms 由硬件识别边沿，随后再处理事件。',
    },
  },
  {
    id: 19,
    title: '用 UART 把一个字节发出去',
    category: '嵌入式进阶',
    eyebrow: 'UART FRAME',
    description: '把一个字节拆成串口时序，再改波特率观察一帧需要多长时间。',
    minutes: 9,
    sections: [
      { title: '起始位给接收端一个时间参考', body: 'UART 的发送和接收依靠事先约定的波特率，不另拉时钟线。常见的 8N1 格式含 8 个数据位、无校验位和 1 个停止位。线路空闲为高，拉低一个起始位后，数据从最低有效位开始发送，最后用高电平的停止位结束。' },
      { title: '一个字节需要十个比特时间', body: '加上起始位和停止位，8N1 每字节占 10 个比特时间。9600 波特时，一位约 104.2 μs，一帧约 1.04 ms。收发两端需要匹配波特率、数据位、校验和停止位等设置。' },
    ],
    task: '先发送 85（0x55），辨认起始位、交替的数据位和停止位。再换成 0，观察中间的数据区，并比较 9600 和 19200 波特的帧长。',
    question: {
      prompt: '8N1 下把波特率从 9600 调到 19200，同一个字节的传输时间怎么变？',
      options: ['约减半', '约翻倍', '保持不变'],
      correct: 0,
      explanation: '位数始终是 10。波特率翻倍后，每位的持续时间变成一半，整帧也随之减半。',
    },
  },
  {
    id: 20,
    title: 'I²C 总线怎么回到高电平',
    category: '嵌入式进阶',
    eyebrow: 'I²C OPEN DRAIN',
    description: '把之前学过的 RC 充电用到 I²C，观察总线电容和上拉电阻怎样拖慢上升沿。',
    minutes: 10,
    sections: [
      { title: '器件拉低线路，上拉电阻拉高线路', body: '常见的 I²C 总线上，SDA 和 SCL 用上拉电阻连接电源。器件可以把线路拉低或释放它。所有器件都释放时，上拉电阻给总线电容充电，电压逐渐上升。线缆、引脚和连接器都会增加总线电容。' },
      { title: '上升沿太慢会占掉一部分高电平时间', body: 'I²C 用电压从电源的 30% 爬到 70% 所用的时间衡量上升沿。理想 RC 模型下，这段时间约为 0.8473 × R × C。快速模式的上限是 300 ns。降低上拉阻值能加快这一过程，也会增加低电平时器件需要吸收的电流。' },
    ],
    task: '固定总线电容为 100 pF，试 4.7 kΩ 和 2.2 kΩ。观察哪种设置能使实验中的上升时间落在 300 ns 以内。',
    question: {
      prompt: '在相同的上拉电阻下，总线电容从 100 pF 增至 200 pF。按 RC 模型，30% 到 70% 的上升时间会怎样？',
      options: ['大约翻倍', '大约减半', '保持不变'],
      correct: 0,
      explanation: '上升时间与 R × C 成正比。R 固定、C 翻倍，电压跨过同一对阈值也需要约两倍的时间。',
    },
  },
  {
    id: 21,
    title: '在 SPI 时钟的哪一边采样',
    category: '嵌入式进阶',
    eyebrow: 'SPI CLOCK MODES',
    description: '看懂片选、时钟和数据线的关系，用采样边沿辨认四种 SPI 模式。',
    minutes: 10,
    sections: [
      { title: '每次传输从片选有效开始', body: '控制器用 CS 选中外设，再通过 SCLK 提供时钟。MOSI 向外设送数据，MISO 可以同时回传数据。实验采用低电平有效的 CS，只画发送方向的信号。' },
      { title: 'CPOL 决定空闲电平，CPHA 决定采样时机', body: 'CPOL 为 0 时，时钟空闲为低，所以每周期的第一条边是上升沿。CPOL 为 1 时，第一条边是下降沿。CPHA 为 0 时在每周期的第一条边采样，为 1 时在第二条边采样。控制器应按外设手册使用相同的模式。' },
    ],
    task: '从模式 0 切到模式 1，再切到模式 2。对照图上的采样点、时钟空闲电平和每个数据位出现的时刻。',
    question: {
      prompt: 'SPI 模式 2 对应 CPOL = 1、CPHA = 0。外设应在哪个边沿采样？',
      options: ['下降沿', '上升沿', 'CS 的上升沿'],
      correct: 0,
      explanation: 'CPOL = 1 让时钟空闲为高，第一条边是下降沿。CPHA = 0 指定在第一条边采样。',
    },
  },
  {
    id: 22,
    title: 'ADC 采样太慢会看见什么',
    category: '嵌入式进阶',
    eyebrow: 'ADC ALIASING',
    description: '让同一段模拟波形经过不同的采样频率，看看快速波动怎样被误看成慢波动。',
    minutes: 10,
    sections: [
      { title: '采样率和量化精度是两回事', body: '12 位描述一次转换能分出多少格，采样率描述每秒转换多少次。采样间隔太长时，样本之间可能藏着额外的波峰和波谷。给每个样本增加位数也不能补回漏掉的变化。' },
      { title: '高频成分可能和低频成分留下相同样本', body: '每秒采样 10 次时，7 Hz 的正弦输入能和一个 3 Hz 的波形在同样的时刻取到相同数值，这叫混叠。恢复带限信号通常要求采样率高于信号中最高频率的两倍，实物还常在 ADC 前用模拟低通压低超出的频率成分。' },
    ],
    task: '保持输入 7 Hz。先将采样率设为 10 次/秒，观察采样点同时落在哪两条线上。再调到 20 次/秒对比。',
    question: {
      prompt: '理想 ADC 每秒采样 10 次。输入是 7 Hz 正弦波。样本会和哪一个低频正弦波的某个相位重合？',
      options: ['1 Hz', '3 Hz', '5 Hz'],
      correct: 1,
      explanation: '采样后可观察的频率会折回到 0–5 Hz。7 Hz 与一次采样频率 10 Hz 相差 3 Hz，调整相位后两者在采样时刻无法区分。',
    },
  },
];

const { mint, pink, wire, quiet } = colors;
const fmt = (value, digits = 0) => value.toFixed(digits);
const result = (label, value) => ({ label, value });
const control = (id, label, min, max, step, initial, format) => ({
  id, label, min, max, step, initial, format,
});
const graphPoints = (end, count, fn) => Array.from({ length: count + 1 }, (_, index) => {
  const time = end * index / count;
  return [time, fn(time)];
});
const trace = (points, color, label, mode = 'line') => ({ points, color, label, mode });
const volts = (value) => `${fmt(value, 2)} V`;
const kilo = (value) => `${value} kΩ`;
const millis = (value) => `${value} ms`;
const hexByte = (value) => `0x${value.toString(16).toUpperCase().padStart(2, '0')}`;

function debounce(raw, debounceTime) {
  const output = [[0, 0]];
  for (let edge = 1; edge < raw.length - 1; edge += 1) {
    const [start, level] = raw[edge];
    const nextEdge = raw[edge + 1][0];
    const confirmation = start + debounceTime;
    const previousLevel = output.at(-1)[1];
    if (level !== previousLevel && confirmation < nextEdge) {
      output.push([confirmation, level]);
    }
  }
  output.push([50, output.at(-1)[1]]);
  return output;
}

function uartFrame(data, bitTime) {
  const bits = Array.from({ length: 8 }, (_, index) => (data >> index) & 1);
  const frame = [0, ...bits, 1];
  const points = frame.map((bit, index) => [index * bitTime, bit]);
  return [[-bitTime, 1], ...points, [11 * bitTime, 1]];
}

function spiTransaction(mode) {
  const cpol = mode >> 1;
  const cpha = mode & 1;
  const data = [1, 0, 1, 0];
  const cs = [[0, 1], [.30, 0], [4.75, 1], [5, 1]];
  const clock = [[0, cpol]];
  const mosi = [[0, 0]];
  const samples = [];

  data.forEach((bit, index) => {
    const leading = index + .75;
    const trailing = index + 1.25;
    clock.push([leading, 1 - cpol], [trailing, cpol]);
    const dataTime = cpha === 1 ? leading : index + .30;
    mosi.push([dataTime, bit]);
    samples.push([cpha === 1 ? trailing : leading, bit]);
  });
  clock.push([5, cpol]);
  mosi.push([5, data.at(-1)]);
  const sampleEdge = cpol === cpha ? '上升沿' : '下降沿';

  return { cs, clock, mosi, samples, cpol, cpha, sampleEdge };
}

const shiftLogic = (points, offset) => points.map(([time, level]) => [time, offset + level * .72]);
const baudRates = [9600, 19200, 57600, 115200];
const risingEdges = (points) => points.slice(1).filter(([, level], index) => level === 1 && points[index][1] === 0);

export const embeddedExperiments = {
  16: {
    controls: [
      control('pullup', '上拉电阻', 1, 100, 1, 10, kilo),
      control('leak', '漏电等效电阻', 5, 100, 5, 30, kilo),
    ],
    note: '实验只看松开的按键。用一只接地电阻模拟漏电，0.8 V 和 2.0 V 是示例阈值。',
    render({ pullup, leak }, prefix) {
      const inputAt = (resistance) => 3.3 * leak / (resistance + leak);
      const points = Array.from({ length: 100 }, (_, index) => [index + 1, inputAt(index + 1)]);
      const voltage = inputAt(pullup);
      const logic = voltage <= .8 ? '低电平 0' : voltage >= 2 ? '高电平 1' : '不确定区';
      return {
        visual: plot({
          prefix, description: `GPIO 输入 ${volts(voltage)}，${logic}`,
          xLabel: '上拉电阻 (kΩ)', yLabel: '输入电压 (V)', x: [0, 100], y: [0, 3.3],
          series: [
            trace(points, mint, '输入电压'),
            { ...trace([[0, 2], [100, 2]], pink, '高电平下限'), dashed: true },
            { ...trace([[0, .8], [100, .8]], quiet, '低电平上限'), dashed: true },
          ],
          markers: [{ x: pullup, y: voltage, color: mint }],
        }),
        results: [result('GPIO 电压', volts(voltage)), result('逻辑判定', logic)],
      };
    },
  },
  17: {
    controls: [control('stable', '稳定时间', 1, 20, 1, 6, millis)],
    note: '两条电平曲线错开显示。原始信号最后一次变化在 19 ms。边沿恰好遇到窗口结束时，本实验先处理新的输入。',
    render({ stable }, prefix) {
      const raw = [[0, 0], [7, 1], [9, 0], [11, 1], [13, 0], [16, 1], [17, 0], [19, 1], [50, 1]];
      const filtered = debounce(raw, stable);
      const accepted = risingEdges(filtered);
      return {
        visual: plot({
          prefix, description: `一次按下出现 ${risingEdges(raw).length} 个原始上升沿，消抖后确认 ${accepted.length} 次`,
          xLabel: '时间 (ms)', yLabel: '按键波形', x: [0, 50], y: [0, 2.2], yTicks: [],
          series: [
            trace(shiftLogic(raw, 1.25), pink, '原始信号', 'step'),
            trace(shiftLogic(filtered, .15), mint, '确认状态', 'step'),
          ],
        }),
        results: [result('确认按下次数', `${accepted.length} 次`), result('第一次确认时刻', millis(accepted[0][0]))],
      };
    },
  },
  18: {
    controls: [
      control('width', '脉冲宽度', 1, 13, 1, 2, millis),
      control('interval', '轮询间隔', 2, 12, 1, 5, millis),
    ],
    note: '轮询从 0 ms 开始。脉冲从 7 ms 开始，结束时立即回到低电平。假设硬件捕捉到上升沿，处理程序固定在 1 ms 后运行。',
    render({ width, interval }, prefix) {
      const start = 7;
      const end = start + width;
      const window = 30;
      const pulse = [[0, 0], [start, 1], [end, 0], [window, 0]];
      const reads = Array.from({ length: Math.floor(window / interval) + 1 }, (_, index) => {
        const time = interval * index;
        return [time, Number(time >= start && time < end)];
      });
      const captured = reads.find(([, level]) => level === 1);
      return {
        visual: plot({
          prefix, description: `脉冲从 7 ms 到 ${end} ms，轮询${captured ? `在 ${captured[0]} ms 捕捉到` : '未捕捉到'}，中断在 8 ms 处理`,
          xLabel: '时间 (ms)', yLabel: '逻辑电平', x: [0, window], y: [-.15, 1.4], yTicks: [0, 1],
          series: [
            trace(pulse, mint, '脉冲', 'step'),
            trace(reads, pink, '轮询读点', 'points'),
          ],
          markers: [{ x: 8, y: 1.23, label: '中断处理', color: wire }],
        }),
        results: [result('轮询首次读到高电平', captured ? millis(captured[0]) : '错过脉冲'), result('中断处理时刻', '8 ms')],
      };
    },
  },
  19: {
    controls: [
      control('data', '发送字节（十进制）', 0, 255, 1, 85, (value) => `${value}（${hexByte(value)}）`),
      control('baudIndex', '波特率', 0, baudRates.length - 1, 1, 0, (value) => `${baudRates[value]} Bd`),
    ],
    note: '时轴随波特率缩放，整帧从 0 时刻开始。粉色圆点标出起始位和停止位的中点。',
    render({ data, baudIndex }, prefix) {
      const bitTime = 1e6 / baudRates[baudIndex];
      return {
        visual: plot({
          prefix, description: `UART 以 ${baudRates[baudIndex]} 波特发送 ${hexByte(data)}，8N1 帧长 ${fmt(bitTime * 10, 1)} 微秒`,
          xLabel: '时间 (μs)', yLabel: 'TX 电平', x: [-bitTime, 11 * bitTime], y: [-.25, 1.5], yTicks: [0, 1],
          series: [trace(uartFrame(data, bitTime), mint, 'TX', 'step')],
          markers: [
            { x: bitTime * .5, y: 0, label: '起始位', color: pink },
            { x: bitTime * 9.5, y: 1, label: '停止位', color: pink },
          ],
        }),
        results: [result('每位持续', `${fmt(bitTime, 1)} μs`), result('完整帧耗时', `${fmt(bitTime * 10, 1)} μs`)],
      };
    },
  },
  20: {
    controls: [
      control('resistance', '上拉电阻', 1, 10, .1, 4.7, (value) => kilo(fmt(value, 1))),
      control('capacitance', '总线电容', 30, 250, 10, 100, (value) => `${value} pF`),
    ],
    note: '曲线近似为释放一根开漏线后的 RC 充电，300 ns 是 I²C 快速模式的上限。实际选型还要核对低电平电压、吸收电流等规格。',
    render({ resistance, capacitance }, prefix) {
      const tau = resistance * capacitance / 1000;
      const crossAt = (fraction) => -Math.log(1 - fraction) * tau;
      const riseTime = 1000 * (crossAt(.7) - crossAt(.3));
      const points = graphPoints(4.2, 350, (time) => 3.3 * (1 - Math.exp(-time / tau)));
      return {
        visual: plot({
          prefix, description: `开漏线释放后电压回升，30% 到 70% 用时 ${fmt(riseTime, 1)} 纳秒`,
          xLabel: '释放后时间 (μs)', yLabel: '线路电压 (V)', x: [0, 4.2], y: [0, 3.5],
          series: [
            trace(points, mint, '线路电压'),
            { ...trace([[0, .99], [4.2, .99]], quiet, '电源的 30%'), dashed: true },
            { ...trace([[0, 2.31], [4.2, 2.31]], pink, '电源的 70%'), dashed: true },
          ],
          markers: [
            { x: crossAt(.3), y: .99, color: quiet },
            { x: crossAt(.7), y: 2.31, color: pink },
          ],
        }),
        results: [result('30% 到 70% 上升时间', `${fmt(riseTime, 1)} ns`), result('快速模式上升时间', riseTime <= 300 ? '在限值内' : '超过限值')],
      };
    },
  },
  21: {
    controls: [control('mode', 'SPI 模式', 0, 3, 1, 0, (value) => `模式 ${value}`)],
    note: '三条逻辑电平曲线错开。MOSI 发送 1010，圆点标出取样时刻，横轴以时钟周期为单位。模型省略传播延迟。',
    render({ mode }, prefix) {
      const { cs, clock, mosi, samples, cpol, cpha, sampleEdge } = spiTransaction(mode);
      return {
        visual: plot({
          prefix, description: `SPI 模式 ${mode}，时钟空闲为 ${cpol}，在${sampleEdge}采样 1010`,
          xLabel: '时间（时钟周期）', yLabel: 'SPI 波形', x: [0, 5], y: [0, 3.14], yTicks: [],
          series: [
            trace(shiftLogic(cs, 2.25), quiet, 'CS', 'step'),
            trace(shiftLogic(clock, 1.2), pink, 'SCLK', 'step'),
            trace(shiftLogic(mosi, .15), mint, 'MOSI', 'step'),
          ],
          markers: shiftLogic(samples, .15).map(([x, y]) => ({ x, y, color: mint })),
        }),
        results: [result('CPOL / CPHA', `${cpol} / ${cpha}`), result('采样边沿', sampleEdge)],
      };
    },
  },
  22: {
    controls: [
      control('frequency', '输入频率', 1, 18, 1, 7, (value) => `${value} Hz`),
      control('rate', '采样频率', 6, 60, 1, 10, (value) => `${value} 次/秒`),
    ],
    note: '画面显示一秒，纵轴用归一化幅度。只模拟均匀采样，不模拟量化误差和抖动。恰好在采样率一半时，样本仍可能丢失相位信息。',
    render({ frequency, rate }, prefix) {
      const signedAlias = frequency - Math.floor(frequency / rate + .5) * rate;
      const apparent = Math.abs(signedAlias);
      const signalAt = (hertz) => (time) => Math.sin(2 * Math.PI * hertz * time + .45);
      const original = signalAt(frequency);
      const alias = signalAt(signedAlias);
      const series = [
        trace(graphPoints(1, 300, original), quiet, '模拟输入'),
        trace(graphPoints(1, rate, original), mint, '采样点', 'points'),
      ];
      if (frequency > rate / 2) {
        series.splice(1, 0, { ...trace(graphPoints(1, 300, alias), pink, '混叠波形'), dashed: true });
      }
      const reading = frequency === rate / 2 ? '处于采样边界' : `${apparent} Hz`;
      return {
        visual: plot({
          prefix, description: `输入 ${frequency} Hz，每秒采样 ${rate} 次，样本对应 ${reading}`,
          xLabel: '时间 (s)', yLabel: '归一化幅度', x: [0, 1], y: [-1.15, 1.15],
          series,
        }),
        results: [result('采样率的一半', `${rate / 2} Hz`), result('样本对应的频率', reading)],
      };
    },
  },
};
