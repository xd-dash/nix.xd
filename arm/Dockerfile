FROM docker.io/library/alpine:3.23
RUN test "$(uname -m)" = aarch64 && apk add --no-cache bash coreutils curl git xz tar ca-certificates
RUN addgroup -g 1000 nixuser && adduser -D -u 1000 -G nixuser -s /bin/bash nixuser \
    && mkdir -p /nix /workspaces && chown nixuser:nixuser /nix /workspaces
USER nixuser
ENV HOME=/home/nixuser USER=nixuser
WORKDIR /home/nixuser
# Version-specific installer; this initial bootstrap still fetches upstream binary payloads.
RUN curl --fail --show-error --location https://releases.nixos.org/nix/nix-2.31.2/install -o /tmp/install-nix \
    && sh /tmp/install-nix --no-daemon --yes && rm /tmp/install-nix
ENV PATH=/home/nixuser/.nix-profile/bin:/nix/var/nix/profiles/default/bin:$PATH
RUN mkdir -p /home/nixuser/.config/nix
COPY --chown=nixuser:nixuser nix.conf /home/nixuser/.config/nix/nix.conf
CMD ["bash"]
