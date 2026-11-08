FROM docker.io/library/alpine:3.23
RUN test "$(uname -m)" = aarch64 && apk add --no-cache bash coreutils curl git xz tar ca-certificates
RUN addgroup -g 1000 nixuser && adduser -D -u 1000 -G nixuser -s /bin/bash nixuser \
    && mkdir -p /nix /workspaces && chown nixuser:nixuser /nix /workspaces
COPY init-nix-store.sh /usr/local/bin/nix-xd-init-store
RUN chmod 755 /usr/local/bin/nix-xd-init-store
USER nixuser
ENV HOME=/home/nixuser USER=nixuser
WORKDIR /home/nixuser
ENV PATH=/home/nixuser/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH
RUN mkdir -p /home/nixuser/.config/nix
COPY --chown=nixuser:nixuser nix.conf /home/nixuser/.config/nix/nix.conf
ENTRYPOINT ["/usr/local/bin/nix-xd-init-store"]
CMD ["sleep", "infinity"]
