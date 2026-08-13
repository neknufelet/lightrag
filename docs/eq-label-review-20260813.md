---
title: 公式比對的標註集 — Tier A 對照 5 組、Tier B 分層 16 對
date_created: 2026-08-13
date_modified: 2026-08-13
status: living
kind: review
supersedes: ""
superseded_by: ""
summary: "eq-dup 的 --min-ratio 目前是 0.8，而那個數字沒有任何依據 —— 它是排序起點不是判準。這份是給人標註的樣本：Tier A 五組當對照（骨架逐字相同，應該一定是同一條），Tier B 按相似度分四段各抽四對。標完才有資格談門檻，也才有回歸基準。"
---

# 公式比對的標註集（2026-08-13）

**每一項底下的「標註：」那一行是給你改的**，把不對的選項刪掉就好，
看不出來就留「看不出來」——那是有效答案，不是逃避。

**為什麼要標**：`eq-dup` 的 `--min-ratio` 現在是 `0.8`，而**那個數字沒有任何依據**。
它是我隨手挑的排序起點。要讓它變成「0.8 以上就算同一條」這種判準，
必須先有一批人看過的答案，否則就是拿一個猜的數字去裁決別人的公式。

**標完之後我會做的**：凍結成 `verdicts/eq-labels.json`，然後
(1) 看門檻該落在哪、或者結論是「不該有門檻」；
(2) 拿它當回歸基準——以後改 `pp/eqkey.py` 的骨架規則，這些標註必須還對得上，
否則就是把某一族公式改到認不出來了。

**判準（給標註用的一句話）**：
「這兩條**是不是同一個物理關係**」，不是「長得像不像」。
變數名不同、寫法不同都不影響；**如果一條是另一條的特例或推導的下一步，算不是同一條。**

樣本是確定性抽樣（等距取樣，不用亂數），重跑會拿到同一批。

---

## 第一部分：Tier A 是不是真的可信（對照組，5 組）

骨架**逐字相同**才會進 Tier A，所以它應該是「一定同一條」。**如果這裡就錯了，底下整套都不用談。**

### A1　9 處、8 個來源　係數一致

- `2019 - Broadband Time-domain Impedance Boundary Mode` #21　常數 ['0']
  ```latex
  \frac { \partial \boldsymbol { q } } { \partial t } + \nabla \cdot \boldsymbol { F } ( \boldsymbol { q } ) = \frac { \partial \boldsymbol { q } } { \partial t } + A _ { j } \frac { \partial \boldsymbol { q } } { \partial x _ { j } } = 0 ,
  ```
- `2019 - Room acoustics modelling in the time-domain w` #27　常數 ['0']
  ```latex
  \frac { \partial \pmb q } { \partial t } + \nabla \cdot \pmb F ( \pmb q ) = \frac { \partial \pmb q } { \partial t } + A _ { j } \frac { \partial \pmb q } { \partial x _ { j } } = 0 ,
  ```
- `2020 - Frequency-dependent transmission boundary con` #31　常數 ['0']
  ```latex
  \frac { \partial \pmb q } { \partial t } + \nabla \cdot \pmb F ( \pmb q ) = \frac { \partial \pmb q } { \partial t } + \pmb { A } _ { j } \frac { \partial \pmb q } { \partial x _ { j } } = 0 ,
  ```
- …其餘 6 處省略

**標註：同一條 / 不是同一條**

### A2　3 處、3 個來源　係數一致

- `2019 - Broadband Time-domain Impedance Boundary Mode` #38　常數 ['1', '1']
  ```latex
  R ( \omega ) = \frac { Z _ { s } ( \omega ) - 1 } { Z _ { s } ( \omega ) + 1 } .
  ```
- `2020 - Time-domain impedance boundary condition mode` #53　常數 ['1', '1']
  ```latex
  R ( \omega ) = \frac { Z _ { s } ( \omega ) - 1 } { Z _ { s } ( \omega ) + 1 } .
  ```
