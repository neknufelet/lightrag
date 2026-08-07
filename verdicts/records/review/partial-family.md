# ∂ 誤讀整族：裁決材料

**這份只是材料與提案，沒有動任何資料。** 定案欄留空給主線。

產生於 2026-08-02（階段 2.5，Opus 執行）。掃描器 `scan_partial.py` 見當次工單的
scratchpad；判準與程序依 `docs/judgement-flow.md` 第 3／4 節。

## 0. 一頁摘要

| 記號 | 處數 | 本次建議 | 信心 |
|---|---:|---|---|
| `\hat{\sigma}` | 927 | → `\partial`（**1 處例外必須排除**，見 §3.1） | 高 |
| `\hat{\partial}` | 26 | → `\partial` | 高 |
| `\hat{o}` | 12 | → `\partial` | 高 |
| `\bar{\partial}` | 6 | → `\partial` | 高 |
| `\hat{\alpha}` | 37 | → `\partial`（全數，見 §4） | 高 |
| `\widehat{\sigma}` | 6 | → `\partial`（**階段 2 的 949 沒涵蓋**） | 高 |
| `\hat{c}` | 24 | **多義，逐條看，不得機械套** | 高（對多義）／低（對任何單一映射） |
| `\bar{c}` | 5 | **多義，逐條看** | 中 |
| `\bar{D}` | 1 | 不動（是物質導數 D/Dt） | 高 |

掃描總命中 **1044** 處。與階段 2 記的 949 對不起來，三個原因都要知道：

1. 本次正則容許 `\hat { \sigma }` 這種**帶空白**的寫法，階段 2 的沒有；
2. 本次多掃了 `\widehat{\sigma}`／`\hat{c}`／`\bar{c}`／`\bar{D}` 四個**階段 2 沒發現的變體**；
3. `\hat{\alpha}` 本次量到 37 處，階段 2 記 21 處。

**「整族」目前不是一個封閉集合** —— 這是這次最該先解決的事。除了上表，
看圖過程中還發現 `\delta`（N Flow #1526 的 `\delta\tau` 實際是 `∂τ`）與
`\hat{\vO}`（#802，實際是 `∂`）也在微分位置上。**在族邊界固定之前，
任何「全族一次改完」的說法都不成立**：改完之後仍會有殘留的同類誤讀，
而且因為主族被改乾淨了，殘留的那些更難被發現。

## 1. 掃描器與它的兩個 bug（先驗偵測器）

judgement-flow 第 3 節要求相信結果之前先驗偵測器。這支掃描器在本輪修掉兩個：

| # | 症狀 | 真因 | 修法 |
|---|---|---|---|
| 1 | 用正則找 `\frac` 的引數 | 正則剖析不了配對括號 | 改寫成真正的配對括號掃描 |
| 2 | `∂p/∂z` 的**分子**被判成 `standalone` | 行內除法只認「前面有 `/`」，分子那側前面沒有 | 成對偵測，分子分母都標 `inline_div` |

**bug 2 直接改變結論。** 修之前有 11 個「非 frac 例外」，看起來像「零例外不成立、
要整族降級」；修之後只剩 **1 個**，而那 1 個是截斷式（§3.1）。
階段 2 記的「3 個非 frac」正是同一個假例外的一部分。

## 2. 主族聚類（`\hat{\sigma}` `\hat{\partial}` `\hat{o}` `\bar{\partial}`）

共 971 處 → 20 個結構聚類。聚類鍵是**結構**（分子/分母各自的首位是什麼、
記號各幾個、幾階、分子是不是裸算子、同式有沒有混用真 `\partial`），
不是字面。刻意不把不同結構硬併 —— 併了就看不出邊界在哪。

下表 7 群覆蓋 946 處；
其餘 13 群共 25 處全部逐一列在 §3。

| 群 | 處數 | 結構 | 代表（文件 #index） | 代表式子 | 建議裁決 | 依據 | 信心 | 定案 |
|---|---:|---|---|---|---|---|---|---|
| C1 | 343 | TOK/TOK / 分子記號1+partial0 / 分母記號1+partial0 / 1階 / 分子帶被微分量 / 全部是誤讀記號 | N Flow Acoustics #33 | `\frac{\hat{o}{\sfp}}{\hat{o}{\sfp}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×343）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C2 | 233 | TOK/TOK / 分子記號1+partial0 / 分母記號1+partial0 / 1階 / 分子裸算子 / 全部是誤讀記號 | N Flow Acoustics #188 | `\frac{\hat{o}}{\hat{\alpha}\mathrm{t}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×233）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C3 | 190 | TOK/TOK / 分子記號1+partial0 / 分母記號1+partial0 / 2階 / 分子帶被微分量 / 全部是誤讀記號 | N Flow Acoustics #208 | `\frac{\hat{\sigma}^{2}}{\hat{\sigma}\mathbf{t}^{2}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×190）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C4 | 150 | TOK/TOK / 分子記號1+partial0 / 分母記號2+partial0 / 2階 / 分子帶被微分量 / 全部是誤讀記號 | N Flow Acoustics #208 | `\frac{\hat{\sigma}^{2}}{\hat{\sigma}\mathbf{x_{i}}\hat{\sigma}\mathbf{t}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×150）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C5 | 10 | 非frac:inline_div | G Porous Absorbers #131 | `\hat{\sigma}\mathrm{p}/\hat{\sigma}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（G Porous Abs×8, N Flow Acous×2）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C6 | 10 | other/TOK / 分子記號0+partial0 / 分母記號1+partial0 / 1階 / 分子帶被微分量 / 全部是誤讀記號 | N Flow Acoustics #387 | `\frac{\hat{c}\rho^{\prime}}{\hat{\sigma}\mathbf{x}_{\mathbf{j}}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×10）；已抽樣看圖確認（§5 裁圖） | 高 |  |
| C7 | 10 | other/other / 分子記號1+partial0 / 分母記號1+partial0 / 1階 / 分子帶被微分量 / 全部是誤讀記號 | N Flow Acoustics #1040 | `\frac{\displaystyle\hat{\sigma}}{\displaystyle\hat{\sigma}\mathbf{x}_{\mathrm{j}}}` | 記號 → `\partial` | 全部落在 frac 的分子或分母首位＝微分算子位置；同結構在同一份文件內部一致（N Flow Acous×10）；已抽樣看圖確認（§5 裁圖） | 高 |  |

