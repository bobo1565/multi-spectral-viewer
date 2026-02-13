# Stage 1: Build
FROM node:18-alpine as builder

WORKDIR /app

# 使用淘宝npm镜像
RUN npm config set registry https://registry.npmmirror.com

# 复制package文件
COPY package.json ./

# 安装依赖
RUN npm install

# 复制源代码
COPY . .

# 构建应用
RUN npm run build

# Stage 2: Production
FROM nginx:alpine

# 复制构建产物到nginx
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制nginx配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
