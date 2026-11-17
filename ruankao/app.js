import { networkLessons } from './network.js';
import { securityLesson, curriculum, coverage } from './curriculum.js';
import { mountLab } from './labs.js';

const storageKey = 'feng.asia/ruankao/study-v1';
const lessons = Object.fromEntries([...networkLessons, securityLesson].map(lesson => [lesson.id, lesson]));
const main = document.querySelector('main');
const trackPicker = document.querySelector('.track-picker');

const warmup = {
  layers: [
    ['应用要选择不同的服务，TCP 或 UDP 首部里的什么字段可用来区分？', '目的端口。例如同一服务器可用不同的端口提供不同服务。'],
    ['数据经过路由器后送上下一条链路，需要重新封装哪一层？', '链路层。路由器按 IP 选路，再按下一条链路的要求封装。']
  ],
  subnet: [
    ['IPv4 的 /24 中有多少位表示主机部分？', '8 位，因为 IPv4 地址有 32 位。'],
    ['两个地址的最后一个十进制数不同，一定不在同一个子网吗？', '不能单看最后一段。要按实际子网掩码计算各自网络地址再比较。']
  ],
  switch: [
    ['交换机收到以太网帧时，从哪个地址学习这个端口后面有哪些设备？', '源 MAC。源地址表明这个帧从哪台设备过来。'],
    ['主机需要获得同链路的下一跳 MAC 时，IPv4 中经常用哪个协议查询？', 'ARP，用下一跳的 IPv4 地址换取 MAC 地址。']
  ],
  vlan: [
    ['同一台交换机上的两个不同 VLAN，是否共用一个广播域？', '每个 VLAN 是独立的二层广播域。'],
    ['一条链路要同时传送多个 VLAN 的帧，怎样区分它们？', '可用 802.1Q Trunk，根据帧的标签等端口约定判定其 VLAN。']
  ],
  routing: [
    ['路由器收到普通单播 IP 包，查路由通常看源地址还是目的地址？', '看目的地址，用来选择包下一步往哪里送。'],
    ['匹配同一个目的地址的 /16 与 /24 路由，哪个覆盖的范围更小？', '/24。它约束的高位更多，描述的网络范围更具体。']
  ],
  'network-case': [
    ['同一网段互通，但所有其他网段都不通，你会优先确认哪项终端配置？', '检查默认网关及其可达性，再沿三层设备查路由。'],
    ['能访问确实提供服务的 IP，但用对应域名失败，可以先验证什么？', '先验证 DNS 查询结果、请求使用的 DNS 服务器和域名是否正确。']
  ],
  'security-case': [
    ['登录成功之后，谁来决定员工可以审批哪些申请？', '系统仍需要检查权限，授权规则决定主体能对具体资源执行什么操作。'],
    ['外包临时排查结束后，这次临时访问应该如何处理？', '回收临时权限，核对并保留需要的审批与操作记录。']
  ]
};

function readState() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey)) || {};
    return {
      track: saved.track === 'security' ? 'security' : 'network',
      answers: saved.answers || {},
      mistakes: saved.mistakes || {},
      completed: saved.completed || {},
      drafts: saved.drafts || {}
    };
  } catch {
    return { track: 'network', answers: {}, mistakes: {}, completed: {}, drafts: {} };
  }
}

const state = readState();

function saveState() {
  try {
    localStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    const note = document.querySelector('.sidebar-note');
    note.textContent = '浏览器存储不可用，本次进度仅保留在当前页面';
  }
}

function element(tag, className, ...children) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  el.append(...children);
  return el;
}

function link(label, target, className) {
  const el = element('a', className, label);
  el.href = target;
  return el;
}

function button(label, className, action) {
  const el = element('button', className, label);
  el.type = 'button';
  if (action) el.addEventListener('click', action);
  return el;
}

function lessonUrl(id) {
  return '#lesson/' + id;
}

function routeItems() {
  return curriculum[state.track].phases.flatMap(phase => phase.items);
}

function practiceItems() {
  return routeItems().filter(item => item.lessonId);
}

