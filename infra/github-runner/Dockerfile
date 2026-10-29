ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}
USER root
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 cmake make libicu70 libssl3 libkrb5-3 zlib1g libatomic1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY runner-dist/ /opt/actions-runner/
COPY entrypoint.sh /usr/local/bin/runner-entrypoint
COPY hdc.sh /usr/local/bin/hdc
RUN chmod +x /usr/local/bin/runner-entrypoint /usr/local/bin/hdc
WORKDIR /runner
ENV HOME=/runner
ENTRYPOINT ["/usr/local/bin/runner-entrypoint"]
CMD ["./run.sh"]
