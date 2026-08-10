// 對帳：送出去的那些，後來真的進知識庫了嗎。
//
// 送出時把**伺服器實際存成的檔名**記在文獻的「其他」欄位；之後問一次
// `/api/state`，拿「檔名 → 在哪一節」的對照決定要不要換標籤。
//
// 為什麼要記檔名而不是每次重算：伺服器遇到同名會加序號，重算出來的名字
// 對不上。收據要拿伺服器給的那張。
//
// 同時被兩邊載入：Zotero 走 `loadSubScript`（拿全域變數），node 走 `require`。
var LightRAGReconcile = (function () {
  'use strict';

  var PREFIX = 'lightrag: ';

  /** 把檔名寫進「其他」欄位，**保留原本所有內容**，同一行只留一份。 */
  function recordFilename(extra, filename) {
    var kept = String(extra == null ? '' : extra)
      .split('\n')
      .filter(function (line) { return line.indexOf(PREFIX) !== 0; });
    // 尾端的空行會讓每存一次就多長一行。
    while (kept.length && kept[kept.length - 1].trim() === '') kept.pop();
    kept.push(PREFIX + filename);
    return kept.join('\n');
  }

  function readFilename(extra) {
    var lines = String(extra == null ? '' : extra).split('\n');
    for (var i = 0; i < lines.length; i++) {
      if (lines[i].indexOf(PREFIX) === 0) {
        var value = lines[i].slice(PREFIX.length).trim();
        if (value) return value;
      }
    }
    return null;
  }

  /**
   * 伺服器回 409 時訊息長「這份已經在收件匣裡了：<檔名>」，把檔名撈出來。
   *
   * ⚠ **撈不到就回 null，不要拿自己算的檔名頂替。** 伺服器是用內容雜湊
   * 比對的，它認得的那份很可能叫別的名字；頂替一個猜的名字進去，之後
   * 對帳會對到別份文件上。
   */
  function existingFilename(message) {
    var text = String(message == null ? '' : message);
    var at = text.lastIndexOf('：');
    if (at < 0) return null;
    var value = text.slice(at + 1).trim();
    return value && /\.pdf$/i.test(value) ? value : null;
  }

  /** {檔名: 節名}。認不得的形狀一律回空的 —— **不猜**。 */
  function buildIndex(state) {
    var index = {};
    var sections = state && state.sections;
    if (!sections || typeof sections !== 'object') return index;
    for (var name in sections) {
      var rows = sections[name];
      if (!Array.isArray(rows)) continue;
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        if (row && typeof row.filename === 'string') index[row.filename] = name;
      }
    }
    return index;
  }

  /**
   * done ／ failed ／ pending ／ missing
   *
   * ⚠ **查不到一律 missing，不能當成 done。** 被重置、被刪掉、檔名記錯都會
   * 落在這裡，而把它標成「已進知識庫」是這支唯一會製造假象的錯法。
   */
  function decide(index, filename) {
    var section = index && filename ? index[filename] : undefined;
    if (section === 'completed') return 'done';
    if (section === 'failed') return 'failed';
    if (section === undefined) return 'missing';
    return 'pending';
  }

  return {
    recordFilename: recordFilename,
    readFilename: readFilename,
    existingFilename: existingFilename,
    buildIndex: buildIndex,
    decide: decide,
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = LightRAGReconcile;
}
