// 選片：一筆文獻底下要送哪個 PDF。
//
// 每一條都對應 2026-08-14 在 PO 的文獻庫實測到的形狀，不是想像出來的案例。
//
// 跑法：node --test zotero-plugin/tests/pickpdf.test.js
const test = require('node:test');
const assert = require('node:assert');
const { choose, isTranslation } = require('../lib/pickpdf.js');

const pdf = (title, tags) => ({ title, tags: tags || [] });
const BABEL = [{ tag: 'BabelDOC_translated' }];

// ── 認出翻譯 ──────────────────────────────────────────────────────────────

test('BabelDOC 的標籤就算數 —— 實測 178 個都對，0 個誤標', () => {
  assert.ok(isTranslation(pdf('隨便什麼名字', BABEL)));
});

test('沒標籤的早期翻譯靠名字認 —— 實測有 10 個是這樣', () => {
  for (const name of ['PDF_ZHT', 'zht_PDF', '2020 - X_zh-TW_dual.pdf',
                      '2026 - X_zh-TW_translation.pdf', 'PDF_ZHT_Supplementary']) {
    assert.ok(isTranslation(pdf(name)), `沒認出是翻譯：${name}`);
  }
});

test('原文不准被誤判成翻譯', () => {
  for (const name of ['PDF', '全文', 'Full Text', 'Preprint PDF', '送出的版本']) {
    assert.ok(!isTranslation(pdf(name)), `誤判成翻譯：${name}`);
  }
});

// ── 挑哪一個 ──────────────────────────────────────────────────────────────

test('只有一個就送它，不問 —— 實測 6 筆屬此', () => {
  const got = choose([pdf('PDF')]);
  assert.strictEqual(got.reason, 'only');
  assert.strictEqual(got.pick.title, 'PDF');
});

test('原文 + 翻譯：排掉翻譯就只剩一個 —— 實測 96 筆是這個組合', () => {
  const got = choose([pdf('PDF'), pdf('PDF_ZHT', BABEL)]);
  assert.strictEqual(got.reason, 'sole-original');
  assert.strictEqual(got.pick.title, 'PDF');
});

test('原文叫「全文」也對得上 —— 靠的是排除翻譯，不是認得原文的名字', () => {
  const got = choose([pdf('全文'), pdf('PDF_ZHT', BABEL)]);
  assert.strictEqual(got.pick.title, '全文');
});

test('剩多個時，PO 的約定是原文就叫 PDF —— 實測 140 筆適用', () => {
  const got = choose([pdf('PDF'), pdf('Preprint PDF'), pdf('PDF_ZHT', BABEL)]);
  assert.strictEqual(got.reason, 'named-PDF');
  assert.strictEqual(got.pick.title, 'PDF');
});

// ── 挑不出來的時候 ────────────────────────────────────────────────────────

test('**分不出來就不送。** 送錯的那份會被抽進圖譜，而且看起來一切正常', () => {
  // 實測的兩筆：庫裡有重複附件（兩個都叫 PDF）。
  const got = choose([pdf('PDF'), pdf('PDF'), pdf('PDF_ZHT', BABEL)]);
  assert.strictEqual(got.pick, null);
  assert.strictEqual(got.reason, 'ambiguous');
  assert.strictEqual(got.candidates.length, 2, '候選要列給人看');
});

test('全部被判成翻譯 —— 那是判斷錯了，退回全部候選而不是挑一個硬送', () => {
  // 只有翻譯本、原文不在 Zotero 裡的情況。硬送等於把中文餵進英文語料。
  const got = choose([pdf('PDF_ZHT', BABEL), pdf('PDF_ZHT_Supplementary', BABEL)]);
  assert.strictEqual(got.pick, null);
  assert.strictEqual(got.reason, 'all-translated');
  assert.strictEqual(got.candidates.length, 2);
});

test('一個附件都沒有', () => {
  for (const empty of [[], null, undefined]) {
    assert.strictEqual(choose(empty).pick, null);
    assert.strictEqual(choose(empty).reason, 'none');
  }
});

test('標籤可以是字串或物件 —— Zotero 兩種都給得出來', () => {
  assert.ok(isTranslation(pdf('X', ['BabelDOC_translated'])));
  assert.ok(isTranslation(pdf('X', [{ tag: 'BabelDOC_translated' }])));
  assert.ok(!isTranslation(pdf('X', [{ tag: 'Absorption' }, 'Coiling Space'])));
});

// ── 檔名裡才看得出來的（0.3.5 起）────────────────────────────────────────
//
// 2026-08-15 掃全庫 2241 個附件，找出 6 個「標題看不出、檔名才看得出」的。
// 下面用的是真實資料，不是編的。

test('**標題看不出、檔名看得出的翻譯本**', () => {
  // 只看標題的話這 5 個會被當成原文送出去，而且不會有任何訊號。
  const real = [
    ['deepseek-mono',
     '2020 - A double porosity material for low frequency sound absorption.no_watermark.zh-TW.mono.pdf'],
    ['deepseek-dual',
     '2022 - In situ acoustic characterization of a locally reacting porous material.no_watermark.zh-TW.dual.pdf'],
    ['Introduction to the special issue on sound absorption and diffusion-deepseek-mono',
     '2026 - Introduction to the special issue.no_watermark.zh-TW.mono.pdf'],
    ['電子書',
     '羅勃特.T.清崎著 ; MTS翻譯團隊譯 - 2022 - 富爸爸, 窮爸爸.pdf'],
  ];
  for (const [title, filename] of real) {
    assert.ok(isTranslation({ title, filename, tags: [] }),
              `沒認出是翻譯：${title}`);
  }
});

test('連字號與點號分隔的 mono／dual 都要認得，不只底線', () => {
  for (const name of ['x-mono.pdf', 'x_mono.pdf', 'x.mono.pdf',
                      'x-dual.pdf', 'x_dual.pdf', 'x.mono.pdf']) {
    assert.ok(isTranslation({ title: name, tags: [] }), `沒認出：${name}`);
  }
});

test('**`Monograph` 不是 mono** —— 分隔號的限制就是為了這個', () => {
  // 真實案例：`Pleban - 2022 - New techniques … Digital Monogr.pdf`
  assert.ok(!isTranslation({
    title: 'PDF',
    filename: 'Pleban - 2022 - New techniques and methods for noise. Digital Monogr.pdf',
    tags: [],
  }), '把專著誤判成翻譯本了');
  assert.ok(!isTranslation({ title: 'Monolithic absorber design', tags: [] }));
  assert.ok(!isTranslation({ title: 'Dualism in acoustic modelling', tags: [] }));
});

test('沒有 filename 欄位也不能爆掉 —— 舊呼叫端只給 title', () => {
  assert.ok(isTranslation({ title: 'PDF_ZHT' }));
  assert.ok(!isTranslation({ title: 'PDF' }));
});
