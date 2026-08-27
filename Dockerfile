# easyocr 会引入最新 torch(要求 Python>=3.10), 故基础镜像用 3.10 而非 3.9
FROM python:3.10-slim

# 系统依赖:
#   adb            - uiautomator2 与 Android 设备通信
#   libgl1/libglib2.0-0/libgomp1 - opencv-python / easyocr(torch) / onnxruntime(ddddocr) 运行库
RUN apt-get update && apt-get install -y --no-install-recommends \
        adb \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /scripts

COPY requirements.txt .
# easyocr 会引入 torch, 镜像较大, 首次构建耗时较长属正常
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 仪表盘作为容器主进程: 管理设备/任务/日志, 页面与 API 均在 8080 端口
EXPOSE 8080
CMD ["python", "dashboard/app.py"]
