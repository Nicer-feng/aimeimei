const colors = {
  wire: '#ad9cdd',
  quiet: '#b8a9d0',
  ink: '#f7edff',
  pink: '#f0a0eb',
  mint: '#a7f3cb',
  line: '#54426c',
  panel: '#221630',
};

const number = (value, digits = 0) => value.toFixed(digits);
const readAdc = (voltage) => Math.round(voltage / 3.3 * 4095);
const volts = (value) => `${number(value, 2)} V`;
const percent = (value) => `${number(value)}%`;
const result = (label, value) => ({ label, value });

function label(x, y, text, options = {}) {
  const { size = 18, color = colors.ink, anchor = 'middle', mono = false, weight = 500 } = options;
  const font = mono ? 'ui-monospace, SFMono-Regular, Menlo, monospace' : 'inherit';
  return `<text x="${x}" y="${y}" text-anchor="${anchor}" fill="${color}" font-family="${font}"
    font-size="${size}" font-weight="${weight}">${text}</text>`;
}

function stroke(path, color = colors.wire, width = 2.5, dashed = false) {
  return `<path d="${path}" fill="none" stroke="${color}" stroke-width="${width}"
    stroke-linecap="round" stroke-linejoin="round"${dashed ? ' stroke-dasharray="4 5"' : ''}/>`;
}

function point(x, y, radius, color) {
  return `<circle cx="${x}" cy="${y}" r="${radius}" fill="${color}"/>`;
}

function canvas(prefix, description, content) {
  return `<svg viewBox="20 0 480 208" width="480" height="208" role="img" aria-label="${description}">
    <defs>
      <radialGradient id="${prefix}-glow">
        <stop stop-color="#f8acff" stop-opacity=".55"/><stop offset="1" stop-color="#f8acff" stop-opacity="0"/>
      </radialGradient>
    </defs>
    ${content}
  </svg>`;
}

function lamp(x, y, brightness, prefix) {
  const level = brightness / 100;
  const outline = brightness > 0 ? colors.pink : colors.line;
  return `<circle cx="${x}" cy="${y}" r="49" fill="url(#${prefix}-glow)" opacity="${level}"/>
    <circle cx="${x}" cy="${y}" r="22" fill="${colors.panel}" stroke="${outline}" stroke-width="2"/>
    <circle cx="${x}" cy="${y}" r="13" fill="${colors.pink}" opacity="${level * .87}"/>
    ${stroke(`M${x - 8} ${y + 5} l5 -10 6 10 5 -10`, brightness > 0 ? colors.ink : colors.quiet, 1.5)}
    ${stroke(`M${x - 8} ${y + 28} h16 m-12 5 h8`, outline, 1.8)}`;
}

function circuit({ voltage, resistance }, current, hasLed, prefix) {
  const on = current > 0;
  const currentText = `${number(current, 2)} mA`;
  const led = hasLed ? `
    ${stroke('M382 68 V100 M382 123 V155')}
    <path d="M370 100 H394 L382 120 Z" fill="${on ? '#654068' : 'none'}" stroke="${colors.pink}" stroke-width="2"/>
    ${stroke('M370 122 h24', colors.pink, 2)}
    ${stroke('M400 104 l14 -14 m-7 0 h7 v7 M405 116 l14 -14 m-7 0 h7 v7', on ? colors.pink : colors.line, 1.7)}
    ${label(427, 133, on ? '发光' : '熄灭', { color: on ? colors.pink : colors.quiet, size: 16 })}
  ` : stroke('M382 68 V155');

  return canvas(prefix, `供电 ${volts(voltage)}，电阻 ${resistance} 欧姆，回路电流 ${currentText}${hasLed ? `，LED ${on ? '发光' : '熄灭'}` : ''}`, `
    ${stroke('M138 104 V68 H214 M304 68 H382 M382 155 H138 V124')}
    ${stroke('M214 68 l8 -11 11 22 11 -22 11 22 11 -22 11 22 11 -22 8 11 h8', colors.pink)}
    ${stroke('M123 104 h30 M129 124 h18')}
    ${label(102, 116, volts(voltage), { anchor: 'end', color: colors.ink, size: 18, mono: true })}
    ${label(165, 102, '+', { size: 16, color: colors.quiet })}
    ${label(165, 133, '−', { size: 16, color: colors.quiet })}
    ${label(258, 43, `R = ${resistance} Ω`, { color: colors.pink, size: 18, mono: true })}
    ${led}
    ${on ? stroke('M277 155 h-33 m0 0 l8 -5 m-8 5 l8 5', colors.mint, 2) : ''}
    ${label(258, 189, `I = ${currentText}`, { color: colors.mint, size: 19, mono: true })}
  `);
}