- `2024 - An Open-Source Time-Domain Wave-Based Room Ac` #34　常數 ['1', '1']
  ```latex
  R ( \omega ) = \frac { Z _ { s } ( \omega ) - 1 } { Z _ { s } ( \omega ) + 1 } .
  ```

**標註：同一條 / 不是同一條**

### A3　2 處、2 個來源　係數一致

- `2004 - Room Sizing and Optimization at Low Frequenci` #51　常數 []
  ```latex
  \widehat { \bf { \delta } } _ { n } = \frac { c } { \displaystyle \omega _ { n } } \left( \frac { \varepsilon _ { n _ { x } } \overline { { \sf { \beta } } } _ { x } } { L _ { x } } + \frac { \varepsilon _ { n _ { y } } \overline { { \sf { \beta } } } _ { y } } { L _ { y } } + \frac { \varepsilon _ 
  ```
- `2015 - Determining Optimum Room Dimensions for Criti` #44　常數 []
  ```latex
  \delta _ { n } = \frac { c } { \omega _ { n } } \left( \frac { \mathcal { E } _ { n _ { x } } \overline { { \beta } } _ { x } } { L _ { x } } + \frac { \mathcal { E } _ { n _ { y } } \overline { { \beta } } _ { y } } { L _ { y } } + \frac { \mathcal { E } _ { n _ { y } } \overline { { \beta } } _ { 
  ```

**標註：同一條 / 不是同一條**

### A4　2 處、2 個來源　係數一致

- `2019 - Room acoustics modelling in the time-domain w` #60　常數 []
  ```latex
  \left( \boldsymbol { S } _ { j } ^ { k } \right) _ { m n } = \int _ { D ^ { k } } l _ { m } ^ { k } ( \boldsymbol { x } ) \frac { \partial l _ { n } ^ { k } ( \boldsymbol { x } ) } { \partial x _ { j } } \mathrm { d } \boldsymbol { x } \quad \in \mathbb { R } ^ { N _ { p } \times N _ { p } } ,
  ```
- `2023 - Extended reacting boundary modeling of porous` #150　常數 []
  ```latex
  ( \mathbf { S } _ { j } ^ { e } ) _ { m n } = \int _ { \varOmega ^ { e } } l _ { m } ^ { e } ( \mathbf { x } ) \frac { \partial l _ { n } ^ { e } ( \mathbf { x } ) } { \partial x _ { j } } \mathrm { d } \mathbf { x } \quad \in \mathbb { R } ^ { N _ { p } \times N _ { p } } ,
  ```

**標註：同一條 / 不是同一條**

### A5　2 處、2 個來源　係數一致

- `2022 - Broadband impedance modulation via non-local ` #131　常數 []
  ```latex
  F _ { \mathrm { no } } = \sum _ { i = 1 } ^ { N } F _ { \mathrm { ni } i } ,
  ```
- `2023 - An Iterative Ray Tracing Algorithm to Increas` #60　常數 []
  ```latex
  E _ { k } = \sum _ { j = 1 } ^ { N } i _ { j , k } e _ { j , k } ,
  ```

**標註：同一條 / 不是同一條**


## 第二部分：Tier B 按相似度分層（16 對）

這是**要決定門檻的那批**。現在 `--min-ratio 0.8` 只是排序起點，沒有任何依據說 0.8 以上就算同一條。


### 相似度 0.95–1.00（這一段共 196 對，抽 4 對）

#### B1　相似度 0.9922　可比常數 1 個　係數一致
- `2021 - Estimation of locally reacting surface impeda` #51　常數 ['1']
  《doc:2021 - Estimation of locally reacting su》
  ```latex
  \frac { \partial p } { \partial n } = \frac { 1 } { c \xi } \frac { \partial p } { \partial t }
  ```
