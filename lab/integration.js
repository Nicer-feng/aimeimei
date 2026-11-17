import { bars, colors, plot, schematic } from './lab-visuals.js';

export const integrationLessons = [
  {
    id: 23,
    title: 'CMOS 逻辑门怎样抵抗噪声',
    category: '数字电路',
    eyebrow: 'CMOS NOISE MARGIN',
    description: '看懂 CMOS 反相器的输入输出曲线，算出两个逻辑门之间留了多少抗干扰空间。',
    minutes: 13,
    sections: [
      { title: '从两个 MOS 管到一个反相器', body: '典型 CMOS 反相器用 PMOS 将输出拉向电源，用 NMOS 将输出拉向地。输入足够低时输出为高，输入足够高时输出为低。中间过渡区的电压会随输入变化，接收门对落在这里的信号不保证按指定逻辑解释。' },
      { title: '发送电平和接收门限之间的余量', body: '模型中发送端保证低电平至多 0.20 V、高电平至少 3.10 V。接收端保证识别不高于 1.00 V 的低电平和不低于 2.20 V 的高电平。低电平噪声容限为 1.00 − 0.20 = 0.80 V，高电平为 3.10 − 2.20 = 0.90 V。' },
    ],
    task: '令发送端输出低电平，把干扰由 0.80 V 调到 0.85 V。再选高电平，比较 0.90 V 和 0.95 V 时接收端的判断。',
    question: {
      prompt: '送出的低电平是 0.20 V，接收门允许低电平最高为 1.00 V。最多能容忍多大的正向干扰？',
      options: ['0.20 V', '0.80 V', '1.20 V'],
      correct: 1,
      explanation: '低电平被干扰抬高后仍需处在 1.00 V 以内，因此余量为 1.00 − 0.20 = 0.80 V。',
    },
  },
  {
    id: 24,
    title: '找出数字电路的时序瓶颈',
    category: '数字电路',
    eyebrow: 'SETUP TIMING',
    description: '给两个寄存器之间的逻辑分配时间，找出时钟提速后数据赶不上采样的原因。',
    minutes: 14,
    sections: [
      { title: '时钟边沿之后数据才开始走', body: '第一个寄存器由时钟触发。它的输出需要 clock-to-Q 延迟，再经过组合逻辑到达下一个寄存器。第二个寄存器要求数据在下一次采样边沿前至少稳定一个建立时间。' },
      { title: '用时序裕量判断能否按时到达', body: '时序裕量等于时钟周期减去 clock-to-Q、组合逻辑延迟和建立时间。裕量小于零就会违反建立时间要求。多个数据通路中要求时间最长的路径约束了最高时钟频率。实际设计还需检查保持时间、时钟偏差和不确定性。' },
    ],
    task: '把组合逻辑延迟设为 12 ns，从 50 MHz 提高到 60 MHz，观察裕量跨过零的时刻。试着在保持 60 MHz 的条件下恢复正裕量。',
    question: {
      prompt: '时钟 50 MHz，clock-to-Q 为 2 ns，组合逻辑延迟 12 ns，建立时间 3 ns。建立裕量是多少？',
      options: ['−3 ns', '5 ns', '3 ns'],
      correct: 2,
      explanation: '50 MHz 对应周期 20 ns。整条路径需要 2 + 12 + 3 = 17 ns，剩下 3 ns 的建立裕量。',
    },
  },
  {
    id: 25,
    title: '写出不漏按键的等待逻辑',
    category: '嵌入式进阶',
    eyebrow: 'NONBLOCKING STATE MACHINE',
    description: '把等待写成状态转换，让同一个主循环能同时处理定时任务和短促的按键事件。',
    minutes: 14,
    sections: [
      { title: '一次阻塞能漏掉整个输入脉冲', body: '主循环用阻塞延时等待灯的定时动作时，延时期间跳过了按键轮询。如果按下和松开都发生在这段时间里，恢复轮询后只能读到松开的状态。' },
      { title: '把到期时刻存进状态', body: '进入等待状态时保存到期时刻。之后主循环继续扫描按键，同时检查时刻是否已到。到期就进行照明动作并切换状态。这个模型假设单线程轮询、没有 GPIO 中断或硬件事件锁存。' },
    ],
    task: '等待设为 500 ms，对比阻塞等待与状态机等待。再把阻塞等待改为 380 ms，看按键还能不能被读到，以及多等了多久。',
    question: {
      prompt: '程序从 0 ms 阻塞等待到 500 ms，按键只在 320 至 420 ms 按住。没有中断或输入锁存时，程序会看到什么？',
      options: ['完全漏掉这次按键', '在 320 ms 立刻处理', '在 500 ms 读到按下'],
      correct: 0,
      explanation: '阻塞时主循环没有扫描。500 ms 恢复扫描时按键已松开，这次按下没有被保存。',
    },
  },
  {
    id: 26,
    title: '用两点校准 ADC 读数',
    category: '嵌入式进阶',
    eyebrow: 'ADC CALIBRATION',
    description: '给偏移和增益都存在误差的 ADC 做两点标定，再用第三个输入检验校准效果。',
    minutes: 14,
    sections: [
      { title: '码值转电压需要斜率和零点', body: '用理想满量程分摊每个 ADC 码，只能得到未校准估计。这个模型的实际斜率与理想值有差别，码值还会整体平移。拿两个已知电压及其读数，可以拟合实际直线。' },
      { title: '拟合后再用独立输入验证', body: '线性拟合可以先从被测码值减去低参考点的码值，再用两个参考点的电压差与码值差换算，最后加回低参考电压。实际测量中的量化、噪声、非线性和饱和仍然会影响结果。' },
    ],
    task: '把测试电压设为 1.50 V，再改变零点偏移。比较两种算法的误差，然后换个测试电压验证。',
    question: {
      prompt: '标定得到 0.50 V 对应 760，2.50 V 对应 3000。若被测码值为 1880，按直线校准后的电压是多少？',
      options: ['1.15 V', '1.50 V', '1.88 V'],
      correct: 1,
      explanation: '1880 到 760 的距离是 1120，恰好为 3000 到 760 距离的一半。对应电压为 0.50 V 与 2.50 V 的中点 1.50 V。',
    },
  },
  {
    id: 27,
    title: '在平滑和响应速度之间取舍',
    category: '信号处理',
    eyebrow: 'EXPONENTIAL SMOOTHING',
    description: '用指数移动平均处理会抖动的光照信号，同时衡量平稳度和开灯前的等待。',
    minutes: 15,
    sections: [
      { title: '每次混合一个新值和上次结果', body: '指数移动平均把本次读数乘以 α，把上次滤波结果乘以 1 − α，再相加。α 可以看作新数据的权重。减小它会让过去数据影响得更久，因此短时波动更难拉动滤波结果。' },
      { title: '同时观察噪声和阶跃响应', body: '实验用变化前四个样本的峰峰值衡量波动，并记录真实光照突然升高后结果首次到达 70% 光照刻度的时间。最终要按应用允许的响应用时选 α，并用不同干扰验证。' },
    ],
    task: '先把噪声幅度设为 8%，比较 α 为 1.00、0.40 和 0.15 的波动与首次到达 70% 的用时。',
    question: {
      prompt: '面对同样的噪声和上升阶跃，减小 α 通常会带来什么变化？',
      options: ['更平稳，响应更快', '波动更大，响应更慢', '更平稳，响应更慢'],
      correct: 2,
      explanation: '新读数权重变小，单个噪声样本能引起的变化减小，新光照需要更多样本才能拉动滤波结果。',
    },
  },
  {
    id: 28,
    title: '算一算电池能用多久',
    category: '嵌入式进阶',
    eyebrow: 'POWER BUDGET',
    description: '用唤醒和休眠的时长计算平均电流，判断省电和传感器响应间隔能否同时达标。',
    minutes: 15,
    sections: [
      { title: '按时间比例分摊电流', body: '设备醒来读一次传感器，休眠到下一次采样。平均电流等于清醒电流乘以清醒时间比例，再加上休眠电流乘以剩余比例。相同的清醒时长配更长的采样周期，平均电流会下降。' },
      { title: '功耗合格还要看多久能发现变化', body: '600 mAh 除以平均电流，可估算理想续航小时数。采样周期拉长后，变化最坏要等接近一个周期才被发现。本模型只计算传感和控制电路，实际续航还要计入 LED、供电损耗、温度和电池可用容量。' },
    ],
    task: '保持每次唤醒 60 ms，比较 300 ms、600 ms 与 1500 ms 的续航。若要求 600 ms 内发现变化，试着在允许的周期里把续航调高。',
    question: {
      prompt: '工作电流 10 mA，休眠电流 0.07 mA。每 200 ms 清醒 20 ms，平均电流约是多少？',
      options: ['1.06 mA', '5.04 mA', '10.00 mA'],
      correct: 0,
      explanation: '清醒比例为 20 ÷ 200 = 10%。平均电流为 10 × 0.10 + 0.07 × 0.90 = 1.063 mA。',
    },
  },
  {
    id: 29,
    title: '定位遥测丢帧的瓶颈',
    category: '嵌入式进阶',
    eyebrow: 'UART BUFFER AND THROUGHPUT',
    description: '把传感器持续产生的数据与串口的发送上限放在一起，看缓冲区何时会溢出。',
    minutes: 16,
    sections: [
      { title: '把波特率换成有效字节速率', body: '这里用常见的 UART 8N1 格式。每个字节包含 1 位起始位、8 位数据和 1 位停止位，以每秒 9600 位通信时，最多每秒发送 960 字节。发 24 字节一帧，理论上限就是每秒 40 帧。' },
      { title: '缓冲区只能暂时吸收积压', body: '每完成一次采样，就把整帧放入缓冲区。串口连续取字节发送。如果生产比发送更快，积压就会增长。模型在缓冲区放不下一整帧时丢弃新帧，两次入队之间按串口速率扣除已发送的字节。' },
    ],
    task: '在 9600 波特下将采样频率从 30 提高到 50 Hz，观察丢帧。再把频率调回 30 Hz、把波特率降到 4800，看看瓶颈是否回来。',
    question: {
      prompt: 'UART 采用 8N1，波特率 9600，每帧 24 字节。持续传输的理论上限是多少帧每秒？',
      options: ['24 帧/秒', '40 帧/秒', '96 帧/秒'],
      correct: 1,
      explanation: '9600 除以每个字节的 10 位，得到每秒 960 字节。再除以 24 字节/帧，得到每秒 40 帧。',
    },
  },
  {
    id: 30,
    title: '调出一盏稳定又灵敏的夜灯',
    category: '综合实验',
    eyebrow: 'NIGHTLIGHT DESIGN CHALLENGE',
    description: '综合滤波、迟滞和持续确认，在同一条光照变化轨迹上完成四项验收。',
    minutes: 18,
    sections: [
      { title: '用两道阈值保留上一状态', body: '低于 40% 时可能开灯，高于或等于关灯阈值时可能关灯。两者之间保留原来的状态，这段间隔就是迟滞。先做平滑，再要求切换条件连续成立若干次，可以抗短暂遮挡和边界抖动。' },
      { title: '让数据同时检验稳定性和延迟', body: '固定测试轨迹先经过短暂遮挡，再在第 2 秒真正变暗，第 4 秒恢复明亮。验收要求遮挡不误亮、变暗后 0.8 秒内开灯、暗段中途不灭、恢复明亮后 1 秒内关灯。每次改参数都重新运行同一轨迹。' },
    ],
    task: '先用初始参数观察误触发，再调 α、迟滞宽度和确认次数。尝试在四项都通过后继续缩短开灯用时。',
    question: {
      prompt: '灯已经亮了。平滑后的光照在开灯阈值与关灯阈值之间保持了一段时间，灯会怎样？',
      options: ['立即关灯', '到确认次数后关灯', '保持亮着'],
      correct: 2,
      explanation: '亮着时，只有达到关灯阈值并满足持续确认才切换。两道阈值之间，控制逻辑保留上一状态。',
    },
  },
];

