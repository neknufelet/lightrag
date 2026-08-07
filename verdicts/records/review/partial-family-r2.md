# ∂ 誤讀整族 第二輪變體（§8.5）：裁決材料

**這份只是材料與提案，沒有動任何資料。** 定案欄留空給主線。

產生於 2026-08-02（階段 2.7，Opus 執行）。上輪的定案與判準見
[partial-family.md](partial-family.md) §8；程序依 `docs/judgement-flow.md` 第 3／4／5 節。

## 0. 一頁摘要

| 記號 | 處數 | 落在 | 本次建議 | 信心 |
|---|---:|---|---|---|
| `\hat{\mathcal{O}}` | 34 | N Flow #494 ×2、#692 ×13、#942 ×3、#977 ×12；G Porous #567 ×4 | → `\partial` | 高 |
| `\hat{\mathcal{D}}` | 13 | N Flow #942（全部） | → `\partial`（**不是** D/Dt，逐處證據見 §3） | 高 |
| `\hat{\boldsymbol{\sigma}}` | 4 | N Flow #726 | → `\partial` | 高 |
| `\bar{\boldsymbol\sigma}` | 3 | N Flow #957 | **本輪已由 #957 整條重轉錄了結** → `\partial` | 高 |
| `\tilde{\boldsymbol\omega}` | 2 | N Flow #957 | **本輪已由 #957 整條重轉錄了結** → `\vec{\bar\omega}`（ω̄⃗，不是 ∂） | 高 |

§8.5 記的 57 處＝上表 56 處＋#957 的 `\cfrac{1}{\hat{c}^2}` 1 處。
後者依 §8.4 第 2 條併入 #957 整條重轉錄，已落成 `\bar{c}`。
**扣掉 #957 的 6 處（`\bar{\boldsymbol\sigma}`3＋`\tilde{\boldsymbol\omega}`2＋`\hat{c}`1），
本檔待主線裁決的是 51 處。**

57 處只落在 **7 個項目**上（#957 已了結，餘 6 個），所以 6 張裁圖覆蓋全部。
每一處都能在對應裁圖上被指認，逐處對照見 §2／§3。

## 1. 先說結論為什麼可以這麼強：三種互相獨立的證據

上輪 `\hat{\alpha}` 那節用的是同一套判準，這裡三種證據**同時**成立：

1. **同式混用真 `\partial`**（#494、#692、#942）——
   `\frac{\hat{\mathcal{O}}}{\partial\mathbf{r}}`：同一個分數，分子讀錯、分母讀對。
   讀對的那一半直接證明另一半是什麼。
2. **同一個算子被寫成兩個不同的誤讀 token**（#942）——
   `\frac{\hat{\mathcal{D}}^{2}}{\hat{\mathcal{O}}\mathrm{t}^{2}}`：分子 `D̂`、分母 `Ô`，
   而它是**同一個**二階時間導數。若 `D̂` 真的是物質導數 D，分母就必須也是 D。
   混用本身就排除了「D 是真符號」。
3. **裁圖**：6 張全部親眼看過，逐處對得上（§2／§3 的「裁圖上寫什麼」欄）。

而且這幾份文件**真的有物質導數**，MinerU 也**真的讀對了它們**：
#494 的 `\frac{\mathrm{D}^{2}}{\mathrm{Dt}^{2}}`、#692 的 `\frac{\bar{\mathrm{D}}}{\mathrm{Dt}}`、
#726 的 `\frac{\bar{\mathbf{D}}}{\mathbf{Dt}}` —— 全部寫成直立的 `\mathrm{D}`／`\bar{\mathrm{D}}`，
**沒有一處寫成 `\hat{\mathcal{D}}`**。真 D 與誤讀 D̂ 在這份語料裡字面上就是分開的。

## 2. 聚類（結構鍵同上輪）

聚類鍵：分子／分母各自的首位是什麼、記號各幾個、幾階、分子是不是裸算子、
同式有沒有混用真 `\partial`。刻意不把不同結構硬併 —— 併了就看不出邊界在哪。