- `2023 - A Review of Finite Element Methods for Room A` #36　常數 ['1']
  《doc:2023 - A Review of Finite Element Method》
  ```latex
  \frac { \partial p } { \partial n } = - \frac { 1 } { c \zeta } \frac { \partial p } { \partial t }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B2　相似度 0.9744　可比常數 3 個　係數一致
- `2019 - Broadband Time-domain Impedance Boundary Mode` #19　常數 ['1', '0', '0']
  《doc:2019 - Broadband Time-domain Impedance B》
  ```latex
  \begin{array} { r } { \displaystyle \frac { \partial \boldsymbol { \nu } } { \partial t } + \frac { 1 } { \rho } \nabla p = 0 , } \\ { \displaystyle \frac { \partial p } { \partial t } + \rho c ^ { 2 } \nabla \cdot \boldsymbol { \nu } = 0 , } \end{array}
  ```
- `2019 - Room acoustics modelling in the time-domain w` #23　常數 ['1', '0', '0']
  《doc:2019 - Room acoustics modelling in the t》
  ```latex
  \begin{array} { r l } & { \displaystyle \frac { \partial \pmb { v } } { \partial t } + \frac { 1 } { \rho _ { 0 } } \nabla p = \pmb { 0 } , } \\ & { \displaystyle \frac { \partial p } { \partial t } + \rho _ { 0 } c _ { 0 } ^ { 2 } \nabla \cdot \pmb { v } = 0 , } \end{array}
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B3　相似度 0.9655　可比常數 0 個　係數一致
- `2019 - Acoustic perfect absorbers via Helmholtz reso` #62　常數 []
  《doc:2019 - Acoustic perfect absorbers via He》
  ```latex
  Z _ { a 0 } = - \frac { j \rho _ { 0 } \omega l _ { a } } { \Psi _ { \nu } } .
  ```
- `2026 - hybrid computational framework for room-acous` #259　常數 []
  《學位論文：Hybrid computational framework for room》
  ```latex
  D _ { 5 0 } = \frac { E _ { 5 0 } } { E _ { \infty } } .
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B4　相似度 0.963　可比常數 0 個　係數一致
- `2024 - A Compact Low-Frequency Acoustic Perfect Abso` #53　常數 []
  《doc:2024 - A Compact Low-Frequency Acoustic 》
  ```latex
  H _ { 1 2 } = \frac { p _ { 2 } } { p _ { 1 } }
  ```
- `2024 - A hybrid room acoustic modeling approach comb` #127　常數 []
  《doc:2024 - A hybrid room acoustic modeling a》
  ```latex
  K _ { i } = \frac { B _ { i } } { B _ { t o t } } .
  ```

**標註：同一條 / 不是同一條 / 看不出來**


### 相似度 0.90–0.95（這一段共 345 對，抽 4 對）

#### B5　相似度 0.9492　可比常數 0 個　係數一致
- `2023 - A Review of Finite Element Methods for Room A` #34　常數 []
  《doc:2023 - A Review of Finite Element Method》
  ```latex
  \frac { \partial p } { \partial n } = - \rho \frac { \partial v _ { n } } { \partial t } ,
  ```
- `N Flow Acoustics` #775　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  { \bf v } _ { \mathrm { x } } = \frac { \partial \Psi } { \partial \bf \Psi } ; \qquad { \bf v } _ { \mathrm { y } } = - \frac { \partial \Psi } { \partial \bf x }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B6　相似度 0.9286　可比常數 0 個　係數一致
- `01504_6.4 Helmholtz resonators` #5　常數 []
  《Kuttruff, Room Acoustics》
  ```latex
  A _ { \mathrm { a } } = { \frac { P _ { \mathrm { abs } } } { I _ { \mathrm { 0 } } } }
  ```
- `2024 - A Compact Low-Frequency Acoustic Perfect Abso` #52　常數 []
  《doc:2024 - A Compact Low-Frequency Acoustic 》
  ```latex
  H _ { R } = \frac { A _ { 2 R } } { A _ { 1 R } }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B7　相似度 0.9231　可比常數 0 個　係數一致