## 3. 例外與邊界案例（逐一全列，不聚類）

### 3.1 唯一的非除法位置：N Flow #947（截斷式）

- **位置類別**：`standalone`（掃描器判定）　**裁圖**：`crops/nflow-0947-p38-hat_sigma-39.png`
- **前後文**：`m { { i } } } } } + { \bf { v } } _ { \mathrm { i } } { \bf { v } } _ { \mathrm { j } } \frac { { { \hat { \sigma } } } } { { \hat { \sigma } } { \bf { x } } _ { \mathrm { i } } } } ) ] ( [ \frac { { \hat { \sigma } { \bf { v } } _ { \mathrm { i } } ^ { \prime } } } \hat \end{array}\tag{46} $$`
- **這是假的 standalone**：LaTeX 在 `\frac { { \hat{\sigma} {\bf v}_i^{\prime} } }` 之後直接
  斷掉（一個沒有引數的裸 `\hat` 接 `\end{array}`），**分母整個不存在**，所以掃描器
  找不到它的 frac。裁圖上該處是 `(∂v_i′/∂t)`。

| 建議裁決 | 依據 | 信心 | 定案 |
|---|---|---|---|
| **不做單點替換**；整條 eq (46) 重新轉錄（走 eq-check 三票） | 裁圖顯示原式完整且可讀，但 MinerU 的 LaTeX 是**截斷**的，缺的不只一個記號 —— 把 `\hat{\sigma}` 換成 `\partial` 會得到一條「記號正確但仍然殘缺」的式子，比現在更難被發現壞掉 | 高 |  |

### 3.2 機械規則的**反例**：N Flow #1015 —— 那個 `\hat{\sigma}` 是 `f`，不是 `∂`

- **裁圖**：`crops/nflow-1015-p41-hat_sigma-42.png`
- **現值**：`$$\mathrm{F_{i}=\mathrm{p_{ij}\frac{\partial\hat{\sigma}}{\partialx_{j}}=\mathrm{p_{ij}\mathrm{n_{j}}}}}\tag{13}$$`
- **裁圖上寫的是**：`F_i = p_ij ∂f/∂x_j = p_ij n_j`（式 13）
- MinerU 這裡把**真的 `\partial` 讀對了**，卻把被微分的量 **`f`** 讀成 `\hat{\sigma}`。
  `f` 是定義聲源曲面 `f=0` 的函數，`∂f/∂x_j = n_j` 是曲面法向量的標準恆等式 ——
  等號右邊的 `p_ij n_j` 自己就把答案寫在那裡。

| 建議裁決 | 依據 | 信心 | 定案 |
|---|---|---|---|
| `\hat{\sigma}` → **`f`**（不是 `\partial`） | 裁圖直讀＋等號右邊 `p_ij n_j` 交叉驗證；FW–H formulation 裡 `∂f/∂x_j = n_j` 是標準式 | 高 |  |

> **這一處就是「零例外」不成立的全部內容。** 機械套用會把它變成 `∂∂/∂x_j`。
> 它同時說明族的判準不能只看記號，要看**位置**：這個 `\hat{\sigma}` 站在
> 「被微分的量」的位置上，不是算子位置 —— 掃描器判它 `frac_num` 是對的，
> 但 `frac_num` 同時涵蓋「算子」與「被微分量」兩種角色，這是目前分類的盲點。

### 3.3 其餘小群與單例

> 讀法兩點：
> 1. **建議欄是「項目層級」的旗標，不是逐一處的最終映射。** 例如 #957 的每一列都寫
>    「逐條看」，但那條式子裡的 `\hat{\sigma}` 本身是單純的 `∂`；標記的用意是
>    **整條式子含有多義記號、不得整批自動處理**。寧可多攔，不可漏攔。
> 2. 同一個 `#index` 出現多列＝同一條式子裡有多處命中，位置類別各自標註。

