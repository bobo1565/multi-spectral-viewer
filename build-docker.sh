#!/bin/bash

# 构建Docker镜像脚本

echo "🚀 开始构建多光谱图像分析系统..."

# 检查Docker是否运行
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker未运行，请先启动Docker"
    exit 1
fi

# 构建镜像
echo "📦 构建Docker镜像..."
docker-compose build

if [ $? -eq 0 ]; then
    echo "✅ 镜像构建成功!"
    echo ""
    echo "使用以下命令启动系统:"
    echo "  docker-compose up -d"
    echo ""
    echo "访问地址:"
    echo "  前端: http://localhost"
    echo "  后端API文档: http://localhost:8000/docs"
else
    echo "❌ 镜像构建失败"
    exit 1
fi