function pendingMistakes() {
  return Object.entries(state.mistakes)
    .filter(([, item]) => !item.recovered && (lessons[item.lessonId]?.track === 'common' || lessons[item.lessonId]?.track === state.track))
    .sort(([, first], [, second]) => first.due - second.due);
}

function activeRoute() {
  const [page, lessonId] = location.hash.slice(1).split('/');
  if (page === 'lesson' && Object.hasOwn(lessons, lessonId)) return { page, lesson: lessons[lessonId] };
  return { page: ['plan', 'review', 'coverage'].includes(page) ? page : 'home' };
}

function heading(title, detail, level = 'h1') {
  return element('div', level === 'h1' ? 'page-heading' : 'section-heading',
    element(level, '', title), element('p', '', detail));
}

function formatDay(day) {
  return String(day).padStart(2, '0');
}

function lessonList(items) {
  const list = element('ul', 'lesson-list');
  for (const item of items) {
    const lesson = lessons[item.lessonId];
    const status = lesson
      ? (state.completed[lesson.id] ? '已学完' : lesson.minutes + ' 分钟')
      : '待上线';
    const row = element(lesson ? 'a' : 'div', lesson ? 'lesson-row' : 'lesson-row is-planned',
      element('span', 'day-box', formatDay(item.day)),
      element('span', 'lesson-title', item.title),
      element('span', 'row-status', status));
    if (lesson) row.href = lessonUrl(lesson.id);
    list.append(element('li', '', row));
  }
  return list;
}

function progressMetric(title, count, total) {
  const progress = element('progress', 'progress-bar');
  progress.max = total;
  progress.value = count;
  progress.setAttribute('aria-label', title);
  return element('section', 'card',
    element('div', 'progress-head', element('h3', '', title), element('strong', 'metric', count + ' / ' + total)),
    progress,
    element('p', '', '当前方向已上线课程'));
}

function home() {
  const items = practiceItems();
  const completed = items.filter(item => state.completed[item.lessonId]).length;
  const next = items.find(item => !state.completed[item.lessonId]);
  const nextLesson = next ? lessons[next.lessonId] : null;
  const art = element('div', 'hero-art',
    element('div', 'hero-graph',
      ...Array.from({ length: 4 }, () => element('span', 'graph-node')),
      ...Array.from({ length: 3 }, () => element('span', 'graph-edge'))));
  art.setAttribute('aria-hidden', 'true');
  const review = pendingMistakes();
  const due = review.filter(([, item]) => item.due <= Date.now()).length;
  main.append(
    heading('今日学习', curriculum[state.track].label + ' · 30 个学习日路线'),
    element('section', 'hero',
      element('div', 'hero-body',
        element('div', 'hero-kicker', nextLesson ? '第 ' + next.day + ' 天 · ' + nextLesson.minutes + ' 分钟' : '首版课程已学完'),
        element('h2', '', nextLesson ? nextLesson.title : '复习你的薄弱点'),
        element('p', '', nextLesson ? nextLesson.subtitle : '打开错题本继续练习，或到学习路线查看后续安排。'),
        nextLesson
          ? link(completed || Object.keys(state.answers).length ? '继续学习 →' : '开始学习 →', lessonUrl(nextLesson.id), 'btn btn-accent')
          : link('打开错题本 →', '#review', 'btn btn-accent')),
      art),
    element('div', 'dashboard-grid',
      progressMetric('学习进度', completed, items.length),
      element('section', 'card',
        element('div', 'progress-head', element('h3', '', '待复习错题'), element('strong', 'metric', String(review.length))),
        element('p', '', review.length ? '今天待复习 ' + due + ' 道，再练巩固。' : '答错的题会自动进入错题本。'),
        link('查看错题 →', '#review', 'text-link'))),
    element('section', 'block',
      heading('已上线课程', '前 5 节为共用网络基础，第 6 天进入所选方向。', 'h2'),
      lessonList(items)));
}