| 群 | 處數 | 結構 | 代表 | 代表式子 | 裁圖 | 裁圖上寫什麼 | 建議 | 依據 | 信心 | 定案 |
|---|---:|---|---|---|---|---|---|---|---|---|
| R1 | 12 | frac 兩側各 1 記號 / 1 階 / 分子裸算子或帶被微分量 / 同式無真 `\partial` | N Flow #977 | `\frac{\hat{\mathcal{O}}}{\hat{\mathcal{O}}\mathbf{t}}` | `crops/nflow-0977-p39-hat_mathcal_O-40.png` | `∂/∂t (ρ−ρ₀) + ∂/∂x_i (ρv_i) = 0` 等，全式只有 ∂，無任何 D | → `\partial` | 分子／分母首位＝微分算子位置；裁圖全式逐處對上；FW–H 連續方程的標準形 | 高 |  |
| R2 | 13 | frac 兩側各 1 記號 / 1 階 / 同式**混用真 `\partial`** | N Flow #692 | `\frac{\hat{\mathcal{O}}}{\hat{\mathcal{O}}\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0692-p26-hat_mathcal_O-27.png` | `D̄/Dt(D̄²Π/Dt² − ∂/∂x_i[c̄²∂Π/∂x_i]) + 2∂v̄_j/∂x_i ∂/∂x_j[…] = −2κ ∂v_j/∂x_i ∂v_k/∂x_j ∂v_i/∂x_k` | → `\partial` | 同式內 `\frac{\partial\Pi}{\hat{\mathcal{O}}x_i}` 一邊讀對一邊讀錯；同式的真物質導數寫成 `\bar{\mathrm{D}}/\mathrm{Dt}`，與本記號字面分開 | 高 |  |
| R3 | 4 | frac 兩側各 1 記號 / 2 階 / 分子帶被微分量 / 同式無真 `\partial` | G Porous #567 | `\frac{\hat{\mathcal{O}}^{2}\mathbf{u}_{3}(\mathbf{P}_{2})}{\hat{\mathcal{O}}\mathtt{x}_{3}^{2}}` | `crops/gporous-0567-p45-hat_mathcal_O-46.png` | `T ∂²u₃(P₂)/∂x₃²`、`S ∂²u₁(P₂)/∂x₃²` | → `\partial` | 分子／分母首位＝微分算子位置；裁圖兩式逐處對上 | 高 |  |
| R4 | 2 | frac 分子 1 記號、**分母是真 `\partial`** / 1 階 / 分子裸算子 | N Flow #494 | `\frac{\hat{\mathcal{O}}}{\partial\mathbf{r}}` | `crops/nflow-0494-p18-hat_mathcal_O-19.png` | `(1/r²)∂/∂r(r²∂/∂r) + … − (1/c₀²)D²/Dt²` | → `\partial` | **同一個分數裡分母就是真 `\partial`**；同式末項的真物質導數 MinerU 寫成 `\mathrm{D}^2/\mathrm{Dt}^2`，讀對了 | 高 |  |
| R5 | 4 | frac 兩側各 1 記號 / 1 階 / 分子裸算子 / 同式無真 `\partial` | N Flow #726 | `\frac{\hat{\boldsymbol{\sigma}}}{\hat{\boldsymbol{\sigma}}\mathbf{t}}` | `crops/nflow-0726-p28-hat_bs_sigma-29.png` | **`D̄/Dt = ∂/∂t + U ∂/∂x`** | → `\partial` | 這一式**本身就是物質導數的定義**：等號左邊是 D̄/Dt（MinerU 寫成 `\bar{\mathbf{D}}/\mathbf{Dt}`，讀對），右邊全部是 ∂。同一式把 D 與本記號並排放著，無法混淆 | 高 |  |
| R6 | 16 | 見 §3（`\hat{\mathcal{D}}`13＋同式 `\hat{\mathcal{O}}`3） | N Flow #942 | `\frac{\hat{\mathcal{D}}^{2}}{\hat{\mathcal{O}}\mathrm{t}^{2}}` | `crops/nflow-0942-p37-hat_mathcal_D-hat_mathcal_O-38.png` | 見 §3 逐處 | → `\partial` | 見 §3（逐處證據，不從結構推定） | 高 |  |

