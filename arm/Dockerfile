FROM docker.io/library/alpine:3.23
ARG TARGETARCH
RUN case "$TARGETARCH:$(uname -m)" in arm64:aarch64|amd64:x86_64) ;; *) exit 1 ;; esac \
    && apk add --no-cache bash coreutils curl git xz tar ca-certificates
RUN addgroup -g 1000 nixuser && adduser -D -u 1000 -G nixuser -s /bin/bash nixuser \
    && mkdir -p /nix /workspaces && chown nixuser:nixuser /nix /workspaces
COPY init-nix-store.sh /usr/local/bin/nix-xd-init-store
RUN chmod 755 /usr/local/bin/nix-xd-init-store
USER nixuser
ENV HOME=/nix/home/nixuser USER=nixuser
WORKDIR /workspaces
ENV PATH=/nix/home/nixuser/.nix-profile/bin:$PATH
COPY nix.conf /etc/nix-xd/nix.conf
ENTRYPOINT ["/usr/local/bin/nix-xd-init-store"]
CMD ["sleep", "infinity"]