const result = (label, value) => ({ label, value });
const formatVolts = (value) => `${value.toFixed(2)} V`;
const formatNanoseconds = (value) => `${value.toFixed(2)} ns`;
const formatMilliseconds = (value) => `${value} ms`;
const formatPercent = (value) => `${value}%`;
const formatAlpha = (value) => value.toFixed(2);

const sampleNoisePattern = [0, 4, -3, 6, -6, 3, -4, 1];
const sampleNoise = (index) => sampleNoisePattern[index % sampleNoisePattern.length];

function inverterOutput(input) {
  if (input <= 1) return 3.1;
  if (input >= 2.2) return 0.2;
  return 3.1 - (input - 1) / 1.2 * 2.9;
}

function adcCode(voltage, offset) {
  return Math.round(1120 * voltage + offset);
}

function smoothSamples(samples, alpha, initial) {
  let previous = initial;
  return samples.map((value) => {
    previous += alpha * (value - previous);
    return previous;
  });
}

const baudValues = [1200, 2400, 4800, 9600];
const encodeBaud = (index) => `${baudValues[index]} 波特`;

function receiveFrames(frequency, bytesPerSecond) {
  const bufferCapacity = 96;
  const frameBytes = 24;
  const trace = [];
  let pending = 0;
  let dropped = 0;

  for (let sample = 0; sample < frequency * 4; sample++) {
    if (sample > 0) pending = Math.max(0, pending - bytesPerSecond / frequency);
    if (pending + frameBytes <= bufferCapacity + 1e-9) {
      pending = Math.min(bufferCapacity, pending + frameBytes);
    } else {
      dropped++;
    }
    trace.push([sample / frequency, pending]);
  }
  trace.push([4, Math.max(0, pending - bytesPerSecond / frequency)]);
  return { trace, dropped, bufferCapacity, frameBytes };
}

