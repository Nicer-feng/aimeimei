import { lessons } from "./lessons.js";
import { mountExperiment } from "./experiments.js";

const storageKey = "feng-electronics-lab:progress:v1";
const lessonIds = new Set(lessons.map(({ id }) => id));
const elements = {
  route: document.querySelector("#route"),
  routeLink: document.querySelector("#route-link"),
  routeLessons: document.querySelector("#route-lessons"),
  routeSummary: document.querySelector("#route-summary"),
  routeToggle: document.querySelector("#route-toggle"),
  storageMessage: document.querySelector("#storage-message"),
  progressFill: document.querySelector("#progress-fill"),
  progressLabel: document.querySelector("#progress-label"),
  projectCtaLabel: document.querySelector("#project-cta-label"),
  lessonIndex: document.querySelector("#lesson-index"),
  lessonCategory: document.querySelector("#lesson-category"),
  lessonTime: document.querySelector("#lesson-time"),
  lessonTitle: document.querySelector("#lesson-title"),
  lessonDescription: document.querySelector("#lesson-description"),
  labTask: document.querySelector("#lab-task"),
  experiment: document.querySelector("#experiment"),
  lessonSections: document.querySelector("#lesson-sections"),
  chipExplorer: document.querySelector("#chip-explorer"),
  chipPartTitle: document.querySelector("#chip-part-title"),
  chipPartDescription: document.querySelector("#chip-part-description"),
  quizForm: document.querySelector("#quiz-form"),
  quizPrompt: document.querySelector("#quiz-prompt"),
  quizOptions: document.querySelector("#quiz-options"),
  quizFeedback: document.querySelector("#quiz-feedback"),
  quizSubmit: document.querySelector("#quiz-submit"),
  lessonFooter: document.querySelector("#lesson-footer"),
};

const icons = {
  time: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
};

const chipParts = {
  adc: {
    title: "ADC · 把电压变成读数",
    description: "光敏分压点接到支持 ADC 的引脚。ADC 采样这个电压后，程序就能拿到一个整数，用它判断周围有多亮。",
  },
  gpio: {
    title: "GPIO · 让引脚输出高低电平",
    description: "把 GPIO 设为输出后，程序可以按光照判断结果写入高电平或低电平。在本课的接法里，高电平经限流电阻点亮 LED。",
  },
  pwm: {
    title: "PWM 定时器 · 反复生成脉冲",
    description: "定时器按设定的周期重复计时，PWM 控制器在每个周期内切换引脚电平。周期为 1 ms、占空比为 25% 时，引脚在每个周期中保持 0.25 ms 高电平。",
  },
};
const chipPartByLesson = { 5: "adc", 6: "gpio", 7: "pwm" };
const chipButtons = elements.chipExplorer.querySelectorAll("[data-part]");

const progress = loadProgress();
const routeButtons = new Map();
let currentQuizSolved = false;

function loadProgress() {
  const initial = { active: lessons[0].id, completed: new Set() };
  let serialized;
  try {
    serialized = localStorage.getItem(storageKey);
  } catch {
    elements.storageMessage.textContent = "浏览器限制了存储，进度仅在当前页面保留";
    return initial;
  }

  if (!serialized) return initial;

  try {
    const saved = JSON.parse(serialized);
    const active = lessonIds.has(saved?.active) ? saved.active : initial.active;
    const completed = Array.isArray(saved?.completed)
      ? new Set(saved.completed.filter((id) => lessonIds.has(id)))
      : initial.completed;
    return { active, completed };
  } catch {
    return initial;
  }
}

function saveProgress() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      active: progress.active,
      completed: [...progress.completed],
    }));
  } catch {
    elements.storageMessage.textContent = "浏览器限制了存储，进度仅在当前页面保留";
  }
}

function createTextElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = content;
  return element;
}

function setRouteOpen(open) {
  elements.route.classList.toggle("is-open", open);
  elements.routeToggle.setAttribute("aria-expanded", String(open));
  elements.routeToggle.querySelector(".sr-only").textContent = open ? "收起学习路线" : "展开学习路线";
}

function renderRoute() {
  const totalMinutes = lessons.reduce((total, lesson) => total + lesson.minutes, 0);
  elements.routeSummary.textContent = `共 ${lessons.length} 节课 · 约 ${totalMinutes} 分钟`;

  for (const lesson of lessons) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "route-lesson";
    const number = createTextElement("span", "route-lesson-number", String(lesson.id).padStart(2, "0"));
    const text = document.createElement("span");
    text.append(
      createTextElement("span", "route-lesson-title", lesson.title),
      createTextElement("span", "route-lesson-category", lesson.category),
    );
    const status = document.createElement("span");
    status.className = "route-lesson-icon";
    button.append(number, text, status);
    button.addEventListener("click", () => selectLesson(lesson.id));
    routeButtons.set(lesson.id, { button, status });
    elements.routeLessons.append(button);
  }
}