R1–R5 合計 35 處、R6 16 處，共 51 處＝本檔待裁全部。
（R1 的 12 處與 §0 的 #977 ×12 相同；R2 的 13 處＝#692 全部。）

## 3. `\hat{\mathcal{D}}` 逐處證據（§8.5 特別要求）

> §8.5：「D/Dt 物質導數是真實可能（`\frac{\mathcal{D}}{\mathcal{D}t}` 與 `∂/∂t` 在字面上同構），
> 裁圖必須分辨 ∂ 字形與 D 字形，**不得從 `\frac{X}{Xt}` 結構推定**。」
> 下表每一處都獨立給出裁圖上的對應子式，不靠結構。

全部 13 處都在 **N Flow #942（式 45，p37）**，裁圖
`crops/nflow-0942-p37-hat_mathcal_D-hat_mathcal_O-38.png`。

裁圖上這一式共三行，**字形分辨的關鍵在第三行末項**：那裡有一個**真的** `Dh/Dt`，
D 是直立、有垂直豎筆的羅馬 D；而式中其餘 20 餘處全部是無豎筆、開口向右的 ∂ 字形。
兩種字形在**同一張圖、同一個字級**上並排，可直接比對。
（注意：`Dh/Dt` 落在現值 LaTeX 的**截斷點之後**，所以現值裡一個真 D 都沒有。）

| # | 位移 | 位置 | 現值片段 | 裁圖上的對應子式 | 字形 | 建議 | 信心 | 定案 |
|---:|---:|---|---|---|---|---|---|---|
| 1 | @198 | `frac_num` | `\frac{\hat{\mathcal{D}}^{2}}{\hat{\mathcal{O}}\mathrm{t}^{2}}` | 第 1 行 `[ ∂²/∂t² + …` 的 `∂²` | ∂ | → `\partial` | 高 |  |
| 2 | @330 | `frac_num` | `\frac{\hat{\mathcal{D}}}{\hat{\mathcal{D}}\mathrm{t}}` | 第 1 行 `2v_i ∂/∂t` 的分子 | ∂ | → `\partial` | 高 |  |
| 3 | @358 | `frac_den` | 同上 | 第 1 行 `2v_i ∂/∂t` 的分母 | ∂ | → `\partial` | 高 |  |
| 4 | @494 | `frac_num` | `\frac{\hat{\mathcal{D}}\mathrm{h}}{\hat{\mathcal{D}}\mathrm{x}_{\mathrm{i}}}` | 第 1 行 `− 2 ∂h/∂x_i` 的分子 | ∂ | → `\partial` | 高 |  |
| 5 | @536 | `frac_den` | 同上 | 第 1 行 `− 2 ∂h/∂x_i` 的分母 | ∂ | → `\partial` | 高 |  |
| 6 | @606 | `frac_num` | `\frac{\hat{\mathcal{D}}}{\hat{\mathcal{D}}\mathrm{x}_{\mathrm{i}}}` | 第 1 行括號後的 `∂/∂x_i` 分子 | ∂ | → `\partial` | 高 |  |
| 7 | @634 | `frac_den` | 同上 | 同上的分母 | ∂ | → `\partial` | 高 |  |
| 8 | @772 | `frac_num` | `\frac{\hat{\mathcal{D}}^{2}}{\hat{\mathcal{D}}\mathrm{x}_{\mathrm{i}}\hat{\mathcal{O}}\mathrm{x}_{\mathrm{j}}}` | 第 1 行 `v_i v_j ∂²/∂x_i∂x_j` 的 `∂²` | ∂ | → `\partial` | 高 |  |
| 9 | @808 | `frac_den` | 同上（分母第一個算子） | 同上的 `∂x_i` | ∂ | → `\partial` | 高 |  |
| 10 | @1001 | `frac_num` | `\frac{\hat{\mathcal{D}}}{\hat{\mathcal{O}}\mathrm{x}_{\mathrm{i}}}` | 第 2 行 `= {[ ∂/∂x_i −` 的分子 | ∂ | → `\partial` | 高 |  |
| 11 | @1227 | `frac_num` | `\frac{\hat{\mathcal{D}}\mathrm{h}}{\hat{\mathcal{D}}\mathrm{x}_{\mathrm{i}}}` | 第 2 行 `− 2 ∂h/∂x_i` 的分子 | ∂ | → `\partial` | 高 |  |
| 12 | @1269 | `frac_den` | 同上 | 第 2 行 `− 2 ∂h/∂x_i` 的分母 | ∂ | → `\partial` | 高 |  |
| 13 | @1407 | `frac_num` | `\frac{\hat{\mathcal{D}}}{\hat{\mathcal{O}}\mathrm{x}_{\mathrm{i}}}` | 第 2 行 `v_i v_j ∂/∂x_i` 的分子 | ∂ | → `\partial` | 高 |  |

