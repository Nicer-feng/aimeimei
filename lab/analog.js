import { colors, plot } from './lab-visuals.js';

export const analogLessons = [
  {
    id: 9,
    title: '给分压器接上负载',
    category: '模拟电路',
    eyebrow: 'LOADED DIVIDER',
    description: '同一个分压点，接上负载后为什么会从 1.65 V 降到 1.10 V？',
    minutes: 10,
    sections: [
      { title: '负载也在从分压点取电流', body: '接在输出与地之间的负载，相当于和分压器下方的电阻并联。负载电阻越小，这一支路的等效阻值越小，输出电压也越低。' },
      { title: '把整个分压器看成一个电源', body: '戴维南等效用一个理想电压源串联一个电阻描述输出。3.3 V 电源和两只 10 kΩ 电阻形成的分压器，等效为 1.65 V 串联 5 kΩ。5 kΩ 来自把理想电源短路后，两只 10 kΩ 在输出端并联。' },
    ],
    task: '试试 5 kΩ、10 kΩ 和 50 kΩ 负载。把 5 kΩ 当成分压器自己的输出电阻，先算 10 kΩ 负载占总阻值的比例，再核对实际输出。',
    question: {
      prompt: '1.65 V 等效电源串联 5 kΩ，再接上一只 10 kΩ 的负载。负载两端电压是多少？',
      options: ['0.55 V', '1.10 V', '1.65 V'],
      correct: 1,
      explanation: '负载分到 10 ÷ (5 + 10) = 2/3 的电压，所以读数是 1.65 V × 2/3 = 1.10 V。',
    },
  },
  {
    id: 10,
    title: '用频率看 RC 滤波器',
    category: '模拟电路',
    eyebrow: 'LOW-PASS RESPONSE',
    description: '给低通滤波器输入快慢不同的正弦波，找出信号从哪里开始明显变弱。',
    minutes: 11,
    sections: [
      { title: '向同一个电路输入不同频率', body: '第 4 课给 RC 电路输入电压阶跃。这里改用正弦波，在输出稳定后对比输入和输出的振幅。频率越高，电容对交流信号的阻抗越小，输出越弱。' },
      { title: '用一个频率描述衰减', body: '一阶 RC 低通的截止频率 fc = 1 ÷ (2πRC)。当输入频率等于 fc，输出振幅约为输入的 70.7%，也就是约 −3 dB。电容越大，截止频率越低。' },
    ],
    task: '把电容设为 100 nF，比较 10 Hz 和 1 kHz 的振幅比，再把电容增大，在图上观察截止点往哪里移动。',
    question: {
      prompt: '电阻为 10 kΩ、电容为 100 nF。输入 159 Hz 正弦波时，输出振幅大约是输入的多少？',
      options: ['50.0%', '70.7%', '100.0%'],
      correct: 1,
      explanation: '这里的截止频率约 159 Hz。截止点的振幅比是 1 ÷ √2，约 70.7%。',
    },
  },
  {
    id: 11,
    title: '放大传感器电压',
    category: '模拟电路',
    eyebrow: 'OP-AMP GAIN',
    description: '调节同相运放的增益，观察输出接近供电轨时为什么会削顶。',
    minutes: 11,
    sections: [
      { title: '负反馈设定同相放大倍数', body: '输入接运放的同相端，反馈电阻 Rf 把输出接回反相端，Rg 从反相端接地。在线性范围内，增益为 1 + Rf ÷ Rg，输出和输入同方向变化。' },
      { title: '输出有上限，也有下限', body: '供电电压和器件的输出摆幅共同限制输出。本实验的 3.3 V 运放模型能输出 0.10–3.20 V。增益公式要求的电压超出范围时，输出会停在边界，形成削顶。' },
    ],
    task: '令 Rf 为 20 kΩ，逐步提高输入电压。先猜输出从什么时候停止增长，再观察两条曲线何时分开。',
    question: {
      prompt: 'Rg = 10 kΩ，Rf = 20 kΩ，输入 1.20 V。该模型实际输出是多少？',
      options: ['2.40 V', '3.20 V', '3.60 V'],
      correct: 1,
      explanation: '增益是 3 倍，按公式会得到 3.60 V。模型的输出上限是 3.20 V，因此实际输出被限制在 3.20 V。',
    },
  },
  {
    id: 12,
    title: '给开关加一点迟滞',
    category: '模拟电路',
    eyebrow: 'HYSTERESIS',
    description: '让缓慢变化的信号带上噪声，比较单一阈值与双阈值下的切换次数。',
    minutes: 12,
    sections: [
      { title: '信号在阈值附近会反复穿越', body: '当光照缓慢变化，叠加在信号上的波动可能让读数在阈值上下反复跳动。每穿过一次阈值就切换状态，夜灯会在临界光照附近反复开关。' },
      { title: '让上升和下降走不同的阈值', body: '本实验的比较器在输入升到上阈值时变高，降到下阈值时变低。输入落在两个阈值之间时保持上一状态。这段电压差叫迟滞宽度。用来控制夜灯时，可以把低状态接成开灯。' },
    ],
    task: '把噪声设为 80 mV，比较迟滞宽度为 0 和 200 mV 时的输出切换次数。再加大噪声，看看同样的迟滞什么时候压不住波动。',
    question: {
      prompt: '下阈值为 1.55 V，上阈值为 1.75 V。输出已经为高，输入降到 1.62 V 时会怎样？',
      options: ['切到低状态', '保持高状态', '以固定频率切换'],
      correct: 1,
      explanation: '输出已经为高，要等输入降到 1.55 V 才切到低状态。1.62 V 落在迟滞窗口内，输出保留此前状态。',
    },
  },
  {
    id: 13,
    title: '用 MOSFET 开关负载',
    category: '模拟电路',
    eyebrow: 'MOSFET SWITCH',
    description: '用低侧开关控制较大的负载电流，再从导通电阻估算压降和发热。',
    minutes: 12,
    sections: [
      { title: 'MOSFET 接在负载和地之间', body: '用 N 沟道 MOSFET 做低侧开关时，源极接地，漏极接负载，负载另一端接电源。GPIO 控制栅源电压 VGS，负载电流从供电回路流过 MOSFET。' },
      { title: '用规定条件下的导通电阻', body: '查数据手册时，找接近实际 VGS 的 RDS(on) 最大值，并留意测试温度。栅极阈值 VGS(th) 通常在很小的漏极电流下测得。充分导通时，压降可估为 I × RDS(on)，导通功耗可估为 I² × RDS(on)。' },
    ],
    task: '把导通电阻设为 50 mΩ，分别试 1 A 和 2 A。对比负载电流翻倍后，开关压降和导通功耗如何变化。',
    question: {
      prompt: '开关充分导通，RDS(on) 为 50 mΩ，流过 2 A。导通功耗是多少？',
      options: ['50 mW', '100 mW', '200 mW'],
      correct: 2,
      explanation: '功耗等于 I² × RDS(on)，也就是 (2 A)² × 0.050 Ω = 0.200 W，换算为 200 mW。',
    },
  },
  {
    id: 14,
    title: '负载突然变大时稳住电源',
    category: '模拟电路',
    eyebrow: 'CAPACITOR DROOP',
    description: '把供电下跌分成两个部分，找到电容容量和 ESR 各自能解决的问题。',
    minutes: 12,
    sections: [
      { title: '先掉一点，再慢慢往下掉', body: '负载突然多取电流时，附近的电容可以在电源来得及响应之前供电。电容的等效串联电阻 ESR 会先造成 I × ESR 的瞬时跌落。随后电容放电，电压继续以约 I ÷ C 的速率下降。' },
      { title: '容量和 ESR 影响两个不同部分', body: '在相同的负载上升电流和持续时间下，容量越大，后续下降越少。ESR 越小，负载刚变化时掉下去的电压越少。实验假设 2 ms 内新增电流全部由电容提供，忽略布线寄生参数和稳压器反馈。' },
    ],
    task: '固定新增电流，先只增大电容，再把电容复原、只降低 ESR。观察阶跃瞬间和 2 ms 末尾各有什么变化。',
    question: {
      prompt: '电容在 2 ms 内多供 100 mA，容量是 1000 μF，ESR 为 100 mΩ。总下降量约是多少？',
      options: ['10 mV', '200 mV', '210 mV'],
      correct: 2,
      explanation: '瞬时跌落为 0.1 A × 0.1 Ω = 0.01 V，放电跌落为 0.1 A × 0.002 s ÷ 0.001 F = 0.20 V，加起来是 0.21 V。',
    },
  },
  {
    id: 15,
    title: '给 ADC 采样电容充够电',
    category: '模拟电路',
    eyebrow: 'ADC SETTLING',
    description: '把第 9 课的源电阻、第 4 课的 RC 和第 5 课的 ADC 问题放在同一个采样实验里。',
    minutes: 13,
    sections: [
      { title: '采样开关闭合后，电容才开始追上输入', body: '以逐次逼近型 ADC 为例，采集窗口内，输入要通过源电阻给内部采样电容充电。如果采样时间太短，窗口结束时记录的电压就会偏离输入。源电阻越大，电容充得越慢。' },
      { title: '用半个最低有效位判断误差', body: '实验采用 3.3 V 满量程、12 位和 100 pF 采样电容。满量程阶跃要把残差降到半个最低有效位（LSB）以内，需要约 9.01 个时间常数。实物的采样电容、开关电阻和采集时序要查对应的数据手册。' },
    ],
    task: '把信号源电阻设为 10 kΩ，分别试 5 μs、9 μs 和 10 μs，找出误差何时进入半 LSB。再增大源电阻试一次。',
    question: {
      prompt: '源电阻是 10 kΩ，采样电容是 100 pF。这个 12 位模型中，哪一个采集窗口足以让满量程阶跃的残差小于半 LSB？',
      options: ['1 μs', '5 μs', '10 μs'],
      correct: 2,
      explanation: '时间常数等于 10 kΩ × 100 pF = 1 μs。满量程阶跃需要约 9.01 μs 才进入半 LSB，10 μs 足够。',
    },
  },
];