function divider({ lower }, voltage, prefix) {
  return canvas(prefix, `分压输入 3.3 伏，上方电阻 10 千欧，下方电阻 ${lower} 千欧，输出 ${volts(voltage)}`, `
    ${stroke('M212 37 V48 M212 91 V122 M212 165 V186')}
    ${stroke('M212 48 l-8 5 16 7 -16 7 16 7 -16 7 8 10', colors.wire)}
    ${stroke('M212 122 l-8 5 16 7 -16 7 16 7 -16 7 8 10', colors.pink)}
    ${stroke('M197 186 h30 m-24 6 h18 m-14 6 h10')}
    ${stroke('M212 106 H388', colors.mint)}
    ${point(212, 106, 4.5, colors.mint)}
    ${point(388, 106, 4, colors.mint)}
    ${label(212, 29, '3.30 V', { color: colors.quiet, mono: true })}
    ${label(187, 74, '10 kΩ', { anchor: 'end', mono: true })}
    ${label(187, 150, `${lower} kΩ`, { anchor: 'end', color: colors.pink, mono: true })}
    ${label(354, 87, volts(voltage), { color: colors.mint, mono: true, size: 21 })}
    ${label(354, 135, '输出电压', { color: colors.quiet })}
  `);
}

function chargingCurve(tau, prefix) {
  const x = (seconds) => 67 + seconds * 40;
  const y = (voltage) => 163 - voltage / 3.3 * 110;
  const timeConstantVoltage = 3.3 * (1 - Math.exp(-1));
  const path = Array.from({ length: 201 }, (_, index) => {
    const seconds = index / 20;
    const voltage = 3.3 * (1 - Math.exp(-seconds / tau));
    return `${index === 0 ? 'M' : 'L'}${number(x(seconds), 1)} ${number(y(voltage), 1)}`;
  }).join(' ');

  return canvas(prefix, `电容充电曲线，时间常数 ${number(tau, 2)} 秒`, `
    ${stroke('M67 41 V163 H477', colors.wire, 1.5)}
    ${stroke('M67 53 H467', colors.line, 1.4, true)}
    ${label(53, 58, '3.3 V', { anchor: 'end', color: colors.quiet, size: 15 })}
    ${[0, 2, 4, 6, 8, 10].map((seconds) => `
      ${stroke(`M${x(seconds)} 163 v6`, colors.wire, 1.4)}
      ${label(x(seconds), 188, seconds === 10 ? '10 s' : seconds, { color: colors.quiet, mono: true, size: 16 })}
    `).join('')}
    ${stroke(`M${x(tau)} 163 V${y(timeConstantVoltage)}`, colors.pink, 1.5, true)}
    ${stroke(path, colors.mint)}
    ${point(x(tau), y(timeConstantVoltage), 4.7, colors.pink)}
    ${label(Math.min(Math.max(x(tau) + 71, 145), 397), y(timeConstantVoltage) + 24, `τ = ${number(tau, 2)} s`, {
      color: colors.pink, mono: true, size: 16,
    })}
  `);
}

function signalBox(center, heading, value, valueColor) {
  return `<rect x="${center - 58}" y="66" width="116" height="78" rx="10" fill="${colors.panel}" stroke="${colors.line}"/>
    ${label(center, 94, heading, { color: colors.quiet, size: 17 })}
    ${label(center, 123, value, { color: valueColor, size: 20, mono: true, weight: 600 })}`;
}

function routeArrow(start, end, y) {
  return stroke(`M${start} ${y} H${end} m-6 -4 l6 4 -6 4`, colors.wire, 1.8);
}

