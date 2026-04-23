# VEC Stated-Preference Platform — Development Plan

> **项目**: KTH × E.ON Virtual Energy Community  
> **目标**: 8步交互式stated-preference实验平台（住宅部分）  
> **开发者**: Xin (solo)  
> **时间**: 4周  
> **日期**: 2026-04-23  

---

## 1. 平台概述

### 用户体验流程（8步）

| Step | 名称 | 核心功能 | 技术实现 |
|------|------|----------|----------|
| 1 | Role & Building | 选择角色（公寓/别墅），输入基本信息 | Dash form |
| 2 | Load Curve & Bill | 生成用电曲线 + 展示月度电费 | Dash + Plotly |
| 3 | Customize Devices | 在时间轴上拖拽设备，调整用电习惯 | **HTML/JS** (拖拽) |
| 4 | Shadow Price | 展示VEC内部影子价格 | Dash + Plotly |
| 5 | Respond to Price | 再次拖拽调整 + 选择理由 | **HTML/JS** (拖拽) |
| 6 | Bill Comparison | 三方账单对比（无VEC / VEC不调 / VEC调整） | Dash + Plotly |
| 7 | Broader Impacts | 政策/电网/环境影响 | Dash tabs |
| 8 | Willingness Survey | 最终参与意愿 + 原因 | Dash form |

### 已确认的9个决策

1. **部署**: Render.com + PostgreSQL (prod), SQLite (dev)
2. **身份**: 匿名, 自动 session ID
3. **社区**: 固定混合模板 (~100住宅 + ~12商业), 被测者按角色嵌入
4. **使用次数**: 单次
5. **语言**: English first, Swedish later
6. **交互**: 时间轴+设备卡片拖拽 (HTML/JS), 其他 Dash
7. **日志**: 记录每次拖拽操作+时间戳
8. **问卷关系**: 住宅完全独立
9. **时间线**: 4周紧凑节奏

---

## 2. 技术架构

```
┌─────────────────────────────────────────────────┐
│                   Browser                        │
│                                                  │
│   Dash Pages (Step 1,2,4,6,7,8)                 │
│   ┌──────────────────────────────────┐           │
│   │  Plotly charts + form inputs     │           │
│   └──────────────────────────────────┘           │
│                                                  │
│   HTML/JS Pages (Step 3,5)                       │
│   ┌──────────────────────────────────┐           │
│   │  Timeline drag & drop            │           │
│   │  → fetch('/api/...') ←           │           │
│   └──────────────────────────────────┘           │
└────────────────────┬────────────────────────────┘
                     │ HTTP
┌────────────────────▼────────────────────────────┐
│              FastAPI Backend                      │
│                                                  │
│   /api/session          → create/get session     │
│   /api/profile          → generate load curve    │
│   /api/bill             → calculate bill         │
│   /api/shadow-prices    → get VEC prices         │
│   /api/device-shift     → log drag operations    │
│   /api/response         → save user responses    │
│   /api/survey           → save final survey      │
│                                                  │
│   ┌──────────────────────────────────┐           │
│   │       CalculationEngine (ABC)    │           │
│   │                                  │           │
│   │   MockEngine (Phase 1)           │           │
│   │   SimulationEngine (later)       │           │
│   └──────────────────────────────────┘           │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│           SQLite (dev) / PostgreSQL (prod)        │
│                                                  │
│   sessions / user_inputs / daily_profiles        │
│   bill_breakdowns / shadow_prices                │
│   device_shifts / drag_logs / survey_responses   │
└──────────────────────────────────────────────────┘
```

### 关键设计原则

- **MockEngine 先行**: 所有计算先用假数据/简单公式，确保端到端流程通。真实仿真引擎后补。
- **Session 驱动**: 每个被测者一个 session_id (UUID4)，所有数据通过 session_id 关联。
- **混合前端**: Dash 做数据展示页，HTML/JS 做拖拽交互页，FastAPI 统一路由。

