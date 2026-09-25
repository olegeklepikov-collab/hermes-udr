FROM zepai/graphiti@sha256:21818c8a8e3b0513fe167370527fec32ed117e98bcc3423f9eb3bc6c73af7d43

USER root
RUN uv pip install --python /app/.venv/bin/python \
    falkordb==1.7.1 \
    httpx==0.28.1

COPY src/hermes_foundation_bridge/graphiti_worker.py /opt/hermes-foundation/graphiti_worker.py
RUN chmod 0555 /opt/hermes-foundation/graphiti_worker.py

USER app
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["exec sleep infinity"]