function nightlightSequence(alpha, hysteresis, confirmation) {
  const raw = Array.from({ length: 61 }, (_, index) => {
    if (index >= 10 && index < 12) return 20;
    if (index >= 20 && index < 26) return 24 + sampleNoise(index);
    if (index >= 26 && index < 40) return 42 + sampleNoise(index);
    return 72 + sampleNoise(index);
  });

  const smoothed = smoothSamples(raw, alpha, 72);
  const offThreshold = 40 + hysteresis;
  let lampOn = false;
  let confirmations = 0;
  const events = [];
  const lamp = smoothed.map((light, index) => {
    const switchRequested = lampOn ? light >= offThreshold : light < 40;
    confirmations = switchRequested ? confirmations + 1 : 0;
    if (confirmations >= confirmation) {
      lampOn = !lampOn;
      events.push({ index, lampOn });
      confirmations = 0;
    }
    return lampOn ? 92 : 8;
  });
  return { raw, smoothed, lamp, events, offThreshold };
}

export const integrationExperiments = {
  23: {
    controls: [
      { id: 'logic', label: '发送逻辑电平', min: 0, max: 1, step: 1, initial: 0, format: (value) => value ? '高电平' : '低电平' },
      { id: 'noise', label: '向门限方向的干扰', min: 0, max: 1.4, step: 0.05, initial: 0.6, format: formatVolts },
    ],
    note: '曲线为分段线性近似。干扰会抬高低电平或压低高电平。可将这些门限和输出保证值与实际器件的数据手册对照。',
    render({ logic, noise }, prefix) {
      const input = Math.round((logic ? 3.1 - noise : 0.2 + noise) * 100) / 100;
      const output = inverterOutput(input);
      const classification = input <= 1 ? '有效低电平' : input >= 2.2 ? '有效高电平' : '进入不确定区';
      return {
        visual: plot({
          prefix, description: `反相器输入 ${formatVolts(input)}，输出 ${formatVolts(output)}，${classification}`,
          xLabel: '输入 / V', yLabel: '输出 / V', x: [0, 3.3], y: [0, 3.3],
          series: [{ points: [[0, 3.1], [1, 3.1], [2.2, 0.2], [3.3, 0.2]], color: colors.mint, label: '传输曲线' }],
          markers: [{ x: input, y: output, label: '工作点', color: colors.pink }],
        }),
        results: [
          result('受扰后的输入', formatVolts(input)),
          result('输入判定', classification),
          result('剩余噪声容限', formatVolts((logic ? 0.9 : 0.8) - noise)),
        ],
      };
    },
  },
  24: {
    controls: [
      { id: 'frequency', label: '时钟频率', min: 10, max: 120, step: 1, initial: 50, format: (value) => `${value} MHz` },
      { id: 'logic-delay', label: '组合逻辑延迟', min: 1, max: 35, step: 1, initial: 12, format: formatNanoseconds },
    ],
    note: '发端 clock-to-Q 固定为 2 ns，收端建立时间固定为 3 ns。柱形分别显示数据到达时刻与允许的最迟到达时刻，均从本次时钟边沿算起。',
    render({ frequency, 'logic-delay': logicDelay }, prefix) {
      const period = 1000 / frequency;
      const arrival = 2 + logicDelay;
      const deadline = period - 3;
      const slack = deadline - arrival;
      return {
        visual: bars({
          prefix, description: `数据到达 ${formatNanoseconds(arrival)}，最迟 ${formatNanoseconds(deadline)}`,
          max: Math.max(arrival, deadline) * 1.15,
          items: [
            { label: '数据到达', value: arrival, display: formatNanoseconds(arrival), color: colors.mint },
            { label: '最迟到达', value: deadline, display: formatNanoseconds(deadline), color: colors.pink },
          ],
        }),
        results: [
          result('时钟周期', formatNanoseconds(period)),
          result('建立裕量', formatNanoseconds(slack)),
          result('建立检查', slack < 0 ? '违反建立时间' : slack < 0.00001 ? '刚好满足' : '满足建立时间'),
        ],
      };
    },
  },
  25: {
    controls: [
      { id: 'wait', label: '定时等待', min: 200, max: 1000, step: 20, initial: 500, format: formatMilliseconds },
      { id: 'mode', label: '等待方式', min: 0, max: 1, step: 1, initial: 0, format: (value) => value ? '状态机' : '阻塞延时' },
    ],
    note: '按键从 320 ms 到 420 ms 前保持按下。轮询间隔为 20 ms，进入等待的时刻设为 0 ms。',
    render({ wait, mode }, prefix) {
      const firstScan = mode ? 0 : wait;
      const possibleRead = Math.max(320, firstScan);
      const captured = possibleRead < 420;
      return {
        visual: schematic({
          prefix, description: captured ? `${possibleRead} 毫秒读到按键` : '等待结束后按键已经松开',
          nodes: [
            { label: '按键有效', value: '320–420 ms', color: colors.wire },
            { label: '首次轮询', value: formatMilliseconds(firstScan), color: colors.pink },
            { label: '按键记录', value: captured ? formatMilliseconds(possibleRead) : '未读到', color: colors.mint },
          ],
        }),
        results: [
          result('等待结束', formatMilliseconds(wait)),
          result('是否处理按键', captured ? '已处理' : '漏掉'),
          result('按键响应延迟', captured ? formatMilliseconds(possibleRead - 320) : '未触发'),
        ],
      };
    },
  },
  26: {
    controls: [
      { id: 'voltage', label: '测试输入电压', min: 0.5, max: 2.5, step: 0.01, initial: 1.5, format: formatVolts },
      { id: 'offset', label: 'ADC 零点偏移', min: -200, max: 250, step: 10, initial: 200, format: (value) => `${value} 码` },
    ],
    note: '实测斜率模型为每伏 1120 码。参考点固定在 0.50 V 和 2.50 V。未经校准的算法按理想满量程 3.30 V 与 4095 码换算。',
    render({ voltage, offset }, prefix) {
      const lowCode = adcCode(0.5, offset);
      const highCode = adcCode(2.5, offset);
      const code = adcCode(voltage, offset);
      const uncalibrated = code * 3.3 / 4095;
      const calibrated = 0.5 + (code - lowCode) * 2 / (highCode - lowCode);
      const errorBefore = Math.round(Math.abs(uncalibrated - voltage) * 1000);
      const errorAfter = Math.round(Math.abs(calibrated - voltage) * 1000);
      return {
        visual: bars({
          prefix, description: `实际电压 ${formatVolts(voltage)}，未校准 ${formatVolts(uncalibrated)}，已校准 ${formatVolts(calibrated)}`,
          max: 3.3,
          items: [
            { label: '实际电压', value: voltage, display: formatVolts(voltage), color: colors.wire },
            { label: '未校准', value: uncalibrated, display: formatVolts(uncalibrated), color: colors.pink },
            { label: '两点校准', value: calibrated, display: formatVolts(calibrated), color: colors.mint },
          ],
        }),
        results: [
          result('原始读数', `${code} 码`),
          result('未校准绝对误差', `${errorBefore} mV`),
          result('校准后绝对误差', `${errorAfter} mV`),
        ],
      };
    },
  },
  27: {
    controls: [
      { id: 'alpha', label: '新数据权重 α', min: 0.1, max: 1, step: 0.05, initial: 0.4, format: formatAlpha },
      { id: 'noise', label: '噪声幅度', min: 0, max: 12, step: 1, initial: 8, format: formatPercent },
    ],
    note: '每 100 ms 取样，光照在 0.8 秒从 25% 跳到 75%。波动指标使用前半段 t = 0.4 到 0.7 秒四个样本。',
    render({ alpha, noise }, prefix) {
      const ideal = Array.from({ length: 49 }, (_, index) => index < 8 ? 25 : 75);
      const samples = ideal.map((value, index) => value + noise * sampleNoise(index) / 6);
      const smoothed = smoothSamples(samples, alpha, 25);
      const peakToPeak = (values) => {
        const window = values.slice(4, 8);
        return (Math.max(...window) - Math.min(...window)).toFixed(1);
      };
      const firstCrossing = smoothed.findIndex((value, index) => index >= 8 && value >= 70);
      const plotPoints = (values) => values.map((value, index) => [index / 10, value]);
      return {
        visual: plot({
          prefix, description: '光照真实值、含噪采样与指数平滑后的结果',
          xLabel: '时间 / s', yLabel: '光照 / %', x: [0, 4.8], y: [0, 100],
          series: [
            { points: plotPoints(ideal), color: colors.wire, label: '真值', mode: 'step', dashed: true },
            { points: plotPoints(samples), color: colors.pink, label: '采样' },
            { points: plotPoints(smoothed), color: colors.mint, label: '平滑' },
          ],
        }),
        results: [
          result('采样峰峰值', `${peakToPeak(samples)} 个百分点`),
          result('平滑峰峰值', `${peakToPeak(smoothed)} 个百分点`),
          result('首次达到 70%', firstCrossing < 0 ? '观察窗内未达到' : formatMilliseconds((firstCrossing - 8) * 100)),
        ],
      };
    },
  },
  28: {
    controls: [
      { id: 'period', label: '采样周期', min: 100, max: 3000, step: 100, initial: 600, format: formatMilliseconds },
      { id: 'active', label: '每周期唤醒时长', min: 10, max: 100, step: 10, initial: 60, format: formatMilliseconds },
    ],
    note: '清醒电流取 10 mA，休眠取 0.07 mA，电池容量取 600 mAh。图上显示两个完整周期。',
    render({ period, active }, prefix) {
      const ratio = active / period;
      const average = 10 * ratio + 0.07 * (1 - ratio);
      const points = ratio === 1
        ? [[0, 10], [2 * period, 10]]
        : [[0, 10], [active, 0.07], [period, 10], [period + active, 0.07], [2 * period, 0.07]];
      return {
        visual: plot({
          prefix, description: `每 ${period} 毫秒唤醒 ${active} 毫秒，平均电流 ${average.toFixed(2)} 毫安`,
          xLabel: '时间 / ms', yLabel: '电流 / mA', x: [0, 2 * period], y: [0, 11],
          series: [
            { points, mode: 'step', color: colors.mint, label: '瞬时电流' },
            { points: [[0, average], [2 * period, average]], color: colors.pink, label: '平均电流', dashed: true },
          ],
        }),
        results: [
          result('清醒时间比例', `${(ratio * 100).toFixed(1)}%`),
          result('平均电流', `${average.toFixed(3)} mA`),
          result('理想续航', `${(600 / average / 24).toFixed(1)} 天`),
        ],
      };
    },
  },
  29: {
    controls: [
      { id: 'frequency', label: '采样频率', min: 5, max: 100, step: 5, initial: 30, format: (value) => `${value} Hz` },
      { id: 'baud', label: '串口速率', min: 0, max: 3, step: 1, initial: 3, format: encodeBaud },
    ],
    note: '图中每个采样点表示尝试将 24 字节帧放入队列后的占用量。缓冲区为 96 字节，发送期间采用连续速率近似。',
    render({ frequency, baud }, prefix) {
      const bytesPerSecond = baudValues[baud] / 10;
      const { trace, dropped, bufferCapacity, frameBytes } = receiveFrames(frequency, bytesPerSecond);
      return {
        visual: plot({
          prefix, description: `四秒内队列占用，丢帧 ${dropped} 次`,
          xLabel: '时间 / s', yLabel: '占用 / 字节', x: [0, 4], y: [0, 106],
          series: [
            { points: [[0, bufferCapacity], [4, bufferCapacity]], color: colors.pink, label: '容量', dashed: true },
            { points: trace, color: colors.mint, label: '队列占用' },
          ],
        }),
        results: [
          result('产生速率', `${frameBytes * frequency} 字节/秒`),
          result('发送上限', `${bytesPerSecond} 字节/秒`),
          result('前 4 秒丢帧', `${dropped} 帧`),
        ],
      };
    },
  },
  30: {
    controls: [
      { id: 'alpha', label: '新数据权重 α', min: 0.1, max: 1, step: 0.1, initial: 0.7, format: formatAlpha },
      { id: 'hysteresis', label: '迟滞宽度', min: 0, max: 38, step: 1, initial: 0, format: (value) => `${value} 个百分点` },
      { id: 'confirmation', label: '连续确认次数', min: 1, max: 12, step: 1, initial: 1, format: (value) => `${value} 次` },
    ],
    note: '每 100 ms 采样一次。灯态曲线的位置高时表示灯亮，位置低时表示灯灭。开灯阈值固定为 40%，关灯阈值等于 40% 加迟滞宽度。',
    render({ alpha, hysteresis, confirmation }, prefix) {
      const { raw, smoothed, lamp, events, offThreshold } = nightlightSequence(alpha, hysteresis, confirmation);
      const falseOn = events.some(({ index, lampOn }) => lampOn && index < 20);
      const on = events.find(({ index, lampOn }) => lampOn && index >= 20 && index < 40);
      const falseOff = events.some(({ index, lampOn }) => on && !lampOn && index > on.index && index < 40);
      const off = events.find(({ index, lampOn }) => !lampOn && index >= 40);
      const onDelay = on ? (on.index - 20) * 100 : null;
      const offDelay = off ? (off.index - 40) * 100 : null;
      const points = (values) => values.map((value, index) => [index / 10, value]);
      return {
        visual: plot({
          prefix, description: `感光夜灯控制序列，关灯阈值 ${offThreshold}%，遮挡${falseOn ? '误亮' : '未误亮'}`,
          xLabel: '时间 / s', yLabel: '光照 / %', x: [0, 6], y: [0, 100],
          series: [
            { points: points(raw), color: colors.wire, label: '采样' },
            { points: points(smoothed), color: colors.pink, label: '平滑' },
            { points: points(lamp), color: colors.mint, label: '灯态', mode: 'step', dashed: true },
          ],
        }),
        results: [
          result('遮挡不误亮', falseOn ? '失败 · 出现误亮' : '通过'),
          result('变暗后 0.8 秒内开灯', onDelay === null ? '失败 · 未开灯' : `${onDelay <= 800 ? '通过' : '失败'} · ${formatMilliseconds(onDelay)}`),
          result('暗段中途不灭', !on ? '失败 · 未开灯' : falseOff ? '失败 · 中途熄灭' : '通过'),
          result('恢复明亮后 1 秒内关灯', offDelay === null ? '失败 · 未关灯' : `${offDelay <= 1000 ? '通过' : '失败'} · ${formatMilliseconds(offDelay)}`),
        ],
      };
    },
  },
};