---

## 3. 项目文件结构

```
energy-sharing/
├── platform/                    # ← 新的平台代码（和现有 modules/ 并行）
│   ├── __init__.py
│   ├── main.py                  # FastAPI app + Dash mount + 路由
│   ├── config.py                # 环境变量、数据库URL、常量
│   │
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── session.py           # Session (id, created_at, completed, role, ...)
│   │   ├── user_input.py        # UserInput (building_type, area, people, DER, ...)
│   │   ├── daily_profile.py     # DailyProfile (96-slot load curve per session)
│   │   ├── bill.py              # BillBreakdown (purchase, grid_fee, tax, PV, ...)
│   │   ├── shadow_price.py      # ShadowPrices (96-slot internal_buy/sell)
│   │   ├── device_shift.py      # DeviceShift (final positions per step)
│   │   ├── drag_log.py          # DragLog (every drag op with timestamp)
│   │   └── survey.py            # SurveyResponse (Q1-Q4 answers)
│   │
│   ├── engine/                  # Calculation engines
│   │   ├── __init__.py
│   │   ├── base.py              # CalculationEngine ABC
│   │   ├── mock.py              # MockEngine (fake data, first)
│   │   └── simulation.py        # SimulationEngine (real models, later)
│   │
│   ├── api/                     # FastAPI route handlers
│   │   ├── __init__.py
│   │   ├── session.py           # POST /api/session, GET /api/session/{id}
│   │   ├── profile.py           # POST /api/profile (generate load curve)
│   │   ├── bill.py              # POST /api/bill (calculate bill)
│   │   ├── shadow_price.py      # GET /api/shadow-prices/{session_id}
│   │   ├── device_shift.py      # POST /api/device-shift, POST /api/drag-log
│   │   └── survey.py            # POST /api/survey
│   │
│   ├── dash_app/                # Dash pages
│   │   ├── __init__.py
│   │   ├── app.py               # Dash app init + multi-page setup
│   │   ├── pages/
│   │   │   ├── step1_role.py    # 角色选择 + 信息输入
│   │   │   ├── step2_profile.py # 用电曲线 + 电费展示
│   │   │   ├── step4_shadow.py  # 影子价格展示
│   │   │   ├── step6_compare.py # 三方账单对比
│   │   │   ├── step7_impacts.py # 政策/电网/环境
│   │   │   └── step8_survey.py  # 最终问卷
│   │   └── components/          # 共用 Dash 组件
│   │       ├── load_chart.py    # 用电曲线图组件
│   │       ├── bill_card.py     # 账单卡片组件
│   │       └── nav_bar.py       # 导航/进度条
│   │
│   └── static/                  # Step 3 & 5 的 HTML/JS 页面
│       ├── step3_customize.html
│       ├── step5_respond.html
│       ├── css/
│       │   └── timeline.css
│       └── js/
│           ├── timeline.js      # 时间轴渲染 + 拖拽逻辑
│           ├── devices.js       # 设备卡片定义
│           └── api.js           # fetch wrapper (调后端API)
│
├── modules/                     # 现有仿真代码（不动）
├── data/
├── results/
├── alembic/                     # 数据库迁移
├── alembic.ini
├── pyproject.toml
└── README.md
```

---

## 4. 数据模型

### Session
```python
class Session(Base):
    __tablename__ = "sessions"
    id: str              # UUID4, primary key
    created_at: datetime
    completed: bool      # Step 8 提交后设为 True
    current_step: int    # 1-8, 追踪进度
    role: str | None     # "apartment" / "villa" / "office" / ...
```

### UserInput (Step 1)
```python
class UserInput(Base):
    __tablename__ = "user_inputs"
    id: int              # auto-increment
    session_id: str      # FK → sessions.id
    building_type: str   # "apartment" / "villa_noder" / "villa_pv" / "villa_pvbess"
    area_m2: float
    people: int
    heating: str         # "district" / "electric" / "heatpump"
    has_ev: bool
    has_pv: bool
    pv_kwp: float | None
    has_bess: bool
    bess_kwh: float | None
```