| 文件 #index | p | 記號 | 位置類別 | 式子 | 建議裁決 | 依據 | 信心 | 定案 |
|---|---|---|---|---|---|---|---|---|
| N Flow Acoustics #566 | 21 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}}{\partial{\bfx}_{\mathrm{i}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #957 | 38 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}}{\partial\mathrm{x}_{\mathrm{i}}}` | **逐條看**：同式內 `\hat{c}` 一處是 `∂`、一處是 `c̄` | 裁圖顯示 `∂²B′/∂x_i²`（該 `\hat{c}` 是 ∂）與 `1/c̄²`（該 `\hat{c}` 是 c̄）—— 同一條式子、同一個記號、兩個意思 | 高 |  |
| N Flow Acoustics #1510 | 63 | `hat_partial` | `frac_num` | `\frac{\hat{\partial}}{\partial\mathbf{x_{i}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1526 | 64 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}}{\partial{\bft}}` | `\hat{\sigma}` → `\partial`，且**同式的 `\delta\tau` 應為 `∂τ`** | 裁圖為 `∂/∂τ`；`\delta` 是本次新見的第六個變體，不在任何既有清單裡 | 高 |  |
| N Flow Acoustics #773 | 30 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}^{2}\mathrm{p}}{\partial\mathrm{t}^{2}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #993 | 40 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}^{2}}{\partial\mathbf{t}^{2}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1156 | 48 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}^{2}}{\partial\mathbf{t}^{2}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1040 | 42 | `hat_sigma` | `frac_num` | `\frac{\displaystyle\hat{\sigma}^{2}}{\displaystyle\hat{\sigma}\mathbf{x}_{\mathrm{i}}\displaystyle\hat{\sigma}\mathbf{x}…` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1040 | 42 | `hat_sigma` | `frac_den` | `\frac{\displaystyle\hat{\sigma}^{2}}{\displaystyle\hat{\sigma}\mathbf{x}_{\mathrm{i}}\displaystyle\hat{\sigma}\mathbf{x}…` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1040 | 42 | `hat_sigma` | `frac_den` | `\frac{\displaystyle\hat{\sigma}^{2}}{\displaystyle\hat{\sigma}\mathbf{x}_{\mathrm{i}}\displaystyle\hat{\sigma}\mathbf{x}…` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #331 | 11 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}\mathrm{F}^{\prime}}{\partial\mathrm{x}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #993 | 40 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}}{\partial\mathbf{t}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #566 | 21 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}^{2}}{\partial{\bfx}_{\mathrm{i}}\hat{\sigma}{\bfx}_{\mathrm{j}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #566 | 21 | `hat_sigma` | `frac_den` | `\frac{\hat{\sigma}^{2}}{\partial{\bfx}_{\mathrm{i}}\hat{\sigma}{\bfx}_{\mathrm{j}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #676 | 26 | `hat_sigma` | `frac_num` | `\frac{\overline{{\hat{\sigma}\mathbf{v}_{\mathrm{j}}^{\prime}}}}{\hat{\sigma}\mathbf{x_{i}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #676 | 26 | `hat_sigma` | `frac_den` | `\frac{\overline{{\hat{\sigma}\mathbf{v}_{\mathrm{j}}^{\prime}}}}{\hat{\sigma}\mathbf{x_{i}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #922 | 36 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}\left({\rho}{\mathrm{uv}_{\mathrm{j}}}+\frac{1}{2}{\rho}{\mathbf{v}_{\mathrm{i}}}^{2}{\mathbf{v}_{\m…` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #922 | 36 | `hat_sigma` | `frac_den` | `\frac{{\hat{\sigma}}\left({\rho}{\mathrm{uv}_{\mathrm{j}}}+\frac{1}{2}{\rho}{\mathbf{v}_{\mathrm{i}}}^{2}{\mathbf{v}_{\m…` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1156 | 48 | `hat_sigma` | `frac_num` | `\frac{{\hat{\sigma}}^{2}\mathrm{T_{ij}}}{\partial\mathbf{x_{i}}\partial\mathbf{x_{j}}}` | 記號 → `\partial` | 位於 frac 分子或分母首位（微分算子位置）；同式常混用真 `\partial` | 中 |  |
| N Flow Acoustics #1526 | 64 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}^{2}}{\partial{\bfx}_{\mathrm{i}}\partial{\bfx}_{\mathrm{j}}}` | `\hat{\sigma}` → `\partial`，且**同式的 `\delta\tau` 應為 `∂τ`** | 裁圖為 `∂/∂τ`；`\delta` 是本次新見的第六個變體，不在任何既有清單裡 | 高 |  |
| N Flow Acoustics #802 | 31 | `hat_sigma` | `frac_den` | `\frac{\hat{\vO}^{2}}{\hat{\sigma}\mathrm{t}^{2}}` | `\hat{\vO}` → `\partial`（`\hat{\sigma}` 同） | 裁圖為 `∂²/∂t²`；`\hat{\vO}` 也是階段 2 未涵蓋的變體 | 高 |  |
| N Flow Acoustics #957 | 38 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}^{2}\mathrm{B}^{\prime}}{\hat{c}\mathrm{x}_{\mathrm{i}}^{2}}` | **逐條看**：同式內 `\hat{c}` 一處是 `∂`、一處是 `c̄` | 裁圖顯示 `∂²B′/∂x_i²`（該 `\hat{c}` 是 ∂）與 `1/c̄²`（該 `\hat{c}` 是 c̄）—— 同一條式子、同一個記號、兩個意思 | 高 |  |
| N Flow Acoustics #1526 | 64 | `hat_sigma` | `frac_num` | `\frac{\hat{\sigma}}{\delta\tau}` | `\hat{\sigma}` → `\partial`，且**同式的 `\delta\tau` 應為 `∂τ`** | 裁圖為 `∂/∂τ`；`\delta` 是本次新見的第六個變體，不在任何既有清單裡 | 高 |  |

