// LightRAG 收件匣 —— Zotero 外掛（bootstrapped，Zotero 8 以上）
//
// 兩件事：
//   1. 選文獻 → 右鍵 → 送進收件匣，打上 `_toRaged`
//   2. 之後自己回頭對帳：真的進知識庫了就換成 `_RAGED`
//
// **取代的是「自己拖檔案 + 自己打標」這兩個手動動作**，不多做別的判斷。
//
// 為什麼要對帳這一層：送進收件匣**不等於**進了知識庫。中間還要解析、過規格、
// 抽取，而且可能被擋下來等人看。只打一個標的話，卡住的那些會安靜地混在
// 「已入庫」裡面 —— 而知識庫少一篇文獻，是查詢的時候才會發現的那種錯。
//
//     _toRaged   送出去了，還在路上（這是你的待辦清單）
//     _RAGED     伺服器說它在 completed 那一節
//
// ⚠ 壞掉的**不打標籤**（PO 裁決），只在對帳的視窗裡列出來。
//
// 去重不在這裡做：伺服器用**內容雜湊**比對，同一份改名再傳一樣會被擋（回 409）。

var LightRAGFilename;    // lib/filename.js
var LightRAGReconcile;   // lib/reconcile.js

var pluginID = null;
var registeredMenus = [];
var timers = [];

const FTL = 'lightrag-inbox.ftl';
const DEFAULTS = {
  server: 'http://100.87.88.7:9710',
  tag: '_toRaged',
  doneTag: '_RAGED',
  intervalMinutes: 10,
};

function log(msg) {
  Zotero.debug('[lightrag-inbox] ' + msg);
}

// 設定放在 Zotero 的偏好設定裡（進階 → 設定編輯器，搜 `lightrag`）。
// 沒設過就用預設值 —— 不做設定畫面，這是自己用的東西。
function pref(key) {
  try {
    const value = Zotero.Prefs.get('lightrag.' + key, true);
    if (value === undefined || value === null || value === '') return DEFAULTS[key];
    return value;
  } catch (e) {
    return DEFAULTS[key];
  }
}

function baseURL() {
  return String(pref('server')).replace(/\/+$/, '');
}

// 用主視窗的 fetch：bootstrap 那層不保證有全域的 fetch，而主視窗是特權範圍，
// 跨網域不受限制。
function windowFetch(url, options) {
  return Zotero.getMainWindow().fetch(url, options);
}

// ── 送出 ──────────────────────────────────────────────────────────────────

/** 回 {state, detail}；state ∈ ok／exists／skip／fail */
async function sendOne(item, tag) {
  let attachment = null;
  let parent = item;
  if (item.isPDFAttachment && item.isPDFAttachment()) {
    attachment = item;
    parent = Zotero.Items.get(item.parentItemID) || item;
  } else if (item.isRegularItem && item.isRegularItem()) {
    attachment = await item.getBestAttachment();
  }
  if (!attachment || !attachment.isPDFAttachment || !attachment.isPDFAttachment()) {
    return { state: 'skip', detail: '沒有 PDF 附件' };
  }

  const path = await attachment.getFilePathAsync();
  if (!path) {
    // 用了「連結的檔案」而檔案不在，或雲端同步還沒下載下來。
    return { state: 'skip', detail: '附件的檔案不在本機' };
  }

  const filename = LightRAGFilename.buildFilename({
    date: parent.getField ? parent.getField('date') : '',
    title: parent.getField ? parent.getField('title') : '',
  });

  const bytes = await IOUtils.read(path);
  const response = await windowFetch(baseURL() + '/api/upload', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/pdf',
      // 標題可能有非 ASCII 字元，HTTP 標頭放不了原文。
      // 伺服器那側是 `urllib.parse.unquote`，兩邊都是 UTF-8 百分比編碼。
      'X-Filename': encodeURIComponent(filename),
    },
    body: bytes,
  });
  const body = await response.text();
  const parsed = parseJSON(body);

  if (response.status === 201) {
    // **記伺服器回的那個名字，不是我們算的**：同名時它會加序號。
    await mark(parent, tag, parsed && parsed.filename ? parsed.filename : filename);
    return { state: 'ok', detail: filename };
  }
  if (response.status === 409) {
    // 已經在收件匣或已經進知識庫了。**還是要打標** —— 不打的話畫面上看起來
    // 像沒送成功，你會一直重按。
    const message = parsed && parsed.error ? parsed.error : body;
    await mark(parent, tag, LightRAGReconcile.existingFilename(message));
    return { state: 'exists', detail: message };
  }
  return { state: 'fail', detail: 'HTTP ' + response.status + '：' + serverMessage(body) };
}

function parseJSON(body) {
  try {
    return JSON.parse(body);
  } catch (e) {
    return null;
  }
}