### DailyProfile (Step 2 output)
```python
class DailyProfile(Base):
    __tablename__ = "daily_profiles"
    id: int
    session_id: str
    step: int            # 2=baseline, 3=customized, 5=responded
    # 96 slots stored as JSON array
    rigid_load: str      # JSON [float x 96] (kW per 15-min)
    flexible_load: str   # JSON [float x 96]
    pv_generation: str   # JSON [float x 96]
    net_load: str        # JSON [float x 96]
    # device-level breakdown
    devices: str         # JSON {device_name: {start_slot, end_slot, load_kw}[]}
```

### BillBreakdown (Step 2, 6)
```python
class BillBreakdown(Base):
    __tablename__ = "bill_breakdowns"
    id: int
    session_id: str
    scenario: str        # "no_vec" / "vec_no_adjust" / "vec_adjusted"
    step: int
    energy_purchase: float  # SEK/month
    grid_fee: float
    energy_tax: float
    pv_self_consumption: float
    vec_discount: float
    feed_in_income: float
    net_cost: float         # total
```

### ShadowPrices (Step 4)
```python
class ShadowPrices(Base):
    __tablename__ = "shadow_prices"
    id: int
    session_id: str
    retail_price: str     # JSON [float x 96]
    internal_buy: str     # JSON [float x 96]
    internal_sell: str    # JSON [float x 96]
    feed_in_price: str    # JSON [float x 96]
```

### DeviceShift (Step 3, 5 final state)
```python
class DeviceShift(Base):
    __tablename__ = "device_shifts"
    id: int
    session_id: str
    step: int             # 3 or 5
    device_name: str
    original_start: int   # slot 0-95
    original_end: int
    final_start: int
    final_end: int
    willing: bool | None  # Step 5 only: 是否愿意调整
    unwilling_reason: str | None  # "inconvenient" / "comfort" / "not_enough" / "hassle" / "other"
```

### DragLog (每次拖拽操作)
```python
class DragLog(Base):
    __tablename__ = "drag_logs"
    id: int
    session_id: str
    step: int
    timestamp: datetime
    device_name: str
    from_start: int       # slot
    from_end: int
    to_start: int
    to_end: int
    action: str           # "move" / "add" / "remove"
```

### SurveyResponse (Step 8)
```python
class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    id: int
    session_id: str
    q1_willingness: str    # "very_willing" / "somewhat" / "need_more_info" / "unlikely" / "not_willing"
    q2_reasons: str        # JSON array of selected reasons
    q3_concerns: str       # JSON array of selected concerns
    q4_savings_perception: str  # "attractive" / "somewhat" / "not_enough" / "unsure"
```

---

## 5. API Endpoints

| Method | Path | Step | 说明 |
|--------|------|------|------|
| POST | `/api/session` | 0 | 创建新session, 返回 session_id |
| GET | `/api/session/{id}` | * | 获取session状态 |
| POST | `/api/user-input` | 1 | 保存角色+建筑信息 |
| POST | `/api/generate-profile` | 2 | 根据input生成用电曲线+账单 |
| GET | `/api/profile/{session_id}` | 2,3,5 | 获取当前曲线数据 |
| POST | `/api/device-shift` | 3,5 | 保存设备最终位置 |
| POST | `/api/drag-log` | 3,5 | 记录单次拖拽操作 |
| POST | `/api/recalculate` | 3,5 | 根据新设备位置重算曲线+账单 |
| GET | `/api/shadow-prices/{session_id}` | 4 | 获取影子价格 |
| GET | `/api/bill-comparison/{session_id}` | 6 | 获取三方账单对比 |
| GET | `/api/impacts/{session_id}` | 7 | 获取政策/电网/环境数据 |
| POST | `/api/survey` | 8 | 保存最终问卷 |
| POST | `/api/complete/{session_id}` | 8 | 标记session完成 |