## 4. `\hat{\alpha}` 全部 37 處（工單指定全列）

α 在本語料裡多義（吸音係數、熱擴散率），所以它是這次的關鍵變數。
**但實際掃出來的 37 處全部落在微分位置，而且有三種互相獨立的證據：**

1. **同式混用真 `\partial`**：`\frac{\hat{\alpha} v_i′}{\partial x_j}`、
   `\frac{\partial \Phi}{\hat{\alpha}\tau}` —— 同一個分數裡一邊讀對一邊讀錯，
   讀對的那邊直接證明另一邊是什麼。
2. **同式混用其他誤讀變體**：`\frac{\hat{o}}{\hat{\alpha} t}`、
   `\frac{\hat{\alpha} e}{\hat{\sigma} t}`。
3. **裁圖**：#1030 為 `∂φ/∂n + (M_n/c₀)∂φ/∂t_x … ∂²T_ij/∂x_i∂x_j`；
   #1307 為 `∂r/∂n`、`∂Φ/∂n`、`∂/∂τ`。逐一對得上。

| 文件 #index | p | 位置類別 | frac | 裁圖 | 建議裁決 | 依據 | 信心 | 定案 |
|---|---|---|---|---|---|---|---|---|
| G Porous Absorbe #467 | 40 | `frac_num` | `\frac{\hat{\alpha}\mathrm{u_{\mathrm{si}}}}{\hat{\alpha}\mathrm{x_{j}}}` | `crops/gporous-0467-p40-hat_alpha-41.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| G Porous Absorbe #467 | 40 | `frac_den` | `\frac{\hat{\alpha}\mathrm{u_{\mathrm{si}}}}{\hat{\alpha}\mathrm{x_{j}}}` | `crops/gporous-0467-p40-hat_alpha-41.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| G Porous Absorbe #467 | 40 | `frac_num` | `\frac{\hat{\alpha}\mathrm{u_{\mathrm{sj}}}}{\hat{\alpha}\mathrm{x_{i}}}` | `crops/gporous-0467-p40-hat_alpha-41.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| G Porous Absorbe #467 | 40 | `frac_den` | `\frac{\hat{\alpha}\mathrm{u_{\mathrm{sj}}}}{\hat{\alpha}\mathrm{x_{i}}}` | `crops/gporous-0467-p40-hat_alpha-41.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #188 | 6 | `frac_den` | `\frac{\hat{o}}{\hat{\alpha}\mathrm{t}}` | `crops/nflow-0188-p6-hat_alpha-hat_o-07.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #188 | 6 | `frac_den` | `\frac{\hat{o}}{\hat{\alpha}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0188-p6-hat_alpha-hat_o-07.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #274 | 10 | `frac_num` | `\frac{\hat{\alpha}\mathrm{e}}{\hat{\sigma}\mathrm{t}}` | `crops/nflow-0274-p10-hat_alpha-hat_sigma-11.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{v}_{\mathrm{i}}^{\prime}}{\partial\mathbf{x}_{\mathrm{j}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 混用真 `\partial` | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{p}_{0}}{\partial\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 混用真 `\partial` | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{v}_{\mathrm{i}}^{\prime}}{\partial\mathbf{x}_{\mathrm{j}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 混用真 `\partial` | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{p}^{\prime}}{\partial\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 混用真 `\partial` | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{v}_{\mathrm{i}}^{\prime}}{\hat{\alpha}\mathbf{x}_{\mathrm{j}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_den` | `\frac{\hat{\alpha}\mathbf{v}_{\mathrm{i}}^{\prime}}{\hat{\alpha}\mathbf{x}_{\mathrm{j}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #396 | 14 | `frac_num` | `\frac{\hat{\alpha}\mathbf{p}^{\prime}}{\partial\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | → `\partial` | 混用真 `\partial` | 高 |  |
| N Flow Acoustics #427 | 15 | `frac_num` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{x_{j}}}` | `crops/nflow-0427-p15-hat_alpha-16.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #427 | 15 | `frac_den` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{x_{j}}}` | `crops/nflow-0427-p15-hat_alpha-16.png` | → `\partial` | 分子/分母首位＝微分算子位置 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_num` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}\mathbf{n}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}\mathbf{n}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_num` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}\mathbf{t}_{\mathbf{x}}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}\mathbf{t}_{\mathbf{x}}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_num` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{t}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{t}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_num` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{x}_{\mathbf{i}}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}}{\hat{\alpha}\mathbf{x}_{\mathbf{i}}}` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_num` | `\frac{\hat{\alpha}^{2}\mathbf{T}_{\mathbf{ij}}}{\hat{\alpha}\mathbf{x}_{\mathbf{i}}\hat{\alpha}\mathbf{x}_{\ma…` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}^{2}\mathbf{T}_{\mathbf{ij}}}{\hat{\alpha}\mathbf{x}_{\mathbf{i}}\hat{\alpha}\mathbf{x}_{\ma…` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1030 | 42 | `frac_den` | `\frac{\hat{\alpha}^{2}\mathbf{T}_{\mathbf{ij}}}{\hat{\alpha}\mathbf{x}_{\mathbf{i}}\hat{\alpha}\mathbf{x}_{\ma…` | `crops/nflow-1030-p42-hat_alpha-43.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}{\bfr}}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_den` | `\frac{\hat{\alpha}{\bfr}}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}{\bfn}}{r^{2}\left(1-{\bfM}_{\mathrm{r}}\right)}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_den` | `\frac{\hat{\alpha}\Phi}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_den` | `\frac{\partial\Phi}{\hat{\alpha}\tau}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 混用真 `\partial`；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}}{\hat{\sigma}\tau}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}{\bfr}}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_den` | `\frac{\hat{\alpha}{\bfr}}{\hat{\alpha}{\bfn}}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |
| N Flow Acoustics #1307 | 54 | `frac_num` | `\frac{\hat{\alpha}\left(1-{\bfM}_{\mathrm{r}}\right)}{\tau}` | `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | → `\partial` | 分子/分母首位＝微分算子位置；裁圖逐一確認 | 高 |  |

