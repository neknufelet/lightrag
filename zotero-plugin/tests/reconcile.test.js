// 對帳：送出去的那些，後來真的進知識庫了嗎。
//
// 兩件事在這裡決定，都測得到：
//   1. 檔名記在文獻的「其他」欄位裡 —— **不能把別人寫的內容洗掉**
//      （Better BibTeX 的 `Citation Key:` 就住在那裡）
//   2. 拿伺服器的狀態決定要換標籤、要報錯、還是什麼都不做
//
// 跑法：node --test zotero-plugin/tests/*.test.js
const test = require('node:test');
const assert = require('node:assert');
const {
  recordFilename, readFilename, buildIndex, decide, existingFilename,
} = require('../lib/reconcile.js');

// ── 檔名記在哪 ────────────────────────────────────────────────────────────

test('空的「其他」欄位就直接寫進去', () => {
  assert.strictEqual(recordFilename('', '2026 - A.pdf'), 'lightrag: 2026 - A.pdf');
  assert.strictEqual(recordFilename(undefined, '2026 - A.pdf'), 'lightrag: 2026 - A.pdf');
});

test('**別人寫的內容一個字都不能動**', () => {
  const before = 'Citation Key: chen2026\ntex.ids: foo';
  const after = recordFilename(before, '2026 - A.pdf');
  assert.ok(after.startsWith(before), after);
  assert.ok(after.includes('lightrag: 2026 - A.pdf'), after);
});

test('再送一次要覆蓋原本那行，不是多寫一行', () => {
  const once = recordFilename('Citation Key: x', '2026 - A.pdf');
  const twice = recordFilename(once, '2026 - B.pdf');
  assert.strictEqual((twice.match(/^lightrag: /gm) || []).length, 1, twice);
  assert.ok(twice.includes('2026 - B.pdf'), twice);
  assert.ok(!twice.includes('2026 - A.pdf'), twice);
  assert.ok(twice.includes('Citation Key: x'), twice);
});

test('讀得回來，沒有就回 null', () => {
  assert.strictEqual(readFilename('lightrag: 2026 - A.pdf'), '2026 - A.pdf');
  assert.strictEqual(readFilename('Citation Key: x\nlightrag: 2026 - A.pdf'), '2026 - A.pdf');
  assert.strictEqual(readFilename('Citation Key: x'), null);
  assert.strictEqual(readFilename(''), null);
  assert.strictEqual(readFilename(undefined), null);
});

test('標題裡有冒號的檔名要完整讀回來', () => {
  // 檔名本身已經把冒號濾掉了，但別人手改過「其他」欄位的話還是可能出現。
  assert.strictEqual(readFilename('lightrag: 2026 - A: B.pdf'), '2026 - A: B.pdf');
});

// ── 伺服器說「已經在裡面了」時，檔名要從那句話裡撈出來 ────────────────────

test('409 的訊息裡帶著實際的檔名', () => {
  assert.strictEqual(
    existingFilename('這份已經在收件匣裡了：2026 - A.pdf'), '2026 - A.pdf');
  assert.strictEqual(
    existingFilename('這份已經進知識庫了：2026 - A.pdf'), '2026 - A.pdf');
});

test('撈不到就回 null —— **不要拿自己算的檔名頂替**', () => {
  // 伺服器是用內容雜湊比對的，它認得的那份可能叫別的名字。
  // 頂替一個猜的名字進去，之後對帳會對到別份文件上。
  assert.strictEqual(existingFilename('只收 PDF，收到的是 .zip'), null);
  assert.strictEqual(existingFilename(''), null);
  assert.strictEqual(existingFilename(undefined), null);
  assert.strictEqual(existingFilename('這份已經進知識庫了：'), null);
});

// ── 拿伺服器的狀態做判斷 ──────────────────────────────────────────────────

const STATE = {
  sections: {
    selection: [{ filename: '待處理.pdf' }],
    parsing: [{ filename: '解析中.pdf' }],
    review: [{ filename: '等你看.pdf' }],
    in_progress: [{ filename: '抽取中.pdf' }],
    completed: [{ filename: '進去了.pdf' }, { filename: '也進去了.pdf' }],
    skipped: [],
    failed: [{ filename: '壞了.pdf' }],
  },
};

test('每一節的檔名都對得到自己那一節', () => {
  const index = buildIndex(STATE);
  assert.strictEqual(index['進去了.pdf'], 'completed');
  assert.strictEqual(index['壞了.pdf'], 'failed');
  assert.strictEqual(index['等你看.pdf'], 'review');
});

test('進了知識庫才算 done —— 其餘在途的一律 pending', () => {
  const index = buildIndex(STATE);
  assert.strictEqual(decide(index, '進去了.pdf'), 'done');
  for (const name of ['待處理.pdf', '解析中.pdf', '等你看.pdf', '抽取中.pdf']) {
    assert.strictEqual(decide(index, name), 'pending', name);
  }
});

test('壞了要看得見，但不打標籤 —— 由呼叫端決定怎麼呈現', () => {
  assert.strictEqual(decide(buildIndex(STATE), '壞了.pdf'), 'failed');
});

test('伺服器上根本沒有這個檔名 —— 算 missing，不能當成 done', () => {
  // 被重置、被刪掉、或檔名記錯了。**最危險的是把它當成 done**：
  // 標籤會說「進知識庫了」而它根本不在。
  assert.strictEqual(decide(buildIndex(STATE), '沒見過.pdf'), 'missing');
});

test('狀態長得不對時不能爆掉，也不能亂猜', () => {
  assert.deepStrictEqual(buildIndex(null), {});
  assert.deepStrictEqual(buildIndex({}), {});
  assert.deepStrictEqual(buildIndex({ sections: { completed: 'not-a-list' } }), {});
  assert.strictEqual(decide({}, 'X.pdf'), 'missing');
});