---

## 6. MockEngine 规格

MockEngine 不调用真实仿真模型，而是用合理的假数据让前端可以完整跑通。

```python
class MockEngine(CalculationEngine):
    
    def generate_profile(self, user_input: UserInput) -> DailyProfile:
        """根据角色类型返回预设的96-slot曲线"""
        # apartment: 基础负荷0.3kW, 早晚峰1.2kW, 无PV
        # villa_pv: 基础0.5kW, 早晚峰1.8kW, PV 日间 -3kW
        # 设备叠加在基础曲线上
    
    def calculate_bill(self, profile: DailyProfile, scenario: str) -> BillBreakdown:
        """简单乘法: 电量 × 价格"""
        # retail: 1.5 SEK/kWh (含税费)
        # grid_fee: ~580 SEK/month (flat)
        # VEC discount: internal_buy 时段省 0.3-0.5 SEK/kWh
    
    def get_shadow_prices(self, session_id: str) -> ShadowPrices:
        """预设的影子价格曲线 (所有用户看到同一个)"""
        # retail: 1.2-2.0 SEK/kWh (日变化)
        # internal_buy: 10:00-14:00 降至 0.8 SEK/kWh
        # internal_sell: > feed-in but < retail
    
    def calculate_impacts(self, session_id: str) -> dict:
        """简单估算"""
        # CO2: 电量 × 0.045 kg/kWh (Nordic mix)
        # peak: 社区峰值变化估算
```

---

## 7. 四周开发计划

### Week 1: 骨架 + Step 1-2 (能在浏览器打开，选角色，看到曲线)

**Day 1-2: 项目骨架**
- [ ] 在 `energy-sharing/` 下创建 `platform/` 目录结构
- [ ] FastAPI main.py + Dash app mount
- [ ] SQLAlchemy models (所有表) + Alembic init
- [ ] SQLite 数据库创建
- [ ] `config.py` (DATABASE_URL, debug mode)
- [ ] MockEngine 骨架 (ABC + Mock 空实现)
- [ ] 验证: `uvicorn platform.main:app` 能启动, 浏览器能打开

**Day 3-4: Step 1 (角色选择)**
- [ ] Dash page: step1_role.py
  - 角色选择 radio buttons (Apartment / Villa)
  - 条件表单 (面积/人数/供暖/DER)
  - "Next" 按钮 → POST /api/session + /api/user-input
- [ ] API endpoints: session + user-input
- [ ] 验证: 能选角色，填信息，数据存入 SQLite

**Day 5: Step 2 (用电曲线 + 电费)**
- [ ] MockEngine.generate_profile() (返回假曲线)
- [ ] MockEngine.calculate_bill() (简单计算)
- [ ] Dash page: step2_profile.py
  - Plotly 堆叠面积图 (设备分色)
  - 电费卡片
  - "Next" 按钮 → 跳转 Step 3
- [ ] 验证: 选完角色后能看到曲线和电费

**Week 1 完成标志**: 浏览器打开 → 选角色 → 看到用电曲线和电费

---

### Week 2: Step 3-5 (拖拽交互 + 影子价格)

**Day 6-8: Step 3 (设备拖拽 — 核心难点)**
- [ ] `static/step3_customize.html` + `js/timeline.js`
  - Canvas 或 SVG 时间轴 (00:00-24:00)
  - 设备色块渲染 (从 API 获取默认位置)
  - 拖拽逻辑 (mousedown/mousemove/mouseup)
  - 右侧设备面板 (可添加新设备)
  - 实时曲线更新 (每次拖完 → fetch /api/recalculate)
  - 每次拖拽 → POST /api/drag-log
- [ ] `js/api.js` (fetch wrapper + session_id 管理)
- [ ] API: drag-log + recalculate + device-shift
- [ ] FastAPI 路由: 静态文件 serve
- [ ] 验证: 能拖设备，曲线实时变化，操作被记录