function converter({ voltage }, reading, prefix) {
  const binary = reading.toString(2).padStart(12, '0');
  const grouped = `${binary.slice(0, 4)} ${binary.slice(4, 8)} ${binary.slice(8)}`;

  return canvas(prefix, `输入 ${volts(voltage)}，12 位 ADC 读数 ${reading}，二进制 ${grouped}`, `
    ${signalBox(99, '模拟电压', volts(voltage), colors.pink)}
    ${routeArrow(166, 194, 105)}
    ${signalBox(260, '量化精度', '12 位', colors.ink)}
    ${routeArrow(327, 355, 105)}
    ${signalBox(421, '数字读数', reading, colors.mint)}
    ${label(421, 165, grouped, { mono: true, size: 15, color: colors.quiet })}
    <rect x="57" y="130" width="84" height="3" rx="1.5" fill="${colors.line}"/>
    <rect x="57" y="130" width="${84 * voltage / 3.3}" height="3" rx="1.5" fill="${colors.pink}"/>
  `);
}

function lightReadings(light) {
  const resistance = 100 * Math.pow(0.01, light / 100);
  const voltage = 3.3 * 10 / (resistance + 10);
  return { voltage, reading: readAdc(voltage) };
}

function thresholdView({ light, threshold }, reading, on, prefix) {
  const marker = (value) => 59 + value / 4095 * 307;
  const left = marker(0);
  const right = marker(4095);

  return canvas(prefix, `模拟光照 ${percent(light)}，ADC 读数 ${reading}，阈值 ${threshold}，灯${on ? '亮' : '灭'}`, `
    ${label(60, 44, '光照输入', { anchor: 'start', color: colors.quiet, size: 16 })}
    ${label(167, 44, percent(light), { color: colors.pink, size: 20, mono: true })}
    <rect x="${left}" y="94" width="${right - left}" height="12" rx="6" fill="${colors.line}"/>
    <rect x="${left}" y="94" width="${marker(reading) - left}" height="12" rx="6" fill="${colors.mint}"/>
    ${stroke(`M${marker(threshold)} 80 V121`, colors.pink, 3)}
    ${label(Math.min(330, Math.max(105, marker(threshold))), 142, `阈值 ${threshold}`, { color: colors.pink, mono: true, size: 15 })}
    ${label(left, 131, '0', { color: colors.quiet, size: 15 })}
    ${label(right, 131, '4095', { color: colors.quiet, size: 15 })}
    ${label(59, 174, `当前读数 ${reading}`, { anchor: 'start', color: colors.mint, size: 19, mono: true })}
    ${lamp(441, 99, on ? 100 : 0, prefix)}
    ${label(441, 161, on ? '灯亮' : '灯灭', { color: on ? colors.pink : colors.quiet, size: 18 })}
  `);
}

function pwmPulse(duty) {
  const start = 75;
  const period = 100;
  const high = 64;
  const low = 131;
  const segments = Array.from({ length: 3 }, (_, cycle) => {
    const edge = start + cycle * period;
    return `V${high} H${edge + period * duty / 100} V${low} H${edge + period}`;
  }).join(' ');

  if (duty === 0 || duty === 100) {
    return `M${start} ${duty === 100 ? high : low} H${start + 3 * period}`;
  }

  return `M${start} ${low} ${segments}`;
}

function waveform({ duty }, prefix) {
  return canvas(prefix, `1 千赫兹 PWM，${percent(duty)} 占空比，LED 模拟亮度 ${percent(duty)}`, `
    ${stroke('M75 50 V148 H384', colors.wire, 1.5)}
    ${stroke('M75 64 H375 M75 131 H375 M175 54 V148 M275 54 V148 M375 54 V148', colors.line, 1.4, true)}
    ${stroke(pwmPulse(duty), colors.mint)}
    ${label(61, 69, '3.3 V', { anchor: 'end', color: colors.quiet, size: 15 })}
    ${label(61, 136, '0 V', { anchor: 'end', color: colors.quiet, size: 15 })}
    ${label(75, 173, '0', { color: colors.quiet, size: 16 })}
    ${label(175, 173, '1 ms', { color: colors.quiet, size: 16 })}
    ${label(275, 173, '2 ms', { color: colors.quiet, size: 16 })}
    ${label(375, 173, '3 ms', { color: colors.quiet, size: 16 })}
    ${lamp(442, 94, duty, prefix)}
    ${label(442, 164, `亮度 ${percent(duty)}`, { color: colors.pink, size: 17 })}
  `);
}