**邊界案例（已解決）**：`\frac{\hat{\alpha}{\bf n}}{r^2(1-M_r)}`（#1307）乍看分母不是
微分量，像是反例。裁圖顯示那是**巢狀分數**：`(∂r/∂n) / (r²(1−M_r))`，
掃描器看到的是內層分數的分母被當成外層分數的分子。仍是 `∂`。

## 5. 族邊界候補（階段 2 的 949 完全沒涵蓋）

| 記號 | 處數 | 建議裁決 | 依據 | 信心 | 定案 |
|---|---:|---|---|---|---|
| `\widehat{\sigma}` | 6 | → `\partial` | 裁圖 #1346 為 `∂²T_ij/∂t²`；與 `\hat{\sigma}` 同型，只差 `\widehat` vs `\hat` | 高 |  |
| `\hat{c}` | 24 | **不得機械套，逐條看** | #957 同一式內兩義（`∂` 與 `c̄`）；c 在本語料是聲速，本身就是高頻變數 | 高（對多義） |  |
| `\bar{c}` | 5 | **不得機械套，逐條看** | 同上；裁圖 #957 顯示 `1/c̄²`、`∂c̄²/∂x_i` 並存 | 中 |  |
| `\bar{D}` | 1 | **不動** | 裁圖 #947 顯示 `Dh/Dt`，是物質導數，不是 ∂ | 高 |  |
| `\delta`（未計數） | ≥1 | 逐條看 | #1526 的 `\delta\tau` 裁圖為 `∂τ`；但 δ 在聲學裡是 Dirac delta，多義程度高 | 中 |  |
| `\hat{\vO}`（未計數） | ≥1 | → `\partial` | #802 裁圖為 `∂²/∂t²` | 高 |  |

逐一列出的候補案例：