**Day 9: Step 4 (影子价格展示)**
- [ ] MockEngine.get_shadow_prices()
- [ ] Dash page: step4_shadow.py
  - 三线图 (retail / internal_buy / internal_sell)
  - 关键时段标注
  - "不调整" 的 VEC 电费估算卡片
- [ ] 验证: 看到价格曲线和预估节省

**Day 10: Step 5 (响应影子价格)**
- [ ] `static/step5_respond.html` (复用 Step 3 的拖拽代码)
  - 新增: 每个设备旁显示 "移到X点可省Y SEK"
  - 新增: 每个设备 "愿意/不愿意" + 原因选择
  - 叠加三条曲线 (原始/自定义/调整后)
- [ ] API: 保存 Step 5 的 device_shift + 意愿数据
- [ ] 验证: 能看到建议，做调整，记录意愿

**Week 2 完成标志**: 完整走通 Step 1→2→3→4→5

---

### Week 3: Step 6-8 + 端到端流程

**Day 11-12: Step 6 (账单对比)**
- [ ] MockEngine: 计算三个scenario的 BillBreakdown
- [ ] Dash page: step6_compare.py
  - 三列卡片 (无VEC / VEC不调 / VEC调整)
  - 详细分解表
  - 24小时对比曲线图
- [ ] 验证: 看到清晰的三方对比

**Day 13: Step 7 (政策/电网/环境)**
- [ ] MockEngine.calculate_impacts()
- [ ] Dash page: step7_impacts.py
  - Tab 1: 政策影响表 (skattereduktion取消, effekttariff)
  - Tab 2: 电网影响 (峰值变化)
  - Tab 3: 环境影响 (CO2减排)
- [ ] 验证: 三个tab都有内容

**Day 14: Step 8 (最终问卷)**
- [ ] Dash page: step8_survey.py
  - Q1: 参与意愿 (5-point Likert)
  - Q2: 主要原因 (多选, top 3)
  - Q3: 最大顾虑 (多选, top 3)
  - Q4: 节省金额感知
  - Submit → POST /api/survey + /api/complete
  - 完成页面 "Thank you"
- [ ] 验证: 能提交问卷，session 标记完成

**Day 15: 端到端测试**
- [ ] Step 1→2→3→4→5→6→7→8 完整走通
- [ ] 检查所有数据都正确存入数据库
- [ ] 修复 bug

**Week 3 完成标志**: 一个人可以从头到尾走完全部8步

---

### Week 4: 部署 + 美化 + 数据导出

**Day 16-17: 部署到 Render.com**
- [ ] PostgreSQL 数据库创建
- [ ] `config.py` 环境变量切换 (DATABASE_URL)
- [ ] Render.com 配置 (build command, start command)
- [ ] GitHub push → 自动部署
- [ ] 验证: 公网 URL 可访问并走通全流程

**Day 18-19: UI 美化**
- [ ] 导航栏 + 进度条 (Step 1/8, 2/8, ...)
- [ ] 响应式布局 (桌面 + 平板)
- [ ] 拖拽页面美化 (设备图标, 色彩一致性)
- [ ] 加载状态 (spinner)
- [ ] 错误处理 (网络断开, 后退按钮)

**Day 20: 数据导出 + 文档**
- [ ] Admin endpoint: GET /api/admin/export (所有session数据导出为CSV)
- [ ] README.md 更新 (部署说明, API文档)
- [ ] 测试: 邀请1-2人试用, 收集反馈

**Week 4 完成标志**: 公网可访问, UI合格, 数据可导出

---

## 8. 给 Claude Code 的使用说明

开发时在 VS Code 中使用 Claude Code 扩展。以下是推荐的 prompt 模式:

### Week 1 Day 1-2 的第一个 prompt:

