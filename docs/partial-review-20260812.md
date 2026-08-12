---
title: ∂ 誤讀逐處判讀 — 71 處，20 個「文件 × 符號」組合
date_created: 2026-08-12
date_modified: 2026-08-12
status: living
kind: spec
supersedes: ""
superseded_by: ""
summary: "每一處都看過原文才下的判定。66 處要改、5 處留手。改法、不能改的東西、以及還抓不到的一類，都寫在這裡。⚠ 尚未改動任何內容。"
---

# ∂ 誤讀逐處判讀（2026-08-12）

MinerU 把 `∂` 的曲線讀成「某個字母戴帽子」。它**不刪字、不改型別**，所以漏字檢查
（覆蓋率永遠 100%）與 preflight（型別沒變）都抓不到，可以完全安靜地進索引。

**現況：71 處、8 種 token、20 個「文件 × 符號」組合。**要重跑就跑，數字不抄在這裡：

```
ssh 100.87.88.7 'cd ~/ghq/github.com/neknufelet/lightrag && python3 scripts/scan-partial.py --details'
```

⚠ **本文件寫的時候一個字都還沒改。**

---

## 判定總表

`改` ＝ 那個 token 換成 `\partial`。`留手` ＝ 證據不足，要看原圖再說。

| 文件 | 符號 | 處數 | 判定 | 憑什麼 |
|---|---|---|---|---|
| 2017 Optimal sound-absorbing | `ô` | 1 | 改 | `D_n = (∂Ω_n/∂n)⁻¹`，模態密度的定義 |
| B General Linear Fluid Acoustics | `ô` | 2 | 改 | `∂aⁱ/∂u_k`，兩側都是被微分量 |
| D Reflection of Sound | `σ̂` | 3 | 改 | `∂/∂n` ×2；`σ̂p/σ̂p` 若 σ̂ 是純量則分子恆為 1，式子會沒有內容 |
| G Porous Absorbers | `Ô` | 2 | 改 | `∂²u₃(P₂)/∂…`，二階導數 |
| G Porous Absorbers | `α̂` | 2 | 改 | `∂u_si/∂x` |
| H Compound Absorbers | `α̂` | 2 | 改 | `∂v_yαβ/∂…` |
| J Duct Acoustics | `ô` | 1 | 改 | `(Δ − c₀⁻²∂²/∂t²)p =`，就是波動方程式 |
| N Flow Acoustics | `∂̄` | 3 | 改（**做法不同，見下**） | 線性化動量方程式，∂ 上面多了一條槓 |
| **N Flow Acoustics** | **`D̂`** | **5** | **留手** | **可能是物質導數 D/Dt，見下** |
| N Flow Acoustics | `Ô` | 12 | 改 | Lighthill／FW-H 那組方程式，`∂/∂x_i`、`∂v̄_j/∂x_i`、`∂/∂t` |
| N Flow Acoustics | `α̂` | 10 | 改 | `∂v'_i/∂…`、`∂Φ/∂n`、`∂²T_ij/∂x_i∂x_j` |
| N Flow Acoustics | `σ̂` | 2 | 改 | `∂/∂t`、`∂/∂x` |
| N Flow Acoustics | `v̂O` | 1 | 改 | Powell 渦聲公式 `∂/∂t ∫[(ω⃗×v⃗)_i]dV`；同一式的另一半寫成 `σ̂` |
| N Flow Acoustics | `ĉ` | 5 | 改 | 線性化 Euler 方程式，`∂ρ'/∂t`、`∂v_ai/∂t`、`∂p_a/∂x` |
| N Flow Acoustics | `ô` | 3 | 改 | `∂/∂t + v⃗·∇`、`∂/∂x_i[Pv_i]` |
| O Analytical and Numerical | `α̂` | 2 | 改 | `∂p/∂n =` |
| O Analytical and Numerical | `ĉ` | 4 | 改 | 邊界積分方程式 `∂g(x,y)/∂n`、`∂p(y)/∂n` |
| O Analytical and Numerical | `ô` | 6 | 改 | 原文自己寫著 **"the partial derivatives ôq/ôa_i"**、**"the operator D = ô/ôn"** |
| P Variational Principles | `ĉ` | 4 | 改 | `∂Φ/∂a = 0, ∂Φ/∂b = 0`，變分駐值條件，章名就叫這個 |
| Q Elasto-Acoustics | `σ̂` | 1 | 改 | `T·∂Φ/∂x` |