function serverMessage(body) {
  const parsed = parseJSON(body);
  if (parsed) return parsed.error || parsed.filename || body;
  return (body || '').slice(0, 200);
}

/** 打標籤，並把伺服器認得的檔名記在「其他」欄位（撈不到就只打標籤）。 */
async function mark(item, tag, filename) {
  let changed = false;
  if (!item.hasTag(tag)) {
    item.addTag(tag);
    changed = true;
  }
  if (filename) {
    const extra = item.getField('extra') || '';
    const next = LightRAGReconcile.recordFilename(extra, filename);
    if (next !== extra) {
      item.setField('extra', next);
      changed = true;
    }
  }
  if (changed) await item.saveTx();
}

async function sendItems(items) {
  if (!items || !items.length) return;

  const tag = pref('tag');
  const counts = { ok: 0, exists: 0, skip: 0, fail: 0 };
  const problems = [];

  for (const item of items) {
    let result;
    try {
      result = await sendOne(item, tag);
    } catch (e) {
      // 連不上、讀不到檔、伺服器沒起來都落在這裡。**一份出事不擋住其餘的**。
      log('送出失敗：' + (e && e.message ? e.message : e));
      result = { state: 'fail', detail: e && e.message ? e.message : String(e) };
    }
    counts[result.state] += 1;
    if (result.state === 'fail' || result.state === 'skip') {
      problems.push(titleOf(item) + ' —— ' + result.detail);
    }
  }

  show('lightrag 收件匣',
    '送進去 ' + counts.ok + '　已經在裡面 ' + counts.exists
    + '　跳過 ' + counts.skip + '　失敗 ' + counts.fail,
    problems);
}

// ── 對帳 ──────────────────────────────────────────────────────────────────

async function itemsWithTag(tag) {
  const search = new Zotero.Search();
  search.libraryID = Zotero.Libraries.userLibraryID;
  search.addCondition('tag', 'is', tag);
  const ids = await search.search();
  return Zotero.Items.getAsync(ids);
}

/**
 * 問一次伺服器，把已經進知識庫的換標籤。
 *
 * **一個請求對帳全部**，不是一篇一個。判斷依據是伺服器現在的狀態，不是
 * 「有沒有收到通知」—— 所以關掉 Zotero 兩星期再打開，一樣會對上。
 */
async function reconcile({ manual }) {
  const sentTag = pref('tag');
  const doneTag = pref('doneTag');

  let state;
  try {
    const response = await windowFetch(baseURL() + '/api/state');
    if (!response.ok) throw new Error('HTTP ' + response.status);
    state = await response.json();
  } catch (e) {
    const detail = '問不到伺服器：' + (e && e.message ? e.message : e);
    log(detail);
    // 自動跑的時候不要跳視窗 —— 筆電沒連上內網時每 10 分鐘彈一次沒人受得了。
    if (manual) show('lightrag 對帳', detail, []);
    return;
  }

  const index = LightRAGReconcile.buildIndex(state);
  const items = await itemsWithTag(sentTag);
  const counts = { done: 0, pending: 0, failed: 0, missing: 0, unrecorded: 0 };
  const problems = [];

  for (const item of items) {
    const filename = LightRAGReconcile.readFilename(item.getField('extra'));
    if (!filename) {
      counts.unrecorded += 1;
      problems.push(titleOf(item) + ' —— 沒記到檔名，重送一次就會有');
      continue;
    }
    const verdict = LightRAGReconcile.decide(index, filename);
    counts[verdict] += 1;
    if (verdict === 'done') {
      item.removeTag(sentTag);
      item.addTag(doneTag);
      await item.saveTx();
    } else if (verdict === 'failed') {
      problems.push(titleOf(item) + ' —— 伺服器說它壞了，去審核台看');
    } else if (verdict === 'missing') {
      // 被重置、被刪掉、或檔名對不上。**不能當成進去了。**
      problems.push(titleOf(item) + ' —— 伺服器上查不到「' + filename + '」');
    }
  }

  const summary = '入庫 ' + counts.done + '　還在路上 ' + counts.pending
    + '　壞了 ' + counts.failed + '　查不到 ' + counts.missing;
  log('對帳：' + summary);
  for (const line of problems) log('  ' + line);

  // 自動跑的時候只有「真的有東西入庫」才出聲，其餘安靜 —— 不然每 10 分鐘
  // 彈一次同樣的抱怨。手動叫的時候一律回報，因為那是你在問。
  if (manual || counts.done > 0) show('lightrag 入庫狀態', summary, problems);
}

// ── 畫面 ──────────────────────────────────────────────────────────────────

function titleOf(item) {
  try {
    const t = (item.getField && item.getField('title'))
      || (item.getDisplayTitle && item.getDisplayTitle());
    return (t || '(無標題)').slice(0, 60);
  } catch (e) {
    return '(無標題)';
  }
}

