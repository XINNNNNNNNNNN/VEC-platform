# VEC Platform — 初始化步骤

在 VS Code 中打开文件夹 `D:\Projects\VEC Platform`，然后打开终端 (Ctrl+`)，逐步执行：

## Step 1: 初始化 uv 环境

```powershell
uv init --python 3.13
```

这会生成默认的 pyproject.toml 和 .python-version。
然后用我给你的 pyproject.toml **替换掉**它自动生成的那个。

## Step 2: 创建虚拟环境 + 安装依赖

```powershell
uv sync
```

## Step 3: 初始化 Git

```powershell
git init
git add .
git commit -m "init: project setup with uv + FastAPI + Dash"
```

## Step 4: 创建项目目录结构

```powershell
# 后端主目录
mkdir -p platform/models
mkdir -p platform/engine
mkdir -p platform/api
mkdir -p platform/dash_app/pages
mkdir -p platform/dash_app/components

# 前端静态文件 (Step 3 & 5 拖拽页面)
mkdir -p platform/static/js
mkdir -p platform/static/css

# 创建所有 __init__.py
New-Item -ItemType File -Path platform/__init__.py -Force
New-Item -ItemType File -Path platform/models/__init__.py -Force
New-Item -ItemType File -Path platform/engine/__init__.py -Force
New-Item -ItemType File -Path platform/api/__init__.py -Force
New-Item -ItemType File -Path platform/dash_app/__init__.py -Force
New-Item -ItemType File -Path platform/dash_app/pages/__init__.py -Force
New-Item -ItemType File -Path platform/dash_app/components/__init__.py -Force
```

注意：如果 `mkdir -p` 在 PowerShell 报错，改用：
```powershell
New-Item -ItemType Directory -Path platform/models -Force
New-Item -ItemType Directory -Path platform/engine -Force
New-Item -ItemType Directory -Path platform/api -Force
New-Item -ItemType Directory -Path platform/dash_app/pages -Force
New-Item -ItemType Directory -Path platform/dash_app/components -Force
New-Item -ItemType Directory -Path platform/static/js -Force
New-Item -ItemType Directory -Path platform/static/css -Force
```

## Step 5: 验证

```powershell
# 激活环境
.venv\Scripts\activate

# 验证 Python 版本
python --version

# 验证关键包
python -c "import fastapi; import dash; import sqlalchemy; print('All good!')"
```

## 完成后的目录结构

```
D:\Projects\VEC Platform\
├── .gitignore
├── .python-version
├── .venv\
├── pyproject.toml
├── uv.lock
├── PLATFORM_DEV_PLAN.md
└── platform\
    ├── __init__.py
    ├── models\
    │   └── __init__.py
    ├── engine\
    │   └── __init__.py
    ├── api\
    │   └── __init__.py
    ├── dash_app\
    │   ├── __init__.py
    │   ├── pages\
    │   │   └── __init__.py
    │   └── components\
    │       └── __init__.py
    └── static\
        ├── js\
        └── css\
```

## 下一步

环境就绪后，开始写代码。打开 Claude Code，输入：

```
读一下 PLATFORM_DEV_PLAN.md，然后按 Week 1 Day 1-2 的任务开始：

1. platform/config.py — DATABASE_URL (SQLite), 常量
2. platform/models/ — 所有 SQLAlchemy models (Session, UserInput, DailyProfile, BillBreakdown, ShadowPrices, DeviceShift, DragLog, SurveyResponse)
3. platform/engine/base.py — CalculationEngine ABC
4. platform/engine/mock.py — MockEngine 空实现
5. platform/main.py — FastAPI app + Dash mount + static files
6. platform/dash_app/app.py — Dash multi-page app init

要求：
- SQLAlchemy 2.0 style (mapped_column, DeclarativeBase)
- FastAPI mount Dash at /dash/
- Static files serve at /static/
- 能 uvicorn platform.main:app --reload 启动
- 浏览器打开 http://localhost:8000 能看到页面
```
