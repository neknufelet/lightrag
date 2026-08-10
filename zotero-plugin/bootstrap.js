// LightRAG 收件匣 —— Zotero 外掛（bootstrapped，Zotero 8／9）
//
// 做的事只有一件：把選起來的文獻的 PDF 傳進 lightrag 的收件匣，成功就打標籤。
// **取代的是「自己拖檔案 + 自己打標」這兩個手動動作**，不多做別的判斷。
//
// ⚠ 標籤的意思是「送進收件匣了」，**不是「已經進知識庫」**。送進去之後還要
// 解析、過規格、抽取，而且可能被擋下來等人看 —— Zotero 這邊看不出來。
// 要對帳的話，審核台上「失敗／等你看」那兩格就是差集。
// （之後要加「回頭確認真的入庫了才換標籤」的話，那是另外一層，
//   掛在送出流程旁邊，不要改這裡。）
//
// 去重不在這裡做：伺服器用**內容雜湊**比對，同一份改名再傳一樣會被擋（回 409）。
// 客戶端自己記「傳過哪些」只會多一份會過期的狀態。
//
// ⚠ Zotero 8 起選單走 `Zotero.MenuManager.registerMenu()`，而且標籤只能給
// `l10nID`（語言檔），不能直接給字串 —— 7 那套自己塞 DOM 的寫法不再用。

var LightRAGFilename;   // lib/filename.js 載進來的
var registeredMenuID = null;
var pluginID = null;

const FTL = 'lightrag-inbox.ftl';
const DEFAULTS = {
  server: 'http://100.87.88.7:9710',
  tag: '_toRaged',
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

// ── 送一份 ────────────────────────────────────────────────────────────────

// 用主視窗的 fetch：bootstrap 那層不保證有全域的 fetch，而主視窗是特權範圍，
// 跨網域不受限制。
function post(url, filename, bytes) {
  const win = Zotero.getMainWindow();
  return win.fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/pdf',
      // 標題可能有非 ASCII 字元，HTTP 標頭放不了原文。
      // 伺服器那側是 `urllib.parse.unquote`，兩邊都是 UTF-8 百分比編碼。
      'X-Filename': encodeURIComponent(filename),
    },
    body: bytes,
  });
}

/** 回 {state, detail}；state ∈ ok／exists／skip／fail */
async function sendOne(item, server, tag) {
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
  const response = await post(server.replace(/\/+$/, '') + '/api/upload', filename, bytes);
  const body = await response.text();

  if (response.status === 201) {
    await addTag(parent, tag);
    return { state: 'ok', detail: filename };
  }
  if (response.status === 409) {
    // 已經在收件匣或已經進知識庫了。**還是要打標** —— 不打的話畫面上看起來
    // 像沒送成功，你會一直重按。
    await addTag(parent, tag);
    return { state: 'exists', detail: serverMessage(body) };
  }
  return { state: 'fail', detail: 'HTTP ' + response.status + '：' + serverMessage(body) };
}

function serverMessage(body) {
  try {
    const parsed = JSON.parse(body);
    return parsed.error || parsed.filename || body;
  } catch (e) {
    return (body || '').slice(0, 200);
  }
}

async function addTag(item, tag) {
  if (item.hasTag(tag)) return;
  item.addTag(tag);
  await item.saveTx();
}

// ── 送一批 ────────────────────────────────────────────────────────────────

async function sendItems(items) {
  if (!items || !items.length) return;

  const server = pref('server');
  const tag = pref('tag');
  const counts = { ok: 0, exists: 0, skip: 0, fail: 0 };
  const problems = [];

  for (const item of items) {
    let result;
    try {
      result = await sendOne(item, server, tag);
    } catch (e) {
      // 連不上、讀不到檔、伺服器沒起來都落在這裡。**一份出事不擋住其餘的**。
      log('失敗：' + (e && e.message ? e.message : e));
      result = { state: 'fail', detail: e && e.message ? e.message : String(e) };
    }
    counts[result.state] += 1;
    if (result.state === 'fail' || result.state === 'skip') {
      problems.push(titleOf(item) + ' —— ' + result.detail);
    }
  }

  report(counts, problems);
}

function titleOf(item) {
  try {
    const t = (item.getField && item.getField('title')) || (item.getDisplayTitle && item.getDisplayTitle());
    return (t || '(無標題)').slice(0, 60);
  } catch (e) {
    return '(無標題)';
  }
}

function report(counts, problems) {
  const summary = '送進去 ' + counts.ok + '　已經在裡面 ' + counts.exists
    + '　跳過 ' + counts.skip + '　失敗 ' + counts.fail;
  log(summary);
  for (const line of problems) log('  ' + line);

  try {
    const done = new Zotero.ProgressWindow();
    done.changeHeadline('lightrag 收件匣');
    done.addDescription(summary);
    // 問題**逐條列出來**，不要只給一個數字 —— 數字看不出來要去修哪一筆。
    for (const line of problems.slice(0, 10)) done.addDescription(line);
    if (problems.length > 10) {
      done.addDescription('…還有 ' + (problems.length - 10) + ' 筆，詳見偵錯輸出');
    }
    done.show();
    // 有問題就不要自己關掉，讓人有時間讀。
    done.startCloseTimer(problems.length ? 30000 : 6000);
  } catch (e) {
    // 畫面掛了不該把已經送成功的事情變成失敗 —— 結果本身已經進 debug log 了。
    log('結果視窗顯示失敗：' + e);
  }
}

// ── 選單（Zotero 8 起的官方 API）──────────────────────────────────────────

function registerMenu() {
  if (!Zotero.MenuManager || !Zotero.MenuManager.registerMenu) {
    log('這個 Zotero 版本沒有 MenuManager —— 選單掛不上（本外掛要 Zotero 8 以上）');
    return;
  }
  registeredMenuID = Zotero.MenuManager.registerMenu({
    menuID: 'lightrag-inbox',
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
  });
}

function unregisterMenu() {
  if (registeredMenuID && Zotero.MenuManager && Zotero.MenuManager.unregisterMenu) {
    Zotero.MenuManager.unregisterMenu(registeredMenuID);
  }
  registeredMenuID = null;
}

// ── 生命週期 ──────────────────────────────────────────────────────────────

async function startup({ id, rootURI }) {
  pluginID = id;
  Services.scriptloader.loadSubScript(rootURI + 'lib/filename.js');
  // `onMainWindowLoad` 只對「之後才開的視窗」觸發，所以已經開著的要自己補。
  for (const win of Zotero.getMainWindows()) {
    insertFTL(win);
  }
  registerMenu();
  log('起來了');
}

function shutdown() {
  unregisterMenu();
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