function plan() {
  const track = curriculum[state.track];
  const items = practiceItems();
  main.append(
    heading('学习路线', track.label + ' · 30 个学习日，可按自己的进度学习。'),
    element('p', 'notice', '当前可学 ' + items.length + ' 天。待上线的课程展示后续顺序。切换备考方向后，共用课进度会保留。'),
    element('div', 'block stack', ...track.phases.map((phase, index) => {
      const details = element('details', 'card phase',
        element('summary', '',
          element('span', 'phase-range', phase.range),
          element('span', '', phase.title)),
        lessonList(phase.items));
      details.open = index === 0;
      return details;
    })),
    element('section', 'card block stack',
      element('h2', '', '备考自测标准'),
      element('p', '', '后续模考按基础知识与应用技术两科记录。站内目标为连续 3 套首次作答的限时模考，两科每次均达到卷面满分的 70%，并复核案例采分点。'),
      link('查询官方考试安排与合格标准', 'https://rsj.gz.gov.cn/ywzt/rcgz/rsks/bmtz/content/post_10736860.html', 'text-link')));
}

function optionLetter(index) {
  return String.fromCharCode(65 + index);
}

function questionCard(question, index, previous, onAnswer) {
  const fieldset = element('fieldset', '',
    element('legend', '', formatDay(index + 1) + '　' + question.prompt));
  const options = element('div', 'choice-list');
  let selected;
  let result = previous;
  const controls = element('div', 'question-controls');
  const feedback = element('div', 'feedback');
  feedback.hidden = true;
  feedback.tabIndex = -1;
  feedback.setAttribute('role', 'status');
  const submit = button('提交答案', 'btn btn-primary', () => {
    if (selected === undefined || result !== undefined) return;
    result = selected;
    showResult();
    onAnswer(result);
    feedback.focus();
  });
  submit.disabled = true;
  controls.append(submit);

  for (const [optionIndex, option] of question.options.entries()) {
    const radio = element('input');
    radio.type = 'radio';
    radio.name = question.id;
    radio.id = question.id + '-' + optionIndex;
    radio.checked = optionIndex === result;
    radio.disabled = result !== undefined;
    radio.addEventListener('change', () => {
      selected = optionIndex;
      submit.disabled = false;
    });
    options.append(element('label', 'choice', radio,
      element('span', 'choice-prefix', optionLetter(optionIndex) + '.'),
      element('span', '', option)));
  }

  function showResult() {
    const correct = result === question.answer;
    for (const radio of options.querySelectorAll('input')) radio.disabled = true;
    feedback.classList.toggle('incorrect', !correct);
    feedback.replaceChildren(
      element('strong', 'feedback-title', (correct ? '回答正确' : '这题需要再练') + ' · 正确答案 ' + optionLetter(question.answer)),
      element('ul', '', ...question.explanations.map((explanation, optionIndex) =>
        element('li', '', element('strong', '', optionLetter(optionIndex) + '　'), explanation))));
    feedback.hidden = false;
    controls.hidden = true;
  }

  if (result !== undefined) showResult();
  fieldset.append(options, controls, feedback);
  return element('article', 'card question-card', fieldset);
}

function recordAnswer(lesson, question, picked, isReview = false) {
  if (!isReview) state.answers[question.id] = picked;
  if (picked !== question.answer) {
    state.mistakes[question.id] = { lessonId: lesson.id, due: Date.now(), recovered: false };
  } else if (state.mistakes[question.id]) {
    const mistake = state.mistakes[question.id];
    const round = (mistake.round || 0) + 1;
    const nextDay = new Date();
    nextDay.setHours(24, 0, 0, 0);
    state.mistakes[question.id] = { lessonId: lesson.id, due: nextDay.getTime(), recovered: round >= 2, round };
  }
  saveState();
}

function caseCard(lesson) {
  const text = element('textarea');
  text.id = 'case-draft';
  text.placeholder = '先写下排查或设计步骤，再展开采分点。';
  text.value = state.drafts[lesson.id] || '';
  text.addEventListener('input', () => {
    state.drafts[lesson.id] = text.value;
    saveState();
  });
  return element('section', 'card reading case-card',
    element('h2', '', '应用题'),
    element('p', '', lesson.case.prompt),
    element('label', '', '我的作答'),
    text,
    element('details', '',
      element('summary', '', '查看参考采分点'),
      element('ul', '', ...lesson.case.points.map(point =>
        element('li', '', element('strong', '', point.label + '　'), point.detail)))));
}

