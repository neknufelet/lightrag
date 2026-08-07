# N Flow 兩條巨型 equation：#1135 與 #1518

**材料，沒有動資料。** 這兩條是階段 2 標成「判不準」的顯示式吞散文案例。

兩者的形狀在本輪看圖後確定了，而且**跟階段 2 的描述不一樣**：
它們不是「一條式子吞掉旁邊的散文」，是**整塊「符號—說明」對照表
（nomenclature／變數說明清單）被 MinerU 整片判成一個 `equation` 項目**。
清單裡的說明文字被排成逐字母的 `\mathrm{s p a t i a l ~ …}`，所以
coverage 偵測器 v1 把它們算成漏詞（偵測器 v2 已修，見體檢表）。

| | #1135 | #1518 |
|---|---|---|
| type | `equation` | `equation` |
| page_idx（0-based） | 47 | 64 |
| bbox（MinerU 0–1000 正規化） | `[88, 132, 801, 629]` | `[166, 102, 892, 387]` |
| bbox（換算 PDF 點） | `(38.6, 87.9, 351.6, 418.9)` | `(72.9, 67.9, 391.6, 257.7)` |
| 頁面尺寸（點） | 439.0 × 666.0 | 439.0 × 666.0 |
| LaTeX 長度 | 1,630 字元 | 1,679 字元 |
| 文字層長度 | 968 字元 | 515 字元 |
| 裁圖 | `crops/nflow-1135-p47-?-48.png` | `crops/nflow-1518-p64-?-65.png` |

## #1135（p47）

裁圖：`crops/nflow-1135-p47-?-48.png`

### 裁圖上實際是什麼

上半是一條真的顯示式 `W(ω) = …`（雙重體積分），接著一行 `with:` 帶出
`Γ(ξ_z, ξ_r, ω) = exp(…)` 的定義式，**再往下整整三分之二頁是符號說明清單**：
`Γ(ξ_z,ξ_r,ω)` → spatial and frequency coherence function、`ξ_z, ξ_r` →
longitudinal and radial separation distances、`L_cz, L_cr`、`ω_t = 2πC_ω ε/k`、
`C_ω = 1,5`、`P(ω) = 2a/(π(1+a²ω²))`、`a = k/(C_S ε)`、`k`、`ε`、`C_S = 6,4`
與各自的英文描述，最後是一條文獻出處（Sanders & Lammers, Combustion and Flame, 1994）。

### equation 現值（退化 LaTeX，前 1600 字元）

```latex
$$
\begin{array} { r l } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } } & { \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } \{ \int _ { 0 } ^ { \infty } \sin ( 2 \pi \zeta ) \sin ( 2 \pi \zeta ) \sin ( 2 \pi \zeta ) \sin ( 2 \pi \zeta ) \} , } \\ & { \quad + \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } \{ ( \frac { \sin 2 \pi \zeta } { \sin \zeta } ) \sin ( 2 \pi \zeta ) \} \{ \exp ( \frac { \pi \zeta } { \sin \zeta } ) \} \{ \sin ( 2 \pi \zeta ) \} } \\ &  \quad + \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } \{ \exp ( \frac { \pi \zeta } { \sin \zeta } ) \sin ( 2 \pi \zeta ) \} \exp ( \frac { \pi \zeta } { \sin \zeta } ) \} \\ &  \quad + \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } \{ \exp ( \frac { \pi \zeta } { \sin \zeta } ) \sin ( 2 \pi \zeta ) \} \exp ( \frac { \pi \zeta } { \sin \zeta } ) \} \\ & { \quad + \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } } \{ \exp ( \frac { \pi \zeta } { \sin \zeta } ) \sin ( 2 \pi \zeta ) \} \exp ( \frac { \pi \zeta } { \sin \zeta } ) } \\ &  \quad \times \frac { \operatorname* { m a x } _ { t = 1 } ^ { \infty } \theta _ { t } }  \operatorname* { m
…（共 1,630 字元）
```

### 同 bbox 的 pdftotext 原文

```text
W(–) =

with:

 
(‰ − 1)2 4
k
Srms (yi )Srms (yi ) z , r, , –
40 c0
Vy  Vy 
 




kac ri 2 kac rj

J0
dyi dyi
× P yi , – P yi, – J20
2
2




 √


−2z
−–2
−2r
exp
exp
z , r , – = exp
L2cz
L2cr
–t
4–2t

z , r , –
z ,  r
Lcz , Lcr
–t = 2C–
–t
C– = 1,5
P(–) =
P(–)

a=

k
CS —

—
k

spatial and frequency coherence function
longitudinal and radial separation distances respectively between acoustic sources
longitudinal and radial coherence scale respectively
characteristic angular frequency of turbulence

2a
 (1 + a2 –2 )
normalised temperature ﬂuctuation spectrum, containing characteristic time for temperature ﬂuctuations, which is a function of the turbulence level and
the characteristic turbulence angular frequency

k
—
CS = 6,4

characteristic time of temperature ﬂuctuations
turbulent kinetic energy
dissipation rate of turbulent kinetic energy
see Sanders, J.P.H. and P.G.G. Lammers
(“Combustion and Flame”, 1994)
```