const supply = 3.3;
const voltageFormat = new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const volts = (value) => `${voltageFormat.format(value)} V`;
const milliVolts = (value) => `${value.toFixed(1)} mV`;
const kiloOhms = (value) => `${value} kΩ`;
const microseconds = (value) => `${value} μs`;
const result = (label, value) => ({ label, value });

function pointsBetween(start, end, calculate, intervals = 100) {
  return Array.from({ length: intervals + 1 }, (_, index) => {
    const x = start + (end - start) * index / intervals;
    return [x, calculate(x)];
  });
}

function frequencyLabel(frequency) {
  return frequency >= 1000 ? `${(frequency / 1000).toPrecision(3)} kHz` : `${Number(frequency.toPrecision(3))} Hz`;
}

export const analogExperiments = {
  9: {
    controls: [
      { id: 'load', label: '负载电阻', min: 1, max: 100, step: 1, initial: 10, format: kiloOhms },
    ],
    note: '电源为 3.3 V，分压器上下两只电阻都是 10 kΩ。粉色点标出当前负载对应的输出。',
    render({ load }, prefix) {
      const unloaded = supply / 2;
      const sourceResistance = 5;
      const outputAt = (resistance) => unloaded * resistance / (resistance + sourceResistance);
      const loaded = outputAt(load);

      return {
        visual: plot({
          prefix, description: `负载 ${load} 千欧时，输出 ${volts(loaded)}，空载 ${volts(unloaded)}`,
          xLabel: '负载（kΩ）', yLabel: '输出（V）', x: [0, 100], y: [0, 1.8],
          series: [
            { points: pointsBetween(0, 100, outputAt), color: colors.mint, label: '负载输出' },
            { points: [[0, unloaded], [100, unloaded]], color: colors.wire, dashed: true, label: '空载电压' },
          ],
          markers: [{ x: load, y: loaded, color: colors.pink }],
        }),
        results: [result('空载电压', volts(unloaded)), result('带负载电压', volts(loaded)), result('等效源电阻', kiloOhms(sourceResistance))],
      };
    },
  },
  10: {
    controls: [
      { id: 'capacitance', label: '电容容量', min: 1, max: 1000, step: 1, initial: 100, format: (value) => `${value} nF` },
      { id: 'frequencyDecade', label: '输入频率', min: 0, max: 5, step: 0.05, initial: 3, format: (value) => frequencyLabel(10 ** value) },
    ],
    note: '电阻固定为 10 kΩ。横轴是对数频率，每增加 1 代表频率乘以 10。粉色点是当前输入，虚线对应 −3 dB。',
    render({ capacitance, frequencyDecade }, prefix) {
      const cutoff = 1 / (2 * Math.PI * 10_000 * capacitance * 1e-9);
      const gainAt = (frequency) => 1 / Math.hypot(1, frequency / cutoff);
      const dbAt = (decade) => 20 * Math.log10(gainAt(10 ** decade));
      const ratio = gainAt(10 ** frequencyDecade);
      const db = dbAt(frequencyDecade);
      const cutoffDb = 20 * Math.log10(Math.SQRT1_2);

      return {
        visual: plot({
          prefix, description: `截止频率 ${frequencyLabel(cutoff)}，当前频率下的增益为 ${db.toFixed(2)} 分贝`,
          xLabel: 'log₁₀[频率（Hz）]', yLabel: '增益（dB）', x: [0, 5], y: [-80, 0],
          series: [
            { points: pointsBetween(0, 5, dbAt), color: colors.mint, label: '频率响应' },
            { points: [[0, cutoffDb], [5, cutoffDb]], color: colors.wire, dashed: true, label: '截止标准' },
          ],
          markers: [{ x: Math.log10(cutoff), y: cutoffDb, color: colors.wire }, { x: frequencyDecade, y: db, color: colors.pink }],
        }),
        results: [result('截止频率', frequencyLabel(cutoff)), result('输出 / 输入振幅', `${(100 * ratio).toFixed(1)}%`), result('当前增益', `${db.toFixed(2)} dB`)],
      };
    },
  },
  11: {
    controls: [
      { id: 'input', label: '输入电压', min: 0, max: 1.5, step: 0.05, initial: 1.2, format: volts },
      { id: 'feedback', label: '反馈电阻 Rf', min: 0, max: 40, step: 1, initial: 20, format: kiloOhms },
    ],
    note: 'Rg 固定为 10 kΩ。模型假定输入位于允许的共模范围内，输出摆幅固定为 0.10–3.20 V。',
    render({ input, feedback }, prefix) {
      const gain = 1 + feedback / 10;
      const actualAt = (voltage) => Math.min(3.2, Math.max(0.1, voltage * gain));
      const ideal = input * gain;
      const actual = actualAt(input);

      return {
        visual: plot({
          prefix, description: `输入 ${volts(input)}，${gain} 倍增益，按增益推算 ${volts(ideal)}，实际输出 ${volts(actual)}`,
          xLabel: '输入（V）', yLabel: '输出（V）', x: [0, 1.5], y: [0, 8],
          series: [
            { points: [[0, 0], [1.5, 1.5 * gain]], color: colors.wire, dashed: true, label: '按增益推算' },
            { points: pointsBetween(0, 1.5, actualAt), color: colors.mint, label: '实际输出' },
          ],
          markers: [{ x: input, y: actual, color: colors.pink }],
        }),
        results: [result('闭环增益', `${gain.toFixed(1)} 倍`), result('按增益推算', volts(ideal)), result('实际输出', volts(actual))],
      };
    },
  },
  12: {
    controls: [
      { id: 'noise', label: '噪声振幅', min: 0, max: 180, step: 5, initial: 80, format: (value) => `${value} mV` },
      { id: 'width', label: '迟滞宽度', min: 0, max: 500, step: 10, initial: 200, format: (value) => `${value} mV` },
    ],
    note: '比较器从低状态开始。虚线是切换阈值，粉色点标出输出状态发生变化的时刻。',
    render({ noise, width }, prefix) {
      const center = 1.65;
      const low = center - width / 2000;
      const high = center + width / 2000;
      const samples = pointsBetween(0, 10, (time) => center + 0.4 * (1 - Math.abs(time - 5) / 2.5)
        + noise / 1000 * Math.sin(2 * Math.PI * 3 * time), 600);
      const markers = [];
      let isHigh = false;

      for (const [time, voltage] of samples) {
        const nextHigh = isHigh && width > 0 ? voltage > low : voltage >= high;
        if (nextHigh !== isHigh) {
          markers.push({ x: time, y: voltage, color: colors.pink });
          isHigh = nextHigh;
        }
      }

      return {
        visual: plot({
          prefix, description: `上阈值 ${volts(high)}，下阈值 ${volts(low)}，输出切换 ${markers.length} 次`,
          xLabel: '时间（s）', yLabel: '输入（V）', x: [0, 10], y: [1, 2.3],
          series: [
            { points: samples, color: colors.mint, label: '带噪输入' },
            { points: [[0, low], [10, low]], color: colors.wire, dashed: true, label: '切换阈值' },
            ...(width > 0 ? [{ points: [[0, high], [10, high]], color: colors.wire, dashed: true }] : []),
          ],
          markers,
        }),
        results: [result('上阈值', `${high.toFixed(3)} V`), result('下阈值', `${low.toFixed(3)} V`), result('切换次数', `${markers.length} 次`)],
      };
    },
  },
  13: {
    controls: [
      { id: 'current', label: '负载电流', min: 0.1, max: 3, step: 0.1, initial: 1, format: (value) => `${value.toFixed(1)} A` },
      { id: 'onResistance', label: 'MOSFET 导通电阻', min: 15, max: 250, step: 5, initial: 50, format: (value) => `${value} mΩ` },
    ],
    note: '模型假设栅极驱动充足，只计算持续导通时的损耗。数据手册的导通电阻会随栅源电压和温度变化。',
    render({ current, onResistance }, prefix) {
      const drop = current * onResistance;
      const lossAt = (amps) => amps ** 2 * onResistance;
      const loss = lossAt(current);
      const lossLimit = Math.ceil(lossAt(3) / 100) * 100;

      return {
        visual: plot({
          prefix, description: `负载电流 ${current} 安，导通电阻 ${onResistance} 毫欧，导通损耗 ${loss.toFixed(1)} 毫瓦`,
          xLabel: '负载电流（A）', yLabel: '导通功耗（mW）', x: [0, 3], y: [0, lossLimit],
          series: [{ points: pointsBetween(0, 3, lossAt), color: colors.mint, label: 'I²R 损耗' }],
          markers: [{ x: current, y: loss, color: colors.pink }],
        }),
        results: [result('导通压降', milliVolts(drop)), result('导通功耗', `${loss.toFixed(1)} mW`)],
      };
    },
  },
  14: {
    controls: [
      { id: 'capacitance', label: '电容容量', min: 220, max: 2200, step: 10, initial: 470, format: (value) => `${value} μF` },
      { id: 'esr', label: '等效串联电阻 ESR', min: 20, max: 500, step: 10, initial: 100, format: (value) => `${value} mΩ` },
      { id: 'stepCurrent', label: '新增负载电流', min: 50, max: 200, step: 25, initial: 100, format: (value) => `${value} mA` },
    ],
    note: '负载在 0 ms 突然增加。电容在随后 2 ms 提供全部新增电流。',
    render({ capacitance, esr, stepCurrent }, prefix) {
      const initialDrop = stepCurrent * esr / 1e6;
      const dischargeDrop = stepCurrent * 2 / capacitance;
      const after = supply - initialDrop - dischargeDrop;

      return {
        visual: plot({
          prefix, description: `初始电压 3.3 伏，瞬时跌落 ${milliVolts(initialDrop * 1000)}，2 毫秒后电压 ${volts(after)}`,
          xLabel: '时间（ms）', yLabel: '供电（V）', x: [-0.25, 2], y: [1.3, 3.4],
          series: [{ points: [[-0.25, supply], [0, supply], [0, supply - initialDrop], [2, after]], color: colors.mint, label: '供电电压' }],
          markers: [{ x: 0, y: supply - initialDrop, color: colors.pink }, { x: 2, y: after, color: colors.pink }],
        }),
        results: [result('ESR 瞬时跌落', milliVolts(initialDrop * 1000)), result('2 ms 放电跌落', milliVolts(dischargeDrop * 1000)), result('2 ms 后供电', volts(after))],
      };
    },
  },
  15: {
    controls: [
      { id: 'resistance', label: '信号源电阻', min: 1, max: 100, step: 1, initial: 10, format: kiloOhms },
      { id: 'window', label: '采集窗口', min: 1, max: 100, step: 1, initial: 5, format: microseconds },
    ],
    note: '采样电容固定为 100 pF，从 0 V 向 3.3 V 充电。曲线在采集窗口结束处停止，虚线表示目标电压。',
    render({ resistance, window }, prefix) {
      const tau = resistance * 0.1;
      const error = supply * Math.exp(-window / tau);
      const halfLsb = supply / 8192;
      const end = Math.max(10, window * 1.1);

      return {
        visual: plot({
          prefix, description: `时间常数 ${tau.toFixed(1)} 微秒，采集持续 ${window} 微秒，采样电压 ${volts(supply - error)}`,
          xLabel: '时间（μs）', yLabel: '采样电压（V）', x: [0, end], y: [0, 3.5],
          series: [
            { points: pointsBetween(0, window, (time) => supply * (1 - Math.exp(-time / tau)), 200), color: colors.mint, label: '采样电容' },
            { points: [[0, supply], [end, supply]], color: colors.wire, dashed: true, label: '目标电压' },
          ],
          markers: [{ x: window, y: supply - error, color: colors.pink }],
        }),
        results: [
          result('时间常数', microseconds(tau.toFixed(1))),
          result('采样残差', error * 1000 >= 0.001 ? `${(error * 1000).toFixed(3)} mV` : '低于 0.001 mV'),
          result('与半 LSB 比较', error <= halfLsb ? '半 LSB 以内' : '超过半 LSB'),
        ],
      };
    },
  },
};