- `2020 - Time-domain impedance boundary condition mode` #174　常數 []
  《doc:2020 - Time-domain impedance boundary co》
  ```latex
  W _ { c } ( N ) = N _ { t i m e s t e p s } \cdot N _ { D O F } ,
  ```
- `2026 - hybrid computational framework for room-acous` #47　常數 []
  《學位論文：Hybrid computational framework for room》
  ```latex
  \phi _ { k } ( \omega ) = \omega \cdot t _ { 0 _ { k } } .
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B8　相似度 0.9091　可比常數 0 個　係數一致
- `01703_8.3 Examination of the impulse response` #2　常數 []
  《Kuttruff, Room Acoustics》
  ```latex
  b = \pi \frac { f _ { _ { 2 } } - f _ { _ { 1 } } } { t _ { _ { s } } }
  ```
- `2025 - Omnidirectional sound wave absorption based o` #121　常數 []
  《doc:2025 - Omnidirectional sound wave absorp》
  ```latex
  \alpha _ { 0 } = \frac { \alpha _ { \mathrm { max } } - \alpha _ { \mathrm { min } } } { \alpha _ { \mathrm { ave } } }
  ```

**標註：同一條 / 不是同一條 / 看不出來**


### 相似度 0.85–0.90（這一段共 675 對，抽 4 對）

#### B9　相似度 0.8989　可比常數 0 個　係數一致
- `2022 - Broadband impedance modulation via non-local ` #43　常數 []
  《doc:2022 - Broadband impedance modulation vi》
  ```latex
  \begin{array} { r } { \mathrm { M } _ { \mathrm { E N _ { 1 } } } = \left( \begin{array} { c c c } { \cos ( k _ { \mathrm { E N _ { 1 } } } t _ { 1 } ) } & { \mathrm { j } \sin ( k _ { \mathrm { E N _ { 1 } } } t _ { 1 } ) Z _ { \mathrm { E N _ { 1 } } } / S _ { \mathrm { E N _ { 1 } } } } \\ { \mat
  ```
- `K Muffler Acoustics` #99　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \begin{array} { r } { \left[ \begin{array} { c c } { \cos ( \mathbf { k } _ { 0 } \ell ) } & { \mathrm { j } \underline { { Z } } _ { 0 } \sin ( \mathbf { k } _ { 0 } \ell ) } \\ { ( \mathrm { j } / \underline { { Z } } _ { 0 } ) \sin ( \mathbf { k } _ { 0 } \ell ) } & { \cos ( \mathbf { k } _ { 0 }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B10　相似度 0.8906　可比常數 1 個　係數**不一致**
- `01701_11.1 Nonlinear Steepening` #18　常數 ['0']
  《Pierce, Acoustics: An Introduction to Its Ph》
  ```latex
  \frac { \partial p } { \partial t } + ( v + c ) \frac { \partial p } { \partial x } = 0 .
  ```
- `O Analytical and Numerical Methods in Acoustics` #294　常數 ['2']
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \varepsilon _ { \mathrm { kh } } \left( \mathrm { u } \right) = \left( \frac { \partial \mathrm { u } _ { \mathrm { k } } } { \partial { \bf x } _ { \mathrm { h } } } + \frac { \partial { \bf u } _ { \mathrm { h } } } { \partial { \bf x } _ { \mathrm { k } } } \right) / 2 .
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B11　相似度 0.871　可比常數 0 個　係數一致
- `2025 - Study on the multi-low-frequency band gaps an` #148　常數 []
  《doc:2025 - Study on the multi-low-frequency 》
  ```latex
  C _ { g } = C _ { g x } + C _ { g y } = a _ { x } { \frac { \partial \omega } { \partial x } } i + a _ { y } { \frac { \partial \omega } { \partial y } } j
  ```
- `N Flow Acoustics` #1318　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \frac { \partial \Phi } { \partial \boldsymbol { \tau } } , \frac { \partial \Phi } { \partial \mathbf { n } }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B12　相似度 0.864　可比常數 0 個　係數一致
- `2023 - A Review of Finite Element Methods for Room A` #34　常數 []
  《doc:2023 - A Review of Finite Element Method》
  ```latex
  \frac { \partial p } { \partial n } = - \rho \frac { \partial v _ { n } } { \partial t } ,
  ```
- `O Analytical and Numerical Methods in Acoustics` #434　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  { \bf a } _ { \mathrm { m } \ell } \colon = \frac { \partial \Psi _ { \mathrm { m } } } { \partial \bf n } \frac { \partial \Psi _ { \ell } ^ { * } } { \partial \bf n } = { \bf a } _ { \ell \mathrm { m } } ^ { * } \mathrm { ~ . ~ }
  ```

**標註：同一條 / 不是同一條 / 看不出來**


### 相似度 0.80–0.85（這一段共 1212 對，抽 4 對）

#### B13　相似度 0.8493　可比常數 0 個　係數一致
- `01503_9.3 The Doppler Effect` #41　常數 []
  《Pierce, Acoustics: An Introduction to Its Ph》
  ```latex
  \begin{array} { r } { \pmb { x } _ { 2 } ( \pmb { x } _ { 1 } , t ) = \pmb { x } _ { 1 } - ( t - t _ { o } ) \pmb { v } _ { 2 ; 1 } , } \end{array}
  ```
- `B General Linear Fluid Acoustics` #235　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \begin{array} { r } { \mathbb G ( \mathbf { r } | \mathbf { r } _ { \mathrm { q } } ) = \mathbf { g } ( \mathbf { r } | \mathbf { r } _ { \mathrm { q } } ) + \mathtt { h } ( \mathbf { r } ) . } \end{array}
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B14　相似度 0.8387　可比常數 0 個　係數一致
- `2023 - Perception-of-room-modes_CH3` #59　常數 []
  《學位論文：Perception of room modes》
  ```latex
  k _ { y } = \frac { n _ { y } \pi } { L _ { y } }
  ```
- `B General Linear Fluid Acoustics` #754　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \kappa = { \frac { \mathrm { C } _ { \mathrm { p } } } { \mathrm { C } _ { \mathrm { v } } } }
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B15　相似度 0.8214　可比常數 0 個　係數一致
- `2026 - hybrid computational framework for room-acous` #61　常數 []
  《學位論文：Hybrid computational framework for room》
  ```latex
  \begin{array} { r } { W _ { \mathrm { tot } } = W _ { \mathrm { s } } + W _ { \mathrm { ns } } , } \end{array}
  ```
- `O Analytical and Numerical Methods in Acoustics` #667　常數 []
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \begin{array} { r } { { \mathbb { A } } ^ { * } { \mathbb { A } } { \mathbb { P } } = { \mathbb { A } } ^ { * } { \mathbb { F } } \ . } \end{array}
  ```

**標註：同一條 / 不是同一條 / 看不出來**

#### B16　相似度 0.8125　可比常數 1 個　係數**不一致**
- `2024 - Additively manufactured acoustic-mechanical m` #152　常數 ['2']
  《doc:2024 - Additively manufactured acoustic-》
  ```latex
  A = \frac { 2 C _ { 1 2 1 2 } } { C _ { 1 1 1 1 } - C _ { 1 1 2 2 } }
  ```
- `M Room Acoustics` #883　常數 ['1']
  《聲學公式手冊（A–R 共 18 章）》
  ```latex
  \delta = 1 - \frac { \mathrm { E } _ { \mathrm { spec } } } { \mathrm { E } _ { \mathrm { total } } } .
  ```

**標註：同一條 / 不是同一條 / 看不出來**