同式的 3 處 `\hat{\mathcal{O}}`（@234 `∂t²` 的分母、@1029、@1435）在上表對應的分母位置，
證據與配對的分子同一處，一併建議 → `\partial`。

**#942 額外兩件事（不在 51 處內，但主線應該知道）：**

1. **#942 也是截斷的。** 現值止於 `+ [ \frac \widehat{\mathcal{D}} \mathrm{v}_\mathrm` 接
   `\end{array}\tag{45}`，第三行只寫了開頭。裁圖第三行完整可讀
   （`· ((v⃗×ω⃗)′_j + ‾[∂v′_i/∂t]) }′ + [ ∂/∂t (1/c²)′ Dh/Dt ]′`）。
   這是繼 #947／#555／#957 之後**第四條**證實截斷的巨型式。
   §3.1 的警告在這裡再次成立：把 13 個 `\hat{\mathcal{D}}` 換成 `\partial` 會得到
   一條「記號正確但仍然殘缺」的式子，比現在更難被發現壞掉。
   **建議：#942 比照 #947／#555／#957 整條重轉錄，不做單點替換。**
2. 截斷尾巴裡的 `\widehat{\mathcal{D}}`（@1627）是**第 14 個** D̂，封閉掃描沒抓到 ——
   見 §5 的掃描器盲點。

## 4. #957 的 `\bar{\boldsymbol\sigma}` 與 `\tilde{\boldsymbol\omega}`（本輪已了結，逐條附裁圖）

§8.5 指出「`\bar{\boldsymbol\sigma}` 已知同式兩義（#957：一處 ∂、一處 ω̄⃗ 疊層重音），
與 ĉ 完全同型，逐條看」。本輪依 §8.4 第 3 條對 #957 做了整條重轉錄，
裁圖 `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` 直接回答了這 5 處：

| 現值片段（`_pp_original_text`） | 裁圖上寫什麼 | 結果 | 依據 |
|---|---|---|---|
| `2\bar{\bf v}_{i}\frac{\bar{\boldsymbol\sigma}}{\hat{\sigma}\mathrm{t}}`（第 1 行） | `2v̄_i ∂/∂t` | → `\partial` | 分子首位＝微分算子位置，分母的 `\hat{\sigma}` 上輪已定案為 ∂，裁圖確認 |
| `(\vec{\bf v}\times\frac{\bar{\boldsymbol\sigma}}{\tilde{\boldsymbol\omega}})_{i}`（第 1 行） | `(v⃗ × ω̄⃗)_i` | **不是分數，也不是 ∂** | 見下 |
| `(\bar{\vec{\bf v}}\times\frac{\bar{\boldsymbol\sigma}}{\tilde{\boldsymbol\omega}})_{i}`（第 2 行） | `(v⃗̄ × ω̄⃗)_i` | 同上 | 同上 |

