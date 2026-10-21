# chemfacts 使用手册

> 面向使用者的功能说明、操作指引与可复核证据。
> 英文版本见 [USAGE.md](USAGE.md) · 项目主页见 [README](../README.md) / [README_zh](../README_zh.md)。

本手册与 chemfacts 的设计目标一致：**不编造，每个数值都可溯源**。因此下面出现的每一段
命令输出都不是示意文字，而是**在固定数据快照上真实跑出来的结果**，你应当能够独立
重放并核对到原始来源。

---

## 0. 阅读约定：本手册的证据快照

为了让"可复核"落到实处，本手册所有示例输出都来自同一次运行环境。重放时先确认你的
环境与下表一致，或按 §5 的方法自行溯源。

| 项目 | 值 |
|---|---|
| 版本 | `0.3.0` |
| 数据源 | PubChem（PUG REST 身份 + PUG View 数值），本地缓存 `~/.cache/chemfacts/facts.db` |
| 缩写注册表 | `~/.cache/chemfacts/aliases.json`（13 条钉位） |
| 缓存规模（本手册快照） | `identity 14 · value 224 · ref 1227` |
| 快照日期 | 2026-10-21（缓存 `accessed` 字段为 2026-10-20 至 2026-10-21） |
| 运行方式 | `uv run chemfacts …`（或安装后 `chemfacts …`） |

> 缓存带 30 天 TTL。数值本身在 TTL 内不会变；若你 `cache clear` 后重查，输出会重新拉取
> PubChem，`accessed` 日期更新，但"来源 + 参考编号 + 数值"这三要素应当保持一致。

---

## 1. 这是什么，解决什么问题

`chemfacts` 是一个**溯源优先（provenance-first）的化学事实核验工具**。你给它一个标识符
（名称 / CAS / CID / SMILES / 已钉位缩写）和一个物性（如闪点），它返回**每一条带来源、
参考编号、查证日期、实测/计算属性的数值**，而不是一个"模型记起来的数"。

三条铁律（贯穿所有命令）：

1. **不编造。** 查不到就是查不到，输出里明写 `no sourced value found for: …`，绝不填补。
2. **每个数值都带溯源。** 来源名（OSHA / HSDB / CAMEO / ILO ICSC / NIOSH / EPA …）+
   PubChem 参考编号 + 查证日期 + `experimental`（实测）/ `computed`（计算）属性。
3. **含糊缩写先钉位。** 一个缩写可能指好几种物质（DMPA、H12MDI、BA…），注册表把它
   一次性钉到唯一 CAS，之后所有查询走同一答案；钉子是 JSON 条目，不是"记得住"。

数据流：

```
标识符 → [alias registry 钉位] → PubChem（身份 + 数值）→ 本地缓存（TTL+溯源）
        → 交叉核对（单位归一/剔除不可比值/属性阈值）→ 状态 → 可审计卡片
```

---

## 2. 安装

**CLI / 库（三选一）**

```bash
pip install chemfacts
# 或
uv tool install chemfacts
# 或（本仓库开发态）
uv run chemfacts --help
```

**MCP 服务（给任意支持 MCP 的 agent 用，见 §4.8）**

```bash
# stdio：agent 本地拉起，无需起服务
# Docker：共享一份检索库，多客户端指向同一 URL
docker build -t chemfacts-mcp .
docker run -d -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
```

要求 Python ≥ 3.11。

---

## 3. 核心概念（先看懂，命令才不迷路）

### 3.1 状态三态

一个物性的多个来源数值交叉核对后，落到三种状态之一：

| 状态 | 含义 | 触发条件 |
|---|---|---|
| `verified` | 已核验 | 单一来源 / 多来源极差在阈值内 / 差异可归因于闭杯 vs 开杯 |
| `conflict` | 冲突 | 极差超阈值且**不是**杯型差异——必须人工复核，工具如实列出每个值 |
| `unverified` | 未查证 | 没有带来源的数值可查——**报缺失，不编** |

各属性冲突阈值（floor）避免把正常来源波动误报成冲突：熔点 ±3 °C、沸点 ±2 °C、
闪点 ±1.5 °C、自燃 ±20 °C、密度 ±0.01 g/cm³；其余属性用 10% 相对阈值。
闭杯（c.c.）与开杯（o.c.）天然不同，工具识别后不算冲突。