function nightlight({ light, threshold, duty }, reading, brightness, prefix) {
  const op = reading < threshold ? '&lt;' : '≥';

  return canvas(prefix, `光照 ${percent(light)}，ADC 读数 ${reading}，阈值 ${threshold}，设定占空比 ${percent(duty)}，亮度 ${percent(brightness)}`, `
    ${signalBox(82, '模拟光照', percent(light), colors.pink)}
    ${routeArrow(147, 173, 105)}
    ${signalBox(238, 'ADC 读数', reading, colors.mint)}
    ${routeArrow(303, 328, 105)}
    ${label(391, 52, '与开灯阈值比较', { color: colors.quiet, size: 16 })}
    ${label(391, 79, `${op} ${threshold}`, { color: colors.mint, size: 19, mono: true })}
    ${lamp(391, 119, brightness, prefix)}
    ${label(391, 180, `灯光亮度 ${percent(brightness)}`, { color: colors.pink, size: 17 })}
  `);
}

const supply = { id: 'voltage', label: '电源电压', min: 1, max: 5, step: 0.1, initial: 3.3, format: volts };
const resistor = { id: 'resistance', label: '电阻阻值', min: 100, max: 1000, step: 10, initial: 330, format: (value) => `${value} Ω` };
const light = { id: 'light', label: '模拟光照', min: 0, max: 100, step: 1, initial: 30, format: percent };
const threshold = { id: 'threshold', label: '开灯阈值', min: 0, max: 4095, step: 1, initial: 2048, format: number };
const duty = { id: 'duty', label: 'PWM 占空比', min: 0, max: 100, step: 1, initial: 40, format: percent };

const experiments = {
  1: {
    controls: [supply, resistor],
    note: '模型将导线视为理想导体，回路电流由电源电压和电阻决定。',
    render(values, prefix) {
      const current = values.voltage / values.resistance * 1000;
      return {
        visual: circuit(values, current, false, prefix),
        results: [result('电阻两端电压', volts(values.voltage)), result('回路电流', `${number(current, 2)} mA`)],
      };
    },
  },
  2: {
    controls: [supply, { ...resistor, label: '限流电阻' }],
    note: '这里将 LED 的正向压降简化为 2.00 V，实际压降取决于型号、电流和温度。',
    render(values, prefix) {
      const acrossResistor = Math.max(0, values.voltage - 2);
      const current = acrossResistor / values.resistance * 1000;
      return {
        visual: circuit(values, current, true, prefix),
        results: [result('限流电阻压降', volts(acrossResistor)), result('LED 电流', `${number(current, 2)} mA`)],
      };
    },
  },
  3: {
    controls: [{ id: 'lower', label: '下方电阻', min: 1, max: 30, step: 1, initial: 10, format: (value) => `${value} kΩ` }],
    note: '上方电阻固定为 10 kΩ，读数采用分压输出端空载的模型。',
    render(values, prefix) {
      const ratio = values.lower / (10 + values.lower);
      const voltage = 3.3 * ratio;
      return {
        visual: divider(values, voltage, prefix),
        results: [result('输出电压', volts(voltage)), result('输出占输入的比例', percent(ratio * 100))],
      };
    },
  },
  4: {
    controls: [{ id: 'capacitance', label: '电容量', min: 10, max: 1000, step: 10, initial: 100, format: (value) => `${value} µF` }],
    note: '电阻固定为 10 kΩ。曲线显示接通 3.3 V 后电容两端的电压，粉色圆点标出一个时间常数。',
    render({ capacitance }, prefix) {
      const tau = 10000 * capacitance * 1e-6;
      return {
        visual: chargingCurve(tau, prefix),
        results: [result('时间常数 τ', `${number(tau, 2)} s`), result('一个 τ 后的电压', volts(3.3 * (1 - Math.exp(-1))))],
      };
    },
  },
  5: {
    controls: [{ ...supply, label: '模拟输入电压', min: 0, max: 3.3, step: 0.01, initial: 1.65 }],
    note: '本实验将 0–3.3 V 映射到 0–4095 并四舍五入。实际 ESP32 的测量范围和精度取决于芯片型号、衰减设置和校准。',
    render(values, prefix) {
      const reading = readAdc(values.voltage);
      return {
        visual: converter(values, reading, prefix),
        results: [result('模拟输入电压', volts(values.voltage)), result('数字读数', reading)],
      };
    },
  },
  6: {
    controls: [light, threshold],
    note: '模拟光照越强，位于分压上方的光敏电阻越小，ADC 读数越高。读数小于阈值时开灯。',
    render(values, prefix) {
      const { voltage, reading } = lightReadings(values.light);
      const on = reading < values.threshold;
      return {
        visual: thresholdView(values, reading, on, prefix),
        results: [result('分压点电压', volts(voltage)), result('GPIO 控灯状态', on ? '灯亮' : '灯灭')],
      };
    },
  },
  7: {
    controls: [duty],
    note: '周期固定为 1 ms。亮度按占空比作示意，实际观感还受到 LED 和人眼响应的影响。',
    render(values, prefix) {
      return {
        visual: waveform(values, prefix),
        results: [result('每周期高电平时间', `${number(values.duty / 100, 2)} ms`), result('LED 模拟亮度', percent(values.duty))],
      };
    },
  },
  8: {
    controls: [light, threshold, duty],
    note: 'ADC 读数低于阈值时，输出按设定的占空比驱动 LED。达到阈值时，输出回到 0%。',
    render(values, prefix) {
      const { reading } = lightReadings(values.light);
      const brightness = reading < values.threshold ? values.duty : 0;
      return {
        visual: nightlight(values, reading, brightness, prefix),
        results: [result('数字读数', reading), result('实际输出占空比', percent(brightness))],
      };
    },
  },
};