```
我在开发一个 FastAPI + Dash 的web平台。请在 energy-sharing/platform/ 下创建项目骨架:

1. platform/main.py: FastAPI app, mount Dash app, serve static files from platform/static/
2. platform/config.py: DATABASE_URL (SQLite for dev), SESSION_SECRET
3. platform/models/__init__.py: SQLAlchemy Base + all models import
4. platform/models/session.py: Session model (参考下面的schema)
5. platform/engine/base.py: CalculationEngine ABC
6. platform/engine/mock.py: MockEngine (空实现, 返回假数据)
7. platform/dash_app/app.py: Dash multi-page app init

Session schema:
- id: str (UUID4, PK)
- created_at: datetime
- completed: bool (default False)
- current_step: int (default 1)
- role: str | None

要求:
- 使用 SQLAlchemy 2.0 style (mapped_column)
- FastAPI + Dash 共存 (Dash mount 在 /dash/ 路径下)
- uvicorn 启动: uvicorn platform.main:app --reload
- Python 3.13 兼容
```

### 后续每个 Step 的 prompt 模式:

```
继续开发 VEC platform。现在做 Step X。

Step X 的功能:
[描述功能]

需要修改/创建的文件:
[列出文件]

数据流:
[前端 → API → Engine → DB]

验证标准:
[怎样算做完]
```

---

## 9. 住宅用户类型与设备

### 角色类型 (Step 1)

| 类型 | 代码 | 面积范围 | PV | BESS | EV |
|------|------|----------|----|----|-----|
| 公寓 (Apartment/Lägenhet) | `apartment` | 40-120 m² | No | No | Optional |
| 别墅无DER (Villa) | `villa_noder` | 80-250 m² | No | No | Optional |
| 别墅+PV | `villa_pv` | 80-250 m² | 3-15 kWp | No | Optional |
| 别墅+PV+BESS | `villa_pvbess` | 80-250 m² | 3-15 kWp | 5-20 kWh | Optional |

### 可调设备 (Step 3 & 5)

| 设备 | 默认时间 | 持续时长 | 负荷 | 可移动性 |
|------|----------|----------|------|----------|
| 洗衣机 (Washing machine) | 19:00-21:00 | 2h | 0.5 kW | 高 |
| 烘干机 (Dryer) | 20:00-22:00 | 2h | 2.0 kW | 高 |
| 洗碗机 (Dishwasher) | 19:30-21:00 | 1.5h | 1.2 kW | 高 |
| EV 充电 (EV charging) | 18:00-06:00 | 8h | 3.7 kW | 高 |
| 热水器 (Water heater) | 05:00-07:00 | 2h | 3.0 kW | 中 |
| 烹饪-早 (Cooking AM) | 07:00-07:30 | 0.5h | 2.0 kW | 低 |
| 烹饪-晚 (Cooking PM) | 18:00-19:00 | 1h | 2.0 kW | 低 |

### 不可调设备 (始终显示在曲线上，不能拖动)

| 设备 | 时间 | 负荷 |
|------|------|------|
| 冰箱 (Refrigerator) | 24h | 0.1 kW |
| 待机 (Standby) | 24h | 0.05 kW |
| 照明 (Lighting) | 06-08, 17-23 | 0.2 kW |

---

## 10. 瑞典电价参数 (MockEngine 用)

```python
# 2026 SE3 典型值 (SEK/kWh)
SPOT_PRICE_RANGE = (0.3, 1.2)       # 日变化
ENERGY_TAX = 0.36                     # 36 öre/kWh
VAT_RATE = 0.25                       # 25% (residential)
GRID_FEE_MONTHLY = 580                # SEK, flat part
GRID_FEE_VARIABLE = 0.20              # SEK/kWh

# VEC internal prices (MockEngine preset)
VEC_BUY_DISCOUNT = 0.50               # 50% of spread during surplus
VEC_SELL_PREMIUM = 0.30               # 30% above feed-in during deficit

# Feed-in
FEED_IN_PRICE = 0.50                  # SEK/kWh (no skattereduktion from 2026)
```
