FROM python:3.11-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/opt/neufert-models HF_HUB_DISABLE_TELEMETRY=1
COPY requirements-runtime.txt /srv/requirements-runtime.txt
RUN pip install --no-cache-dir torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r /srv/requirements-runtime.txt
COPY . /srv/pipeline
RUN python -c "import json; from pathlib import Path; from huggingface_hub import snapshot_download; m=json.load(open('/srv/pipeline/deployment-data/model.json')); p=Path(snapshot_download(m['model'], revision=m['revision'], allow_patterns=['*.json','*.safetensors','sentencepiece.bpe.model'])); refs=p.parent.parent/'refs'; refs.mkdir(exist_ok=True); (refs/'main').write_text(m['revision']); from sentence_transformers import SentenceTransformer; model=SentenceTransformer(m['model'],local_files_only=True); assert model.get_sentence_embedding_dimension()==384"
ENV NEUFERT_CLOUD=1 NEUFERT_DATA_DIR=/tmp/neufert HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
CMD ["sh", "-c", "uvicorn pipeline.server:app --host 0.0.0.0 --port ${PORT:-80}"]
