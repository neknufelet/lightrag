#!/usr/bin/env python3
"""`VERIFY-9` — 這個專案有沒有照上位規範做。

**為什麼需要這支**：`standards/BASELINE.md` 定了一整套規範（文件 frontmatter、
必要檔案、交接檔行數上限、commit 格式），但**沒有任何東西會發現沒做**。
2026-08-07 實測的落差：9 個 `.md` 檔零個有 frontmatter、`NEXT.md` 799 行
（上限約 80）、`STATUS.md`／`CHANGELOG.md`／`docs/decisions/` 全部不存在、
而且當天先前提的 6 個 commit 全部不符合它自己規定的格式。

成因寫在 `BASELINE.md` 自己第 17 行：**被引用的檔不會自動載入 session context，
只寫「請參閱本檔」＝裝飾。** 標準對 9 條核心規則做了 inline snapshot 所以它們生效，
其餘規則沒有 inline，於是對 AI 等於不存在。這支就是那些規則的機器執行者。

**三級，比照 `compat-check.py`**：

    hard      BASELINE 明文要求且本專案沒有豁免 ⇒ 擋
    soft      值得知道但不該擋（例如缺 CHANGELOG.md）
    waived    本專案有明文理由的豁免 ⇒ 通過，但把理由印出來

**豁免必須附理由，而且理由寫在這支腳本裡**（不是另開一個豁免清單檔）——
兩份會漂移，而漂移時不會有錯誤訊息。比照 `ledger.py` 對 `unverifiable`
沒有 `--note` 直接拒收的設計：沒有理由的豁免跟沒檢查無法區分。

用法：
    standards-check.py              人讀的報告，exit 0 通過／1 hard 失敗／5 只有 soft
    standards-check.py --json      機器讀
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# standards repo 只在 florian-coder。在 dker 上與它相關的檢查一律「驗不了」，
# 不是失敗 —— 把「沒得驗」講成「壞了」是這個專案一路在防的事。
STANDARDS = REPO.parent / "standards"

LEVELS = ("hard", "soft")

# BASELINE「文件規範」要求的 frontmatter 最小欄位集。
REQUIRED_FRONTMATTER = ("title", "date_created", "date_modified",
                        "status", "kind", "summary")

# 純 README／INDEX 類豁免 supersedes/superseded_by（BASELINE 明文），
# 這裡整份豁免 frontmatter —— 它們說明資料夾用途，不是治理或技術文件。
README_LIKE = {"README.md", "verdicts/README.md", "cairn/README.md"}

# 行數上限。BASELINE 對 NEXT.md 寫「經驗閾值 < ~80 行；超過就是該掃了」；
# CHEATSHEET 對 STATUS.md 寫「≤100 silent / 101–200 warning / >200 拒絕」。
LINE_LIMITS = {"docs/NEXT.md": 80, "STATUS.md": 100}


@dataclass
class Result:
    id: str
    level: str
    title: str
    ok: bool
    detail: str
    waived_reason: str = ""

    @property
    def state(self) -> str:
        if self.waived_reason:
            return "waived"
        return "ok" if self.ok else "FAIL"


@dataclass
class Checker:
    results: list[Result] = field(default_factory=list)

    def add(self, id_: str, level: str, title: str, ok: bool, detail: str,
            waived_reason: str = "") -> None:
        assert level in LEVELS, f"未知的級別 {level!r}"
        self.results.append(Result(id_, level, title, ok, detail, waived_reason))

    # ---------- 文件層 ----------

    def governed_docs(self) -> list[Path]:
        """要受 frontmatter 規範的 .md。

        ADR 用自己的格式（`* Status:` / `* Date:`），由 A04 單獨檢查，不在此列。
        """
        out: list[Path] = []
        for p in sorted(REPO.glob("*.md")) + sorted(REPO.glob("docs/*.md")) \
                + sorted(REPO.glob("cairn/*.md")):
            rel = p.relative_to(REPO).as_posix()
            if rel in README_LIKE or rel.startswith("docs/decisions/"):
                continue
            out.append(p)
        return out

    @staticmethod
    def frontmatter_of(path: Path) -> dict[str, str] | None:
        """讀 YAML frontmatter 的鍵值（只做扁平 key: value，夠用且不引依賴）。"""
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        end = text.find("\n---", 4)
        if end == -1:
            return None
        out: dict[str, str] = {}
        for line in text[4:end].splitlines():
            if line.startswith(("#", " ", "\t")) or ":" not in line:
                continue
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("\"'")
        return out

    def check_frontmatter(self) -> None:
        docs = self.governed_docs()
        missing: list[str] = []
        incomplete: list[str] = []
        for p in docs:
            rel = p.relative_to(REPO).as_posix()
            fm = self.frontmatter_of(p)
            if fm is None:
                missing.append(rel)
                continue
            lack = [k for k in REQUIRED_FRONTMATTER if not fm.get(k)]
            if lack:
                incomplete.append(f"{rel}（缺 {'/'.join(lack)}）")
        detail = (f"{len(docs) - len(missing) - len(incomplete)}/{len(docs)} 份合格")
        if missing:
            detail += f"；完全沒有 frontmatter：{', '.join(missing)}"
        if incomplete:
            detail += f"；欄位不全：{', '.join(incomplete)}"
        # 級別是 soft 而非 hard：這是存量債（2026-08-07 起算 9 份裡只有 2 份合格），
        # 一次全補會變成一個大到不會被 review 的 diff。soft 讓數字每天被看見而不擋工作，
        # 補完之後再升 hard —— 屆時它會擋住「又長出一份沒有 frontmatter 的文件」。
        self.add("A01", "soft", "治理與技術文件有 YAML frontmatter",
                 not missing and not incomplete, detail)

    def check_line_limits(self) -> None:
        over: list[str] = []
        seen: list[str] = []
        for name, limit in LINE_LIMITS.items():
            p = REPO / name
            if not p.is_file():
                continue
            n = len(p.read_text(encoding="utf-8").splitlines())
            seen.append(f"{name} {n}/{limit}")
            if n > limit:
                over.append(f"{name} {n} 行（上限 {limit}）")
        detail = "、".join(seen) if seen else "沒有受限的檔案"
        if over:
            detail += f"；超標：{'、'.join(over)}"
        # hard：這一條是可以立刻做到的（2026-08-07 已把 NEXT.md 從 799 壓到 79），
        # 而交接檔一膨脹就不再被讀完，讀不完的清單等於全部失效。
        self.add("A02", "hard", "交接檔沒有超過行數上限", not over, detail)

    def check_required_files(self) -> None:
        wanted = {
            "docs/NEXT.md": ("hard", ""),
            "docs/KNOWN_ISSUES.md": ("hard", ""),
            "docs/decisions": ("hard", ""),
            "CHANGELOG.md": ("soft", ""),
            "STATUS.md": ("soft", ""),
            # 本專案的明文豁免：CLAUDE.md 是既有的 SSOT，不是範本要求的單行
            # @AGENTS.md stub。理由寫在 AGENTS.md 檔頭（它承載鐵則、契約、跨機座標，
            # 每個 session 自動載入，內容與職責都不可被取代）。
            "AGENTS.md": ("hard", ""),
        }
        missing_hard: list[str] = []
        missing_soft: list[str] = []
        for rel, (level, _) in wanted.items():
            if (REPO / rel).exists():
                continue
            (missing_hard if level == "hard" else missing_soft).append(rel)
        self.add("A03", "hard", "標準要求的必要檔案存在",
                 not missing_hard,
                 f"缺 {', '.join(missing_hard)}" if missing_hard else "全部在")
        self.add("A03b", "soft", "選用的標準檔案存在",
                 not missing_soft,
                 f"缺 {', '.join(missing_soft)}（標準範本有，本專案尚未建立）"
                 if missing_soft else "全部在")

    def check_adr_format(self) -> None:
        d = REPO / "docs" / "decisions"
        if not d.is_dir():
            self.add("A04", "soft", "ADR 格式（Status／Date 齊全）", True,
                     "沒有 docs/decisions/，跳過")
            return
        files = sorted(p for p in d.glob("*.md") if not p.name.startswith("0000"))
        bad: list[str] = []
        for p in files:
            head = p.read_text(encoding="utf-8")[:600]
            if "**Status**" not in head and "* Status" not in head:
                bad.append(f"{p.name}（缺 Status）")
            elif "**Date**" not in head and "* Date" not in head:
                bad.append(f"{p.name}（缺 Date）")
        self.add("A04", "hard", "ADR 格式（Status／Date 齊全）", not bad,
                 f"{len(files) - len(bad)}/{len(files)} 份合格"
                 + (f"；不合格：{', '.join(bad)}" if bad else ""))

    # ---------- 執行者層 ----------

    def check_commit_hook(self) -> None:
        hook = REPO / ".git" / "hooks" / "commit-msg"
        cfg = REPO / ".pre-commit-config.yaml"
        ok = hook.is_file() and cfg.is_file()
        detail = (f"hook {'在' if hook.is_file() else '不在'}、"
                  f"設定檔 {'在' if cfg.is_file() else '不在'}")
        # hard：commit 格式是「規則寫了沒人執行」最典型的一條 ——
        # 2026-08-07 那天先前的 6 個 commit 全部違反，而我讀過 CLAUDE.md。
        self.add("A05", "hard", "pre-commit 的 commit-msg hook 已安裝", ok, detail)

    @staticmethod
    def core_rules(text: str, section_marker: str) -> list[str]:
        """抓某個 section 內的編號規則行。

        **必須限定 section**：兩份檔案裡都還有別的編號清單（CLAUDE.md 的鐵則、
        重票觸發清單；BASELINE.md 的版本史），整份掃會多抓一堆。
        第一版就是這樣錯的 —— 報了一個假的 hard 失敗，而它會每天打一次 ntfy。
        """
        i = text.find(section_marker)
        if i == -1:
            return []
        seg = text[i:]
        end = seg.find("\n---", 10)
        return re.findall(r"^\d+\.\s+\*\*.+$", seg[:end] if end != -1 else seg,
                          re.MULTILINE)

    @staticmethod
    def stamps(text: str) -> tuple[str, str]:
        v = re.search(r"baseline_version:?\s*`?([0-9.]+)", text)
        s = re.search(r"rules_sha256:?\s*`?([0-9a-f]{16})", text)
        return (v.group(1) if v else ""), (s.group(1) if s else "")

    def check_baseline_snapshot(self) -> None:
        """CLAUDE.md 的 BASELINE snapshot 有沒有跟上游漂移。

        **比對的是規則本文與版本戳記，不重算那個 sha256。** 上游 frontmatter 的
        `rules_sha256` 註解寫著算法是 `sha256(grep '^N. **' rules)[:16]`，但確切的
        邊界（要不要 trailing newline、從哪份檔案取）沒有落檔，重現它是脆的 ——
        真正要答的問題是「這 9 條有沒有變」，那就直接逐條比字串。
        戳記則兩邊互相對照即可（它們本來就該是同一個值）。

        standards repo 只在 coder ⇒ 在 dker 上是「驗不了」，回 soft 通過並說明。
        """
        claude_text = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
        c_ver, c_sha = self.stamps(claude_text)
        upstream = STANDARDS / "BASELINE.md"
        if not upstream.is_file():
            self.add("A06", "soft", "BASELINE snapshot 與上游一致", True,
                     f"驗不了：{upstream} 不存在（standards repo 只在 coder，"
                     f"dker 沒有）。CLAUDE.md 記 {c_ver or '?'}／{c_sha or '?'}")
            return

        up_text = upstream.read_text(encoding="utf-8")
        b_ver, b_sha = self.stamps(up_text)
        up_rules = self.core_rules(up_text, "## 核心規則（9 條）")
        snap_rules = self.core_rules(claude_text, "## 藍桶規則（9 條")

        problems: list[str] = []
        if len(up_rules) != 9 or len(snap_rules) != 9:
            problems.append(f"條數異常：上游 {len(up_rules)} 條、snapshot {len(snap_rules)} 條")
        elif diff := [i + 1 for i, (x, y) in enumerate(zip(up_rules, snap_rules)) if x != y]:
            problems.append(f"第 {'、'.join(map(str, diff))} 條文字與上游不同")
        if c_ver != b_ver:
            problems.append(f"baseline_version 上游 {b_ver}、snapshot {c_ver}")
        if c_sha != b_sha:
            problems.append(f"rules_sha256 上游 {b_sha}、snapshot {c_sha}")

        self.add("A06", "hard", "BASELINE snapshot 與上游一致", not problems,
                 f"9 條逐字相同、戳記 {b_ver}／{b_sha}" if not problems
                 else "；".join(problems) + " ⇒ 去同步 snapshot（改規則只改上游）")

    def run(self) -> None:
        self.check_frontmatter()
        self.check_line_limits()
        self.check_required_files()
        self.check_adr_format()
        self.check_commit_hook()
        self.check_baseline_snapshot()


def report(c: Checker, as_json: bool) -> int:
    hard_fail = [r for r in c.results if not r.ok and r.level == "hard" and not r.waived_reason]
    soft_fail = [r for r in c.results if not r.ok and r.level == "soft" and not r.waived_reason]

    if as_json:
        print(json.dumps({
            "suite": "VERIFY-9",
            "results": [{"id": r.id, "suite": "VERIFY-9", "level": r.level,
                         "title": r.title, "state": r.state, "detail": r.detail,
                         "waived_reason": r.waived_reason} for r in c.results],
            "hard_fail": len(hard_fail), "soft_fail": len(soft_fail),
        }, ensure_ascii=False, indent=1))
    else:
        print("VERIFY-9　標準合規檢查\n")
        for r in c.results:
            mark = {"ok": "  ok  ", "FAIL": " FAIL ", "waived": "waived"}[r.state]
            print(f"  VERIFY-9-{r.id:<5} {r.level:<4} {mark}  {r.title}")
            print(f"        {r.detail}")
            if r.waived_reason:
                print(f"        豁免理由：{r.waived_reason}")
        # 鐵則 6：收合輸出必須報出「幾項通過未列出」，否則沒印出來跟沒檢查長得一樣。
        # 這裡全部列出，所以只報總計。
        print(f"\n共 {len(c.results)} 項：通過 "
              f"{sum(1 for r in c.results if r.ok and not r.waived_reason)}　"
              f"hard 失敗 {len(hard_fail)}　soft 失敗 {len(soft_fail)}　"
              f"豁免 {sum(1 for r in c.results if r.waived_reason)}")
        if hard_fail:
            print("\nhard 失敗必須處理：")
            for r in hard_fail:
                print(f"  VERIFY-9-{r.id}　{r.title}\n    {r.detail}")

    if hard_fail:
        return 1
    return 5 if soft_fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="VERIFY-9：這個專案有沒有照上位規範做")
    ap.add_argument("--json", action="store_true", help="機器可讀輸出")
    a = ap.parse_args()
    c = Checker()
    c.run()
    return report(c, a.json)


if __name__ == "__main__":
    sys.exit(main())
