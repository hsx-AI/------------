# 核电质量计划看板

前端 Vue 看板 + FastAPI 后端，读取项目根目录 `data/ecs_documents.db`。

## 启动

先开后端（默认 `127.0.0.1:8787`）：

```powershell
.\run_dashboard_api.bat
# 或
.\pc_receiver\.venv\Scripts\python.exe -m dashboard_api.main
```

再开前端：

```powershell
cd nuclear-quality-dashboard
npm install
npm run dev
```

浏览器打开 Vite 提示的地址（通常是 `http://127.0.0.1:5173`）。前端通过代理访问 `/api/*`。

## 页面

- 质量计划总览：指标卡、状态分布、制造单位、清单、报送级别
- 计划台账：搜索 / 状态筛选 / 分页
- 流程追踪：节点停留、处理中计划、近期字段变更
- 供方分析：供方排行、工作模式分布
- 数据治理：字段完整率、同步批次、变更明细

## 主要接口

- `GET /api/health`
- `GET /api/filters`
- `GET /api/overview`
- `GET /api/documents`
- `GET /api/trace`
- `GET /api/suppliers`
- `GET /api/governance`
- `GET /api/export`
