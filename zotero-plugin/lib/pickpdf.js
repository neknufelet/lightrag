// 一筆文獻底下要送哪一個 PDF 附件。
//
// **這是外掛裡第二件自己判斷的事**（第一件是檔名），所以同樣獨立成純函式
// 讓 node 測得到。判斷錯的後果比檔名錯嚴重：送錯的那份會被解析、抽取、
// 進圖譜，而且看起來一切正常。
//
// ## 為什麼非有這條規則不可
//
// 2026-08-14 實測 PO 的文獻庫（179 筆在知識庫裡的文獻）：
//
//     155 筆有兩個 PDF，其中 96 筆是標準的「原文 + 中文翻譯」
//
// 「全部都送」會讓一百多篇論文在圖譜裡被抽兩次，而且**中英兩份會被當成
// 兩個獨立來源** —— 公式跨來源比對的整個價值就建立在「不同來源」上，
// 那會製造出大量看起來很像真的假發現。
//
// ## 翻譯本怎麼認出來（實測，不是猜的）
//
//     名字像翻譯   有 BabelDOC 標籤    幾個
//        否            否              205   ← 原文
//        是            是              178   ← 翻譯，兩邊都認得
//        是            否               10   ← 早期翻的，那時還沒打標籤
//        否            是                0   ← **一個都沒有**
//
// 最後一行是關鍵：**標籤從不誤標**，有標籤的一定是翻譯。但它會漏 10 個。
// 名字樣式反過來，完整但只是樣式比對。所以**兩個都用、取聯集**。
//
// ⚠ 排除之後如果一個都不剩，**視為沒有規則可用**而不是「這筆沒東西可送」——
//    那表示這筆的附件全被判成翻譯，判斷八成錯了。這種情況要退回全部候選讓人看。
var LightRAGPickPDF = (function () {
  'use strict';

  // BabelDOC（翻譯工具）自己打的標籤。機器打的，所以一致。
  var TRANSLATED_TAG = 'BabelDOC_translated';

  // 實測到的翻譯命名法（2026-08-15 掃全庫 2241 個附件）：
  //
  //     PDF_ZHT / zht_PDF          最常見
  //     …_zh-TW_dual.pdf           BabelDOC 的雙語對照版
  //     …_zh-TW_translation.pdf    純翻譯
  //     …zh-TW.mono.pdf            BabelDOC 的單語版，**點號分隔**
  //     deepseek-mono / -dual      標題只寫工具名，**連字號分隔**
  //
  // ⚠ `mono`／`dual` 前面要有分隔號（`-_.`）才算。沒這個限制的話
  //    `… Digital Monogr.pdf`（專著）會被誤判成翻譯本而不送。
  // ⚠ 這張表是**猜**的那一半，新的寫法出現時會漏 —— 所以它只是標籤的補漏，
  //    不是主要依據。漏掉的後果是那筆落到「要問人」，不是靜靜送錯。
  var TRANSLATED_NAME = /(_?zht|zh-?tw|[-_.]dual\b|[-_.]mono\b|_translation|翻譯)/i;

  function isTranslation(att) {
    var a = att || {};
    var tags = a.tags || [];
    for (var i = 0; i < tags.length; i++) {
      var name = typeof tags[i] === 'string' ? tags[i] : (tags[i] && tags[i].tag);
      if (name === TRANSLATED_TAG) return true;
    }
    // ⚠ **標題與檔名都要看。** 2026-08-15 實測：6 個附件的標題看不出是翻譯
    //    （`deepseek-mono`、`電子書`），證據只在檔名裡（`….zh-TW.mono.pdf`）。
    //    只看標題的話那些會被當成原文送出去 —— 而且不會有任何訊號。
    var blob = String(a.title == null ? '' : a.title) + ' '
             + String(a.filename == null ? '' : a.filename);
    return TRANSLATED_NAME.test(blob);
  }

  /**
   * 從候選裡挑出要送的那一個。
   *
   * 回傳 `{pick, reason}`；挑不出來時 `pick` 是 null，`candidates` 列出還在
   * 檯面上的那些讓呼叫端說給人聽。**挑不出來就不送** —— 送錯比不送嚴重。
   */
  function choose(attachments) {
    var all = (attachments || []).filter(Boolean);
    if (!all.length) return { pick: null, reason: 'none', candidates: [] };
    if (all.length === 1) return { pick: all[0], reason: 'only', candidates: all };

    var rest = all.filter(function (a) { return !isTranslation(a); });
    // 全被判成翻譯 ＝ 判斷八成錯了。退回全部候選，不要挑一個硬送。
    if (!rest.length) return { pick: null, reason: 'all-translated', candidates: all };
    if (rest.length === 1) return { pick: rest[0], reason: 'sole-original', candidates: rest };

    // PO 的約定：原文的附件標題就叫 `PDF`。實測 179 筆裡 140 筆適用。
    var exact = rest.filter(function (a) {
      return String(a.title == null ? '' : a.title).trim() === 'PDF';
    });
    if (exact.length === 1) return { pick: exact[0], reason: 'named-PDF', candidates: rest };

    // 走到這裡是真的分不出來（實測 179 筆裡 2 筆，都是庫裡有重複附件）。
    return { pick: null, reason: 'ambiguous', candidates: rest };
  }

  /**
   * 人在條目清單裡**直接點某一份 PDF 附件那一列**按送出時，要不要照送。
   *
   * ## 為什麼不是「再跑一次 choose()」
   *
   * 人明確點了某一份，那是**意圖**：他可能就是要送那一份補充資料、那一章。
   * 拿 `choose()` 蓋掉他的選擇，等於按了送出卻送出別的東西 —— 那是另一種
   * 安靜的錯，不比原來的洞好。
   *
   * ⇒ 只擋一件事：**他點到的那一份本身就是翻譯本**。這種情況幾乎一定是誤點
   * （在 Zotero 裡原文與翻譯上下相鄰），而送出去的代價是中文混進英文語料、
   * 被公式跨來源比對當成一個獨立來源。
   *
   * ## 這條路徑原本完全沒有規則（KI-016）
   *
   * `bootstrap.js` 的 `sendOne()` 對 `isPDFAttachment()` 那一支直接
   * `attachment = item`，`choose()` 整段不執行。**規則存在，但那條路徑沒呼叫
   * 它** —— 所以 `tests/pickpdf.test.js` 裡有一條盯著呼叫點的測試，純函式
   * 測得到判斷，測不到「有沒有被呼叫」。
   *
   * @returns `{ok, reason}`；`reason ∈ explicit／translation／missing`
   */
  function acceptDirect(att) {
    if (!att) return { ok: false, reason: 'missing' };
    if (isTranslation(att)) return { ok: false, reason: 'translation' };
    return { ok: true, reason: 'explicit' };
  }

  return {
    choose: choose, isTranslation: isTranslation, acceptDirect: acceptDirect,
    TRANSLATED_TAG: TRANSLATED_TAG, TRANSLATED_NAME: TRANSLATED_NAME,
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = LightRAGPickPDF;
}