| 文件 #index | p | 記號 | 位置類別 | frac | 裁圖 |
|---|---|---|---|---|---|
| N Flow Acoustics #187 | 6 | `bar_D` | `frac_num` | `\frac{\bar{D}p^{\prime}}{Dt}` | `crops/nflow-0187-p6-bar_D-07.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho^{\prime}}{\hat{c}\mathbf{t}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_den` | `\frac{\hat{c}\rho^{\prime}}{\hat{c}\mathbf{t}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho^{\prime}}{\hat{\sigma}\mathbf{x}_{\mathbf{j}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho_{0}}{\hat{\sigma}\mathbf{x}_{\mathbf{j}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathbf{v}_{\mathbf{i}}^{\prime}}{\hat{\sigma}\mathbf{x}_{\mathbf{i}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathbf{v}_{0\mathbf{i}}}{\hat{\sigma}\mathbf{x}_{\mathbf{i}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho_{0}}{\hat{\sigma}\mathbf{t}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho_{0}}{\hat{\sigma}\mathbf{x}_{\mathbf{j}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #387 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\rho^{\prime}}{\hat{\sigma}\mathbf{x}_{\mathbf{j}}}` | `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` |
| N Flow Acoustics #396 | 14 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathbf{p}^{\prime}}{\partial\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathrm{v}_{\mathrm{ai}}}{\hat{c}\mathrm{t}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_den` | `\frac{\hat{c}\mathrm{v}_{\mathrm{ai}}}{\hat{c}\mathrm{t}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathrm{v}_{\mathrm{ai}}}{\hat{c}\mathrm{x}_{\mathrm{j}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_den` | `\frac{\hat{c}\mathrm{v}_{\mathrm{ai}}}{\hat{c}\mathrm{x}_{\mathrm{j}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathrm{p}_{\mathrm{a}}}{\hat{c}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_den` | `\frac{\hat{c}\mathrm{p}_{\mathrm{a}}}{\hat{c}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathrm{v}_{\mathrm{0i}}}{\hat{c}\mathrm{x}_{\mathrm{j}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_den` | `\frac{\hat{c}\mathrm{v}_{\mathrm{0i}}}{\hat{c}\mathrm{x}_{\mathrm{j}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #409 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathrm{p}_{\mathrm{0}}}{\hat{\sigma}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #415 | 15 | `hat_c` | `frac_num` | `\frac{\hat{c}\mathbf{p}_{\mathrm{t}}}{\hat{\sigma}\mathbf{x}_{\mathrm{i}}}` | `crops/nflow-0415-p15-hat_c-hat_sigma-16.png` |
| N Flow Acoustics #555 | 20 | `hat_c` | `frac_den` | `\frac{\partial^{2}(\mathbf{T}_{\mathrm{i}})_{\mathrm{r}}}{\hat{c}}` | `crops/nflow-0555-p20-hat_c-21.png` |
| N Flow Acoustics #724 | 28 | `bar_c` | `frac_den` | `\frac{1}{\bar{c}^{2}}` | `crops/nflow-0724-p28-bar_c-hat_sigma-29.png` |
| N Flow Acoustics #766 | 30 | `bar_c` | `frac_den` | `\frac{1}{\bar{c}^{2}}` | `crops/nflow-0766-p30-bar_c-hat_sigma-31.png` |
| N Flow Acoustics #957 | 38 | `hat_c` | `frac_den` | `\frac{\hat{\sigma}^{2}\mathrm{B}^{\prime}}{\hat{c}\mathrm{x}_{\mathrm{i}}^{2}}` | `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` |
| N Flow Acoustics #957 | 38 | `hat_c` | `standalone` | （無 frac，見前後文） | `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` |
| N Flow Acoustics #957 | 38 | `bar_c` | `frac_num` | `\frac{\hat{\sigma}\bar{c}^{2}}{\hat{\sigma}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` |
| N Flow Acoustics #957 | 38 | `hat_c` | `frac_den` | `\frac{1}{\hat{c}^{2}}` | `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` |
| N Flow Acoustics #957 | 38 | `bar_c` | `frac_num` | `\frac{\hat{\sigma}\bar{c}^{2}}{\hat{\sigma}\mathrm{x}_{\mathrm{i}}}` | `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` |
| N Flow Acoustics #1123 | 46 | `bar_c` | `standalone` | （無 frac，見前後文） | `crops/nflow-1123-p46-bar_c-47.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_num` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{ij}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_den` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{ij}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_num` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{kl}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_den` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{kl}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_num` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{ij}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |
| N Flow Acoustics #1346 | 56 | `widehat_sigma` | `frac_den` | `\frac{\widehat{\sigma}^{2}\mathrm{T}_{\mathrm{ij}}}{\widehat{\sigma}\mathrm{t}^{2}}` | `crops/nflow-1346-p56-widehat_sigma-57.png` |

## 6. 裁圖索引

全部用 `pp/pdfcrop` 產生，`EQ_PAD_X=4`／**`EQ_PAD_Y=1`**（垂直不擴 —— 6 點會把上下
鄰居框進圖裡，那正是鐵則 4 記的那次假分歧）。