後兩處的真相：叉積右運算元 **ω̄⃗ 帶疊層重音**（箭頭疊在橫槓上）。
MinerU 把那道**橫槓當成了分數線**，於是一個符號被拆成上下兩半 ——
上半（箭頭＋橫槓）讀成 `\bar{\boldsymbol\sigma}`、下半（ω 本體）讀成 `\tilde{\boldsymbol\omega}`。
兩個 token 合起來只是**一個** `\vec{\bar\omega}`。叉積左邊的 `\vec{\bf v}`／`\bar{\vec{\bf v}}`
MinerU 讀對了，所以錯的只有帶疊層重音的那一邊。

**所以 3 處 `\bar{\boldsymbol\sigma}` 裡只有 1 處是 ∂**，另 2 處根本不在微分位置；
`\tilde{\boldsymbol\omega}` 的 2 處同理，沒有一處是 ∂。

> 這件事對族邊界的意義：**位置分類本身會被上游的剖析錯誤污染。**
> 掃描器看到的「frac 分子/分母首位」在裁圖上根本不是分數 —— 那道「分數線」
> 是一個重音符號。而位置正是 §8.3 用來取代符號枚舉的判準。
> 這是位置封閉法的第一個已知失效模式，建議記進 judgement-flow：
> **位置判準的前提是 frac 結構本身是真的**，而這個前提來自同一個會讀錯的 MinerU。

## 5. 封閉掃描的盲點（新發現，建議一併裁決）

§8.3 的封閉掃描以 **accent 命令**（`\hat`／`\bar`／`\widehat`／`\tilde`／`\overline`）為錨。
本輪逐字核對 `\mathcal{O}`／`\mathcal{D}` 的**全部**出現位置，發現 3 處落在錨點之外：

| 文件 #index | 位移 | 現值 | 為什麼沒被抓到 | 裁圖上寫什麼 | 建議 | 信心 | 定案 |
|---|---:|---|---|---|---|---|---|
| N Flow #494 | @469 | `\frac{\mathcal{O}}{\partial\vartheta}` | **沒有 accent**（裸 `\mathcal{O}`），ACCENT 正則配不到 | `sin ϑ ∂/∂ϑ` | → `\partial` | 高 |  |
| N Flow #942 | @866 | `\frac{\hat{\mathcal{D}}^2}{\hat{\mathcal{D}}x_i\hat{\mathcal{O}}x_j}` 的第二個算子 | 位置測試只認「首位」與「接算子單元後」，而它前面是另一個**誤讀**算子（不是 `\partial`） | `∂²/∂x_i∂x_j` 的 `∂x_j` | → `\partial` | 高 |  |
| N Flow #942 | @1627 | `\frac \widehat{\mathcal{D}} \mathrm{v}_\mathrm`（截斷尾） | `\frac` 之後不是 `{`，配對括號掃描剖析不了這個 frac | 第 3 行 `‾[∂v′_i/∂t]` 的 `∂` | → `\partial`（實務上併入 #942 整條重轉錄） | 高 |  |

**這三處說明「以位置封閉」還沒真的封閉**，缺的兩個條件是：

1. 錨點不該只認 accent —— `\mathcal{O}` 這種**裸 token** 一樣站得上算子位置；
2. 「接算子單元後」只認真 `\partial`，於是 `∂x_i∂x_j` 這種**連續兩個誤讀算子**
   只抓得到第一個。判準應改成「接**任何**算子單元後」。

順帶查過的**非** ∂ 家族（同型 token，但確認不是誤讀，列出來省得下一輪重查）：

| token | 處數 | 出現在 | 判定 |
|---|---:|---|---|
| `\mathfrak{O}` | 10 | C #369/#382/#386/#392/#402/#467/#472/#498/#508/#516 | **不是 ∂**：一律是 `𝔒 = (a/b)²`／`= πa²/(4bc)` 的孔隙率符號 |
| `\mathfrak{o}` | 2 | N Flow #1436 | **不是 ∂**：`𝔬_t = 2πε/ϵ`，帶下標的量 |
| `\mathfrak{o}` | 1 | G Porous #464 | **不是 ∂**：在乘積因子位置，非算子位置 |
| `\mathcal{O}` | 1 | 2026-JAX-BEM #60 | **不是 ∂**：大 O 複雜度記號 |