### 3.2 物性 slug（CLI 用，映射到 PubChem PUG View 标题）

| slug | PUG View 标题 |
|---|---|
| `flash-point` / `flash` | Flash Point |
| `boiling-point` / `boiling` / `bp` | Boiling Point |
| `melting-point` / `melting` / `mp` | Melting Point |
| `density` | Density |
| `solubility` | Solubility |
| `vapor-pressure` | Vapor Pressure |
| `autoignition-point` | Autoignition Point |
| `explosive-limits` | Explosive Limits |
| `surface-tension` | Surface Tension |
| `viscosity` | Viscosity |
| `molecular-weight` / `mw` | MolecularWeight（走 PUG REST 身份） |
| `formula` | MolecularFormula（走 PUG REST 身份） |

### 3.3 退出码（脚本里判断用）

| 命令 | 退出码 |
|---|---|
| `resolve` | 0=成功 |
| `verify` | 0=CONFIRMED，1=MISMATCH / NOT_FOUND |
| `crosscheck` | 0=VERIFIED / UNVERIFIED，2=CONFLICT |
| `lookup` / `card` / `alias` / `cache` / `export` | 0=成功 |
| `zhname` | 0=成功（条目命中/变更），1=未录入 |

---

## 4. 命令逐个讲（功能 + 操作 + 真实输出）

> 以下输出均为 §0 快照上的真实结果。每条后附**如何复核**。

### 4.1 `resolve` — 把标识符解析成身份

作用：名称 / CAS / SMILES / InChI / CID / 已钉位缩写 → 唯一化合物身份，带溯源。

```
$ chemfacts resolve NMP
pinned via alias: NMP -> 872-50-4  # N-methyl-2-pyrrolidone (solvent)
identity        : N-methyl-2-pyrrolidone
CID             : 13387
CAS             : 872-50-4
IUPAC           : 1-methylpyrrolidin-2-one
Formula         : C5H9NO
MW              : 99.13 g/mol
SMILES          : CN1CCCC1=O
InChIKey        : SECXISVLQFMRJM-UHFFFAOYSA-N
Accessed        : 2026-10-20 13:30:02Z  source: pubchem
```

**怎么复核：** `CID 13387` 直接开
<https://pubchem.ncbi.nlm.nih.gov/compound/13387>，分子式 C5H9NO、MW 99.13、
InChIKey 应当逐字一致。`pinned via alias` 一行说明 NMP 走了注册表钉位（见 §4.7）。

### 4.2 `lookup` — 列出某物性的全部带来源数值

作用：把某物性的**每一条**来源值都列出来，逐条带来源/参考编号/日期/属性。这是"可复核"
的底层。

```
$ chemfacts lookup NMP flash-point
204 °F                                                       | OSHA (ref #84, experimental) | 2026-10-20
204 °F (96 °C) (OPEN CUP)                                    | HSDB (ref #46, experimental) | 2026-10-20
204 °F (NTP, 1992)                                           | CAMEO (ref #9, experimental) | 2026-10-20
86 °C c.c.                                                   | ILO ICSC (ref #47, experimental) | 2026-10-20
96 °C                                                        | N-Methyl-2-pyrrolidone (ref #44, experimental) | 2026-10-20
```

**怎么复核：** `ref #47` = ILO ICSC 卡片。ICSC 对 NMP（N-Methylpyrrolidone）的闪点
闭杯值 86 °C 可查 ILO ICSC 数据库；`ref #46` = HSDB（Hazardous Substances Data Bank），
`204 °F (96 °C) (OPEN CUP)` 即开杯值。同一物性闭杯 86 °C、开杯 96 °C 并存——这正是
§3.1 里"杯型差异不算冲突"的活例子。

### 4.3 `verify` — 把"声称值"压到所有来源值上（本工具的核心）

作用：你（或某个模型）报了一个数，工具拿它去对每一条来源值，给 `confirmed / mismatch /
not_found` 三种判定，并指出最接近的来源值。

三个真实判定，覆盖三种结果：

