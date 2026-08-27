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
# 基础镜像自带 pip 较旧, 会误判 PyPI 新式规范化 whl 文件名(如 typing_extensions)为元数据不一致,
# 丢 wheel 转源码构建导致失败, 故先升级 pip
RUN pip install --no-cache-dir --upgrade pip
# easyocr 依赖的 torch 若从默认 PyPI 解析会连带下载 nvidia/cudnn 等 CUDA 轮子(数 GB),
# 宿主无 GPU 用不上; 从官方 CPU 源提供 +cpu 本地版本号, 同版本下优先于 PyPI 的 CUDA 轮子被选中
RUN pip install --no-cache-dir torch==2.13.0 torchvision==0.28.0 \
        --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 仪表盘作为容器主进程: 管理设备/任务/日志, 页面与 API 均在 11000 端口
EXPOSE 11000
CMD ["python", "dashboard/app.py"]