function show(headline, summary, problems) {
  try {
    const window = new Zotero.ProgressWindow();
    window.changeHeadline(headline);
    window.addDescription(summary);
    // 問題**逐條列出來**，不要只給一個數字 —— 數字看不出來要去修哪一筆。
    for (const line of problems.slice(0, 10)) window.addDescription(line);
    if (problems.length > 10) {
      window.addDescription('…還有 ' + (problems.length - 10) + ' 筆，詳見偵錯輸出');
    }
    window.show();
    // 有問題就不要自己關掉，讓人有時間讀。
    window.startCloseTimer(problems.length ? 30000 : 6000);
  } catch (e) {
    // 畫面掛了不該把已經做完的事情變成失敗 —— 結果本身已經進 debug log 了。
    log('結果視窗顯示失敗：' + e);
  }
}

// ── 選單（Zotero 8 起的官方 API）──────────────────────────────────────────

function registerMenus() {
  if (!Zotero.MenuManager || !Zotero.MenuManager.registerMenu) {
    log('這個 Zotero 版本沒有 MenuManager —— 選單掛不上（本外掛要 Zotero 8 以上）');
    return;
  }
  registeredMenus.push(Zotero.MenuManager.registerMenu({
    menuID: 'lightrag-inbox-send',
    pluginID: pluginID,
    target: 'main/library/item',
    menus: [{
      menuType: 'menuitem',
      l10nID: 'lightrag-inbox-send',
      onCommand: (event, context) => {
        // 不 await：選單的處理常式不該擋著畫面。
        sendItems(context && context.items ? context.items : []);
      },
    }],
  }));
  registeredMenus.push(Zotero.MenuManager.registerMenu({
    menuID: 'lightrag-inbox-reconcile',
    pluginID: pluginID,
    // 放工具選單而不是右鍵：它跟選了哪幾筆無關，一次對帳全部。
    target: 'main/tools',
    menus: [{
      menuType: 'menuitem',
      l10nID: 'lightrag-inbox-reconcile',
      onCommand: () => { reconcile({ manual: true }); },
    }],
  }));
}

function unregisterMenus() {
  for (const id of registeredMenus) {
    try {
      Zotero.MenuManager.unregisterMenu(id);
    } catch (e) {
      log('選單卸不掉：' + e);
    }
  }
  registeredMenus = [];
}

// ── 定時對帳 ──────────────────────────────────────────────────────────────

// 用 nsITimer 而不是視窗的 setInterval：視窗關掉時 setInterval 會跟著死，
// 而這個外掛的重點就是「你不用管它」。
function startTimer(delayMs, repeating) {
  try {
    const timer = Components.classes['@mozilla.org/timer;1']
      .createInstance(Components.interfaces.nsITimer);
    timer.initWithCallback(
      { notify: () => { reconcile({ manual: false }); } },
      delayMs,
      repeating
        ? Components.interfaces.nsITimer.TYPE_REPEATING_SLACK
        : Components.interfaces.nsITimer.TYPE_ONE_SHOT);
    timers.push(timer);
  } catch (e) {
    // 定時對帳掛了不該讓選單也跟著沒有 —— 手動那條路仍然可用。
    log('定時對帳掛不上（手動的還在）：' + e);
  }
}

function stopTimers() {
  for (const timer of timers) {
    try {
      timer.cancel();
    } catch (e) { /* 關的時候不值得吵 */ }
  }
  timers = [];
}

// ── 生命週期 ──────────────────────────────────────────────────────────────

async function startup({ id, rootURI }) {
  pluginID = id;
  Services.scriptloader.loadSubScript(rootURI + 'lib/filename.js');
  Services.scriptloader.loadSubScript(rootURI + 'lib/reconcile.js');
  // `onMainWindowLoad` 只對「之後才開的視窗」觸發，所以已經開著的要自己補。
  for (const win of Zotero.getMainWindows()) {
    insertFTL(win);
  }
  registerMenus();

  const minutes = Number(pref('intervalMinutes')) || DEFAULTS.intervalMinutes;
  startTimer(30 * 1000, false);              // 開起來 30 秒後補一次
  startTimer(minutes * 60 * 1000, true);     // 之後定時
  log('起來了（每 ' + minutes + ' 分鐘對帳一次）');
}

function shutdown() {
  stopTimers();
  unregisterMenus();
}

function insertFTL(win) {
  try {
    win.MozXULElement.insertFTLIfNeeded(FTL);
  } catch (e) {
    log('語言檔掛不上（選單會顯示空白標籤）：' + e);
  }
}

function onMainWindowLoad({ window }) {
  insertFTL(window);
}

function onMainWindowUnload() {}

function install() {}
function uninstall() {}