```
$ chemfacts verify NMP mw --claim 99.13      # CONFIRMED
verdict: CONFIRMED
detail : 1 sourced value(s) agree within 2%
closest: 99.13 g/mol (PubChem PUG REST (computed from formula))
match  : 99.13 g/mol (PubChem PUG REST (computed from formula))
(退出码 0)

$ chemfacts verify NMP mw --claim 80         # MISMATCH
verdict: MISMATCH
detail : claim 80 not confirmed; closest sourced value: 99.13 g/mol (PubChem PUG REST (computed from formula))
closest: 99.13 g/mol (PubChem PUG REST (computed from formula))
(退出码 1)

$ chemfacts verify NMP explosive-limits --claim "0.6-9.0"   # NOT_FOUND
verdict: NOT_FOUND
detail : no sourced value found for this property - claim stays unverified
(退出码 1)
```

**怎么复核：** CONFIRMED 的那条——MW 99.13 由 PubChem PUG REST 从分子式 C5H9NO 计算
（C 5×12.011 + H 9×1.008 + N 14.007 + O 15.999 ≈ 99.13），来源标注为
`computed from formula`，不是实测值。想质疑就自己按分子式算一遍。
NOT_FOUND 那条是**故意**的：NMP 没有带来源的爆炸极限数值，工具不编，直接报缺失。

### 4.4 `crosscheck` — 交叉核对一个物性，判状态

作用：把某物性所有来源值放在一起，按 §3.1 规则给出 `verified / conflict / unverified`。

三种状态各抓一个真实例子：

```
$ chemfacts crosscheck NMP        # VERIFIED（杯型差异被识别，不算冲突）
status: VERIFIED
204 °F               | OSHA (ref #84)
204 °F (96 °C) (OPEN CUP) | HSDB (ref #46)
204 °F (NTP, 1992)   | CAMEO (ref #9)
86 °C c.c.           | ILO ICSC (ref #47)
96 °C                | N-Methyl-2-pyrrolidone (ref #44)
(退出码 0)

$ chemfacts crosscheck TDI_24     # CONFLICT（数值打架，工具如实列出每个值）
status: CONFLICT
127 °C               | Toluene-2,4-diisocyanate (ref #36)
127 °C c.c.          | ILO ICSC (ref #43)
260 °F               | NIOSH (ref #73)
260 °F (127 °C)      | HSDB (ref #39)
270 °F (EPA, 1998)   | CAMEO (ref #6)
270 °F for an 80/20% 2,4/ 2,6 TDI mixture | OSHA (ref #59)
(退出码 2)

$ chemfacts crosscheck IBOA       # UNVERIFIED（查无来源值，报缺失不编）
status: UNVERIFIED
(退出码 0)
```

**怎么复核 TDI_24 的 CONFLICT：** 末两条把 270 °F（≈132 °C）和 127 °C（≈260 °F）并列，
且 OSHA 那条明确写是"80/20% 2,4/2,6 TDI 混合物"——来源本身口径不同（纯 2,4-TDI vs
工业混合品），工具识别为**真实冲突**而不是杯型差异，于是给 CONFLICT 并原样列出每个值
让你判断。这正是"不替你下结论、但把证据摊开"的设计。

### 4.5 `card` — 生成可审计事实卡片

作用：把某化合物的身份 + 关键物性 + 状态打包成一张可归档卡片，三种格式：
`md`（默认）/ `obsidian`（带 frontmatter）/ `json`。可用 `--out` 写文件、`--properties`
指定物性列表。

`md` 完整输出（NMP）：

```
# N-methyl-2-pyrrolidone (C5H9NO)

- Aliases (registry-pinned): NMP

- IUPAC: 1-methylpyrrolidin-2-one
- Formula: `C5H9NO` | MW: 99.13 g/mol
- SMILES: `CN1CCCC1=O`
- CAS: 872-50-4 | CID: 13387

## Properties (status: verified)

### Flash Point
- 204 °F — OSHA (ref #84, accessed 2026-10-20)
- 204 °F (96 °C) (OPEN CUP) — HSDB (ref #46, accessed 2026-10-20)
- 86 °C c.c. — ILO ICSC (ref #47, accessed 2026-10-20)
...

## Notes
- abbreviation pinned via registry: NMP -> 872-50-4 (N-methyl-2-pyrrolidone (solvent))
```

`obsidian` 格式（带 frontmatter，可直接进 Obsidian 库）：

```
---
name: "N-methyl-2-pyrrolidone"
cas: 872-50-4
cid: 13387
status: verified
accessed: 2026-10-20
aliases: ["NMP"]
---

# N-methyl-2-pyrrolidone

- CAS: `872-50-4` | PubChem CID: 13387
- 查证日期: 2026-10-20
...
```

