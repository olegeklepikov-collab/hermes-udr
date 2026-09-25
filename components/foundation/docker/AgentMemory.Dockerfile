FROM node@sha256:5711a0d445a1af54af9589066c646df387d1831a608226f4cd694fc59e745059

RUN npm install --global @agentmemory/agentmemory@0.9.29 \
    && agentmemory --version

COPY src/hermes_foundation_bridge/agentmemory_worker.mjs /opt/hermes-foundation/agentmemory_worker.mjs
RUN chmod 0555 /opt/hermes-foundation/agentmemory_worker.mjs \
    && mkdir -p /home/node/.agentmemory /data \
    && chown -R node:node /home/node/.agentmemory /data /opt/hermes-foundation

USER node
ENV HOME=/home/node \
    CI=1 \
    AGENTMEMORY_DATA_DIR=/data \
    AGENTMEMORY_AGENT_SCOPE=isolated \
    AGENTMEMORY_TOOLS=core \
    AGENT_ID=hermes-greenfield

ENTRYPOINT ["agentmemory"]
CMD ["--data-dir", "/data"]