let nextMount = 0;

export function mountExperiment(container, lessonId) {
  const experiment = experiments[Number(lessonId)];
  if (!experiment) {
    container.replaceChildren();
    return;
  }

  const prefix = `lab-${++nextMount}`;
  const values = Object.fromEntries(experiment.controls.map(({ id, initial }) => [id, initial]));
  const first = experiment.render(values, prefix);
  container.innerHTML = `
    <div class="lab-visual">${first.visual}</div>
    <div class="lab-controls">
      ${experiment.controls.map(({ id, label, min, max, step, initial, format }) => {
        const inputId = `${prefix}-${id}`;
        return `<div class="lab-control">
          <label class="lab-control-head" for="${inputId}">
            <span id="${inputId}-label">${label}</span>
            <output for="${inputId}" aria-live="off">${format(initial)}</output>
          </label>
          <input id="${inputId}" type="range" min="${min}" max="${max}" step="${step}" value="${initial}"
            aria-labelledby="${inputId}-label" aria-valuetext="${format(initial)}"
            style="--range-progress: ${(initial - min) / (max - min) * 100}%">
        </div>`;
      }).join('')}
    </div>
    <div class="lab-results" aria-live="polite">
      ${first.results.map(({ label, value }) => `<div class="lab-result">
        <span class="lab-result-label">${label}</span><strong class="lab-result-value">${value}</strong>
      </div>`).join('')}
    </div>
    <p class="lab-note">${experiment.note}</p>
  `;

  const visual = container.querySelector('.lab-visual');
  const resultValues = container.querySelectorAll('.lab-result-value');
  const sliderGroups = container.querySelectorAll('.lab-control');
  experiment.controls.forEach(({ id, min, max, format }, index) => {
    const input = sliderGroups[index].querySelector('input');
    const output = sliderGroups[index].querySelector('output');
    input.addEventListener('input', () => {
      values[id] = input.valueAsNumber;
      const formatted = format(values[id]);
      output.value = formatted;
      input.setAttribute('aria-valuetext', formatted);
      input.style.setProperty('--range-progress', `${(values[id] - min) / (max - min) * 100}%`);
      const updated = experiment.render(values, prefix);
      visual.innerHTML = updated.visual;
      updated.results.forEach(({ value }, resultIndex) => {
        resultValues[resultIndex].textContent = value;
      });
    });
  });
}