`json` 格式（DMPA，注意 `status: unverified` 与缺失说明，是"报缺失不编"的样本）：

```
{
  "identity": { "cid": 78501, "name": "Dimethylolpropionic acid",
    "cas": "4767-03-7", "formula": "C5H10O4", "molecular_weight": 134.13,
    "accessed_at": "2026-10-20 16:36:36Z", "source": "pubchem" },
  "status": "unverified",
  "aliases": ["DMPA"],
  "notes": [ "no sourced value found for: Flash Point, Boiling Point, Melting Point, Density" ],
  "properties": { "Flash Point": [], "Boiling Point": [], ... }
}
```

**怎么复核：** 卡片上每个 `ref #` 都能回到 §4.2 的溯源；`status` 由 §4.4 的规则决定。
`--out` 可把卡片直接落到你的 Obsidian 库（本用户库在 `F:\Hermes\Obsidian lib\chemical-facts\`）。

### 4.6 `cache` — 管理本地检索库

```
$ chemfacts cache show
identity   14
value      224
ref        1227
```

`cache clear` 清空整个缓存（下次查询重新拉 PubChem，`accessed` 日期刷新）。
**复核手段：** 想看"数值会不会变"，就 `cache clear` 后重跑 §4.2/4.4，数值与来源应不变，
只有 `accessed` 日期更新。

### 4.7 `alias` — 管理"缩写 → 化合物"钉位注册表

作用：把一个含糊缩写钉到**唯一** CAS，并记录"为什么选它、排除了哪些"。钉子是纯 JSON
（默认 `~/.cache/chemfacts/aliases.json`，可用 `CHEMFACTS_ALIASES` 覆盖），可提交版本控制。

真实操作（临时条目，用完即删）：

```
$ chemfacts alias add XYZ123 100-00-0 --note "manual-doc test pin (temporary)"
pinned XYZ123 -> 100-00-0 (2026-10-21)

$ chemfacts alias show XYZ123
alias     : XYZ123
pinned to : 100-00-0
note      : manual-doc test pin (temporary)
added     : 2026-10-21

$ chemfacts alias remove XYZ123
removed XYZ123
```

现有 13 条钉位（`alias list` 真实输出，节选）：

```
DMPA       -> 4767-03-7  # dimethylolpropionic acid, ... (NOT 1,4-dimethylpiperazine / TMEDA)
H12MDI     -> 5124-30-1  # hydrogenated MDI / 4,4'-dicyclohexylmethane diisocyanate
                        #  (NOT 1,12-diisocyanatododecane 13879-35-1)
IBOA       -> 5888-33-5  # isobornyl acrylate C13H20O2, MW 208.30
                        #  (NOT the C13H22O2 / 210.32 mis-memory)
NMP        -> 872-50-4   # N-methyl-2-pyrrolidone (solvent)
```

**怎么复核：** 每条的 `NOT …` 注释就是"排除项"证据——比如 H12MDI 钉到氢化 MDI
（5124-30-1），明确排除了同名的 1,12-二异氰酸酯十二烷（13879-35-1）。把 CAS 丢进
PubChem 搜，两个物质的分子式/MW 不同，你就看到钉位为什么必要。

### 4.8 `export` — 总对应表（缩写 | 中文名 | 英文名 | 物性）

一条命令生成"化学物质-中文名-英文名-缩写-分子量-熔沸点"总表：对给定的物质清单，
输出 缩写 → 中文名 → 英文名 → IUPAC → CAS → CID → 分子式 → 分子量 → 熔点/沸点/闪点/密度，
每个物性值都带来源清单。

- **联网优先**：本地检索库空了、过期了都不影响出表——缺什么就地拉 PubChem（本地库只是
  TTL 加速器，不是事实来源）。`--fresh` 强制本次全部现拉。
- **人工列只认注册表**：缩写列、中文名列只来自 `aliases.json` + `zhnames.json`，
  没录入就是空格，绝不猜。
- 解析不出的物质以 `(unresolved: …)` 行明示，不悄悄丢掉。

真实输出（THF 行）：

```
$ chemfacts export tetrahydrofuran --format md
| 缩写 | 中文名 | 英文名 | IUPAC | CAS | CID | 分子式 | 分子量 | … | 熔点 | … |
|  | 四氢呋喃 | Tetrahydrofuran | oxolane | 109-99-9 | 8028 | C4H8O | 72.11 g/mol | … | -108.3 °C ; … | … |
```

```
# 全注册表 + 指定物质，CSV 落盘，联网现拉：
chemfacts export --all-aliases tetrahydrofuran "4,4'-diphenylmethanediisocyanate" \
    --format csv --out map.csv --fresh