function updateProgress() {
  const completeCount = progress.completed.size;
  elements.progressFill.style.width = `${(completeCount / lessons.length) * 100}%`;
  elements.progressFill.parentElement.setAttribute("aria-valuenow", String(completeCount));
  elements.progressLabel.textContent = `${completeCount} / ${lessons.length} 节已完成`;
  elements.projectCtaLabel.textContent = completeCount === lessons.length
    ? "回顾课程"
    : progress.active === lessons[0].id && completeCount === 0 ? "开始学习" : "继续学习";

  for (const [id, { button, status }] of routeButtons) {
    const active = id === progress.active;
    const completed = progress.completed.has(id);
    if (active) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
    button.classList.toggle("is-done", completed);
    status.innerHTML = completed ? icons.check : active ? icons.arrow : "";
    if (completed) status.append(createTextElement("span", "sr-only", "已完成"));
  }
}

function activeLesson() {
  return lessons.find(({ id }) => id === progress.active);
}

function selectLesson(id) {
  if (id !== progress.active) {
    progress.active = id;
    saveProgress();
    renderLesson();
  }
  setRouteOpen(false);
  elements.lessonTitle.focus({ preventScroll: true });
  elements.lessonTitle.scrollIntoView({ block: "start" });
}

function selectChipPart(part) {
  elements.chipPartTitle.textContent = chipParts[part].title;
  elements.chipPartDescription.textContent = chipParts[part].description;
  for (const button of chipButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.part === part));
  }
}

function renderLesson() {
  const lesson = activeLesson();
  elements.lessonIndex.textContent = `第 ${lesson.id} 课`;
  elements.lessonCategory.textContent = lesson.category;
  elements.lessonTime.innerHTML = icons.time;
  elements.lessonTime.append(`约 ${lesson.minutes} 分钟`);
  elements.lessonTitle.textContent = lesson.title;
  elements.lessonDescription.textContent = lesson.description;
  elements.labTask.textContent = lesson.task;
  mountExperiment(elements.experiment, lesson.id);

  elements.lessonSections.replaceChildren(...lesson.sections.map(({ title, body }) => {
    const section = document.createElement("div");
    section.append(createTextElement("h4", "", title), createTextElement("p", "", body));
    return section;
  }));

  const chipPart = chipPartByLesson[lesson.id];
  elements.chipExplorer.hidden = !chipPart;
  elements.chipExplorer.open = false;
  if (chipPart) selectChipPart(chipPart);

  renderQuiz(lesson);
  updateProgress();
}

function renderQuiz(lesson) {
  currentQuizSolved = false;
  elements.quizPrompt.textContent = lesson.question.prompt;
  elements.quizOptions.replaceChildren(...lesson.question.options.map((option, index) => {
    const label = document.createElement("label");
    label.className = "quiz-option";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = String(index);
    label.append(input, createTextElement("span", "", option));
    return label;
  }));
  elements.quizFeedback.textContent = "";
  elements.quizFeedback.classList.remove("is-correct");
  elements.quizSubmit.textContent = "检查答案";
  elements.quizSubmit.disabled = true;
  renderLessonFooter(lesson);
}

function renderLessonFooter(lesson) {
  elements.lessonFooter.replaceChildren();
  if (!progress.completed.has(lesson.id)) return;

  const allComplete = progress.completed.size === lessons.length;
  elements.lessonFooter.append(createTextElement("p", "", allComplete ? "全部 8 节课已完成" : "本课已完成"));
  const next = lessons.find(({ id }) => id > lesson.id && !progress.completed.has(id))
    ?? lessons.find(({ id }) => !progress.completed.has(id));
  if (!next) return;

  const button = createTextElement("button", "secondary-button", next.id > lesson.id ? "下一课" : "继续未完成的课");
  button.type = "button";
  button.addEventListener("click", () => selectLesson(next.id));
  elements.lessonFooter.append(button);
}

elements.routeToggle.addEventListener("click", () => {
  setRouteOpen(elements.routeToggle.getAttribute("aria-expanded") !== "true");
});

elements.routeLink.addEventListener("click", () => setRouteOpen(true));

for (const button of chipButtons) {
  button.addEventListener("click", () => selectChipPart(button.dataset.part));
}

elements.quizOptions.addEventListener("change", () => {
  if (currentQuizSolved) return;
  elements.quizSubmit.disabled = false;
  elements.quizSubmit.textContent = "检查答案";
  elements.quizFeedback.textContent = "";
});

elements.quizForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const selected = elements.quizOptions.querySelector("input:checked");
  if (!selected || currentQuizSolved) return;

  const lesson = activeLesson();
  const { correct, explanation } = lesson.question;
  if (Number(selected.value) !== correct) {
    elements.quizFeedback.textContent = "再试一次。可以先回到实验调一调参数。";
    elements.quizSubmit.disabled = true;
    return;
  }

  currentQuizSolved = true;
  elements.quizFeedback.textContent = `答对了。${explanation}`;
  elements.quizFeedback.classList.add("is-correct");
  selected.closest("label").classList.add("is-correct");
  selected.focus({ preventScroll: true });
  for (const input of elements.quizOptions.querySelectorAll("input")) {
    input.disabled = true;
  }
  elements.quizSubmit.disabled = true;
  elements.quizSubmit.textContent = "已答对";
  progress.completed.add(lesson.id);
  saveProgress();
  updateProgress();
  renderLessonFooter(lesson);
  elements.lessonFooter.querySelector("button")?.focus({ preventScroll: true });
});

renderRoute();
renderLesson();