function lessonPage(lesson) {
  const breadcrumbs = element('div', 'breadcrumb', link('‹ 返回学习路线', '#plan'));
  const header = element('header', 'lesson-header',
    element('div', 'lesson-meta', '第 ' + lesson.day + ' 天 · ' + lesson.minutes + ' 分钟'),
    element('h1', '', lesson.title),
    element('p', '', lesson.subtitle),
    element('p', 'lesson-goal', element('strong', '', '学完后　'), lesson.goal),
    element('ul', 'tags', ...lesson.tags.map(tag => element('li', 'tag', tag))));
  const readings = element('section', 'stack', element('h2', '', '原理讲解'));
  for (const section of lesson.sections) {
    const card = element('article', 'card reading', element('h3', '', section.title), element('p', '', section.body));
    if (section.callout) card.append(element('p', 'callout', section.callout));
    readings.append(card);
  }

  const checkpoint = element('section', 'card reading checkpoint',
    element('h2', '', '课前小测'),
    ...warmup[lesson.id].map(([prompt, answer]) =>
      element('details', '', element('summary', '', prompt), element('p', '', answer))));
  readings.classList.add('block');
  main.append(breadcrumbs, header, checkpoint, readings);
  if (lesson.lab) {
    const lab = element('section', 'block');
    mountLab(lab, lesson.lab);
    main.append(lab);
  }
  main.append(element('section', 'card reading block',
    element('h2', '', '例题'),
    element('p', '', lesson.example.prompt),
    element('ol', '', ...lesson.example.reasoning.map(step => element('li', '', step))),
    element('p', 'callout', element('strong', '', '结论　'), lesson.example.answer)));

  const score = element('p', 'row-status');
  score.setAttribute('role', 'status');
  const quiz = element('section', 'quiz stack',
    element('div', 'quiz-head', element('h2', '', '本课练习'), score));
  const completion = button('标记学完', 'btn btn-primary', () => {
    state.completed[lesson.id] = true;
    saveState();
    refreshScore();
  });

  function refreshScore() {
    const answered = lesson.questions.filter(question => Object.hasOwn(state.answers, question.id));
    const correct = answered.filter(question => state.answers[question.id] === question.answer);
    score.textContent = '已答 ' + answered.length + ' / ' + lesson.questions.length + ' · 正确 ' + correct.length;
    completion.textContent = state.completed[lesson.id] ? '已学完' : '标记学完';
    completion.disabled = state.completed[lesson.id] || answered.length !== lesson.questions.length;
  }

  for (const [index, question] of lesson.questions.entries()) {
    quiz.append(questionCard(question, index, state.answers[question.id], result => {
      recordAnswer(lesson, question, result);
      refreshScore();
    }));
  }
  main.append(quiz);
  if (lesson.case) {
    const card = caseCard(lesson);
    card.classList.add('block');
    card.querySelector('label').htmlFor = 'case-draft';
    main.append(card);
  }
  const available = practiceItems();
  const index = available.findIndex(item => item.lessonId === lesson.id);
  const next = available[index + 1];
  main.append(element('div', 'lesson-actions',
    completion,
    next ? link('下一课 →', lessonUrl(next.lessonId), 'btn btn-secondary') : link('查看后续路线 →', '#plan', 'btn btn-secondary'),
    element('p', '', '答完本课练习后可标记学完。')));
  refreshScore();
}

