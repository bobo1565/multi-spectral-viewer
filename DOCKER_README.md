# 多光谱图像分析系统 - Docker部署指南

## 系统架构

本系统采用B/S架构，包含：
- **后端**: FastAPI + Python (OpenCV图像处理)
- **前端**: React + TypeScript + Ant Design
- **部署**: Docker + Docker Compose

## 快速开始

### 1. 构建Docker镜像

```bash
./build-docker.sh
```

### 2. 启动系统

```bash
docker-compose up -d
```

### 3. 访问系统

- **前端界面**: http://localhost
- **后端API文档**: http://localhost:8000/docs

### 4. 停止系统

```bash
docker-compose down
```

## 功能特性

### 已实现功能
✅ 图像上传和管理  
✅ 图像查看  
✅ 白平衡调节  
✅ 饱和度调节  
✅ 通道增益调节  
✅ 直方图计算  
✅ 多光谱波段混合  
✅ 光谱曲线显示  
✅ 植被指数计算 (NDVI, GNDVI, NDRE, SAVI, EVI)  
✅ 图像对齐  

### 待扩展功能
(可根据需要继续开发更多UI组件)

## 目录结构

```
├── backend/              # 后端FastAPI应用
│   ├── app/
│   │   ├── api/         # API路由
│   │   ├── core/        # 核心算法
│   │   ├── services/    # 业务逻辑
│   │   └── storage/     # 文件管理
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/            # 前端React应用
│   ├── src/
│   │   ├── components/  # React组件
│   │   ├── services/    # API调用
│   │   └── types/       # TypeScript类型
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml   # Docker编排配置
└── build-docker.sh      # 构建脚本
```

## API文档

启动系统后访问 http://localhost:8000/docs 查看完整的API文档和交互式测试界面。

## 数据持久化

上传的图像存储在 `./uploads` 目录中，该目录通过Docker卷映射，确保数据持久化。

## 开发模式

### 后端开发
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 前端开发
```bash
cd frontend
npm install
npm run dev
```

## 故障排除

### 端口冲突
如果80或8000端口被占用，修改docker-compose.yml中的端口映射：
```yaml
ports:
  - "8080:80"   # 前端改为8080
  - "8001:8000" # 后端改为8001
```

### 镜像构建失败
确保Docker有足够的内存分配（建议4GB以上）

## 技术支持

如有问题，请查看日志：
```bash
docker-compose logs -f
```