| 檔名 | 文件 | #index | 頁 | 記號 |
|---|---|---|---|---|
| `crops/gporous-0131-p10-hat_sigma-11.png` | G Porous Absorbers | #131 | 10 | `hat_sigma` |
| `crops/gporous-0133-p10-hat_sigma-11.png` | G Porous Absorbers | #133 | 10 | `hat_sigma` |
| `crops/gporous-0458-p40-hat_partial-41.png` | G Porous Absorbers | #458 | 40 | `hat_partial` |
| `crops/gporous-0467-p40-hat_alpha-41.png` | G Porous Absorbers | #467 | 40 | `hat_alpha` |
| `crops/nflow-0008-p0-hat_o-01.png` | N Flow Acoustics | #8 | 0 | `hat_o` |
| `crops/nflow-0187-p6-bar_D-07.png` | N Flow Acoustics | #187 | 6 | `bar_D` |
| `crops/nflow-0188-p6-hat_alpha-hat_o-07.png` | N Flow Acoustics | #188 | 6 | `hat_alpha`, `hat_o` |
| `crops/nflow-0199-p7-bar_partial-08.png` | N Flow Acoustics | #199 | 7 | `bar_partial` |
| `crops/nflow-0274-p10-hat_alpha-hat_sigma-11.png` | N Flow Acoustics | #274 | 10 | `hat_alpha`, `hat_sigma` |
| `crops/nflow-0331-p11-hat_sigma-12.png` | N Flow Acoustics | #331 | 11 | `hat_sigma` |
| `crops/nflow-0387-p14-hat_c-hat_sigma-15.png` | N Flow Acoustics | #387 | 14 | `hat_c`, `hat_sigma` |
| `crops/nflow-0396-p14-hat_alpha-hat_c-15.png` | N Flow Acoustics | #396 | 14 | `hat_alpha`, `hat_c` |
| `crops/nflow-0409-p15-hat_c-hat_sigma-16.png` | N Flow Acoustics | #409 | 15 | `hat_c`, `hat_sigma` |
| `crops/nflow-0415-p15-hat_c-hat_sigma-16.png` | N Flow Acoustics | #415 | 15 | `hat_c`, `hat_sigma` |
| `crops/nflow-0427-p15-hat_alpha-16.png` | N Flow Acoustics | #427 | 15 | `hat_alpha` |
| `crops/nflow-0555-p20-hat_c-21.png` | N Flow Acoustics | #555 | 20 | `hat_c` |
| `crops/nflow-0566-p21-hat_sigma-22.png` | N Flow Acoustics | #566 | 21 | `hat_sigma` |
| `crops/nflow-0676-p26-hat_sigma-27.png` | N Flow Acoustics | #676 | 26 | `hat_sigma` |
| `crops/nflow-0724-p28-bar_c-hat_sigma-29.png` | N Flow Acoustics | #724 | 28 | `bar_c`, `hat_sigma` |
| `crops/nflow-0766-p30-bar_c-hat_sigma-31.png` | N Flow Acoustics | #766 | 30 | `bar_c`, `hat_sigma` |
| `crops/nflow-0773-p30-hat_sigma-31.png` | N Flow Acoustics | #773 | 30 | `hat_sigma` |
| `crops/nflow-0802-p31-hat_sigma-32.png` | N Flow Acoustics | #802 | 31 | `hat_sigma` |
| `crops/nflow-0922-p36-hat_sigma-37.png` | N Flow Acoustics | #922 | 36 | `hat_sigma` |
| `crops/nflow-0947-p38-hat_sigma-39.png` | N Flow Acoustics | #947 | 38 | `hat_sigma` |
| `crops/nflow-0957-p38-bar_c-hat_c-hat_sigma-39.png` | N Flow Acoustics | #957 | 38 | `bar_c`, `hat_c`, `hat_sigma` |
| `crops/nflow-0993-p40-hat_sigma-41.png` | N Flow Acoustics | #993 | 40 | `hat_sigma` |
| `crops/nflow-1015-p41-hat_sigma-42.png` | N Flow Acoustics | #1015 | 41 | `hat_sigma` |
| `crops/nflow-1030-p42-hat_alpha-43.png` | N Flow Acoustics | #1030 | 42 | `hat_alpha` |
| `crops/nflow-1040-p42-hat_sigma-43.png` | N Flow Acoustics | #1040 | 42 | `hat_sigma` |
| `crops/nflow-1123-p46-bar_c-47.png` | N Flow Acoustics | #1123 | 46 | `bar_c` |
| `crops/nflow-1135-p47-?-48.png` | N Flow Acoustics | #1135 | 47 | — |
| `crops/nflow-1156-p48-hat_sigma-49.png` | N Flow Acoustics | #1156 | 48 | `hat_sigma` |
| `crops/nflow-1307-p54-hat_alpha-hat_sigma-55.png` | N Flow Acoustics | #1307 | 54 | `hat_alpha`, `hat_sigma` |
| `crops/nflow-1346-p56-widehat_sigma-57.png` | N Flow Acoustics | #1346 | 56 | `widehat_sigma` |
| `crops/nflow-1510-p63-hat_partial-64.png` | N Flow Acoustics | #1510 | 63 | `hat_partial` |
| `crops/nflow-1518-p64-?-65.png` | N Flow Acoustics | #1518 | 64 | — |
| `crops/nflow-1526-p64-hat_sigma-65.png` | N Flow Acoustics | #1526 | 64 | `hat_sigma` |

## 7. 建議的裁決順序（提案）

1. **先關族邊界，再談套用。** 目前確定的變體有 9 個（`\hat{\sigma}` `\hat{\partial}` `\hat{o}` `\bar{\partial}` `\hat{\alpha}` `\widehat{\sigma}` `\hat{c}` `\bar{c}` 以及 `\delta`／`\hat{\vO}`），
   而這個清單是**這一輪才長出來的** —— 上一輪掃描說 949、這一輪說 1044+。
   在「還會不會再多出一個」有答案之前，套用只會讓殘留更難找。
2. **位置分類要再細一階。** 目前 `frac_num` 同時涵蓋「算子」與「被微分的量」，
   #1015 就是踩在這個盲點上。加一條「分子首位是記號**且**其後緊接被微分量」的
   判準，才能把 #1015 這型自動排除，而不是靠人記得它。
3. **可機械的與不可機械的分開處置**：`\hat{\sigma}`／`\hat{\partial}`／`\hat{o}`／
   `\bar{\partial}`／`\hat{\alpha}`／`\widehat{\sigma}` 證據一致、建議機械套用；
   `\hat{c}`／`\bar{c}`／`\delta` 多義，建議逐條看，理由與 NEXT 的
   「23 處 `\mathsf{P}` 不碰」完全同型。
4. **#947 走 eq-check 三票整條重轉錄**，不做單點替換。

## 8. 定案（主線裁決，2026-08-02）