## 6. 裁圖索引

`pp/pdfcrop` 產生，`EQ_PAD_X=4`／**`EQ_PAD_Y=1`**（垂直不擴，理由見 partial-family §6）。

| 檔名 | 文件 | #index | 頁 | 覆蓋處數 | 記號 |
|---|---|---|---|---:|---|
| `crops/gporous-0567-p45-hat_mathcal_O-46.png` | G Porous Absorbers | #567 | 45 | 4 | `hat_mathcal_O` |
| `crops/nflow-0494-p18-hat_mathcal_O-19.png` | N Flow Acoustics | #494 | 18 | 2（＋盲點 1） | `hat_mathcal_O`、裸 `\mathcal{O}` |
| `crops/nflow-0692-p26-hat_mathcal_O-27.png` | N Flow Acoustics | #692 | 26 | 13 | `hat_mathcal_O` |
| `crops/nflow-0726-p28-hat_bs_sigma-29.png` | N Flow Acoustics | #726 | 28 | 4 | `hat_bs_sigma` |
| `crops/nflow-0942-p37-hat_mathcal_D-hat_mathcal_O-38.png` | N Flow Acoustics | #942 | 37 | 16（＋盲點 2） | `hat_mathcal_D`、`hat_mathcal_O` |
| `crops/nflow-0977-p39-hat_mathcal_O-40.png` | N Flow Acoustics | #977 | 39 | 12 | `hat_mathcal_O` |
| `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` | N Flow Acoustics | #957 | 38 | 6（**本輪已了結**） | `bar_bs_sigma`、`tilde_bs_omega`、`hat_c` |

## 7. 建議的裁決順序（提案）

1. **51 處全部 → `\partial`**（R1–R6）。三種獨立證據都成立，且真 D 在同一份文件裡
   被 MinerU 讀對成 `\mathrm{D}`／`\bar{\mathrm{D}}`，字面上與本族分開。
2. **但 #942 的 16 處不要單點替換** —— 它跟 #947／#555／#957 一樣是截斷式，
   應整條重轉錄（§3 第 1 點）。單點替換會產出「記號正確但仍然殘缺」的式子。
3. **先補掃描器的兩個盲點再宣告封閉**（§5）：錨點放寬到裸 token、
   「接算子單元後」改成接任何算子單元。補完重跑，殘留清單應只剩已定案的真符號
   （c̄、c̄_p、D̄、ρ̃、ρ̄、Ψ̄ 等）。
4. **把 §4 的失效模式記進 judgement-flow**：位置分類會被上游剖析錯誤污染
   （叉積被讀成分數 → 兩個向量各自站上「分子/分母首位」）。
   位置封閉法不是無條件成立的。

## 8. 定案（主線裁決，2026-08-02 晚）

主線親驗 #942（∂ 與直立 D 同圖同字級可辨，末項 `Dh/Dt` 是唯一真 D）、
#977（FW–H 連續方程組）、#726（物質導數定義式）三張關鍵裁圖，
加上前輪已驗的 #567 同族結構。**提案全數照准：**

1. **R1–R5 共 35 處 → `\partial`，機械套用**（判準沿 §8.1：分側首位；
   #494 的裸 `\mathcal{O}` @469 一併納入）。
2. **#942 全部 16＋盲點 2 處不做單點替換，整條重轉錄**（第四條截斷式，
   比照 #947／#555／#957 流程）。
3. **掃描器兩個盲點先補再宣告封閉**（裸 token 錨點、「接任何算子單元後」），
   補完重跑封閉掃描，殘留只准剩已定案真符號（c̄、c̄_p、D̄、ρ̃、ρ̄、Ψ̄、
   `\mathfrak{O}` 孔隙率、大 O 記號）。多出新 token → 停。
4. §4 失效模式由主線寫入 judgement-flow（文檔工作）。
