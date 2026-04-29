# VEC Platform v2.0 → v3.0 Gap Report

**日期**: 2026-04-29
**当前 commit**: `5c281e4` (master, pushed to origin)
**作用**: 对比当前 v2.0 实现与 v3.0 设计，输出诊断结论；本文档**不修改任何代码**

---

## 1. 当前代码状态盘点

### 1.1 顶层结构

```
D:\Projects\VEC Platform\
├── vec_platform/          ← 源码（4703 行）
├── PLATFORM_DEV_PLAN.md   ← 旧设计文档（4 周计划，描述当前 v2.0 形态）
├── SETUP_INSTRUCTIONS.md  ← 初始化步骤
├── pyproject.toml         ← 依赖清单
├── uv.lock
├── vec_platform.db        ← SQLite 本地开发库（.gitignore 已排除）
└── ngrok.exe              ← 开发用穿透工具（.gitignore 已排除）
```

**注意**:
- 没有 `docs/` 目录（本报告会触发首建）
- 没有 `alembic/` 目录，但 `pyproject.toml` 列出了 `alembic>=1.13.0` 依赖。当前用 `Base.metadata.create_all()` 在启动时建表（[main.py:27](../vec_platform/main.py#L27)），**没有迁移机制**
- 没有 `config/`、`locales/`、`i18n/` 之类的多国化基础设施

### 1.2 vec_platform/ 文件清单与行数

| 文件 | 行数 | 作用 |
|------|------|------|
| [main.py](../vec_platform/main.py) | 1552 | FastAPI 主入口 + 所有 Dash 页面 + 路由 callback |
| [models/__init__.py](../vec_platform/models/__init__.py) | 194 | 8 张表的 SQLAlchemy ORM 定义 |
| [config.py](../vec_platform/config.py) | 56 | 价格/常量/可选项静态字典 |
| [engine/base.py](../vec_platform/engine/base.py) | 62 | `CalculationEngine` ABC |
| [engine/mock.py](../vec_platform/engine/mock.py) | 220 | `MockEngine` 实现 |
| [api/profile.py](../vec_platform/api/profile.py) | 248 | `/api/user-input`、`/api/profile`、`/api/recalculate` |
| [api/device_shift.py](../vec_platform/api/device_shift.py) | 153 | `/api/device-shift`、`/api/drag-log` 读写 |
| [api/bill.py](../vec_platform/api/bill.py) | 115 | `/api/bill`、`/api/bill-comparison` |
| [api/survey.py](../vec_platform/api/survey.py) | 93 | `/api/survey`、`/api/impacts` |
| [api/session.py](../vec_platform/api/session.py) | 82 | `/api/session` 读写、`/api/session/{id}/complete` |
| [api/shadow_price.py](../vec_platform/api/shadow_price.py) | 42 | `/api/shadow-prices/{id}`（按需生成） |
| [dash_app/app.py](../vec_platform/dash_app/app.py) | 65 | **未使用**的多页 Dash 工厂（main.py 没引用） |
| [static/step3_customize.html](../vec_platform/static/step3_customize.html) | 93 | Step 3 拖拽页 HTML 框架 |
| [static/step5_respond.html](../vec_platform/static/step5_respond.html) | 98 | Step 5 响应价格页 HTML 框架 |
| [static/js/timeline.js](../vec_platform/static/js/timeline.js) | 477 | Step 3 主逻辑（拖拽 + 实时图 + 账单卡） |
| [static/js/step5.js](../vec_platform/static/js/step5.js) | 597 | Step 5 主逻辑（拖拽 + 建议提示 + 三线图 + 意愿表单） |
| [static/js/shared.js](../vec_platform/static/js/shared.js) | 123 | `VECCompute` 纯函数（clamp、bill 公式、cheapest-window） |
| [static/js/devices.js](../vec_platform/static/js/devices.js) | 86 | 设备元数据 + 价格常量 |
| [static/js/api.js](../vec_platform/static/js/api.js) | 58 | fetch 封装 |
| [static/css/timeline.css](../vec_platform/static/css/timeline.css) | 281 | Step 3/5 样式 |

### 1.3 main.py 架构（FastAPI + Dash 挂载方式）

| 行号 | 内容 |
|------|------|
| 1-22 | imports（含 `WSGIMiddleware`） |
| 24-31 | DB 引擎 + `Base.metadata.create_all()` + `SessionLocal` + `MockEngine` 单例 |
| 33-40 | `get_db()` Yield 依赖 |
| 42-49 | Dash app 实例化（`requests_pathname_prefix="/dash/"`，`suppress_callback_exceptions=True`） |
| 51-95 | `make_progress()` 进度条组件 + Dash root layout（含 `dcc.Location` 和 `page-content`） |
| 100-106 | `_parse_session_id(search)` 工具函数 |
| 108-136 | `display_page` 路由 callback（pathname 匹配 → 调用对应 step layout） |
| 138-203 | `step1_layout()` Dash 表单 |
| 206-282 | `submit_step1` callback（保存 UserInput + 生成 profile + 算 3 场景账单 + 跳 step2） |
| 285-475 | Step 2 layout + 辅助（`_load_curve_figure`、`_bill_card`） |
| 479-739 | Step 4 layout + 辅助（影子价格图、节省卡、关于 VEC 卡） |
| 741-1003 | Step 6 layout + 辅助（场景元数据、卡片、breakdown 表、对比图） |
| 1005-1271 | Step 7 layout + 三个 Tab（`_policy_tab`、`_grid_tab`、`_environment_tab`） |
| 1273-1471 | Step 8 layout + `submit_survey` callback |
| 1474-1527 | FastAPI app + `/`、`/health`、`/step3`、`/step5` 路由 |
| 1528-1552 | API router 挂载 + `WSGIMiddleware` 挂 Dash 到 `/dash` + 静态文件挂载 + `app = fastapi_app` |

**架构关键点**:
- 单一 FastAPI 进程，Dash 通过 `WSGIMiddleware` 挂在 `/dash/`
- Step 3 和 Step 5 是 FastAPI 直接 serve 的 HTML（路由 `/step3`、`/step5`），JS 从 URL 读 `session_id`
- Dash callback **直接读写 DB**（不走 HTTP API），与 API 路由各走各的
- 没有用 [dash_app/app.py](../vec_platform/dash_app/app.py)（孤儿模块，待清理）

### 1.4 数据库 Schema

| 表 | 主要字段 | 备注 |
|----|---------|------|
| `sessions` | id (UUID36, PK), created_at, completed (bool), current_step (int), role (str?, **当前存 building_type**) | `role` 字段语义被占用（存 `apartment`/`villa_pv` 之类），与 v3.0 想要的 `expert`/`general` 冲突 |
| `user_inputs` | id, session_id (FK), building_type, area_m2, people, heating, has_ev, has_pv, pv_kwp?, has_bess, bess_kwh? | 整张表的字段都映射 v2.0 Step 1，多个字段在 v3.0 要去掉/换 |
| `daily_profiles` | id, session_id, step (2/3/5), rigid_load (JSON 96), flexible_load, pv_generation, net_load, devices (JSON dict) | 按 step 多次插入 |
| `bill_breakdowns` | id, session_id, scenario, step, energy_purchase, grid_fee, energy_tax, pv_self_consumption, vec_discount, feed_in_income, net_cost | scenario ∈ {no_vec, vec_no_adjust, vec_adjusted} |
| `shadow_prices` | id, session_id, retail_price (JSON 96), internal_buy, internal_sell, feed_in_price | 一 session 一行 |
| `device_shifts` | id, session_id, step (3/5), device_name, original_start, original_end, final_start, final_end, willing (bool?), unwilling_reason (str 50?) | 存**最终位置** + 意愿（每设备每 step 一行） |
| `drag_logs` | id, session_id, step, timestamp, device_name, from_start, from_end, to_start, to_end, action ('move'/'add'/'remove') | 存**每次拖拽事件** |
| `survey_responses` | id, session_id, q1_willingness, q2_reasons (JSON), q3_concerns (JSON), q4_savings_perception | 一 session 一行；只够 Q1-Q4 |

**关键发现**:
- v3.0 spec 里的 "device_shifts: session_id, action_type, device, original_time, new_time, timestamp（拖拽日志）" → 实际对应当前的 [drag_logs](../vec_platform/models/__init__.py#L147) 表，不是 [device_shifts](../vec_platform/models/__init__.py#L128) 表。**命名冲突**，需要在新设计里澄清。
- 当前 `device_shifts` 多承载了"willing/unwilling_reason"字段，是 step 5 的意愿数据宿主。

### 1.5 API endpoints 全清单

挂载在 `/api/*` 的 15 个 endpoints:

| Method | Path | 作用 | 文件 |
|--------|------|------|------|
| POST | `/api/session` | 创建 session | [api/session.py:32](../vec_platform/api/session.py#L32) |
| GET | `/api/session/{id}` | 读 session | [api/session.py:48](../vec_platform/api/session.py#L48) |
| PUT | `/api/session/{id}/step` | 更新 current_step | [api/session.py:57](../vec_platform/api/session.py#L57) |
| PUT | `/api/session/{id}/complete` | 标记完成 | [api/session.py:73](../vec_platform/api/session.py#L73) |
| POST | `/api/user-input` | 写 UserInput + 触发 profile/账单 | [api/profile.py:43](../vec_platform/api/profile.py#L43) |
| POST | `/api/generate-profile` | 重生成 profile | [api/profile.py:114](../vec_platform/api/profile.py#L114) |
| GET | `/api/profile/{id}?step=N` | 读某步 profile | [api/profile.py:88](../vec_platform/api/profile.py#L88) |
| POST | `/api/recalculate` | 重算 step=N profile + 三场景账单 | [api/profile.py:150](../vec_platform/api/profile.py#L150) |
| POST | `/api/bill` | 写 bill | [api/bill.py:38](../vec_platform/api/bill.py#L38) |
| GET | `/api/bill/{id}?scenario=...` | 读单 bill | [api/bill.py:66](../vec_platform/api/bill.py#L66) |
| GET | `/api/bill-comparison/{id}` | 读三场景账单 | [api/bill.py:94](../vec_platform/api/bill.py#L94) |
| GET | `/api/shadow-prices/{id}` | 读（必要时建）影子价格 | [api/shadow_price.py:14](../vec_platform/api/shadow_price.py#L14) |
| POST | `/api/device-shift` | 写最终位置+意愿 | [api/device_shift.py:39](../vec_platform/api/device_shift.py#L39) |
| GET | `/api/device-shift/{id}?step=N` | 读最终位置 | [api/device_shift.py:72](../vec_platform/api/device_shift.py#L72) |
| POST | `/api/drag-log` | 写单次拖拽事件 | [api/device_shift.py:98](../vec_platform/api/device_shift.py#L98) |
| GET | `/api/drag-log/{id}?step=N` | 读拖拽事件流 | [api/device_shift.py:131](../vec_platform/api/device_shift.py#L131) |
| POST | `/api/survey` | 写 survey + 标记完成 | [api/survey.py:24](../vec_platform/api/survey.py#L24) |
| GET | `/api/survey/{id}` | 读 survey | [api/survey.py:58](../vec_platform/api/survey.py#L58) |
| GET | `/api/impacts/{id}` | 调 `MockEngine.calculate_impacts()` 返回随机数 | [api/survey.py:80](../vec_platform/api/survey.py#L80) |

挂载在 FastAPI 根的非 API 路由（非 Dash）:

| Method | Path | 作用 |
|--------|------|------|
| GET | `/` | 创建新 session 后 302 跳 `/dash/step1?session_id=...` |
| GET | `/health` | 返回 `{"status":"ok","engine":"mock"}` |
| GET | `/step3` | serve `step3_customize.html`（FileResponse） |
| GET | `/step5` | serve `step5_respond.html`（FileResponse） |

### 1.6 页面清单

**Dash 页面** (URL `/dash/stepN`，由 [display_page](../vec_platform/main.py#L114) 渲染):

| Step | 函数 | 行号 | 状态 |
|------|------|------|------|
| 1 | `step1_layout` | 138-203 | ✅ 已实现（building_type / area / people / heating / has_ev） |
| 2 | `step2_layout` | 393-475 | ✅ 已实现（堆叠面积图 + 月账单卡） |
| 4 | `step4_layout` | 655-739 | ✅ 已实现（4 线影子价格 + 节省卡 + 关于 VEC） |
| 6 | `step6_layout` | 916-1003 | ✅ 已实现（3 卡片 + breakdown 表 + 3 线对比） |
| 7 | `step7_layout` | 1211-1271 | ✅ 已实现（Policy/Grid/Environment 三 Tab） |
| 8 | `step8_layout` | 1366-1410 | ✅ 已实现（Q1-Q4 + 提交） |

**静态 HTML 页面** (FastAPI 直接 serve):

| Step | 文件 | 状态 |
|------|------|------|
| 3 | [step3_customize.html](../vec_platform/static/step3_customize.html) + [timeline.js](../vec_platform/static/js/timeline.js) | ✅ 已实现（拖拽 + 实时图 + 账单卡 + 调色板） |
| 5 | [step5_respond.html](../vec_platform/static/step5_respond.html) + [step5.js](../vec_platform/static/js/step5.js) | ✅ 已实现（拖拽 + 建议提示 + 三线对比图 + 意愿/原因表单） |

**未实现**:
- Step 0（同意 + 第一次预期）
- Tenant 假设性声明（条件性）
- 中间页 1（信息校准 A/B/C + 兴趣 Likert）

### 1.7 MockEngine 实现细节

[engine/mock.py](../vec_platform/engine/mock.py)，220 行。

**`generate_profile(user_input)`** ([mock.py:24](../vec_platform/engine/mock.py#L24)):
- 按 `building_type` 设 base load 振幅（apartment 0.3/1.2 kW、villa_noder 0.5/1.5、villa_pv/villa_pvbess 0.5/1.8）
- 早晚峰窗口 06-09 + 17-22
- 固定柔性设备：cooking_am 28-30 (2 kW)、cooking_pm 72-76 (2 kW)、dishwasher 78-84 (1.2 kW)、washing_machine 76-84 (0.5 kW)
- `heating in {electric, heatpump}` → 加 water_heater 20-28 (3 kW)
- `has_ev` → 加 ev_charger 64-96 (3.7 kW)
- `has_pv` → noon 钟形 PV 曲线，峰值 = `pv_kwp × 0.6`（默认 5 kWp → 3 kW 峰）
- 返回 96-slot per-device 数组，结果存 `daily_profiles.devices`

**`calculate_bill(profile, scenario)`** ([mock.py:49](../vec_platform/engine/mock.py#L49)):
- **月度** = 日均 × 30（**当前是固定的"典型一天"，不区分夏/冬**）
- consumed_monthly × 1.5 SEK/kWh = energy_purchase
- + 580 SEK/月固定网费 + consumed × 0.45 SEK/kWh 能源税
- scenario 决定折扣率：no_vec 0%、vec_no_adjust 15%、vec_adjusted 25%
- feed_in：no_vec 用 `FEED_IN_PRICE` (0.95)，VEC 场景用 `VEC_INTERNAL_SELL` (1.05)

**`get_shadow_prices(session_id)`** ([mock.py:104](../vec_platform/engine/mock.py#L104)):
- 合成数据：retail 早晚峰 +0.5、夜间 -0.3；internal_buy 10-14h 降到 0.75、其他 0.85；internal_sell 恒 1.05；feed_in 恒 0.95
- **不是真实 SE3 spot price**

**`calculate_impacts(session_id)`** ([mock.py:139](../vec_platform/engine/mock.py#L139)):
- 用 `random.uniform()` 返回，**每次调用结果都变**。但 Step 7 没用这个，而是在 [main.py:1011 `_compute_impacts`](../vec_platform/main.py#L1011) 里**确定性地**从 step 2 vs step 5 net_load 重算。

### 1.8 当前 Step 1 实际字段（用于对比 v3.0）

[main.py:138-203](../vec_platform/main.py#L138)：

- `building-type` 4 选 1 单选：apartment / villa_noder / villa_pv / villa_pvbess
- `area` number input (30-300 m²)
- `people` number input (1-6)
- `heating` 3 选 1 select：district / electric / heatpump
- `has-ev` 单 checkbox
- 没有：ownership_type、occupation、DER 多选 UI（has_pv / has_bess 由 `building_type` 隐式推导）

### 1.9 当前 Step 8 实际题目

[main.py:1275-1306](../vec_platform/main.py#L1275)：

- Q1 willingness（5 选 1）：very_willing / somewhat / need_more_info / unlikely / not_willing
- Q2 reasons（多选，UI 上写"pick up to 3"，callback 截前 3 个）：savings / environment / community / control / convenience / other
- Q3 concerns（多选，截前 3）：privacy / complexity / insufficient_savings / loss_of_control / distrust / other
- Q4 savings perception（4 选 1）：attractive / somewhat / not_enough / unsure
- 没有：exit threshold（5 选 1：100/75/50/25/0%）、expert 3 题、demographics

---

## 2. 可保留（v3.0 直接复用）

下面这些代码 v3.0 不会动，可以直接搬过去：

### 2.1 整体架构骨架（不动）
- FastAPI + `WSGIMiddleware` 挂 Dash 的混合架构（[main.py:1547](../vec_platform/main.py#L1547)）—— v3.0 仍然是 Dash + 静态 HTML 混合
- `dcc.Location` + `display_page` 路由模式
- `_parse_session_id` 工具
- 静态文件挂载 `/static`、Step 3/5 通过 `/stepN` FileResponse serve

### 2.2 计算 / 数据模型层（绝大部分不动）
- [DailyProfile](../vec_platform/models/__init__.py#L70)、[BillBreakdown](../vec_platform/models/__init__.py#L91)、[ShadowPrices](../vec_platform/models/__init__.py#L112) 表结构
- [DragLog](../vec_platform/models/__init__.py#L147) 表（v3 的"device_shifts 拖拽日志"语义就是它）
- [`CalculationEngine` ABC](../vec_platform/engine/base.py)
- [MockEngine.generate_profile()](../vec_platform/engine/mock.py#L24) 的 96-slot 设备分解结构（数据形状不变，只是数值需要换成"夏季典型情境"）
- [MockEngine._device_block / _get_pv_generation](../vec_platform/engine/mock.py#L199) 工具
- [VECCompute](../vec_platform/static/js/shared.js)（clampStart、buildDeviceArrays、computeNetLoad、cheapestWindow、computeBillScenario）—— **v3 ±10% 全局微调可以直接调用这些**
- [DEVICE_CATALOG](../vec_platform/static/js/devices.js)（颜色/标签/默认时间）

### 2.3 复用的 Dash 页面骨架
- Step 2 layout 的"曲线 + 账单卡"骨架，**只需在底部加预期/把握度题**
- Step 6 三卡片 + breakdown 表 + 三线对比图（v3 也要三方对比）
- Step 7 三 Tab 布局
- Step 8 表单壳子（Q1-Q4 这 4 题在 v3 中保留，**只需扩展到 8-9 题 + 退出阈值 + 专家题 + 人口学**）

### 2.4 拖拽底层
- [timeline.js](../vec_platform/static/js/timeline.js) 的 pointerdown/move/up + slot snap 逻辑 —— 完全可复用
- [step5.js](../vec_platform/static/js/step5.js) 的"willingness + unwilling_reason"表单结构 —— v3 仍然要

### 2.5 已有 API
- 全部 15 个 `/api/*` endpoint 都保留。`/api/recalculate` 在 v3 增加新表/新字段时只需扩展，不需要重写。

---

## 3. 需修改（保留架构，改内容/字段）

### Step 1 → 重做表单内容（中等改造）
**文件**: [main.py:138-282](../vec_platform/main.py#L138)（layout + submit_step1 callback）、[models/__init__.py:50-67](../vec_platform/models/__init__.py#L50)（UserInput）

| 字段 | 当前 | v3.0 |
|------|------|------|
| 建筑/产权 | `building_type`：apartment/villa_noder/villa_pv/villa_pvbess（4 选 1） | `ownership_type`：tenant/owner（2 选 1） |
| DER | 由 building_type 隐式推导（has_pv / has_bess 是后台 booleans） | 显式 multi-select：PV / BESS / EV / heat pump / EV charger 等 |
| 居住人数 | `people` (1-6) | v3 spec 没提，建议**保留**或删 |
| 取暖 | `heating` 3 选 1 select | **删除** |
| 面积 | `area` number | **保留** |
| 职业 | 没有 | **新增** `occupation`，用于 expert 分流（能源公司员工/能源研究员/能源 PhD → expert，其他 → general） |

**复杂度**: 中。表单 UI、submit_step1、UserInput 字段、MockEngine 输入都要改。MockEngine 当前用 `building_type` 设 base load 振幅，v3 没了 building_type 后，需要用 ownership_type + DER 推导（例如 tenant → 公寓振幅、owner+PV → 别墅振幅）。

### Assumption statement → 新建条件性中间页（小）
**位置**: Step 1 提交后，进 Step 2 之前。仅 `ownership_type == "tenant"` 时显示。

**复杂度**: 小。Dash 页（或干脆 FastAPI 一个 markdown serve 页）。

### Step 2 → 在尾部追加测量题（小）
**文件**: [main.py:285-475](../vec_platform/main.py#L285)

- 当前末尾只有 Back / Next 两个按钮 + 月账单卡
- v3 要追加：第二次预期百分比 slider、把握度 Likert
- 每个测量提交时调用一个新 endpoint 写 `prior_expectations` 表（measurement_round=2）

**复杂度**: 小。骨架不动，只是底部加一个测量小卡 + 新 callback 写 `prior_expectations` 一行。

### Step 3 → 新增"全局负荷 ±10%"微调（中）
**文件**: [step3_customize.html](../vec_platform/static/step3_customize.html)、[timeline.js](../vec_platform/static/js/timeline.js)

- 当前只能拖单个设备，没有整体缩放控件
- v3 要：一个滑块（每次 ±5%、总范围 ±10%）整体等比缩放 baseline 负荷
- JS 端要在 `VECCompute.computeNetLoad` 之前对 `baseLoad` 做 `× scale_factor`
- `/api/recalculate` 也要接收并持久化 `scale_factor` 字段

**复杂度**: 中。前端加滑块 + 缩放函数；后端 `RecalculateRequest` schema 加字段；`daily_profiles.devices` JSON 内可以保留 scale_factor。

### Step 4 → 删除"画曲线"功能（如果存在）+ 新增 2 道选择题（小）
**文件**: [main.py:479-739](../vec_platform/main.py#L479)

- 当前只有图 + 节省卡 + 关于 VEC 卡，**没有"画曲线"功能**（spec 要求删除的功能并不存在，只需注意：v3 的设计文档可能源于一个有此功能的旧版本，当前 v2.0 已经没有了）
- 要新增：2 道简化选择题（具体题目内容由 v3 设计文档定义）

**复杂度**: 小。

### Step 5 → 切换到真实 SE3 spot price + 反事实追问（大）
**文件**: [step5.js](../vec_platform/static/js/step5.js)、[mock.py:get_shadow_prices](../vec_platform/engine/mock.py#L104)

- 当前 `MockEngine.get_shadow_prices` 是**合成数据**（10-14h 降价那种）
- v3 要**真实 SE3 spot price 一天数据**（PV 大盈余夏日，从 ENTSO-E / Nord Pool / 历史 CSV 拿）
- 当前已经是"一天 96-slot"，**没有 4 个独立 scenario**（v3 spec 说要删的"4 scenario"在当前代码中**并不存在**）
- 反事实追问：在 Step 5 提交意愿后追加 1-2 道题（"如果价差再大一倍你会不会调？"之类）

**复杂度**: 大（数据来源），但 UI 改动小。需要建立真实 SE3 数据加载机制（CSV → DB 或硬编码常量）。

### Step 6 → 追加"失望感 + 会考虑意愿"题（小）
**文件**: [main.py:741-1003](../vec_platform/main.py#L741)

- 当前只有 3 卡片 + breakdown 表 + 对比图
- v3 在底部追加：失望感（与 Step 0 第一次预期对比）+ "会考虑加入吗" 5 点 Likert
- 数据写入 survey_responses 或新表

**复杂度**: 小。

### Step 7 → 末尾追加 Likert（小）
**文件**: [main.py:1005-1271](../vec_platform/main.py#L1005)

- 当前是纯展示 3 Tab
- v3 末尾要 Likert（衡量 broader-impacts framing 的影响）

**复杂度**: 小。

### Step 8 → 扩展到 8-9 题 + 退出阈值 + 专家分流 + 人口学（中）
**文件**: [main.py:1273-1471](../vec_platform/main.py#L1273)、[models/__init__.py:166](../vec_platform/models/__init__.py#L166)、[api/survey.py](../vec_platform/api/survey.py)

- Q1-Q4 保留
- 追加 4-5 题（具体题目由 v3 设计文档定义）
- 退出阈值题（5 选 1：100% / 75% / 50% / 25% / 0%）→ 写入新 `exit_thresholds` 表
- expert 分流：仅 `sessions.role == "expert"` 时显示额外 3 题
- 人口学块：年龄区间、性别（v3 是 Step 8 自选 country，country_code 也在这里）

**复杂度**: 中。`SurveyResponse` 表要 ALTER（加新列）或拆成"core + extras + demographics"三张表。

### Session table → 新增字段（小）
**文件**: [models/__init__.py:16-47](../vec_platform/models/__init__.py#L16)

- 加 `country_code` (str), `language` (str), `info_calibration_arm` (str A/B/C)
- **`role` 字段语义换语**：当前存 `building_type`（apartment/villa_pv/...），v3 要存 `expert`/`general`。两个解决方案：
  - **方案 A**：删 sessions.role，改成在 `user_inputs.ownership_type` 里存产权 + 在新字段 `sessions.expertise` 存 expert/general
  - **方案 B**：保留 `sessions.role`，把当前往 role 写 building_type 的两处（[main.py:251](../vec_platform/main.py#L251)、[api/profile.py:73](../vec_platform/api/profile.py#L73)）改成写"expert"/"general"

**推荐方案 A**：语义清晰，避免迁移现有数据时混乱。

**复杂度**: 小（schema 层面），但要找出所有 `session.role` 读写处一起改。

---

## 4. 需删除（v3.0 已废弃）

**重要发现**: v3 spec 列的"必须删除清单"里的内容，绝大多数在当前 v2.0 代码里**并不存在**（spec 似乎是基于一个比当前 v2.0 更复杂的早期/平行版本）。

逐项核对：

| v3 spec "必须删除" | 当前代码中是否存在 | 处理 |
|------------------|-------------------|------|
| Step 0 参与门槛 SEK 数字 | ❌ 不存在（Step 0 整个都没有） | 跳过 |
| Step 0 把握程度 | ❌ 不存在 | 跳过 |
| Step 1 5 选 1 房屋类型 | ⚠️ **存在但是 4 选 1**：[main.py:159-164](../vec_platform/main.py#L159) | 删除整段（替换为 ownership_type） |
| Step 1 取暖方式 | ⚠️ **存在**：[main.py:181-191](../vec_platform/main.py#L181)、[UserInput.heating](../vec_platform/models/__init__.py#L59) | 删除字段 + UI |
| Step 1 电热水器 | ❌ 没有这一题（只是 MockEngine 内部根据 heating 自动加 water_heater 设备） | 跳过 |
| Step 1 家庭角色 | ❌ 不存在 | 跳过 |
| Step 1 教育水平 | ❌ 不存在 | 跳过 |
| Step 1 性别/子女/雇佣 | ❌ 不存在 | 跳过（可能 v3 的人口学题在 Step 8 末尾） |
| Step 2 账单真实性 5 选 1 | ❌ 不存在 | 跳过 |
| Step 4 预期价格曲线绘制 | ❌ 不存在 | 跳过 |
| Step 4 实际 vs 预期符合度 | ❌ 不存在 | 跳过 |
| Step 5 4 个独立 scenario | ❌ 不存在（当前已经是单一一天的拖拽 + 影子价格） | 跳过 |
| 中间页 2 整个 (aggregator framing) | ❌ 不存在 | 跳过 |
| Step 6 reference frame 4 组操纵 | ❌ 不存在（当前只有静态 3 列对比） | 跳过 |
| Step 8 Q5 manipulation check | ❌ 不存在 | 跳过 |
| Step 8 Q9 follow-up email | ❌ 不存在 | 跳过 |

**实际需要删除的代码**:
1. **Step 1 building_type radio 控件**: [main.py:156-167](../vec_platform/main.py#L156)（含整个 `RadioItems`）
2. **Step 1 heating select 控件**: [main.py:181-191](../vec_platform/main.py#L181)
3. **submit_step1 callback 里 heating/building_type 处理**: [main.py:227-282](../vec_platform/main.py#L227) 整段重写
4. **UserInput.building_type, .heating 字段**: [models/__init__.py:56,59](../vec_platform/models/__init__.py#L56)（schema 删字段）
5. **MockEngine 对 building_type/heating 的依赖**: [mock.py:154-197](../vec_platform/engine/mock.py#L154)（_get_base_load、_get_devices 重写）
6. **config.BUILDING_TYPES、HEATING_TYPES**: [config.py:37-40](../vec_platform/config.py#L37)（无用常量）
7. **孤儿模块** [dash_app/app.py](../vec_platform/dash_app/app.py)（main.py 没引用，可清理）
8. **MockEngine.calculate_impacts 的随机版**: [mock.py:139-150](../vec_platform/engine/mock.py#L139)（已被 main.py:_compute_impacts 替代，可删）
9. **可能闲置的 API endpoint**: `POST /api/generate-profile`（[api/profile.py:114](../vec_platform/api/profile.py#L114)）—— 当前没人用（Step 1 走 `/api/user-input`、其他走 `/api/recalculate`）。可删。

---

## 5. 需新建（v3.0 全新内容）

### 5.1 新页面 / Step

| 项 | 文件位置（建议） | 说明 |
|----|-----------------|------|
| Step 0：同意 + 一句话 VEC + 第一次预期 | `main.py` 加 `step0_layout` + 新 URL `/dash/step0`；或 `vec_platform/static/step0_intro.html` | 同意按钮、一句话 VEC、第一次预期 0-50% 滑块 |
| 假设性声明（仅租户） | 新增 Dash route `/dash/tenant_disclaimer` 或在 step1 callback 里条件分流 | 一段静态 markdown |
| 中间页 1：信息校准 A/B/C + 兴趣 Likert | `main.py` 加 `info_calibration_layout` + 新 URL；session 入场时按 A/B/C 三组随机分配 | A=乐观情景、B=现实情景、C=不展示。每个 session 创建时随机抽签存到 `sessions.info_calibration_arm` |

### 5.2 新数据表

| 表 | 字段 | 用途 |
|----|------|------|
| `prior_expectations` | id, session_id (FK), measurement_round (int 1 或 2), pct (float), timestamp | Step 0 / Step 2 各测一次 |
| `exit_thresholds` | id, session_id (FK), threshold_ratio (float, ∈ {1.0, 0.75, 0.5, 0.25, 0.0}), timestamp | Step 8 退出阈值题 |

### 5.3 sessions 表新字段

`country_code`, `language`, `info_calibration_arm`, （重新定义）`role`(expert/general)。

### 5.4 多国架构

完全新建：

| 项 | 路径建议 |
|----|---------|
| 国家配置 YAML | `config/countries/se.yaml`、`config/countries/intl.yaml`（价格、电网费、税率、设备默认时间） |
| YAML 加载器 | `vec_platform/i18n/country_config.py` |
| 翻译 messages | `locales/en/messages.json`、`locales/sv/messages.json` |
| 服务端 i18n 工具 | `vec_platform/i18n/translator.py`（按 `sessions.language` 取串） |
| 客户端 i18next | 新增前端 `npm` 依赖或用 CDN，static/js 里集成 |
| Step 8 国家自选 | 加一个 country dropdown，用户选完之后写回 `sessions.country_code` |

依赖新增：`PyYAML`（YAML 加载）、`Jinja2`（如果 i18n 用模板）或自己写简单 dict 查询。

### 5.5 Expert 分流

| 项 | 文件 |
|----|------|
| Step 1 occupation 题（4 选 1+ "其他"） | `main.py:step1_layout` |
| `sessions.role` 赋值逻辑（occupation 中三类 → expert，其他 → general） | `submit_step1` |
| Step 8 conditional 渲染 expert 3 题 | `step8_layout` 内根据 `session.role` 显隐 |

### 5.6 信息校准随机分组

| 项 | 文件 |
|----|------|
| 入场分组（三组等概率） | `/`（[main.py:1490](../vec_platform/main.py#L1490)）创建 session 时 `random.choice(['A','B','C'])` 写入 `sessions.info_calibration_arm` |
| 中间页 1 按 arm 渲染不同内容 | 新 `info_calibration_layout` |

### 5.7 真实 SE3 spot price 数据

| 项 | 路径建议 |
|----|---------|
| 真实数据 CSV | `vec_platform/data/se3_summer_pv_surplus_2025.csv` 或类似 |
| 加载器 | `MockEngine.get_shadow_prices` 改成读 CSV 或预处理后硬编码常量 |

### 5.8 Step 5 反事实追问、Step 6 失望感、Step 7 Likert

参考第 3 节，主要是表单题，写入新表或扩展 `survey_responses`。

### 5.9 数据迁移基础设施

`alembic/` 目录从无到有：

```
alembic.ini
alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 0001_v3_initial_schema.py
```

`alembic` 在 [pyproject.toml](../pyproject.toml#L11) 里早已声明，但**还没初始化**。v3 必须有迁移机制（schema 改动多）。

---

## 6. 数据库 migration 影响

### 6.1 现有 SQLite 库

[vec_platform.db](../vec_platform.db) 在本地存在（约 466 KB），含开发期测试数据。**`.gitignore` 已排除**，远端 GitHub 仓库不影响。

### 6.2 schema 变更概览

| 表 | 变动类型 | 详情 |
|----|---------|------|
| `sessions` | **ALTER**（加列 + 重定义 role 语义） | + country_code (str), + language (str), + info_calibration_arm (str), role 改存 expert/general |
| `user_inputs` | **ALTER**（删旧字段 + 加新字段） | - building_type, - heating, + ownership_type (str), + occupation (str)。`area_m2`、`has_ev/has_pv/has_bess/pv_kwp/bess_kwh` 保留（DER 多选的存储） |
| `daily_profiles` | 不变 | 数据数值变（夏季典型情境），结构不变 |
| `bill_breakdowns` | 不变 | |
| `shadow_prices` | 不变（数据源换成真实 SE3） | |
| `device_shifts` | 可考虑新增 `scale_factor` 字段以记录 Step 3 全局缩放 | 或单独存到 `daily_profiles.devices` JSON |
| `drag_logs` | 不变 | |
| `survey_responses` | **ALTER 大幅扩展** | 加 5 列左右（Q5-Q9 + 退出阈值或拆表） |
| `prior_expectations` | **新建** | |
| `exit_thresholds` | **新建** | |

### 6.3 SQLite 兼容性

SQLite 对 ALTER TABLE 支持有限：
- ✅ ADD COLUMN 可以
- ⚠️ DROP COLUMN 在 SQLite 3.35+ 才支持，3.35 之前要"创建新表 + 复制数据 + 删旧表 + 改名"
- ⚠️ ALTER COLUMN 类型变更不支持

**推荐**：因为开发期数据库可丢弃 + 远端没数据，**v3 直接新建 schema、删旧 db、初始化 alembic 第一版迁移**。生产部署到 PostgreSQL 后再正常用 alembic upgrade。

### 6.4 是否破坏现有数据

- 本地 [vec_platform.db](../vec_platform.db)：会破坏（结构 + role 语义都变），**可直接删**
- 远端：没有生产数据，零影响

---

## 7. 风险与建议改造顺序

### 7.1 主要风险

| 风险 | 影响 | mitigation |
|------|------|------------|
| **`sessions.role` 语义换义** | 当前两处赋值（[main.py:251](../vec_platform/main.py#L251)、[api/profile.py:73](../vec_platform/api/profile.py#L73)）会写错；Step 4 / Step 6 / Step 7 等读 session 的地方暂时没用 role，但日后 expert 分流加上去后**很容易被旧赋值覆盖** | 一次性 grep `session.role`、`SessionModel.role` 全部改完；最好直接弃用旧 `role`，加新字段 `expertise` |
| **`building_type` 是 MockEngine 唯一的"建筑形态"驱动器** | 删了之后 base load 振幅 / device 出现条件没了根据 | 先在 MockEngine 内部建立"derive_building_type(ownership, has_pv, has_bess, area)"私有函数；表面字段去掉，内部逻辑还能跑 |
| **i18n 工程量** | 多国 + i18next + YAML 是独立子项目，至少 1 周 | 第一阶段先做"代码里所有英文字符串集中到 messages.en.json"（不切换语言），等核心流程跑通再叠加 sv |
| **真实 SE3 数据** | Nord Pool 历史数据需要授权或找开放数据集；夏季 PV 盈余日的选择标准也要定 | 先用一个"硬编码 96 浮点数组"占位，等数据源敲定后再换 CSV |
| **alembic 与 `Base.metadata.create_all()` 冲突** | 当前 [main.py:27](../vec_platform/main.py#L27) 启动时 `create_all`，alembic 引入后两者会打架 | v3 第一步：删 `create_all`、初始化 alembic、第一版 migration 重建所有表 |
| **静态 HTML/JS 的 i18n** | timeline.js / step5.js 里硬编码英文（"Already in a cheap window"、"Move to..."） | 改成读 `window.MESSAGES` 全局对象，由后端模板注入 |
| **多端 fetch URL 硬编码 `/api/...`** | 多国时如果有反向代理 path 前缀会断 | api.js 里抽 `BASE_URL` 全局变量 |

### 7.2 建议改造顺序

按"先骨架、后内容"原则，分 4 阶段：

**Phase 1：清地基（半天 ~ 1 天）**
1. 创建 `docs/v3_gap_report.md`（即本文档）✅
2. 初始化 alembic（`alembic init alembic`、配 sqlalchemy.url）
3. 第一版 migration = "现有 v2.0 schema 的 baseline"，不动结构。`Base.metadata.create_all` 保留为 fallback
4. 删 [dash_app/app.py](../vec_platform/dash_app/app.py)、[MockEngine.calculate_impacts](../vec_platform/engine/mock.py#L139)、`POST /api/generate-profile` 这些孤儿
5. 把 main.py 拆成多个文件（建议）：`pages/step1.py`、`pages/step2.py`、… `pages/step8.py`、`pages/_helpers.py`。1552 行单文件后续改不动

**Phase 2：v3 schema 落地（1-2 天）**
1. 加 `prior_expectations`、`exit_thresholds` 表
2. `sessions` 加 `country_code`、`language`、`info_calibration_arm`、把 `role` 拆成 `expertise`
3. `user_inputs` 加 `ownership_type`、`occupation`，删 `building_type`、`heating`
4. `survey_responses` 扩展（或拆三表）
5. 把"删除 `building_type`"对 MockEngine 的影响 contain 在内部 `derive_building_type()`
6. 写 alembic migration 0002，本地删 db 重跑，确认能 from-zero 启动
7. **此时旧的 step layout 还能跑**（因为 building_type 是 derived，不暴露给用户但表里有）

**Phase 3：v3 Step 内容改造（按依赖顺序）**
1. **Step 1 重写表单**（ownership / DER / area / occupation）
2. **Step 0 + 假设性声明 + 中间页 1** 三个新页 + 信息校准随机分组
3. Step 2 加测量题（第二次预期 + 把握度）
4. Step 3 加 ±10% 全局缩放
5. Step 4 加 2 道选择题
6. Step 5 切换真实 SE3 数据（先占位常量）+ 反事实追问
7. Step 6 加失望感 + 会考虑 Likert
8. Step 7 末尾 Likert
9. Step 8 扩展到 8-9 题 + 退出阈值 + 专家 3 题 + 人口学

**Phase 4：i18n & 多国（1-2 周，可后置）**
1. 抽英文字符串到 `locales/en/messages.json`
2. YAML 国家配置（先 SE，后 INTL）
3. 集成 i18next 客户端 + Python `Translator`
4. Step 8 加 country 自选

**为什么是这个顺序：**
- alembic 不先做，schema 一改就要手动 SQL 维护，痛苦
- 拆 main.py 不先做，每加一个 step 都在 1500 行文件里翻找
- schema 在前、UI 在后：UI 需要新表才能存数据，反过来不行
- i18n 后置：核心流程没跑通前，多语言只是负担

### 7.3 不要做的事

- **不要**保留旧 `building_type` 4 选 1 UI 当作"过渡"。设计明确要去掉，多留只会让用户和测试都迷惑
- **不要**在不动 alembic 的情况下手 ALTER TABLE。SQLite 删字段语法不全，PostgreSQL 又有锁问题，统一走迁移
- **不要**用 IP 地理推断国家。spec 明确"Step 8 自选"

---

## 附：各 Step 当前状态 vs v3.0 一览

| Step | v2.0 现状 | v3.0 要求 | 改造量 |
|------|----------|----------|--------|
| 0 | ❌ 不存在 | 同意 + 一句话 VEC + 第一次预期 | **新建** |
| 1 | building_type 4 + area + people + heating + has_ev | ownership 2 + DER multi + area + occupation | **重写** |
| Tenant 假设 | ❌ 不存在 | 仅租户显示一段说明 | **新建** |
| 中间页 1 | ❌ 不存在 | 信息校准 A/B/C + Likert | **新建** |
| 2 | 曲线 + 月账单 | + 第二次预期 + 把握度 | **小补丁** |
| 3 | 拖拽设备 | + 全局负荷 ±10% | **中补丁** |
| 4 | 影子价格 4 线 + 节省卡 + 关于 VEC | + 2 道选择题 | **小补丁** |
| 5 | 拖拽响应 + willingness/reasons + 三线对比 | 切真实 SE3 数据 + 反事实追问 | **数据源大改、UI 小改** |
| 6 | 三卡 + breakdown + 三线 | + 失望感 + 会考虑 Likert | **小补丁** |
| 7 | Policy/Grid/Environment 三 Tab | + 末尾 Likert | **小补丁** |
| 8 | Q1-Q4 | 8-9 题 + 退出阈值 + 专家 3 + 人口学 | **中补丁** |
| 多国 | ❌ 全英文硬编码 | YAML + i18next + Step 8 自选 | **新建（可后置）** |
| 数据库迁移 | ❌ 用 create_all | alembic | **新建** |

---

**报告结束**。下一步等用户审阅后决定改造起点。
