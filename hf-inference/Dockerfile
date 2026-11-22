FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/.cache/huggingface \
    HF_MODEL_DIR=/data/models/9jalingo-african-tts \
    SPARKVOX_DIR=/opt/SparkVox \
    TTS_SOURCE_DIR=/opt/9jalingo-Spark-tts

RUN apt-get update && apt-get install -y --no-install-recommends git ffmpeg libsndfile1 build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/SparkAudio/SparkVox.git /opt/SparkVox \
    && git clone --depth 1 https://github.com/9jaLingo/9jalingo-Spark-tts.git /opt/9jalingo-Spark-tts

RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" python-multipart \
    numpy soundfile librosa einops \
    lightning pytorch-lightning hydra-core omegaconf \
    transformers huggingface_hub safetensors accelerate sentencepiece \
    vector-quantize-pytorch descript-audiotools protobuf==3.20.3 torchaudio==2.6.0

WORKDIR /app
COPY app.py /app/app.py
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