## #1518（p64）

裁圖：`crops/nflow-1518-p64-?-65.png`

### 裁圖上實際是什麼

**幾乎整塊都是散文**：`L_i` components of local force that acts on fluid、
`L_i = [p_ij n_j + ρv_i(v_n − u_n)]`、`L_r = L_i r_i`、`L_M = L_i M_i`、
`M_i` velocity of surface f = 0 normalised to ambient sound speed、`M_r`、`r`，
最後一句是完整的英文句子「The dot over a symbol implies source-time
differentiation of that symbol, e.g.」再接一條小式子 `L̇_r = (∂L_i/∂τ) r_i`。
真正是「式子」的部分只有三四條短式，其餘都是說明文字。

### equation 現值（退化 LaTeX，前 1600 字元）

```latex
$$
\begin{array} { r l } & { \mathrm { { L } _ { i } } } \\ & { \mathrm { { L } _ { i } } } \\ & { \mathrm { { { ( { \scriptsize ~ { [ \bar { \alpha } } ] ~ i s ~ i d e n t i c a l ~ o f ~ l o c e ~ t h a t ~ a t ~ i s ~ o f ~ u n ~ } ) ~ f i u i d } } } } \\ & { \mathrm { { L } _ { i } } = [ { \| { \bf { p } } _ { 1 } \mathrm { { i } } \mathrm { { i } } + \mathrm { { \scriptsize { [ \alpha } { \omega } _ { \mathrm { { \scriptsize { ' } } } } } } } \mathrm { { { L } _ \mathrm { i } } } \mathrm { { { \scriptsize { [ \alpha } } } } } \\ & { \mathrm { { { \scriptsize { \Sigma } } } } } \\ { \mathrm { { L } _ { i } } = \mathrm { { { L } _ \mathrm { { { f } } } } } } \\ & { \mathrm { { { L } _ \mathrm { \omega } } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { L } _ \omega } } } \\ & { \mathrm { { { M } _ { i } } } } \\ & { \mathrm { { { M _ { i } } } } } \\ & { \mathrm { { { M _ { i } } } } } \\ & { \mathrm { { { M _ { i } } } } } \\ & { \mathrm { { { \scriptsize } } } } \\ & { \mathrm { { { \scriptsize } } } } \\ & { \mathrm { { { \Sigma } } } } \\ &  \mathrm { { { ( { \scriptsize \bar { \alpha } } m p ~ a n ~ e ~ t h o ~ l i m p l i c s ~ s o n t r a t ~ a t ~ a t ~ a t ~ a t ~ a t ~ a ~ r i s ~ o f ~ t h a t ~ a ~ r i s ~ p o l y ~ i n ) } } } \\ & { \mathrm { { } } } \\ & { \mathrm { { \scriptsize { ( { \scriptsize { \bar { \alpha } } } \mathrm { { \scriptsize { ' } } } } } } } \\ & { \mathrm { { {
…（共 1,679 字元）
```

### 同 bbox 的 pdftotext 原文

```text
Li

components of local force that acts on ﬂuid
(Li is identical with Li used above)


Li = pij nj + vi (vn − un )
Lr = Li ri
Lr

component of local force that acts on ﬂuid (due to body) in
radiation direction

LM = Li Mi
Mi

velocity of surface f = 0 normalised to ambient sound speed

Mr

component of velocity in radiation direction normalised to c0

r

distance from source point on surface to observer

The dot
 over
 a symbol implies source-time differentiation of that symbol, e.g.
•
∂Li
ri .
Lr =
∂‘
```

## 為什麼這件事還沒有處置建議

coverage 那一半已經了結：偵測器 v2 之後 N Flow 從 8.7% 掉到 4.8%，
**這些字並沒有從 content_list 消失**，只是以逐字母 LaTeX 的形式待在 equation 裡。
所以它不再是「解析漏字」問題。

剩下的是**型別與結構**問題，而它落在現有規則的外面：

- 這個項目的 `type` 是 `equation`。LightRAG 的 `_coerce_text` 會照讀 `text`，
  所以進索引的是那串退化 LaTeX，不是可讀的說明文字。
- 現有的修補規則只有三條：消音（header/footer）、空表格轉錄、chart→image。
  **沒有一條在處理「型別判錯」**，而把 `equation` 改成 `text` 會同時改變
  下游的 IR 建法 —— 那是新規則，需要它自己的證據與閘門。
- 兩份文件的兩處（本檔）是目前僅有的樣本。依「只有 1 份文件的證據很可能是
  那份文件的巧合」，樣本數不足以長出耐久規則。

**建議：維持不動，留在體檢表當 `pp.equations` 的 note。** 若要處理，建議的
下一步不是改這兩處，而是先掃全庫「`equation` 項目裡英文詞佔比異常高」的分佈，
看這個型別判錯是不是一個有母體的現象（judgement-flow 第 2 節：分類需要母體，
不是樣本）。在那之前，動這兩處只是把兩個個案改好看。