```

### 4.9 `zhname` — 维护中文名（PubChem 不提供中文名，本工具也绝不编造）

`zhnames.json`（默认 `~/.cache/chemfacts/zhnames.json`，`CHEMFACTS_ZHNAMES` 可覆盖）存
**用户核实过的**中文名，以 CAS（优先）或 CID 为键——与 `aliases.json` 同一标识空间，
两个文件对"哪个物质"的说法永远一致。`add` 时若给的是名称/缩写，会先走 PubChem 解析，
按解析出的 CAS 落库，并记录你核实该名的出处（`--source`）。

```
$ chemfacts zhname add THF 四氢呋喃 --source "通用名 (common name)"
curated 109-99-9 -> 四氢呋喃 (2026-10-21) [resolved to Tetrahydrofuran (109-99-9)]

$ chemfacts zhname show THF
identifier : 109-99-9
name_zh    : 四氢呋喃
source     : 通用名 (common name)

$ chemfacts zhname list
109-99-9           四氢呋喃  # 来源: 通用名 (common name)
```

录入后，中文名会出现在 `resolve` 输出、事实卡片（Obsidian/MD/JSON）、MCP 工具返回
（`name_zh`、`name_zh_source`、`registered_abbrevs`）以及 `export` 总表的中文名列。
没录入的物质就是空格——缺就是缺，不猜。

### 4.10 `mcp` — 让任意支持 MCP 的 agent 用它

作用：把上面 6 个能力（resolve/lookup/crosscheck/verify/card/alias）以 MCP 工具形式暴露，
Claude Code、Codex、ZCode、Hermes 等任一 MCP 客户端都能按溯源方式查化学事实，而不是靠
模型记忆。两种传输：`stdio`（agent 本地拉起）与 `streamable-http`（Docker/多客户端共享一份
检索库）。

真实工具清单（MCP 客户端 `list_tools` 拉回）：

```
chemfacts_resolve, chemfacts_lookup, chemfacts_crosscheck,
chemfacts_verify, chemfacts_card, chemfacts_alias
```

一个工具调用的真实返回（结构化 JSON，带溯源）：

```
$ chemfacts_verify('NMP', 'flash-point', '96 C')
{
  "ok": true, "property": "Flash Point", "claim": "96 C", "verdict": "confirmed",
  "detail": "1 sourced value(s) agree within 2%",
  "closest": { "value": "96 °C", "source": "N-Methyl-2-pyrrolidone",
               "reference_number": 44, "kind": "experimental",
               "accessed_at": "2026-10-20 13:30:03Z" }
}
```

注册方式（各 agent 语法略有差异，命令恒为 `chemfacts-mcp`，默认 stdio）：

```bash
# Claude Code
claude mcp add chemfacts -- chemfacts-mcp
# 共享服务（Docker + streamable-HTTP，一个部署给所有 agent）
docker build -t chemfacts-mcp .
docker run -d -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
# 各 agent 指向 http://<host>:8000/mcp ；/data 卷就是共享检索库（facts.db + aliases.json）
```

**注意（本机代理坑）：** 若宿机跑了全局 HTTP 代理，访问本地 MCP 服务要设
`NO_PROXY=127.0.0.1,localhost`，否则 agent↔server 的 localhost 流量会被绕进代理。

---

## 5. 可复核证据：怎么把每个数追到原始来源

这是本手册与"模型背出来的手册"的分界线。 chemfacts 的每条输出都携带**四要素**，足以
让你不依赖本工具、独立追到一手来源：

| 要素 | 在哪 | 用途 |
|---|---|---|
| 来源名 | 每条数值后 `OSHA / HSDB / CAMEO / ILO ICSC / NIOSH / EPA` | 知道是谁测/谁编的 |
| 参考编号 | `ref #46` 等 | 对应 PubChem 该化合物参考列表里的具体条目 |
| 查证日期 | `accessed 2026-10-20` | 数据快照时间，判断是否过期 |
| 属性 | `experimental` / `computed` | 实测还是从分子式算的 |