主線親自驗證 16 張裁圖（#1015、#947、#1030、#467、#957、#187、#409、#131、
#1346、#555、#387、#1123、#802、#1526、#566、#922），涵蓋每一個決策類別與
全部高風險邊界案例。**提案零推翻。** 定案如下：

### 8.1 機械套用（准）

**套用判準：只換分子／分母「首位」的記號**（首位＝該側第一個 token，其後接
被微分量或為裸算子；行內除法兩側同理）。同側**前方已有 `\partial`** 的記號是
被微分量（#1015 型），一律排除並列入回報。

| 範圍 | 定案 |
|---|---|
| C1–C7 全部（946 處） | → `\partial` |
| §3.3 單例（除 #947、#957、#1015 外全部，含 #1526 的 `\delta\tau`→`\partial\tau`、#802 的 `\hat{\vO}`） | → `\partial` |
| §4 `\hat{\alpha}` 全 37 處 | → `\partial` |
| §5 `\widehat{\sigma}` 6 處 | → `\partial` |

### 8.2 逐條定案（非機械）

| 處 | 定案 | 裁圖依據 |
|---|---|---|
| #1015 `\hat{\sigma}` | → **`f`**（不是 ∂） | `∂f/∂x_j = n_j`，FW–H 曲面函數 |
| #947 整條 | 不做單點替換；eq-check 三票整條重轉錄後走 verified 裁定檔寫入 | 裁圖完整可讀，LaTeX 截斷 |
| `\hat{c}`：#387 全部、#396、#409 全部、#415、#555 | → `\partial` | 連續方程／動量方程／Ribner 解，逐張驗過 |
| `\hat{c}`：#957 的 `\frac{1}{\hat{c}^2}` | → **`\bar{c}`**（1/c̄²） | 裁圖同式並存 `1/c̄²` 與 `∂c̄²/∂x_i` |
| `\hat{c}`：#957 其餘（`\hat{σ}²B′/\hat{c}x_i²` 的 ĉ、standalone） | → `\partial`（套用時對照裁圖逐處確認） | `∂²B′/∂x_i²` |
| `\bar{c}` 全 5 處（#724、#766、#957×2、#1123） | **不動**（真 c̄／c̄_p） | `1/c̄²`、`∂c̄²/∂x_i`、`c̄_p` |
| `\bar{D}` #187 | **不動**（D̄/Dt 平均流物質導數） | `D̄p′/Dt` |

### 8.3 族邊界封閉（套用後必跑）

套用完成後跑**符號無關**的位置掃描：任何 accent 類 token（`\hat`／`\bar`／
`\widehat`／`\tilde`）出現在 frac 首位或行內除法算子位置而不是 `\partial` 的，
全列殘留清單。清單上只應剩本檔已定案的真符號（c̄、c̄_p、D̄）。
**多出任何新 token → 停下回報，不得自行套用。** 這是對「族還會不會再長」的
結構性回答：以位置封閉，不以符號枚舉。

## 8.4 套用輪呈上的三個裁決（主線定案，2026-08-02 晚）

1. **`pp.equations` 對 N Flow／G Porous 維持 `fail`**（執行者的裁量正確）：
   量到了具體缺陷（57 處未定案新變體），「驗了、沒過」不是「沒得驗」。
   變體定案後再翻。
2. **#957 的 `\cfrac{1}{\hat{c}^2}` → `\bar{c}`**：裁圖為 `1/c̄²`；
   「standalone → ∂」的原裁決建立在掃描器漏認 `\cfrac` 的錯誤標籤上，
   同式同形的 `\frac{1}{\hat{c}^2}` 已裁 c̄。裁圖勝過標籤。
   實際執行併入 #957 整條重轉錄（見下）。
3. **#555 與 #957 比照 #947 整條重轉錄**：兩條都證實截斷
   （#555 分母只剩裸 ∂、#957 缺第三行），§3.1 的警告成立——
   「記號正確但仍然殘缺」的式子比明顯壞掉的更危險。
4. 執行者對「首位判準」的解讀（排除「緊接算子之後」而非「同側含 ∂ 即排除」）
   **追認為正確**——§8.1 原文的兩句話只有這個讀法能同時成立，
   且數字精確對帳（983＋40＋#947 18＋#957 16＋#1015 1）。

## 8.5 族邊界第二輪：57 處新變體（待裁決）

封閉掃描攔下：`\hat{\mathcal{O}}` 34、`\hat{\mathcal{D}}` 13、
`\hat{\boldsymbol{\sigma}}` 4、`\bar{\boldsymbol\sigma}` 3、
`\tilde{\boldsymbol\omega}` 2。裁決材料（裁圖＋建議）由下一輪工單產出。
**特別注意 `\hat{\mathcal{D}}`：D/Dt 物質導數是真實可能**
（`\frac{\mathcal{D}}{\mathcal{D}t}` 與 `∂/∂t` 在字面上同構），
裁圖必須分辨 ∂ 字形與 D 字形，不得從結構推定。
`\bar{\boldsymbol\sigma}` 已知同式兩義（#957：一處 ∂、一處 ω̄⃗ 疊層重音），
與 ĉ 完全同型，逐條看。