**合計：改 66 處、留手 5 處。**

---

## 留手的那 5 處：`N Flow Acoustics` 第 942 項

證據**互相矛盾**，所以不猜。

**指向「是 ∂」的：**

```
\frac{\partial^2 B'}{\partial x_i^2}   同一條式子的第一項，∂ 讀對了
\frac{ D̂ }{ Ô x_i }                    分子 D̂、分母 Ô —— 同一個算子兩種讀法
\frac{ D̂ h }{ D̂ x_i }                  D/Dx 在數學上不存在
```

D̂ 與 Ô 可以互換 ⇒ 它們是同一個字形；而它出現在 `X/X x_i`（對空間微分）的位置
⇒ 那個字形是 ∂。

**指向「是 D」的：**

物質導數 `D/Dt` 在流動聲學裡**是真的存在**，而這一段正是對流波動方程式
（第 941 項寫著「The idealised case of the homentropic flow of the lossless fluid」）。
Howe 那一族的算子確實長成 `D²/Dt²` 與 `∂/∂x_i` 混用的樣子。

⇒ **要看原圖那一頁才知道。** 這正是兩隻眼睛該上場的地方，而且只有一頁。

⚠ 改錯的代價不對稱：把 `D/Dt` 改成 `∂/∂t` 是**把物質導數變成偏導數**，
在有平均流的問題裡那是兩個不同的東西，而且改完沒有人看得出來。

---

## `∂̄`（3 處）的改法跟其他不一樣

其他是「把讀錯的字母換成 `\partial`」，這 3 處是「**把 ∂ 上面多出來的那條槓拿掉**」：

```
ρ̄ ∂̄v'_i/∂̄t + ρ̄ v_j ∂̄v'_i/∂̄x_j + ∂̄p'/∂̄x_i = 0     線性化動量方程式（第 199 項）
```

同一條式子裡 `ρ̄` 的槓是真的（平均密度），`v'`、`p'` 沒有槓（擾動量）——
所以那不是「整條式子取平均」，∂ 上面那條槓是多出來的。

---

## 已經確認**不能碰**的

| 在哪 | 是什麼 | 為什麼 |
|---|---|---|
| `N Flow Acoustics` #149 | `(ρ̄ f̄)/ρ̄` | 密度加權平均（Favre）的定義式，ρ̄ 是真的平均密度 |
| `01705_11.5 Evolution of Sawtooth Waveforms` #51 | `1 + x/x̄ ≈ x/x̄` | x̄ 是震波形成距離，那是無因次距離的比值 |

兩個都**已經在探針裡擋掉了**（見 `tests/test_scan_partial.py`），不會再被報出來。

---

## 探針還抓不到的一類：同一個 ∂ 被讀成兩個不同字母

```
第 942 項：  \frac{ D̂ }{ Ô x_i }         分子 D̂、分母 Ô
第 802 項：  \frac{ v̂O² }{ σ̂ t² }        分子 v̂O、分母 σ̂
O 那份 #782：\frac{ ĉ g(x,y) }{ α̂ n(y) }  分子 ĉ、分母 α̂
```

**上下同形這條規則永遠看不到它們**，因為兩側不同形。

⚠ **不要靠放寬這條規則去抓。** 放寬等於「任何 accent 對 accent 的分數都算導數」，
而真的比值就是長那樣（Favre、Biot 那兩個誤報都是這個形狀）。
要抓得另立判準 —— 例如「這份文件已經確定有 ∂ 誤讀，而且分母的被微分量是座標或時間」。

**現在的處置：記在這裡，不動。** 這一類的量還沒數過。

---

## 改法（尚未執行）

```
1. 改 content_list.json，原文留在 _pp_original_*     可還原、可查帳
2. 改完重跑探針                                      66 處那些應該歸零
3. 改完重跑 canary                                   確認規則沒有意外飄掉
4. reindex 才會反映到知識庫                          ⚠ 這一步等 PO 決定何時做
```

⚠ **改字與重建索引要分開看。** 改字不花錢、而且不管以後重不重抽都不會白做；
重建索引才是會白做的那一步（如果之後決定重抽，兩者應該併做）。