**三条独立复核路径：**

1. **走 PubChem 参考编号。** 打开 `resolve` 给出的 CID 页（如 NMP=13387）→
   "Experimental Properties" → 该物性下列出各来源；`ref #` 就是这里的参考列表条目号。
   来源名（OSHA/HSDB/ICSC…）与 `ref #` 对得上，即通过。
2. **走一手数据库。** `ILO ICSC` = 国际劳工组织化学品安全卡片（免费公开，按 CAS 或
   名称搜）；`HSDB` = 有毒物质危险物质数据库（NIH 托管）；`NIOSH/OSHA/CAMEO` 各有公开页。
   卡片上的数值应能在这些库里找到同一条。
3. **走缓存重现。** `cache show` 看快照规模 → `cache clear` → 重跑同一命令 → 数值/来源/
   参考编号应当一致，只有 `accessed` 日期变。一致即说明"数据可复现"。

**可复核的边界（诚实声明）：**
- `computed` 值（如 MW 从分子式算）不是实测，是 PubChem 由分子式推的，复核方式是按分子式
  手算，而非找实验记录。
- `conflict` 状态不是"错了"，是"来源之间真打架"，工具摊开每个值让你判，不替你下结论。
- `unverified` / NOT_FOUND 是"没有带来源的数据"，工具报缺失，**任何声称的数都不因此被
  视为已核实**——这是设计，不是缺陷。

---

## 6. 常见工作流（照做即可）

**A. 开反应前查某溶剂的闪点/自燃点（安全）**
```
chemfacts lookup NMP flash-point          # 看全部来源值
chemfacts verify NMP autoignition-point --claim 253   # 核你手头记的数
```
闪点用"开杯/闭杯"分别报；自燃点单值。拿 `confirmed` 才写进安全评估。

**B. 把论文里一个物性数值核实后再引用**
```
chemfacts verify <物质> <物性> --claim <论文里的数>
```
`CONFIRMED` 可引；`MISMATCH` 看 `closest` 那条来源改数；`NOT_FOUND` 说明该数无公开
来源支撑，引用要谨慎。

**C. 新遇到一个含糊缩写，先钉位再用**
```
chemfacts alias add <缩写> <CAS> --note "为什么选它，排除哪些"
chemfacts resolve <缩写>        # 之后永远走钉位答案
```

**D. 把某化合物的完整事实卡归档到 Obsidian**
```
chemfacts card <物质> --format obsidian --out "F:\Hermes\Obsidian lib\chemical-facts\<name>.md"
```

**E. 让 agent（Claude Code/ZCode/Hermes）按溯源查化学事实**
按 §4.8 注册 MCP 服务；agent 调 `chemfacts_verify` 等工具，返回带溯源的 JSON，
而不是模型凭记忆编数。

---

## 7. FAQ / 坑

- **数值看着不对？** 先看 `experimental` 还是 `computed`、闭杯还是开杯、参考编号对应
  的一手来源。工具摊开每个值，判断权在你。
- **CONFLICT 怎么办？** 不是报错。逐条看 `ref #` 与来源口径（纯品 vs 混合品、不同测试法），
  自己选可信值，必要时 `alias` 注释里记一句。
- **UNVERIFIED / NOT_FOUND 能"补"吗？** 不能。没有公开来源就不给数；要找就换来源
  数据库手动查，别指望工具编。
- **缓存会不会过期？** 默认 30 天 TTL。要最新就 `cache clear` 重查。
- **本地 MCP 连不上 / 报 "Server returned an error"？** 多半是全局代理劫持了
  127.0.0.1：设 `NO_PROXY=127.0.0.1,localhost` 再试。
- **缩写钉错了怎么办？** `alias show` 看 note → `alias remove` 删 → 重新 `alias add` 钉对。

---

## 附：与 README 的分工

- 想懂"为什么这么设计"（架构图、状态判定逻辑、缩写消歧）→ 读 [README_zh](../README_zh.md)。
- 想"拿起来就用" → 读本手册。
- 本手册 §0/§5 保证：你看到的每个数都能重放、都能追到一手来源。