function reviewPage() {
  const items = pendingMistakes();
  main.append(heading('错题复习', '答错的题当天可以重做。重做正确后，第二天再答对一次即可移出待复习。'));
  if (!items.length) {
    main.append(element('section', 'card stack', element('h2', '', '当前没有待复习的错题'),
      element('p', '', '做完一道题后可以在课内看解析。答错的题会在这里重新出现。'),
      link('返回今日学习 →', '#home', 'text-link')));
    return;
  }
  const review = element('div', 'stack');
  for (const [index, [questionId, entry]] of items.entries()) {
    const lesson = lessons[entry.lessonId];
    const question = lesson.questions.find(item => item.id === questionId);
    if (!question) continue;
    const due = entry.due <= Date.now();
    const note = element('div', 'review-label',
      link(lesson.title, lessonUrl(lesson.id), 'text-link'),
      due ? '今天可重做' : '下次复习 ' + new Date(entry.due).toLocaleDateString('zh-CN'));
    if (due) {
      const panel = element('section', '', note);
      function startReview() {
        const quiz = questionCard(question, index, undefined, picked => {
          recordAnswer(lesson, question, picked, true);
          const status = state.mistakes[question.id];
          note.replaceChildren(link(lesson.title, lessonUrl(lesson.id), 'text-link'),
            status.recovered ? '已完成两次正确复习' : picked === question.answer ? '已安排下次复习' : '还需复习');
          if (picked !== question.answer) {
            const retry = button('再练一次', 'btn btn-secondary retry-button', () => {
              startReview();
              panel.querySelector('input').focus();
            });
            panel.append(retry);
          }
        });
        panel.replaceChildren(note, quiz);
      }
      startReview();
      review.append(panel);
    } else {
      review.append(element('section', 'card', note, element('p', '', question.prompt)));
    }
  }
  main.append(review);
}

function coveragePage() {
  const track = curriculum[state.track];
  const topics = coverage[state.track];
  const available = topics.filter(item => item.lessonId).length;
  const list = element('ul', 'lesson-list coverage-list');
  for (const item of topics) {
    const title = element('span', 'lesson-title', item.topic);
    if (item.sourceNote) title.append(element('small', '', item.sourceNote));
    const row = element(item.lessonId ? 'a' : 'div', item.lessonId ? 'lesson-row' : 'lesson-row is-planned',
      title, element('span', 'row-status', item.lessonId ? '有课有题 →' : '待补'));
    if (item.lessonId) row.href = lessonUrl(item.lessonId);
    list.append(element('li', '', row));
  }
  main.append(
    heading('考点索引', track.label + ' · 对照各主题的课程和练习'),
    element('section', 'card stack',
      element('div', 'progress-head',
        element('h2', '', '索引主题已上线'), element('strong', 'metric', available + ' / ' + topics.length)),
      element('p', '', '当前为备考主题索引。官方大纲细项还需逐条对照，以上数量为本页主题数。'),
      link(track.edition + ' ↗', track.source, 'text-link')),
    element('div', 'block', list));
}

function render() {
  const route = activeRoute();
  if (route.lesson && route.lesson.track !== 'common' && route.lesson.track !== state.track) {
    state.track = route.lesson.track;
    saveState();
  }
  const currentNav = route.page === 'lesson' ? 'plan' : route.page;
  for (const item of document.querySelectorAll('.site-nav [data-page]')) {
    if (item.dataset.page === currentNav) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
  for (const option of trackPicker.querySelectorAll('button')) {
    option.setAttribute('aria-pressed', String(option.dataset.track === state.track));
  }

  main.replaceChildren();
  if (route.lesson) lessonPage(route.lesson);
  else if (route.page === 'plan') plan();
  else if (route.page === 'review') reviewPage();
  else if (route.page === 'coverage') coveragePage();
  else home();
  document.title = main.querySelector('h1').textContent + ' · 软考学习站';
}

trackPicker.addEventListener('click', event => {
  const option = event.target.closest('button[data-track]');
  if (!option || option.dataset.track === state.track) return;
  state.track = option.dataset.track;
  saveState();
  const { lesson } = activeRoute();
  if (lesson && lesson.track !== 'common') {
    location.hash = 'plan';
  } else {
    render();
  }
});

document.querySelector('.skip-link').addEventListener('click', event => {
  event.preventDefault();
  main.focus();
  main.scrollIntoView();
});

window.addEventListener('hashchange', () => {
  render();
  window.scrollTo({ top: 0, behavior: 'instant' });
  main.focus({ preventScroll: true });
});

render();
